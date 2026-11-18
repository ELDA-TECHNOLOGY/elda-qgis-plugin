"""Duplicate detection against the layers that already exist in ELDA, not only this session's memory."""
from collections import namedtuple

from elda_qgis.core.publish.gis import GisApi, LayerRef
from elda_qgis.ui import texts
from elda_qgis.ui.publish import state as ps
from tests.core.fakes import logged, resp
from tests.ui.publish.test_state import rows

L = namedtuple("L", "id name folder_id status")


def named(*names):
    out = rows(len(names))
    return [r.__class__(**{**r.__dict__, "name": n}) for r, n in zip(out, names)]


def test_same_name_in_the_same_folder_is_a_duplicate_whatever_the_case_or_spacing():
    plan = ps.duplicate_plan(named("Pistes  Été"), [L(9, " pistes été ", 5, "ready")], 5, {})
    assert plan.names == ["Pistes Été"] or plan.names == ["Pistes  Été"]
    assert plan.targets == {"id0": 9}
    assert plan.several is False


def test_same_name_in_another_folder_is_not_a_duplicate():
    plan = ps.duplicate_plan(named("Pistes"), [L(9, "Pistes", 6, "ready")], 5, {})
    assert plan.names == [] and plan.targets == {}


def test_root_folder_matches_root_only():
    layers = [L(9, "Pistes", None, "ready"), L(10, "Pistes", 5, "ready")]
    assert ps.duplicate_plan(named("Pistes"), layers, None, {}).targets == {"id0": 9}


def test_two_layers_with_that_name_cannot_be_replaced():
    layers = [L(9, "Pistes", 5, "ready"), L(10, "Pistes", 5, "ready")]
    plan = ps.duplicate_plan(named("Pistes"), layers, 5, {})
    assert plan.names == ["Pistes"] and plan.targets is None and plan.several is True


def test_a_layer_still_processed_or_failed_cannot_be_replaced():
    for status in ("ingesting", "failed"):
        plan = ps.duplicate_plan(named("Pistes"), [L(9, "Pistes", 5, status)], 5, {})
        assert plan.names == ["Pistes"] and plan.targets is None and plan.several is False


def test_one_blocked_layer_blocks_replacement_for_the_whole_batch():
    layers = [L(9, "A", 5, "ready"), L(10, "B", 5, "ingesting")]
    assert ps.duplicate_plan(named("A", "B"), layers, 5, {}).targets is None


def test_unticked_layers_are_ignored():
    r = named("Pistes")
    r[0] = r[0].__class__(**{**r[0].__dict__, "checked": False})
    assert ps.duplicate_plan(r, [L(9, "Pistes", 5, "ready")], 5, {}).names == []


def test_session_memory_still_counts_when_the_list_is_unavailable():
    plan = ps.duplicate_plan(named("Pistes"), None, 5, {"id0": 120})
    assert plan.names == ["Pistes"] and plan.targets == {"id0": 120}


def test_the_layer_found_in_elda_wins_over_the_session_memory():
    plan = ps.duplicate_plan(named("Pistes"), [L(9, "Pistes", 5, "ready")], 5, {"id0": 120})
    assert plan.targets == {"id0": 9}


def test_no_duplicate_no_question():
    plan = ps.duplicate_plan(named("Pistes"), [L(9, "Autre", 5, "ready")], 5, {})
    assert plan.names == [] and plan.targets == {} and plan.several is False


def test_site_layers_reads_the_fields_the_plugin_needs_and_skips_bad_rows():
    body = [
        {"id": 9, "name": " Pistes ", "folder_id": 5, "status": "ready", "data": None, "feature_count": 3},
        {"id": "10", "name": "Racine", "folder_id": None, "status": "ingesting"},
        {"id": None, "name": "x"},
        "junk",
    ]
    api, transport = logged([resp(200, body)])
    layers = GisApi(api).site_layers(21)
    assert layers == [LayerRef(9, " Pistes ", 5, "ready"), LayerRef(10, "Racine", None, "ingesting")]
    assert transport.requests[-1].url.endswith("/api/operational-layers/resort/21")
    assert transport.requests[-1].method == "GET"


def test_questions_speak_of_elda_not_of_the_session():
    assert "existe déjà dans ELDA" in texts.choose_duplicate(["Pistes"])
    assert "existe déjà dans ELDA" in texts.confirm_duplicate(["Pistes"], False)
    assert "Plusieurs" in texts.confirm_duplicate(["Pistes"], True)
