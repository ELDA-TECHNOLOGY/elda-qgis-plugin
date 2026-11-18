from __future__ import annotations

import unittest
from collections import namedtuple

from elda_qgis.core.publish.vector import Outcome
from elda_qgis.core.session.rights import Rights
from elda_qgis.ui.publish import state as ps
from elda_qgis.ui import texts

L = namedtuple("L", "layer_id name kind feature_count")
YES, NO = Rights(True, True), Rights(False, True)
FINISHED = (ps.ST_PUBLISHED, ps.ST_FAILED, ps.ST_CANCELLED, ps.ST_TIMEOUT, ps.ST_UNPUBLISHED)


def fresh(*names, rights=YES):
    return ps.rows_for([L(n, n, "vector", 1) for n in names], rights)


def ticked(*names):
    out = fresh(*names)
    for n in names:
        out = ps.set_checked(out, n, True)
    return out


def statuses(rows):
    return [r.status for r in rows]


class LateStepTest(unittest.TestCase):
    def test_finished_row_ignores_steps(self):
        for code in FINISHED:
            row = ps.update_row(fresh("a"), "a", lambda r: r.__class__(**{**r.__dict__, "status": code}))[0]
            for step in ("initiate", "upload", "processing"):
                self.assertIs(ps.apply_step(row, step, 5, 10), row, (code, step))

    def test_published_row_receiving_upload_stays_published(self):
        (row,) = ps.update_row(fresh("a"), "a", lambda r: ps.apply_outcome(r, Outcome("a", "published", 3, None)))
        self.assertEqual(ps.apply_step(row, "upload", 1, 2).status, ps.ST_PUBLISHED)


class RowEditTest(unittest.TestCase):
    def test_set_checked(self):
        rows = ps.set_checked(fresh("a", "b"), "b", True)
        self.assertEqual([r.checked for r in rows], [False, True])

    def test_not_selectable_never_checked(self):
        rows = ps.set_checked(fresh("a", rights=NO), "a", True)
        self.assertFalse(rows[0].checked)

    def test_rename_normalises(self):
        rows = ps.rename(fresh("a"), "a", "  Pistes   été / 2026  ")
        self.assertEqual(rows[0].name, "Pistes été / 2026")
        self.assertEqual(ps.rename(fresh("a"), "a", "   ")[0].name, "Couche QGIS")

    def test_rename_refused_when_not_selectable(self):
        self.assertEqual(ps.rename(fresh("a", rights=NO), "a", "x")[0].name, "a")

    def test_fail_row(self):
        (row,) = ps.fail_row(fresh("a"), "a", "boom")
        self.assertEqual((row.status, row.message, row.percent), (ps.ST_FAILED, "boom", None))

    def test_unknown_key_untouched(self):
        rows = fresh("a")
        self.assertEqual(ps.fail_row(rows, "zz", "boom"), rows)


class MergeTest(unittest.TestCase):
    def test_keeps_ticks_edited_names_and_status_of_present_layers(self):
        old = ps.rename(ticked("a", "b"), "a", "Mon nom")
        old = ps.fail_row(old, "b", "boom")
        new = ps.rows_for([L("b", "B2", "vector", 1), L("c", "c", "vector", 1), L("a", "A2", "vector", 1)], YES)
        got = ps.merge_rows(old, new, {"a"})
        self.assertEqual([r.key for r in got], ["b", "c", "a"])
        self.assertEqual([r.checked for r in got], [True, False, True])
        self.assertEqual([r.name for r in got], ["B2", "c", "Mon nom"])
        self.assertEqual((got[0].status, got[0].message), (ps.ST_FAILED, "boom"))

    def test_tick_dropped_when_no_longer_selectable(self):
        got = ps.merge_rows(ticked("a"), fresh("a", rights=NO), set())
        self.assertFalse(got[0].checked)
        self.assertFalse(got[0].selectable)

    def test_edited_name_dropped_when_no_longer_selectable(self):
        old = ps.rename(fresh("a"), "a", "Mon nom")
        self.assertEqual(ps.merge_rows(old, fresh("a", rights=NO), {"a"})[0].name, "a")


class BatchQueueTest(unittest.TestCase):
    def test_next_waiting_in_table_order(self):
        rows = ps.mark_waiting(ps.set_checked(ticked("a", "b", "c"), "a", False))
        self.assertEqual(ps.next_waiting(rows), "b")
        rows = ps.update_row(rows, "b", lambda r: ps.apply_step(r, "initiate", 0, 0))
        self.assertEqual(ps.next_waiting(rows), "c")

    def test_nothing_waiting(self):
        self.assertIsNone(ps.next_waiting(fresh("a")))

    def test_advance_to_next(self):
        rows = ps.mark_waiting(ticked("a", "b"))
        rows = ps.update_row(rows, "a", lambda r: ps.apply_outcome(r, Outcome("a", "published", 1, None)))
        got, nxt = ps.advance(rows, "a", cancelled=False)
        self.assertEqual((statuses(got), nxt), ([ps.ST_PUBLISHED, ps.ST_WAITING], "b"))

    def test_advance_last_row_ends(self):
        rows = ps.fail_row(ps.mark_waiting(ticked("a")), "a", "x")
        self.assertEqual(ps.advance(rows, "a", cancelled=False)[1], None)

    def test_cancel_marks_rest_and_stops(self):
        rows = ps.mark_waiting(ticked("a", "b", "c"))
        rows = ps.update_row(rows, "a", lambda r: ps.apply_outcome(r, Outcome("a", "published", 1, None)))
        got, nxt = ps.advance(rows, "a", cancelled=True)
        self.assertEqual((statuses(got), nxt), ([ps.ST_PUBLISHED, ps.ST_CANCELLED, ps.ST_CANCELLED], None))

    def test_cancel_during_export_marks_current_row_too(self):
        rows = ps.mark_waiting(ticked("a", "b"))
        rows = ps.update_row(rows, "a", lambda r: ps.apply_step(r, "initiate", 0, 0))
        got, nxt = ps.advance(rows, "a", cancelled=True)
        self.assertEqual((statuses(got), nxt), ([ps.ST_CANCELLED, ps.ST_CANCELLED], None))

    def test_export_failure_continues(self):
        rows = ps.mark_waiting(ticked("a", "b"))
        rows = ps.fail_row(rows, "a", "export")
        got, nxt = ps.advance(rows, "a", cancelled=False)
        self.assertEqual((statuses(got), nxt, got[0].message), ([ps.ST_FAILED, ps.ST_WAITING], "b", "export"))


class FolderNodeTest(unittest.TestCase):
    def test_root(self):
        root = ps.FolderNode(None, None)
        self.assertEqual(root.label(), texts.SITE_ROOT)

    def test_child_path(self):
        a = ps.FolderNode(1, None).child(2, "Pistes")
        b = a.child(3, "Été")
        self.assertEqual((b.folder_id, b.label()), (3, "Pistes / Été"))
        self.assertEqual(ps.FolderNode(None, None).child(4, "").label(), "(sans nom)")

    def test_load_once_and_retry_after_failure(self):
        node = ps.FolderNode(1, None)
        self.assertTrue(node.start_load())
        self.assertFalse(node.start_load())
        node.load_failed()
        self.assertTrue(node.start_load())
        node.loaded()
        self.assertFalse(node.start_load())


class VisibilitySummaryTest(unittest.TestCase):
    def test_texts(self):
        self.assertEqual(texts.visibility_summary(False, 3, 4), "Tout le site")
        self.assertEqual(texts.visibility_summary(True, 2, 1), "Restreint : 2 groupes, 1 utilisateur")
        self.assertEqual(texts.visibility_summary(True, 1, 0), "Restreint : 1 groupe")
        self.assertEqual(texts.visibility_summary(True, 0, 3), "Restreint : 3 utilisateurs")
        self.assertEqual(texts.visibility_summary(True, 0, 0), "Restreint : vous seul")

    def test_confirm_slow(self):
        self.assertEqual(
            texts.confirm_slow(75),
            "L'envoi devrait durer environ 75 minutes, au-delà de la limite d'une heure. Continuer ?",
        )

    def test_count_and_kind(self):
        self.assertEqual((texts.feature_count(None), texts.feature_count(1200)), ("", "1200"))
        self.assertEqual([texts.kind_text(k) for k in ("vector", "raster", "other")], ["Vecteur", "Raster", "Autre"])
