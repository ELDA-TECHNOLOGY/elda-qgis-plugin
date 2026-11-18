import pytest

from elda_qgis.core.publish.vector import Outcome
from elda_qgis.ui import texts
from elda_qgis.ui.publish import state as ps
from tests.ui.publish.test_state import rows


@pytest.mark.parametrize(
    "outcome, reached",
    [
        (Outcome("k", "published", 42, None), True),
        (Outcome("k", "timeout", 42, "long"), True),
        (Outcome("k", "cancelled", 42, "still processing"), True),
        (Outcome("k", "cancelled", None, "cancelled"), False),
        (Outcome("k", "failed", None, "boom"), False),
        (Outcome("k", "failed", 42, "processing failed, removed"), False),
    ],
)
def test_which_outcomes_leave_a_layer_on_elda(outcome, reached):
    assert ps.reached_elda(outcome) is reached


def test_only_ticked_layers_already_sent_are_reported():
    r = rows(3)
    r[2] = r[2].__class__(**{**r[2].__dict__, "checked": False})
    assert ps.duplicate_plan(r, None, None, {"id0": 1, "id2": 2, "other": 3}).names == ["Couche 0"]


def test_nothing_reported_on_a_first_publish():
    assert ps.duplicate_plan(rows(2), None, None, {}).names == []


def test_question_names_the_layers_and_the_consequence():
    text = texts.confirm_duplicate(["Pistes", "Enneigeurs"], False)
    assert "« Pistes », « Enneigeurs »" in text and "doublon" in text
