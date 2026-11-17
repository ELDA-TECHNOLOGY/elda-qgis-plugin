import pytest

from elda_qgis.core.errors import RequestRefused, SessionLost
from elda_qgis.core.publish.gis import GisApi
from elda_qgis.core.publish.vector import Job
from tests.core.fakes import logged, resp
from tests.core.publish.test_vector import LAYER_ID, FakeGis, Harness
from tests.core.publish.test_vector_edges import _Case

STYLE = {"polygon": {"fillColor": "#112233"}}


class StyledGis(FakeGis):
    def save_style(self, layer_id, style):
        return self._do("save_style", layer_id, style)


@pytest.fixture
def go():
    case = _Case()

    def run(gis, style=STYLE, notes=()):
        h = Harness(case, gis)
        h.job = Job("k1", h.path, "Pistes", 7, [], [], None, style, tuple(notes))
        return h.run()

    yield run
    for fn in case.cleanups:
        fn()


def test_style_is_saved_once_the_layer_is_ready_and_not_before(go):
    gis = StyledGis(layer_status=["ingesting", "ready"])
    out = go(gis)
    assert (out.status, out.layer_id, out.message_fr) == ("published", LAYER_ID, None)
    names = [n for n in gis.names() if n != "is_cancelled"]
    assert names[-2:] == ["layer_status", "save_style"]
    assert ("save_style", LAYER_ID, STYLE) in gis.calls


def test_no_style_no_call(go):
    gis = StyledGis()
    assert go(gis, style=None).message_fr is None
    assert gis.count("save_style") == 0


def test_notes_about_the_style_come_back_with_a_published_layer(go):
    out = go(StyledGis(), notes=["Symbole à plusieurs couches : seule la première est reprise."])
    assert out.status == "published" and "plusieurs couches" in out.message_fr


def test_a_style_that_cannot_be_saved_never_fails_the_publication(go):
    out = go(StyledGis(save_style=[RequestRefused(500, "boom")]))
    assert out.status == "published" and out.layer_id == LAYER_ID
    assert "style" in out.message_fr and "boom" not in out.message_fr


def test_style_is_not_saved_on_a_failed_import(go):
    gis = StyledGis(layer_status=["failed"])
    assert go(gis).status == "failed"
    assert gis.count("save_style") == 0


@pytest.mark.parametrize("error", [SessionLost(), TypeError("not serialisable"), RuntimeError("x")])
def test_nothing_raised_while_saving_the_style_can_undo_a_publication(go, error):
    out = go(StyledGis(save_style=[error]))
    assert out.status == "published" and out.layer_id == LAYER_ID and "style" in out.message_fr


def test_a_layer_left_in_processing_says_its_style_was_not_carried_over(go):
    out = go(StyledGis(layer_status=["ingesting"]))
    assert out.status == "timeout" and "style" in out.message_fr


def test_save_style_sends_only_the_style_as_an_object():
    api, transport = logged([resp(200, {"message": "ok"})])
    GisApi(api).save_style(42, STYLE)
    request = transport.requests[-1]
    assert (request.method, request.url) == ("PUT", "https://elda.example/api/operational-layers/42")
    assert request.json == {"style": STYLE}
