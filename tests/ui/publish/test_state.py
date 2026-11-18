from __future__ import annotations

import dataclasses
import unittest
from collections import namedtuple

from elda_qgis.core.publish.vector import Outcome
from elda_qgis.core.session.rights import Rights
from elda_qgis.ui.publish import state as ps
from elda_qgis.ui import texts

L = namedtuple("L", "layer_id name kind feature_count")
YES, NO = Rights(True, True), Rights(False, True)


def rows(n=3, checked=True):
    out = ps.rows_for([L("id%d" % i, "Couche %d" % i, "vector", 5) for i in range(n)], YES)
    return [r.__class__(**{**r.__dict__, "checked": checked}) for r in out]


def with_status(row, status, **kw):
    return row.__class__(**{**row.__dict__, "status": status, **kw})


class RowsForTest(unittest.TestCase):
    def test_vector_selectable_with_right(self):
        (r,) = ps.rows_for([L("a", "  Mes   pistes ", "vector", 3)], YES)
        self.assertEqual((r.key, r.name, r.kind), ("a", "Mes pistes", "vector"))
        self.assertTrue(r.selectable)
        self.assertIsNone(r.reason)
        self.assertFalse(r.checked)
        self.assertEqual((r.status, r.percent, r.message), ("", None, None))

    def test_vector_without_right(self):
        (r,) = ps.rows_for([L("a", "x", "vector", 3)], NO)
        self.assertFalse(r.selectable)
        self.assertEqual(r.reason, "Votre compte n'a pas le droit de publier des couches vecteur sur ce site.")

    def test_raster_and_other_never_selectable(self):
        for kind in ("raster", "other"):
            (r,) = ps.rows_for([L("a", "x", kind, 0)], YES)
            self.assertFalse(r.selectable)
            self.assertEqual(r.reason, "Disponible dans une prochaine version")

    def test_row_is_frozen(self):
        (r,) = ps.rows_for([L("a", "x", "vector", 1)], YES)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.checked = True


class CanPublishTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(ps.can_publish(rows(2), True, False), (True, None))

    def test_not_logged_in(self):
        ok, reason = ps.can_publish(rows(2), False, False)
        self.assertFalse(ok)
        self.assertEqual(reason, texts.NOT_LOGGED_IN)

    def test_busy(self):
        self.assertEqual(ps.can_publish(rows(2), True, True), (False, texts.PUBLISH_BUSY))

    def test_nothing_ticked(self):
        self.assertEqual(ps.can_publish(rows(2, checked=False), True, False), (False, "Cochez au moins une couche."))

    def test_twenty_ok_twentyone_refused(self):
        self.assertEqual(ps.can_publish(rows(20), True, False), (True, None))
        self.assertEqual(ps.can_publish(rows(21), True, False), (False, "20 couches au maximum par envoi."))


class VisibilityTest(unittest.TestCase):
    def test_not_restricted(self):
        self.assertEqual(ps.visibility(False, [1], [2], 9), ([], []))

    def test_restricted_adds_own_once(self):
        self.assertEqual(ps.visibility(True, [3, 1], [5], 9), ([3, 1, 9], [5]))
        self.assertEqual(ps.visibility(True, [3, 9, 1], [5], 9), ([3, 9, 1], [5]))

    def test_restricted_nothing_chosen(self):
        self.assertEqual(ps.visibility(True, [], [], 9), ([9], []))


class StepTest(unittest.TestCase):
    def test_steps(self):
        r = rows(1)[0]
        self.assertEqual(ps.apply_step(r, "initiate", 0, 0).status, ps.ST_PREPARING)
        s = ps.apply_step(r, "upload", 42, 100)
        self.assertEqual((s.status, s.percent), (ps.ST_UPLOADING, 42))
        self.assertEqual(ps.apply_step(r, "upload", 1, 3).percent, 33)
        self.assertEqual(ps.apply_step(r, "upload", 500, 100).percent, 100)
        self.assertEqual(ps.apply_step(r, "upload", -5, 100).percent, 0)
        z = ps.apply_step(r, "upload", 0, 0)
        self.assertEqual((z.status, z.percent), (ps.ST_UPLOADING, None))
        p = ps.apply_step(with_status(r, "x", percent=50), "processing", 0, 0)
        self.assertEqual((p.status, p.percent), (ps.ST_PROCESSING, None))

    def test_returns_new_row(self):
        r = rows(1)[0]
        self.assertIsNot(ps.apply_step(r, "initiate", 0, 0), r)
        self.assertEqual(r.status, "")


class OutcomeTest(unittest.TestCase):
    def out(self, status, msg=None):
        return Outcome("id0", status, None, msg)

    def test_statuses(self):
        r = with_status(rows(1)[0], ps.ST_UPLOADING, percent=10)
        for status, text in [("published", ps.ST_PUBLISHED), ("cancelled", ps.ST_CANCELLED),
                             ("timeout", ps.ST_TIMEOUT), ("failed", ps.ST_FAILED), ("weird", ps.ST_FAILED)]:
            o = ps.apply_outcome(r, self.out(status))
            self.assertEqual((o.status, o.percent), (text, None))

    def test_failed_keeps_message(self):
        o = ps.apply_outcome(rows(1)[0], self.out("failed", "Fichier refusé"))
        self.assertEqual(o.message, "Fichier refusé")

    def test_message_kept_for_timeout_cancelled_and_published_remarks(self):
        r = with_status(rows(1)[0], ps.ST_FAILED, message="vieille erreur")
        self.assertEqual(ps.apply_outcome(r, self.out("timeout", "trop long")).message, "trop long")
        self.assertEqual(ps.apply_outcome(r, self.out("cancelled", "stop")).message, "stop")
        self.assertIsNone(ps.apply_outcome(r, self.out("published", None)).message)
        self.assertEqual(ps.apply_outcome(r, self.out("published", "remarque sur le style")).message, "remarque sur le style")


class MarkTest(unittest.TestCase):
    def test_waiting_only_ticked(self):
        rs = rows(3)
        rs[1] = with_status(rs[1], "", checked=False)
        out = ps.mark_waiting(rs)
        self.assertEqual([r.status for r in out], [ps.ST_WAITING, "", ps.ST_WAITING])

    def test_waiting_skips_ticked_non_selectable(self):
        rs = rows(2)
        rs[0] = with_status(rs[0], "", selectable=False)
        self.assertEqual([r.status for r in ps.mark_waiting(rs)], ["", ps.ST_WAITING])

    def test_waiting_resets_everything_else(self):
        rs = rows(2)
        rs[0] = with_status(rs[0], ps.ST_FAILED, percent=3, message="boom", checked=False)
        rs[1] = with_status(rs[1], ps.ST_PUBLISHED, percent=9, message="m")
        out = ps.mark_waiting(rs)
        self.assertEqual((out[0].status, out[0].percent, out[0].message), ("", None, None))
        self.assertEqual((out[1].status, out[1].percent, out[1].message), (ps.ST_WAITING, None, None))

    def test_unpublished_from_key_skips_finished(self):
        rs = ps.mark_waiting(rows(4))
        rs[0] = with_status(rs[0], ps.ST_PUBLISHED)
        rs[1] = with_status(rs[1], ps.ST_UPLOADING)
        out = ps.mark_unpublished(rs, "id1")
        self.assertEqual([r.status for r in out],
                         [ps.ST_PUBLISHED, ps.ST_UNPUBLISHED, ps.ST_UNPUBLISHED, ps.ST_UNPUBLISHED])

    def test_cancelled_from_key(self):
        rs = ps.mark_waiting(rows(3))
        rs[0] = with_status(rs[0], ps.ST_FAILED)
        out = ps.mark_cancelled(rs, "id1")
        self.assertEqual([r.status for r in out], [ps.ST_FAILED, ps.ST_CANCELLED, ps.ST_CANCELLED])

    def test_unknown_key_marks_every_active_row(self):
        rs = ps.mark_waiting(rows(3))
        rs[0] = with_status(rs[0], ps.ST_PUBLISHED)
        rs[1] = with_status(rs[1], ps.ST_PROCESSING)
        self.assertEqual([r.status for r in ps.mark_cancelled(rs, "nope")],
                         [ps.ST_PUBLISHED, ps.ST_CANCELLED, ps.ST_CANCELLED])
        self.assertEqual([r.status for r in ps.mark_unpublished(rs, "nope")],
                         [ps.ST_PUBLISHED, ps.ST_UNPUBLISHED, ps.ST_UNPUBLISHED])

    def test_unticked_untouched(self):
        rs = rows(2, checked=False)
        self.assertEqual([r.status for r in ps.mark_cancelled(rs, "id0")], ["", ""])


CODE = {"": "", "Publiée": ps.ST_PUBLISHED, "Échec": ps.ST_FAILED, "Annulée": ps.ST_CANCELLED,
        "Traitement trop long": ps.ST_TIMEOUT, "Non publiée": ps.ST_UNPUBLISHED}


class SummaryTest(unittest.TestCase):
    def build(self, *statuses):
        base = rows(max(len(statuses), 1))
        return [with_status(r, CODE[s]) for r, s in zip(base, statuses)]

    def test_texts(self):
        cases = [
            (("Publiée",), "1 couche publiée."),
            (("Publiée",) * 3 + ("Échec",), "3 couches publiées, 1 en échec."),
            (("Publiée", "Publiée", "Échec", "Annulée"), "2 couches publiées, 1 en échec, 1 annulée."),
            (("Échec", "Échec"), "Aucune couche publiée, 2 en échec."),
            ((), "Aucune couche publiée."),
            (("", ""), "Aucune couche publiée."),
            (("Publiée", "Traitement trop long", "Non publiée", "Non publiée"),
             "1 couche publiée, 1 traitement trop long, 2 non publiées."),
            (("Publiée", "Annulée", "Annulée"), "1 couche publiée, 2 annulées."),
        ]
        for statuses, expected in cases:
            self.assertEqual(ps.summary(self.build(*statuses) if statuses else []), expected)

    def test_second_batch_ignores_first(self):
        rs = rows(2)
        rs[1] = with_status(rs[1], "", checked=False)
        rs = ps.mark_waiting(rs)
        rs[0] = with_status(rs[0], ps.ST_PUBLISHED)
        rs = [with_status(rs[0], rs[0].status, checked=False), with_status(rs[1], "", checked=True)]
        rs = ps.mark_waiting(rs)
        self.assertEqual(rs[0].status, "")
        rs[1] = with_status(rs[1], ps.ST_PUBLISHED)
        self.assertEqual(ps.summary(rs), "1 couche publiée.")


class CanPublishSelectableTest(unittest.TestCase):
    def test_ticked_non_selectable_not_counted(self):
        rs = rows(2)
        rs[0] = with_status(rs[0], "", selectable=False)
        self.assertEqual(ps.can_publish(rs, True, False), (True, None))
        rs[1] = with_status(rs[1], "", selectable=False)
        self.assertEqual(ps.can_publish(rs, True, False), (False, texts.TICK_AT_LEAST_ONE))


if __name__ == "__main__":
    unittest.main()
