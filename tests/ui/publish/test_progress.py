import pytest

from elda_qgis.ui.publish import state as ps
from tests.ui.publish.test_state import rows, with_status


def one(status, percent=None):
    return [with_status(rows(1)[0], status, percent=percent)]


def test_bar_is_hidden_outside_a_batch():
    assert ps.progress(rows(2), 0) is None


def test_bar_only_moves_forward_through_one_layer():
    steps = [
        ps.progress(one(ps.ST_WAITING), 0),
        ps.progress(one(ps.ST_PREPARING), 0),
        ps.progress(one(ps.ST_UPLOADING, 0), 0),
        ps.progress(one(ps.ST_UPLOADING, 50), 0),
        ps.progress(one(ps.ST_UPLOADING, 100), 0),
        ps.progress(one(ps.ST_PROCESSING), 0),
        ps.progress(one(ps.ST_PROCESSING), 10),
        ps.progress(one(ps.ST_PROCESSING), 60),
        ps.progress(one(ps.ST_PROCESSING), 1800),
        ps.progress(one(ps.ST_PUBLISHED), 0),
    ]
    assert steps == sorted(steps)
    assert steps[0] == 0 and steps[-1] == 100


def test_upload_end_is_not_the_end_of_the_bar():
    assert ps.progress(one(ps.ST_UPLOADING, 100), 0) <= 60


def test_processing_keeps_moving_but_never_claims_to_be_done():
    early, late = ps.progress(one(ps.ST_PROCESSING), 5), ps.progress(one(ps.ST_PROCESSING), 1800)
    assert early < late < 100


@pytest.mark.parametrize("status", [ps.ST_FAILED, ps.ST_CANCELLED, ps.ST_TIMEOUT, ps.ST_UNPUBLISHED])
def test_a_finished_layer_counts_as_done_whatever_its_result(status):
    assert ps.progress(one(status), 0) == 100


def test_batch_of_two_is_half_done_after_the_first_layer():
    r = rows(2)
    r[0] = with_status(r[0], ps.ST_PUBLISHED)
    r[1] = with_status(r[1], ps.ST_WAITING)
    assert ps.progress(r, 0) == 50


def test_layers_left_out_of_the_batch_do_not_count():
    r = rows(2)
    r[0] = with_status(r[0], ps.ST_PUBLISHED)
    assert ps.progress(r, 0) == 100
