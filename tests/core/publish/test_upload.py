import os
import tempfile
import unittest

from elda_qgis.core.errors import NetworkError, RequestRefused, ServerError, UnsafeUrl
from elda_qgis.core.publish.gis import MultipartPut, SinglePut
from elda_qgis.core.net.http import Caller, Request, Response
from elda_qgis.core.publish.upload import SINGLE_MAX_BYTES, UPLOAD_TIMEOUT, Cancelled, TooSlow, send_file
from tests.core.fakes import FakeTransport

CHUNK = 16
SIGNED = "https://s3.example.com/b/k?X-Amz-Signature=deadbeef"


def ok(etag='"e1"'):
    return Response(200, {"etag": etag} if etag else {}, b"")


def parts(n):
    return MultipartPut(CHUNK, [(i + 1, "https://s3.example.com/p%d?X-Amz-Signature=deadbeef" % (i + 1)) for i in range(n)])


class SendFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, data):
        path = os.path.join(self.dir.name, "f.gpkg")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def run_send(self, script, data, put, cancel=lambda: False, slow=lambda m: True, clock=None):
        transport = FakeTransport(script)
        sleeps = []
        progress = []
        args = dict(is_cancelled=cancel, confirm_slow=slow)
        if clock:
            args["clock"] = clock
        try:
            result = send_file(Caller(transport, sleep=sleeps.append), self.file(data), put, "application/x-test", lambda a, b: progress.append((a, b)), **args)
        finally:
            self.transport, self.progress = transport, progress
        return result

    def test_single_put_sends_whole_file_without_authorization(self):
        self.assertIsNone(self.run_send([ok(None)], b"hello", SinglePut(SIGNED)))
        (r,) = self.transport.requests
        self.assertEqual((r.method, r.body, r.timeout), ("PUT", b"hello", UPLOAD_TIMEOUT))
        self.assertEqual(r.headers["Content-Type"], "application/x-test")
        self.assertNotIn("authorization", [k.lower() for k in r.headers])
        self.assertEqual(self.progress, [(5, 5)])

    def test_multipart_ranges_etags_and_progress(self):
        data = bytes(range(2 * CHUNK + 10))
        etags = self.run_send([ok('"a"'), ok('W/"b"'), Response(200, {"ETag": '"c"'}, b"")], data, parts(3))
        self.assertEqual(etags, [(1, '"a"'), (2, 'W/"b"'), (3, '"c"')])
        self.assertEqual([r.body for r in self.transport.requests], [data[:16], data[16:32], data[32:]])
        self.assertEqual(self.progress, [(16, 42), (32, 42), (42, 42)])
        self.assertTrue(all("authorization" not in [k.lower() for k in r.headers] for r in self.transport.requests))

    def test_cancel_before_second_part(self):
        calls = []

        def cancel():
            calls.append(1)
            return len(calls) == 2

        with self.assertRaises(Cancelled):
            self.run_send([ok(), ok()], b"x" * 40, parts(3), cancel=cancel)
        self.assertEqual(len(self.transport.requests), 1)

    def test_part_retries_500_500_200(self):
        self.run_send([Response(500, {}, b""), Response(500, {}, b""), ok()], b"x" * 4, parts(1))
        self.assertEqual(len(self.transport.requests), 3)

    def test_part_exhausting_retries_raises_server_error(self):
        with self.assertRaises(ServerError):
            self.run_send([Response(500, {}, b"")] * 4, b"x" * 4, parts(1))

    def test_missing_etag_raises_server_error(self):
        with self.assertRaises(ServerError):
            self.run_send([ok(None)], b"x" * 4, parts(1))

    def test_slow_estimate_asks_once_and_false_cancels(self):
        ticks = iter([0, 1200, 1300, 1400])
        asked = []

        def slow(minutes):
            asked.append(minutes)
            return False

        with self.assertRaises(Cancelled):
            self.run_send([ok()], b"x" * 49, parts(4), slow=slow, clock=lambda: next(ticks))
        self.assertEqual(asked, [60])

    def test_slow_estimate_accepted_asks_only_once(self):
        ticks = iter([0, 1200, 1300, 1400, 1500])
        asked = []
        self.run_send([ok()] * 4, b"x" * 49, parts(4), slow=lambda m: asked.append(m) or True, clock=lambda: next(ticks))
        self.assertEqual(asked, [60])

    def test_too_slow_after_an_hour(self):
        ticks = iter([0, 3601])
        with self.assertRaises(TooSlow):
            self.run_send([ok()], b"x" * 49, parts(4), clock=lambda: next(ticks))

    def test_part_count_mismatch_sends_nothing(self):
        with self.assertRaises(ServerError):
            self.run_send([], b"x" * 30, parts(3))
        self.assertEqual(self.transport.requests, [])

    def test_empty_file_refused_before_sending(self):
        with self.assertRaises(ServerError):
            self.run_send([], b"", SinglePut(SIGNED))
        self.assertEqual(self.transport.requests, [])

    def test_unsafe_url_refused_before_sending(self):
        for url in ("http://s3.example.com/x", "ftp://x/y", "https_x", "http://localhost.evil.com/x"):
            with self.assertRaises(UnsafeUrl):
                self.run_send([], b"abc", SinglePut(url))
        self.assertEqual(self.transport.requests, [])

    def test_loopback_http_allowed(self):
        self.run_send([ok()], b"abc", SinglePut("http://127.0.0.1:9000/x"))

    def test_signed_url_never_in_errors(self):
        body = ('{"message": "bad %s"}' % SIGNED).encode()
        for script, cls in (([Response(403, {}, body)], RequestRefused), ([Response(500, {}, b"")] * 4, ServerError), ([NetworkError()] * 4, NetworkError)):
            with self.assertRaises(cls) as ctx:
                self.run_send(script, b"abc", SinglePut(SIGNED))
            self.assertNotIn("deadbeef", str(ctx.exception) + ctx.exception.message_fr)
            self.assertNotIn("deadbeef", repr(ctx.exception))

    def test_request_repr_hides_body_and_both_forbidden(self):
        self.assertNotIn("secret", repr(Request("PUT", "https://x", body=b"secret")))
        with self.assertRaises(ValueError):
            Request("PUT", "https://x", json={}, body=b"")

    def test_single_put_401_is_a_refusal_without_progress(self):
        with self.assertRaises(RequestRefused) as ctx:
            self.run_send([Response(401, {}, b"")], b"abc", SinglePut(SIGNED))
        self.assertEqual(self.progress, [])
        self.assertIn("stockage", ctx.exception.message_fr)

    def test_part_401_is_a_refusal_not_a_missing_etag(self):
        with self.assertRaises(RequestRefused):
            self.run_send([Response(401, {}, b"")], b"x" * 4, parts(1))

    def test_no_too_slow_after_the_last_part(self):
        ticks = iter([0, 100, 3700])
        etags = self.run_send([ok('"a"'), ok('"b"')], b"x" * 20, parts(2), clock=lambda: next(ticks))
        self.assertEqual(len(etags), 2)

    def test_too_slow_before_a_remaining_part(self):
        ticks = iter([0, 100, 3700, 3700])
        with self.assertRaises(TooSlow):
            self.run_send([ok(), ok()], b"x" * 40, parts(3), clock=lambda: next(ticks), slow=lambda m: True)
        self.assertEqual(len(self.transport.requests), 2)

    def test_single_file_over_cap_refused_before_sending(self):
        path = os.path.join(self.dir.name, "big.gpkg")
        with open(path, "wb") as handle:
            handle.truncate(SINGLE_MAX_BYTES + 1)
        transport = FakeTransport([])
        with self.assertRaises(ServerError):
            send_file(Caller(transport), path, SinglePut(SIGNED), "m", lambda a, b: None, lambda: False, lambda m: True)
        self.assertEqual(transport.requests, [])

    def test_sigv2_url_in_storage_error_body_never_surfaces(self):
        url = "https://s3.example.com/b/k?AWSAccessKeyId=AKIAXYZ&Signature=abc123&Expires=1"
        body = ('{"message": "bad %s"}' % url).encode()
        with self.assertRaises(RequestRefused) as ctx:
            self.run_send([Response(403, {}, body)], b"abc", SinglePut(url))
        text = str(ctx.exception) + ctx.exception.message_fr
        for secret in ("abc123", "AKIAXYZ", "s3.example.com/b"):
            self.assertNotIn(secret, text)
        self.assertNotIn("serveur ELDA", ctx.exception.message_fr)

    def test_missing_etag_message_names_the_storage(self):
        with self.assertRaises(ServerError) as ctx:
            self.run_send([ok(None)], b"x" * 4, parts(1))
        self.assertEqual(ctx.exception.message_fr, "Le stockage n'a pas confirmé la réception du fichier.")

    def test_storage_5xx_and_network_errors_use_storage_wording(self):
        for script, cls in (([Response(500, {}, b"")] * 4, ServerError), ([NetworkError()] * 4, NetworkError)):
            with self.assertRaises(cls) as ctx:
                self.run_send(script, b"abc", SinglePut(SIGNED))
            text = ctx.exception.message_fr
            self.assertIn("stockage", text)
            self.assertNotIn("serveur ELDA", text)
            self.assertNotIn("deadbeef", text)
            self.assertIsNone(ctx.exception.__cause__)
