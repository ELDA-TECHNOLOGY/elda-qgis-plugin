import json
import unittest

from elda_qgis.core.errors import NetworkError, RequestRefused, ServerError
from elda_qgis.core.net.http import Caller, Request, Response
from elda_qgis.version import VERSION
from tests.core.fakes import FakeTransport

URL = "https://data.eldatechnology.fr/v1/x"


def resp(status, body=b"", headers=None):
    return Response(status, headers or {}, body)


def make(script):
    transport = FakeTransport(script)
    sleeps = []
    return Caller(transport, sleep=sleeps.append), transport, sleeps


def req():
    return Request("GET", URL, {})


class CallerTest(unittest.TestCase):
    def test_retries_three_times_on_5xx_then_raises(self):
        caller, transport, sleeps = make([resp(503)] * 4)
        with self.assertRaises(ServerError) as ctx:
            caller.call(req())
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(transport.requests), 4)
        self.assertEqual(sleeps, [1, 2, 4])

    def test_retries_on_network_failure_then_succeeds(self):
        caller, transport, sleeps = make([NetworkError(), NetworkError(), resp(200)])
        self.assertEqual(caller.call(req()).status, 200)
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_network_failure_exhausted_raises_network_error(self):
        caller, transport, _ = make([NetworkError()] * 4)
        with self.assertRaises(NetworkError):
            caller.call(req())
        self.assertEqual(len(transport.requests), 4)

    def test_never_retries_a_4xx(self):
        caller, transport, sleeps = make([resp(403, json.dumps({"message": "Interdit"}).encode())])
        with self.assertRaises(RequestRefused) as ctx:
            caller.call(req())
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.message_fr, "Interdit")
        self.assertEqual((len(transport.requests), sleeps), (1, []))

    def test_refused_message_from_error_field_or_generic(self):
        caller, _, _ = make([resp(400, b'{"error": "Mauvais"}')])
        with self.assertRaises(RequestRefused) as ctx:
            caller.call(req())
        self.assertEqual(ctx.exception.message_fr, "Mauvais")
        caller, _, _ = make([resp(404, b"<html>")])
        with self.assertRaises(RequestRefused) as ctx:
            caller.call(req())
        self.assertTrue(ctx.exception.message_fr)
        self.assertNotIn("html", ctx.exception.message_fr)

    def test_waits_retry_after_on_429(self):
        caller, transport, sleeps = make([resp(429, headers={"Retry-After": "7"}), resp(200)])
        self.assertEqual(caller.call(req()).status, 200)
        self.assertEqual(sleeps, [7])
        self.assertEqual(len(transport.requests), 2)

    def test_retry_after_is_capped_at_60(self):
        caller, _, sleeps = make([resp(429, headers={"retry-after": "600"}), resp(200)])
        caller.call(req())
        self.assertEqual(sleeps, [60])

    def test_non_numeric_retry_after_falls_back_to_backoff(self):
        caller, _, sleeps = make([resp(429, headers={"Retry-After": "soon"}), resp(200)])
        caller.call(req())
        self.assertEqual(sleeps, [1])

    def test_429_shares_the_retry_budget(self):
        caller, transport, sleeps = make([resp(429, headers={"Retry-After": "1"})] * 4)
        with self.assertRaises(RequestRefused) as ctx:
            caller.call(req())
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(len(transport.requests), 4)
        self.assertEqual(len(sleeps), 3)

    def test_retry_false_sends_once(self):
        caller, transport, sleeps = make([resp(500)])
        with self.assertRaises(ServerError):
            caller.call(req(), retry=False)
        self.assertEqual((len(transport.requests), sleeps), (1, []))

    def test_retry_false_network_error_sends_once(self):
        caller, transport, _ = make([NetworkError()])
        with self.assertRaises(NetworkError):
            caller.call(req(), retry=False)
        self.assertEqual(len(transport.requests), 1)

    def test_401_is_returned_not_raised(self):
        caller, transport, _ = make([resp(401)])
        self.assertEqual(caller.call(req()).status, 401)
        self.assertEqual(len(transport.requests), 1)

    def test_user_agent_is_set_on_every_send(self):
        caller, transport, _ = make([resp(500), resp(200)])
        caller.call(Request("GET", URL, {"Accept": "x"}))
        self.assertEqual(len(transport.requests), 2)
        for sent in transport.requests:
            self.assertEqual(sent.headers["User-Agent"], "ELDA-QGIS/" + VERSION)
            self.assertEqual(sent.headers["Accept"], "x")

    def test_default_timeout(self):
        self.assertEqual(req().timeout, 15.0)

    def test_every_3xx_is_refused(self):
        for status, headers in ((302, {"Location": "https://evil.example.com/x"}), (301, {"location": "/v1/y"}), (304, {})):
            with self.subTest(status=status):
                caller, transport, _ = make([resp(status, headers=headers)])
                with self.assertRaises(RequestRefused) as ctx:
                    caller.call(req())
                self.assertEqual(ctx.exception.status, status)
                self.assertIn("redirection", ctx.exception.message_fr)
                self.assertEqual(len(transport.requests), 1)

    def test_server_message_is_scrubbed(self):
        caller, _, _ = make([resp(400, b'{"message": "echec Bearer opaque123 password=s3cr3t"}')])
        with self.assertRaises(RequestRefused) as ctx:
            caller.call(req())
        self.assertNotIn("opaque123", ctx.exception.message_fr)
        self.assertNotIn("s3cr3t", ctx.exception.message_fr)

    def test_caller_user_agent_is_replaced(self):
        caller, transport, _ = make([resp(200)])
        caller.call(Request("GET", URL, {"user-agent": "evil", "USER-AGENT": "evil2"}))
        sent = transport.requests[0].headers
        self.assertEqual([k for k in sent if k.lower() == "user-agent"], ["User-Agent"])
        self.assertEqual(sent["User-Agent"], "ELDA-QGIS/" + VERSION)

    def test_client_identification_header_is_sent(self):
        caller, transport, _ = make([resp(200)])
        caller.call(Request("GET", URL, {"x-elda-client": "evil"}))
        sent = transport.requests[0].headers
        self.assertEqual([k for k in sent if k.lower() == "x-elda-client"], ["X-Elda-Client"])
        self.assertEqual(sent["X-Elda-Client"], "ELDA-QGIS/" + VERSION)


class RequestReprTest(unittest.TestCase):
    def test_repr_hides_headers_and_body(self):
        req = Request("POST", URL, {"Authorization": "Bearer bearer-secret-1"}, {"password": "pw-secret-2"})
        text = repr(req)
        self.assertNotIn("bearer-secret-1", text)
        self.assertNotIn("pw-secret-2", text)


class ResponseTest(unittest.TestCase):
    def test_json_error_does_not_keep_body_in_context(self):
        with self.assertRaises(ServerError) as ctx:
            resp(200, b"secret-body").json()
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_json_ok(self):
        self.assertEqual(resp(200, b'{"a": 1}').json(), {"a": 1})

    def test_json_on_non_json_body_raises_server_error(self):
        for body in (b"<html>", b"", b"\xff\xfe"):
            with self.subTest(body=body):
                with self.assertRaises(ServerError):
                    resp(200, body).json()


if __name__ == "__main__":
    unittest.main()


class RequestReprTest(unittest.TestCase):
    def test_repr_shows_method_and_host_only(self):
        text = repr(Request("PUT", "https://b.s3.example.com/path/k?X-Amz-Signature=deadbeef", {}, timeout=300.0))
        self.assertEqual(text, "Request(method='PUT', host='b.s3.example.com', timeout=300.0)")

    def test_repr_never_raises_on_a_malformed_url(self):
        for url in ("http://[bad", "", "no-scheme/path?x=1"):
            self.assertIn("Request(method='GET'", repr(Request("GET", url)))
