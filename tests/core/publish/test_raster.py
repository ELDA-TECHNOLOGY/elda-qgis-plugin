import pytest

from elda_qgis.core.errors import NetworkError, RequestRefused, ServerError, SessionLost
from elda_qgis.core.publish.gis import GisApi, RasterRef, SinglePut, VectorUpload
from elda_qgis.core.publish.raster import RasterJob, publish_raster
from elda_qgis.core.publish.upload import Cancelled
from elda_qgis.core.publish.vector import Outcome
from tests.core.fakes import logged, resp
from tests.core.publish.test_vector import FakeGis
from tests.core.publish.test_vector_edges import _Case

RID = 77
SIGNED = "https://s3.example/bucket/key?X-Amz-Signature=abc"


class Gis(FakeGis):
    def raster_initiate(self, *args):
        return self._do("raster_initiate", *args, default=VectorUpload(RID, SinglePut(SIGNED)))

    def raster_finalize(self, raster_id, etags):
        return self._do("raster_finalize", raster_id, etags)

    def raster_abort(self, raster_id):
        return self._do("raster_abort", raster_id)

    def raster_status(self, raster_id):
        return self._do("raster_status", raster_id, default="ready")

    def delete_failed_raster(self, raster_id):
        return self._do("delete_failed_raster", raster_id)


class Run:
    def __init__(self, tmp_path, gis, send=None, cancel_when=None):
        self.gis, self.now, self.sleeps, self.steps = gis, 0.0, [], []
        self._send, self.cancel_when = send, cancel_when or (lambda: False)
        path = tmp_path / "mnt.tif"
        path.write_bytes(b"x" * 10)
        self.job = RasterJob("k1", str(path), "  MNT  2025 ", "dtm", 7, [1], [3])

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def send_file(self, caller, path, put, mime, on_progress, is_cancelled, confirm_slow):
        self.gis.calls.append(("send_file", mime))
        if self._send:
            return self._send()
        on_progress(10, 10)
        return None

    def go(self):
        return publish_raster(
            self.job, self.gis, "caller", lambda *a: self.steps.append(a), self.cancel_when, lambda m: True,
            sleep=self.sleep, clock=lambda: self.now, send_file=self.send_file,
        )


def names(gis):
    return [c[0] for c in gis.calls]


def test_success_order_and_arguments(tmp_path):
    gis = Gis(raster_status=["processing", "ready"])
    run = Run(tmp_path, gis)
    assert run.go() == Outcome("k1", "published", RID, None)
    assert names(gis) == ["raster_initiate", "send_file", "raster_finalize", "raster_status", "raster_status"]
    assert gis.calls[0][1:] == ("mnt.tif", "MNT 2025", "dtm", 10, 7, [1], [3])
    assert gis.calls[1] == ("send_file", "image/tiff")
    assert run.steps[0] == ("initiate", 0, 0) and run.steps[-1] == ("processing", 0, 0)


def test_upload_failure_aborts_once_and_never_finalizes(tmp_path):
    def boom():
        raise NetworkError()

    gis = Gis()
    out = Run(tmp_path, gis, send=boom).go()
    assert out.status == "failed" and out.layer_id is None
    assert names(gis).count("raster_abort") == 1 and "raster_finalize" not in names(gis)


def test_cancel_during_upload_aborts(tmp_path):
    def stop():
        raise Cancelled()

    gis = Gis()
    out = Run(tmp_path, gis, send=stop).go()
    assert out.status == "cancelled" and names(gis).count("raster_abort") == 1


def test_processing_failure_removes_the_raster_the_plugin_created(tmp_path):
    gis = Gis(raster_status=["failed"])
    out = Run(tmp_path, gis).go()
    assert out.status == "failed" and ("delete_failed_raster", RID) in gis.calls


def test_a_raster_never_ready_times_out_without_deleting_anything(tmp_path):
    gis = Gis(raster_status=["processing"])
    out = Run(tmp_path, gis).go()
    assert out.status == "timeout" and out.layer_id == RID
    assert "delete_failed_raster" not in names(gis) and "raster_abort" not in names(gis)


def test_cancel_while_elda_processes_leaves_the_raster_alone(tmp_path):
    state = {"n": 0}

    def cancel_after_finalize():
        state["n"] += 1
        return state["n"] > 2

    gis = Gis(raster_status=["processing"])
    out = Run(tmp_path, gis, cancel_when=cancel_after_finalize).go()
    assert out.status == "cancelled" and out.layer_id == RID
    assert "delete_failed_raster" not in names(gis)


def test_a_raster_missing_from_the_list_is_gone(tmp_path):
    gis = Gis(raster_status=[None])
    out = Run(tmp_path, gis).go()
    assert out.status == "failed" and "n'existe plus" in out.message_fr


def test_finalize_gateway_error_still_follows_the_status(tmp_path):
    gis = Gis(raster_finalize=[ServerError(502)], raster_status=["ready"])
    assert Run(tmp_path, gis).go().status == "published"


def test_finalize_refused_aborts(tmp_path):
    gis = Gis(raster_finalize=[RequestRefused(409, "x")])
    out = Run(tmp_path, gis).go()
    assert out.status == "failed" and names(gis).count("raster_abort") == 1


def test_session_lost_goes_up(tmp_path):
    with pytest.raises(SessionLost):
        Run(tmp_path, Gis(raster_initiate=[SessionLost()])).go()


def test_initiate_request_and_answer():
    body = {"raster_id": 77, "upload_id": "u", "s3_key": "k", "mode": "single", "put_url": SIGNED, "expires_in": 3600}
    api, transport = logged([resp(201, body)])
    upload = GisApi(api).raster_initiate("mnt.tif", "MNT", "dtm", 10, None, [], [3])
    assert upload == VectorUpload(77, SinglePut(SIGNED))
    request = transport.requests[-1]
    assert request.url.endswith("/api/gis/raster/initiate") and request.method == "POST"
    assert request.json == {
        "filename": "mnt.tif", "layer_name": "MNT", "raster_type": "dtm", "size": 10, "mime": "image/tiff",
        "description": None, "folder_id": None, "visible_to_users": None, "visible_to_groups": [3],
    }


def test_status_reads_the_list_and_only_this_sites_rasters():
    rows = {"rasters": [
        {"id": 77, "layerName": "MNT", "folderID": 5, "status": "processing", "resort_id": 21},
        {"id": 78, "layerName": "Autre site", "folderID": None, "status": "ready", "resort_id": 99},
        {"id": "x"}, "junk",
    ]}
    api, transport = logged([resp(200, rows), resp(200, rows), resp(200, rows)])
    gis = GisApi(api)
    assert gis.raster_status(77) == "processing"
    assert gis.raster_status(123) is None
    assert gis.site_rasters(21) == [RasterRef(77, "MNT", 5, "processing")]
    assert transport.requests[-1].url.endswith("/api/gis/raster")


def test_finalize_abort_and_delete_routes():
    api, transport = logged([resp(200, {}), resp(200, {}), resp(200, {})])
    gis = GisApi(api)
    gis.raster_finalize(77, [(1, "e1")])
    gis.raster_abort(77)
    gis.delete_failed_raster(77)
    urls = [(r.method, r.url.split("/api/")[1], r.json) for r in transport.requests[-3:]]
    assert urls == [
        ("POST", "gis/raster/finalize/77", {"mode": "multipart", "parts": [{"part_number": 1, "etag": "e1"}]}),
        ("POST", "gis/raster/abort/77", None),
        ("DELETE", "gis/raster/77", None),
    ]
