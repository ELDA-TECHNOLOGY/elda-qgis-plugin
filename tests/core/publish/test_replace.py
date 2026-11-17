import pytest

from elda_qgis.core.errors import NetworkError, RequestRefused, ServerError, SessionLost
from elda_qgis.core.publish import vector
from elda_qgis.core.publish.gis import GisApi
from elda_qgis.core.publish.vector import Job, Outcome, publish_vector
from tests.core.fakes import logged, resp


class Gis:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def replace_features(self, layer_id, geojson):
        self.calls.append(("replace_features", layer_id, geojson))
        if isinstance(self.result, Exception):
            raise self.result

    def __getattr__(self, name):
        raise AssertionError("replace must not call %s" % name)


ONE = b'{"type":"FeatureCollection","features":[{"type": "Feature","geometry":null,"properties":{}}]}'


def run(tmp_path, gis, content=ONE, cancelled=False):
    path = tmp_path / "layer.geojson"
    path.write_bytes(content)
    steps = []
    job = Job("k1", str(path), "Pistes", 7, [], [], replace_layer_id=42)
    out = publish_vector(job, gis, "caller", lambda *a: steps.append(a), lambda: cancelled, lambda m: True)
    return out, steps


def test_replace_sends_the_file_to_the_existing_layer_and_creates_nothing(tmp_path):
    gis = Gis()
    out, steps = run(tmp_path, gis)
    assert out == Outcome("k1", "published", 42, None)
    assert gis.calls == [("replace_features", 42, ONE)]
    assert steps == [("processing", 0, 0)]


def test_replace_refuses_a_file_over_the_server_limit_before_sending(tmp_path, monkeypatch):
    monkeypatch.setattr(vector, "MAX_REPLACE_BYTES", 5)
    gis = Gis()
    out, _ = run(tmp_path, gis)
    assert out.status == "failed" and "nouvelle couche" in out.message_fr
    assert gis.calls == []


def test_replace_cancelled_before_sending_changes_nothing(tmp_path):
    gis = Gis()
    out, _ = run(tmp_path, gis, cancelled=True)
    assert out.status == "cancelled" and gis.calls == []


@pytest.mark.parametrize(
    "error, word",
    [
        (RequestRefused(404, "Operational layer not found"), "n'existe plus"),
        (RequestRefused(413, "request entity too large"), "volumineuse"),
        (RequestRefused(403, "Accès refusé"), "Accès refusé"),
        (NetworkError(), "Vérifiez"),
        (ServerError(500), "Vérifiez"),
    ],
)
def test_replace_failures_say_what_to_do(tmp_path, error, word):
    out, _ = run(tmp_path, Gis(error))
    assert out.status == "failed" and word in out.message_fr
    assert "not found" not in out.message_fr and "entity" not in out.message_fr


def test_replace_session_lost_goes_up(tmp_path):
    with pytest.raises(SessionLost):
        run(tmp_path, Gis(SessionLost()))


def test_replace_request_is_one_put_with_the_raw_file_never_retried():
    api, transport = logged([resp(200, {"message": "ok"})])
    GisApi(api).replace_features(42, b'{"type":"FeatureCollection","features":[]}')
    request = transport.requests[-1]
    assert (request.method, request.url) == ("PUT", "https://elda.example/api/operational-layers/42/features")
    assert request.body == b'{"type":"FeatureCollection","features":[]}' and request.json is None
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.timeout >= 300


def test_replace_request_failure_is_not_sent_twice():
    api, transport = logged([resp(500, {}), resp(200, {})])
    with pytest.raises(ServerError):
        GisApi(api).replace_features(42, b"{}")
    assert len(transport.requests) == 2


@pytest.mark.parametrize(
    "content",
    [
        b'{"type":"FeatureCollection","features":[]}',
        b'{ "type": "FeatureCollection", "name": "layer", "features": [\n] }',
        b"not json at all",
    ],
)
def test_replace_never_sends_a_file_without_any_feature(tmp_path, content):
    gis = Gis()
    out, _ = run(tmp_path, gis, content=content)
    assert out.status == "failed" and "aucune entité" in out.message_fr
    assert gis.calls == []
