import pytest

from elda_qgis.core.publish.vector import Outcome
from elda_qgis.ui.publish import state as ps
from tests.ui.publish.test_state import rows, with_status


@pytest.mark.parametrize(
    "outcome, stays_ticked",
    [
        (Outcome("id0", "published", 42, None), False),
        (Outcome("id0", "timeout", 42, "long"), False),
        (Outcome("id0", "cancelled", 42, "still processing"), False),
        (Outcome("id0", "cancelled", None, "cancelled"), True),
        (Outcome("id0", "failed", None, "boom"), True),
        (Outcome("id0", "failed", 42, "processing failed"), True),
    ],
)
def test_a_layer_that_reached_elda_is_unticked(outcome, stays_ticked):
    assert ps.apply_outcome(rows(1)[0], outcome).checked is stays_ticked


def test_retry_after_a_mixed_batch_only_resends_the_failed_layer():
    done = [
        ps.apply_outcome(rows(2)[0], Outcome("id0", "published", 42, None)),
        ps.apply_outcome(rows(2)[1], Outcome("id1", "failed", None, "boom")),
    ]
    assert [r.status for r in ps.mark_waiting(done)] == [ps.ST_IDLE, ps.ST_WAITING]


def test_session_lost_while_processing_does_not_claim_unpublished():
    r = rows(3)
    r[0] = with_status(r[0], ps.ST_PROCESSING)
    r[1] = with_status(r[1], ps.ST_WAITING)
    r[2] = with_status(r[2], ps.ST_WAITING)
    out = ps.mark_session_lost(r, "id0")
    assert [x.status for x in out] == [ps.ST_CANCELLED, ps.ST_UNPUBLISHED, ps.ST_UNPUBLISHED]
    assert out[0].checked is False and out[0].message


def test_session_lost_while_uploading_is_unpublished():
    r = rows(1)
    r[0] = with_status(r[0], ps.ST_UPLOADING)
    out = ps.mark_session_lost(r, "id0")
    assert out[0].status == ps.ST_UNPUBLISHED and out[0].checked is True
