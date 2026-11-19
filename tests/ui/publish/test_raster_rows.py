"""Raster rows in the publish table: rights, type choice, duplicates that can only be new rasters."""
from collections import namedtuple

from elda_qgis.core.publish.raster_checks import RasterInfo
from elda_qgis.core.session.rights import Rights
from elda_qgis.ui import texts
from elda_qgis.ui.publish import state as ps

P = namedtuple("P", "layer_id name kind feature_count raster")
E = namedtuple("E", "id name folder_id status")
ALL, VECTOR_ONLY = Rights(True, True), Rights(True, False)
ORTHO = RasterInfo("/d/ortho.tif", 3, ("Byte",) * 3, True, 10)
DTM = RasterInfo("/d/mnt.tif", 1, ("Float32",), True, 10)


def rows(*layers, rights=ALL, checked=True):
    out = ps.rows_for(list(layers), rights)
    return [r.__class__(**{**r.__dict__, "checked": checked and r.selectable}) for r in out]


def test_a_raster_is_selectable_with_the_raster_right_only():
    (yes,) = ps.rows_for([P("r", "MNT", "raster", None, DTM)], ALL)
    (no,) = ps.rows_for([P("r", "MNT", "raster", None, DTM)], VECTOR_ONLY)
    assert yes.selectable and yes.reason is None
    assert not no.selectable and no.reason == texts.NO_RASTER_RIGHT


def test_an_8_bit_colour_image_gets_its_type_and_a_terrain_model_must_be_chosen():
    ortho, dtm = ps.rows_for([P("o", "Ortho", "raster", None, ORTHO), P("d", "MNT", "raster", None, DTM)], ALL)
    assert ortho.raster_type == "ortho_rgb" and dtm.raster_type is None


def test_other_layer_kinds_stay_unavailable():
    (row,) = ps.rows_for([P("x", "WMS", "other", None, None)], ALL)
    assert not row.selectable and row.reason == texts.COMING_SOON


def test_publishing_waits_for_every_ticked_raster_to_have_a_type():
    r = rows(P("d", "MNT", "raster", None, DTM))
    assert ps.can_publish(r, True, False) == (False, texts.CHOOSE_RASTER_TYPE)
    r = ps.set_raster_type(r, "d", "dtm")
    assert ps.can_publish(r, True, False) == (True, None)
    r = ps.set_raster_type(r, "d", None)
    assert ps.can_publish(r, True, False)[0] is False


def test_an_unticked_raster_without_type_does_not_block():
    r = rows(P("v", "Pistes", "vector", 3, None), P("d", "MNT", "raster", None, DTM))
    r = ps.set_checked(r, "d", False)
    assert ps.can_publish(r, True, False) == (True, None)


def test_the_chosen_type_survives_a_refresh_of_the_table():
    before = ps.set_raster_type(rows(P("d", "MNT", "raster", None, DTM)), "d", "dsm")
    fresh = ps.rows_for([P("d", "MNT", "raster", None, DTM)], ALL)
    assert ps.merge_rows(before, fresh, set())[0].raster_type == "dsm"


def test_a_raster_with_the_same_name_is_a_duplicate_that_can_only_be_created_again():
    r = ps.set_raster_type(rows(P("d", "MNT 2025", "raster", None, DTM)), "d", "dtm")
    plan = ps.duplicate_plan(r, [], 5, {}, rasters=[E(9, "mnt 2025", 5, "ready")])
    assert plan.names == ["MNT 2025"] and plan.targets is None and plan.why == "raster"


def test_a_raster_never_matches_a_vector_layer_of_the_same_name_nor_the_reverse():
    r = rows(P("d", "Zone", "raster", None, DTM), P("v", "Zone", "vector", 3, None))
    r = ps.set_raster_type(r, "d", "dtm")
    plan = ps.duplicate_plan(r, [E(1, "Zone", 5, "ready")], 5, {}, rasters=[])
    assert plan.names == ["Zone"] and plan.targets == {"v": 1}


def test_mixed_duplicates_keep_replacement_for_the_vector_layer_and_say_so_for_the_raster():
    r = rows(P("d", "MNT", "raster", None, DTM), P("v", "Pistes", "vector", 3, None))
    r = ps.set_raster_type(r, "d", "dtm")
    plan = ps.duplicate_plan(r, [E(1, "Pistes", 5, "ready")], 5, {}, rasters=[E(9, "MNT", 5, "ready")])
    assert plan.targets == {"v": 1} and plan.raster_names == ["MNT"]
    assert "raster" in texts.choose_duplicate(plan.names, plan.raster_names).lower()


def test_reasons_given_when_replacing_is_not_possible():
    for why in ("several", "busy"):
        assert "remplac" in texts.confirm_duplicate(["X"], why)
    assert "raster" in texts.confirm_duplicate(["MNT"], "raster", ["MNT"]).lower()


def test_a_raster_this_session_already_sent_never_becomes_a_replace_target():
    r = ps.set_raster_type(rows(P("d", "MNT", "raster", None, DTM), P("v", "Pistes", "vector", 3, None)), "d", "dtm")
    plan = ps.duplicate_plan(r, [], 5, {"d": 77, "v": 12}, rasters=[])
    assert plan.targets == {"v": 12} and plan.raster_names == ["MNT"]


def test_a_blocked_vector_duplicate_still_says_what_happens_to_the_raster():
    r = ps.set_raster_type(rows(P("d", "MNT", "raster", None, DTM), P("v", "Pistes", "vector", 3, None)), "d", "dtm")
    plan = ps.duplicate_plan(r, [E(1, "Pistes", 5, "ingesting")], 5, {}, rasters=[E(9, "MNT", 5, "ready")])
    assert plan.targets is None and plan.why == "busy"
    text = texts.confirm_duplicate(plan.names, plan.why, plan.raster_names)
    assert "traitement" in text and "raster" in text.lower() and "« MNT »" in text


def test_several_rasters_are_listed_in_correct_french():
    text = texts.choose_duplicate(["A", "B", "C"], ["A", "B"])
    assert "« A », « B »" in text and "sera créé" not in text


def test_refusal_messages_send_to_the_right_qgis_menus():
    from elda_qgis.core.publish import raster_checks as rc

    assert "Image rendue" in rc.NOT_8_BIT and "Byte" not in rc.NOT_8_BIT
    assert "Enregistrer sous" in rc.NO_CRS


def test_check_all_only_takes_the_layers_the_account_may_publish():
    mixed = rows(P("v", "Zones", "vector", 3, None), P("r", "MNT", "raster", None, DTM), rights=VECTOR_ONLY, checked=False)
    assert not ps.all_checked(mixed)
    ticked = ps.set_all_checked(mixed, True)
    assert [r.checked for r in ticked] == [True, False] and ps.all_checked(ticked)
    assert not any(r.checked for r in ps.set_all_checked(ticked, False))
    assert not ps.all_checked([])
