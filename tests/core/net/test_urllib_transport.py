import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from elda_qgis.core.errors import NetworkError
from elda_qgis.core.net.http import Request
from elda_qgis.core.net.urllib_transport import UrllibTransport


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, status, body=b"", headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self._reply(200, data, {"Content-Type": "application/json", "X-Seen-Agent": self.headers.get("User-Agent", "")})

    def do_GET(self):
        if self.path == "/redirect":
            self._reply(302, headers={"Location": "http://other.invalid/x"})
        elif self.path == "/cut":
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"short")
            self.wfile.flush()
            self.close_connection = True
        elif self.path == "/cut500":
            self.send_response(500)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"short")
            self.wfile.flush()
            self.close_connection = True
        elif self.path == "/slow":
            time.sleep(1)
            self._reply(200)
        elif self.path == "/setcookie":
            self._reply(200, headers={"Set-Cookie": "access-token=abc; Path=/"})
        elif self.path == "/cookie":
            self._reply(200, headers={"X-Cookie": self.headers.get("Cookie", "")})
        else:
            self._reply(404, b'{"message":"nope"}')


class UrllibTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_json_round_trip(self):
        request = Request("POST", self.base + "/echo", {"User-Agent": "t"}, {"a": 1})
        response = UrllibTransport().send(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json(), {"a": 1})
        self.assertEqual(response.headers["X-Seen-Agent"], "t")

    def test_error_status_is_a_response(self):
        response = UrllibTransport().send(Request("GET", self.base + "/missing"))
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.body), {"message": "nope"})

    def test_redirect_is_returned_not_followed(self):
        response = UrllibTransport().send(Request("GET", self.base + "/redirect"))
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], "http://other.invalid/x")

    def test_cookies_are_never_stored_nor_resent(self):
        transport = UrllibTransport()
        transport.send(Request("GET", self.base + "/setcookie"))
        response = transport.send(Request("GET", self.base + "/cookie"))
        self.assertEqual(response.headers["X-Cookie"], "")

    def test_closed_port_raises_network_error(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with self.assertRaises(NetworkError):
            UrllibTransport().send(Request("GET", "http://127.0.0.1:%d/" % port))

    def test_timeout_raises_network_error(self):
        with self.assertRaises(NetworkError):
            UrllibTransport().send(Request("GET", self.base + "/slow", timeout=0.2))

    def test_truncated_body_raises_network_error(self):
        with self.assertRaises(NetworkError):
            UrllibTransport().send(Request("GET", self.base + "/cut"))

    def test_truncated_error_body_raises_network_error(self):
        with self.assertRaises(NetworkError):
            UrllibTransport().send(Request("GET", self.base + "/cut500"))


class RawBodyTest(unittest.TestCase):
    def test_raw_body_sent_unchanged_without_json_content_type(self):
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_PUT(self):
                seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                seen["type"] = self.headers["Content-Type"]
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:%d/x" % server.server_address[1]
        UrllibTransport().send(Request("PUT", url, {"Content-Type": "application/x-test"}, body=b"\x00\xffraw"))
        self.assertEqual(seen, {"body": b"\x00\xffraw", "type": "application/x-test"})


class ChainTest(unittest.TestCase):
    def test_network_error_does_not_chain_the_original(self):
        with self.assertRaises(NetworkError) as ctx:
            UrllibTransport().send(Request("GET", "http://127.0.0.1:1/x?X-Amz-Signature=deadbeef"))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)
