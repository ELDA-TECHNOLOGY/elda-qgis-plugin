import os
import tempfile
import unittest

from elda_qgis.core.publish import names, polling
from elda_qgis.core.errors import NetworkError, RequestRefused, ServerError, SessionLost
from elda_qgis.core.publish.gis import MultipartPut, SinglePut, VectorUpload
from elda_qgis.core.publish.vector import Job, Outcome, publish_vector
from elda_qgis.core.publish.upload import Cancelled, TooSlow

LAYER_ID = 42
FAILED_MSG = "Le traitement par ELDA a échoué."


class FakeGis:
    """Records calls; `script` maps a method name to a list of results/exceptions replayed in order."""

    def __init__(self, **script):
        self.calls = []
        self.script = {k: list(v) for k, v in script.items()}

    def _do(self, name, *args, default=None):
        self.calls.append((name,) + args)
        queue = self.script.get(name)
        if not queue:
            return default
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def vector_initiate(self, *args):
        return self._do("vector_initiate", *args, default=VectorUpload(LAYER_ID, SinglePut("https://s3.example/x")))

    def vector_finalize(self, layer_id, etags):
        return self._do("vector_finalize", layer_id, etags)

    def vector_abort(self, layer_id):
        return self._do("vector_abort", layer_id)

    def layer_status(self, layer_id):
        return self._do("layer_status", layer_id, default="ready")

    def delete_failed_vector(self, layer_id):
        return self._do("delete_failed_vector", layer_id)

    def names(self):
        return [c[0] for c in self.calls]

    def count(self, name):
        return self.names().count(name)


class Harness:
    def __init__(self, test, gis, send=None, cancel_when=None, size=10):
        self.gis = gis
        self.now = 0.0
        self.sleeps = []
        self.steps = []
        self.cancel_checks = 0
        self.cancel_when = cancel_when or (lambda: False)
        self.send_args = None
        self._send = send
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "layer.gpkg")
        with open(self.path, "wb") as handle:
            handle.write(b"x" * size)
        self.job = Job("k1", self.path, "  Pistes  été ", 7, [1, 2], [3])

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now

    def is_cancelled(self):
        self.cancel_checks += 1
        self.gis.calls.append(("is_cancelled",))
        return self.cancel_when()

    def send_file(self, caller, path, put, mime, on_progress, is_cancelled, confirm_slow):
        self.gis.calls.append(("send_file",))
        self.send_args = (caller, path, put, mime)
        if self._send:
            return self._send(on_progress, is_cancelled)
        on_progress(5, 10)
        on_progress(10, 10)
        return None

    def run(self):
        return publish_vector(
            self.job,
            self.gis,
            "caller",
            lambda *a: self.steps.append(a),
            self.is_cancelled,
            lambda minutes: True,
            sleep=self.sleep,
            clock=self.clock,
            send_file=self.send_file,
        )


class PublishTest(unittest.TestCase):
    def go(self, gis, **kw):
        h = Harness(self, gis, **kw)
        return h, h.run()

    def test_success_order_and_arguments(self):
        gis = FakeGis(layer_status=["ingesting", "ready"])
        h, out = self.go(gis)
        self.assertEqual(out, Outcome("k1", "published", LAYER_ID, None))
        self.assertEqual(
            [n for n in gis.names() if n != "is_cancelled"],
            ["vector_initiate", "send_file", "vector_finalize", "layer_status", "layer_status"],
        )
        init = next(c for c in gis.calls if c[0] == "vector_initiate")
        self.assertEqual(init[1:], (names.safe_filename("  Pistes  été "), names.layer_name("  Pistes  été "), 10, 7, [1, 2], [3]))
        self.assertEqual(h.send_args[1:], (h.path, SinglePut("https://s3.example/x"), "application/geopackage+sqlite3"))
        self.assertEqual(h.send_args[0], "caller")
        self.assertIn(("vector_finalize", LAYER_ID, None), gis.calls)

    def test_multipart_etags_reach_finalize(self):
        etags = [(1, '"a"'), (2, '"b"')]
        vu = VectorUpload(LAYER_ID, MultipartPut(5, [(1, "u1"), (2, "u2")]))
        gis = FakeGis(vector_initiate=[vu])
        self.go(gis, send=lambda p, c: etags)
        self.assertIn(("vector_finalize", LAYER_ID, etags), gis.calls)

    def test_session_lost_propagates_without_cleanup(self):
        for where in ("vector_initiate", "vector_finalize", "layer_status", "send"):
            with self.subTest(where=where):
                if where == "send":
                    def boom(p, c):
                        raise SessionLost()
                    gis = FakeGis()
                    h = Harness(self, gis, send=boom)
                else:
                    gis = FakeGis(**{where: [SessionLost()]})
                    h = Harness(self, gis)
                with self.assertRaises(SessionLost):
                    h.run()
                self.assertEqual(gis.count("vector_abort"), 0)
                self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_error_before_finalize_aborts_once(self):
        cases = [
            (ServerError(500, "Boom."), "failed", "Boom."),
            (NetworkError(), "failed", NetworkError.default_fr),
            (TooSlow(), "failed", TooSlow.default_fr),
            (Cancelled(), "cancelled", None),
        ]
        for exc, status, msg in cases:
            with self.subTest(exc=type(exc).__name__):
                def boom(p, c, exc=exc):
                    raise exc
                gis = FakeGis()
                h, out = self.go(gis, send=boom)
                self.assertEqual(out.status, status)
                self.assertEqual(out.layer_id, None)
                self.assertTrue(out.message_fr)
                if msg:
                    self.assertEqual(out.message_fr, msg)
                self.assertEqual(gis.calls.count(("vector_abort", LAYER_ID)), 1)
                self.assertEqual(gis.count("vector_finalize"), 0)
                self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_finalize_error_aborts(self):
        gis = FakeGis(vector_finalize=[RequestRefused(409)])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertEqual(gis.calls.count(("vector_abort", LAYER_ID)), 1)
        self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_abort_failure_is_swallowed(self):
        gis = FakeGis(vector_finalize=[RequestRefused(400)], vector_abort=[ServerError(500)])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertEqual(gis.count("vector_abort"), 1)

    def test_abort_session_lost_propagates(self):
        gis = FakeGis(vector_finalize=[RequestRefused(400)], vector_abort=[SessionLost()])
        with self.assertRaises(SessionLost):
            Harness(self, gis).run()

    def test_initiate_error_has_nothing_to_abort(self):
        gis = FakeGis(vector_initiate=[RequestRefused(403)])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertTrue(out.message_fr)
        self.assertEqual([n for n in gis.names() if n != "is_cancelled"], ["vector_initiate"])

    def test_failed_status_deletes_once(self):
        gis = FakeGis(layer_status=["ingesting", "failed"])
        h, out = self.go(gis)
        self.assertEqual(out, Outcome("k1", "failed", LAYER_ID, FAILED_MSG))
        self.assertEqual(gis.calls.count(("delete_failed_vector", LAYER_ID)), 1)
        self.assertEqual(gis.count("vector_abort"), 0)

    def test_delete_failure_is_reported_without_retry(self):
        gis = FakeGis(layer_status=["failed"], delete_failed_vector=[ServerError(500)])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertTrue(out.message_fr.startswith(FAILED_MSG))
        self.assertIn("supprim", out.message_fr)
        self.assertEqual(gis.count("delete_failed_vector"), 1)

    def test_cancel_while_polling_keeps_layer(self):
        gis = FakeGis(layer_status=["ingesting"])

        def cancel():
            return gis.count("layer_status") >= 1

        h, out = self.go(gis, cancel_when=cancel)
        self.assertEqual(out.status, "cancelled")
        self.assertIn("ELDA", out.message_fr)
        self.assertIn("traitement", out.message_fr)
        self.assertEqual(gis.count("layer_status"), 1)
        self.assertEqual(gis.count("vector_abort"), 0)
        self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_timeout_after_max_wait(self):
        gis = FakeGis(layer_status=["ingesting"])
        h, out = self.go(gis)
        self.assertEqual(out.status, "timeout")
        self.assertEqual(out.layer_id, LAYER_ID)
        self.assertTrue(out.message_fr)
        self.assertGreaterEqual(h.now, polling.MAX_WAIT_SECONDS)
        self.assertLess(h.now, polling.MAX_WAIT_SECONDS + 15 + 1)
        self.assertEqual(gis.count("vector_abort"), 0)
        self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_waits_follow_schedule_and_cancel_checked_before_each_status(self):
        gis = FakeGis(layer_status=["ingesting"] * 7 + ["ready"])
        h, out = self.go(gis)
        self.assertEqual(out.status, "published")
        self.assertEqual(h.sleeps, [2, 3, 5, 8, 12, 15, 15])
        names_ = gis.names()
        for i, n in enumerate(names_):
            if n == "layer_status":
                self.assertEqual(names_[i - 1], "is_cancelled")

    def test_status_error_keeps_polling(self):
        gis = FakeGis(layer_status=[NetworkError(), ServerError(503), "ready"])
        h, out = self.go(gis)
        self.assertEqual(out.status, "published")
        self.assertEqual(h.sleeps, [2, 3])

    def test_persistent_status_errors_end_in_timeout(self):
        gis = FakeGis(layer_status=[NetworkError()])
        h, out = self.go(gis)
        self.assertEqual(out.status, "timeout")
        self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_status_404_means_layer_gone(self):
        gis = FakeGis(layer_status=[RequestRefused(404)])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertEqual(out.message_fr, "La couche n'existe plus dans ELDA.")
        self.assertEqual(gis.count("delete_failed_vector"), 0)
        self.assertEqual(gis.count("vector_abort"), 0)

    def test_only_initiated_id_is_ever_cleaned(self):
        for script in (dict(layer_status=["failed"]), dict(vector_finalize=[ServerError(500)])):
            gis = FakeGis(**script)
            self.go(gis)
            for c in gis.calls:
                if c[0] in ("vector_abort", "delete_failed_vector"):
                    self.assertEqual(c[1], LAYER_ID)

    def test_on_step_sequence(self):
        gis = FakeGis()
        h, out = self.go(gis)
        self.assertEqual(h.steps, [("initiate", 0, 0), ("upload", 5, 10), ("upload", 10, 10), ("processing", 0, 0)])

    def test_missing_or_empty_file_fails_before_initiate(self):
        gis = FakeGis()
        h = Harness(self, gis, size=0)
        out = h.run()
        self.assertEqual(out.status, "failed")
        self.assertTrue(out.message_fr)
        self.assertEqual(gis.count("vector_initiate"), 0)
        os.remove(h.path)
        out = h.run()
        self.assertEqual(out.status, "failed")
        self.assertEqual(gis.count("vector_initiate"), 0)


def raiser(exc):
    def boom(*args):
        raise exc

    return boom


class FixRound1Test(unittest.TestCase):
    def go(self, gis, **kw):
        h = Harness(self, gis, **kw)
        return h, h.run()

    def test_unexpected_exception_in_send_aborts_once(self):
        for exc in (OSError("disk"), MemoryError()):
            with self.subTest(exc=type(exc).__name__):
                gis = FakeGis()
                h, out = self.go(gis, send=raiser(exc))
                self.assertEqual(out.status, "failed")
                self.assertEqual(out.message_fr, "L'envoi a échoué pour une raison inattendue.")
                self.assertEqual(gis.calls.count(("vector_abort", LAYER_ID)), 1)
                self.assertEqual(gis.count("vector_finalize"), 0)

    def test_on_step_raising_during_upload_aborts_once(self):
        gis = FakeGis()
        h = Harness(self, gis)

        def on_step(step, sent, total):
            if step == "upload":
                raise RuntimeError("ui")

        out = publish_vector(h.job, gis, "c", on_step, h.is_cancelled, lambda m: True,
                             sleep=h.sleep, clock=h.clock, send_file=h.send_file)
        self.assertEqual(out.status, "failed")
        self.assertEqual(gis.calls.count(("vector_abort", LAYER_ID)), 1)

    def test_keyboard_interrupt_aborts_then_reraises(self):
        gis = FakeGis()
        h = Harness(self, gis, send=raiser(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            h.run()
        self.assertEqual(gis.calls.count(("vector_abort", LAYER_ID)), 1)

    def test_finalize_network_error_polls_instead_of_aborting(self):
        gis = FakeGis(vector_finalize=[NetworkError()], layer_status=["ready"])
        h, out = self.go(gis)
        self.assertEqual(out, Outcome("k1", "published", LAYER_ID, None))
        self.assertEqual(gis.count("vector_abort"), 0)
        self.assertEqual(h.steps[-1], ("processing", 0, 0))

    def test_finalize_server_error_never_ready_times_out(self):
        gis = FakeGis(vector_finalize=[ServerError(502)], layer_status=["ingesting"])
        h, out = self.go(gis)
        self.assertEqual(out.status, "timeout")
        self.assertEqual(gis.count("vector_abort"), 0)
        self.assertEqual(gis.count("delete_failed_vector"), 0)

    def test_finalize_server_error_then_failed_deletes_once(self):
        gis = FakeGis(vector_finalize=[ServerError(502)], layer_status=["failed"])
        h, out = self.go(gis)
        self.assertEqual(out.status, "failed")
        self.assertEqual(gis.calls.count(("delete_failed_vector", LAYER_ID)), 1)
        self.assertEqual(gis.count("vector_abort"), 0)

    def test_cancel_before_initiate_creates_nothing(self):
        gis = FakeGis()
        h, out = self.go(gis, cancel_when=lambda: True)
        self.assertEqual(out.status, "cancelled")
        self.assertTrue(out.message_fr)
        self.assertEqual(gis.count("vector_initiate"), 0)

    def test_abort_failure_mentions_leftover_import(self):
        for exc, status in ((Cancelled(), "cancelled"), (ServerError(500, "Boom."), "failed")):
            with self.subTest(exc=type(exc).__name__):
                gis = FakeGis(vector_abort=[NetworkError()])
                h, out = self.go(gis, send=raiser(exc))
                self.assertEqual(out.status, status)
                self.assertIn("import inachevé peut subsister dans ELDA", out.message_fr)

    def test_clean_abort_does_not_mention_leftover(self):
        gis = FakeGis()
        h, out = self.go(gis, send=raiser(Cancelled()))
        self.assertNotIn("subsister", out.message_fr)


if __name__ == "__main__":
    unittest.main()
