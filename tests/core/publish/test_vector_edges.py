import pytest

from elda_qgis.core.publish import vector
from elda_qgis.core.errors import RequestRefused, ServerError
from tests.core.publish.test_vector import LAYER_ID, FakeGis, Harness


class _Case:
    """Minimal stand-in for the TestCase the harness registers its cleanup on."""

    def __init__(self):
        self.cleanups = []

    def addCleanup(self, fn):
        self.cleanups.append(fn)


@pytest.fixture
def go():
    case = _Case()

    def run(gis, **kw):
        h = Harness(case, gis, **kw)
        return h, h.run()

    yield run
    for fn in case.cleanups:
        fn()


def test_finalize_plain_500_aborts_instead_of_polling(go):
    gis = FakeGis(vector_finalize=[ServerError(500)])
    _, out = go(gis)
    assert (out.status, out.layer_id) == ("failed", None)
    assert gis.calls.count(("vector_abort", LAYER_ID)) == 1
    assert gis.count("layer_status") == 0


@pytest.mark.parametrize("status", [502, 503, 504])
def test_finalize_gateway_error_still_polls(go, status):
    gis = FakeGis(vector_finalize=[ServerError(status)], layer_status=["ready"])
    _, out = go(gis)
    assert out.status == "published"
    assert gis.count("vector_abort") == 0


def test_poll_refused_stops_at_once_and_keeps_the_layer(go):
    gis = FakeGis(layer_status=[RequestRefused(403, "Forbidden")])
    h, out = go(gis)
    assert (out.status, out.layer_id) == ("timeout", LAYER_ID)
    assert "Forbidden" not in out.message_fr
    assert gis.count("layer_status") == 1
    assert gis.count("delete_failed_vector") == 0
    assert h.sleeps == []


def test_initiate_404_says_the_folder_is_gone(go):
    gis = FakeGis(vector_initiate=[RequestRefused(404, "Folder not found")])
    _, out = go(gis)
    assert out.status == "failed"
    assert "dossier" in out.message_fr and "Folder" not in out.message_fr


def test_file_over_the_server_limit_is_refused_before_any_request(go, monkeypatch):
    monkeypatch.setattr(vector, "_file_size", lambda path: vector.MAX_FILE_BYTES + 1)
    gis = FakeGis()
    _, out = go(gis)
    assert out.status == "failed"
    assert gis.count("vector_initiate") == 0


def test_file_at_the_server_limit_goes_through(go, monkeypatch):
    monkeypatch.setattr(vector, "_file_size", lambda path: vector.MAX_FILE_BYTES)
    gis = FakeGis()
    _, out = go(gis)
    assert out.status == "published"
