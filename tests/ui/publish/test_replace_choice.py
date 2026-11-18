from elda_qgis.ui import texts
from elda_qgis.ui.publish import state as ps
from tests.ui.publish.test_state import rows


def test_every_ticked_layer_already_published_can_be_replaced():
    assert ps.duplicate_plan(rows(2), None, None, {"id0": 41, "id1": 42}).targets == {"id0": 41, "id1": 42}


def test_layers_never_sent_are_left_out():
    assert ps.duplicate_plan(rows(2), None, None, {"id1": 42}).targets == {"id1": 42}


def test_no_replacement_offered_when_one_layer_is_still_being_processed():
    assert ps.duplicate_plan(rows(2), None, None, {"id0": 41, "id1": None}).targets is None


def test_unticked_layers_do_not_count():
    r = rows(2)
    r[1] = r[1].__class__(**{**r[1].__dict__, "checked": False})
    assert ps.duplicate_plan(r, None, None, {"id0": 41, "id1": None}).targets == {"id0": 41}


def test_question_explains_what_replacing_keeps():
    text = texts.choose_duplicate(["Pistes"])
    assert "« Pistes »" in text and "dossier" in text and "style" in text
