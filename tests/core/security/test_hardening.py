"""One test per attack of the security review that the pure core can refuse."""
import json
import time

import pytest

from elda_qgis.core.errors import ServerError, UnsafeUrl
from elda_qgis.core.net import server_url
from elda_qgis.core.net.http import Caller, Request, Response, _retry_after
from elda_qgis.core.net.redact import scrub, without_paths
from elda_qgis.core.publish.gis import MAX_CHUNK_BYTES, GisApi
from tests.core.fakes import logged, resp

SIGNED = "https://s3.example/bucket/key?X-Amz-Signature=abc"


def test_logout_hands_the_refresh_token_back_so_the_server_revokes_it():
    api, transport = logged([resp(200, {})])
    api.logout()
    assert transport.requests[1].url.endswith("/api/users/logout")
    assert transport.requests[1].json == {"token": "rt-secret-456"}


def test_a_hostile_error_text_cannot_freeze_the_redaction():
    hostile = "eyJ" * 400_000
    start = time.perf_counter()
    scrub(hostile)
    assert time.perf_counter() - start < 1.0


def test_tokens_are_still_masked_after_the_regex_fix():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJpZCI6N30.c2lnbmF0dXJl"
    assert jwt not in scrub("token: %s end" % jwt)
    assert "abc123" not in scrub("refresh_token=abc123&x=1")
    assert "abc123" not in scrub("https://s3/x?Signature=abc123&Expires=1")
    assert "dXNlcjpwdw==" not in scrub("Authorization: Basic dXNlcjpwdw==")


def test_server_error_text_shown_to_the_user_is_bounded():
    transport_reply = Response(400, {}, json.dumps({"message": "x" * 100_000}).encode())

    class One:
        def send(self, request):
            return transport_reply

    with pytest.raises(Exception) as caught:
        Caller(One(), sleep=lambda s: None).call(Request("GET", "https://elda.example/x"))
    assert len(caught.value.message_fr) <= 501


@pytest.mark.parametrize("body", [b"[" * 100_000, b"\xff\xfe", b"{", b""])
def test_unparsable_json_is_a_server_error_never_a_crash(body):
    with pytest.raises(ServerError):
        Response(200, {}, body).json()


@pytest.mark.parametrize("raw, expected", [("30", 30), ("9999", 60), ("\u00b2", None), ("12345", None), ("-1", None), ("1.5", None)])
def test_retry_after_accepts_only_short_ascii_digits(raw, expected):
    assert _retry_after(Response(429, {"Retry-After": raw}, b"")) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:80@evil.example/x",
        "https://user:pw@s3.example/x",
        "http://s3.example/x",
        "file:///etc/passwd",
        "ftp://s3.example/x",
        "https:///x",
        "https://s3.example\\@evil.example/x",
        "https://s3 .example/x",
        "",
    ],
)
def test_storage_address_refused(url):
    with pytest.raises(UnsafeUrl):
        server_url.check_storage(url, api_is_loopback=True)


def test_storage_on_this_machine_only_when_the_api_is_on_this_machine_too():
    server_url.check_storage("http://localhost:9000/bucket/key", api_is_loopback=True)
    server_url.check_storage(SIGNED, api_is_loopback=False)
    with pytest.raises(UnsafeUrl):
        server_url.check_storage("http://localhost:9000/bucket/key", api_is_loopback=False)
    with pytest.raises(UnsafeUrl):
        server_url.check_storage("http://127.0.0.1:6379/", api_is_loopback=False)


def test_upload_start_refuses_a_storage_address_on_the_users_machine():
    api, _ = logged([resp(200, {"layer_id": 1, "mode": "single", "put_url": "http://localhost:6379/x"})])
    with pytest.raises(ServerError):
        GisApi(api).vector_initiate("a.gpkg", "a", 10, None, [], [])


def test_upload_start_refuses_an_oversized_chunk():
    part = [{"part_number": 1, "url": SIGNED}]
    body = {"layer_id": 1, "mode": "multipart", "chunk_size": MAX_CHUNK_BYTES + 1, "presigned_part_urls": part}
    api, _ = logged([resp(200, body)])
    with pytest.raises(ServerError):
        GisApi(api).vector_initiate("a.gpkg", "a", 10, None, [], [])


def test_only_production_is_a_known_server():
    assert list(server_url.KNOWN) == ["https://data.eldatechnology.fr"]


def test_response_repr_never_prints_the_body():
    assert "secret" not in repr(Response(200, {"Set-Cookie": "secret"}, b'{"accessToken":"secret"}'))


@pytest.mark.parametrize(
    "text",
    [r"\\serveur\partage\Léa Martin\layer.gpkg", "/Users/Léa Martin/tmp/elda x/layer.gpkg"],
)
def test_network_shares_and_paths_with_spaces_are_removed(text):
    cleaned = without_paths("Echec " + text)
    assert "Martin" not in cleaned and "layer.gpkg" not in cleaned
