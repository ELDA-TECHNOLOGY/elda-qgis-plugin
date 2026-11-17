from __future__ import annotations

import json
import unittest

from elda_qgis.core.session.api import EldaApi
from elda_qgis.core.errors import AuthError, NetworkError, RequestRefused, ServerError, SessionLost
from elda_qgis.core.net.http import Caller, Response
from elda_qgis.core.session.account import Account, Site
from tests.core.fakes import FakeTransport

SERVER = "https://elda.example"
PASSWORD = 'p"w é' + "x" * 120


def resp(status, body):
    return Response(status, {}, json.dumps(body).encode("utf-8"))


def login_ok(**over):
    body = {
        "success": True,
        "user": {"id": 7, "username": "léa"},
        "resorts": [{"id": 21, "name": "A"}, {"id": "22", "name": "B"}],
        "activeResortId": 21,
        "permissions": ["gis_operational:manage"],
        "accessToken": "at-secret-123",
        "refreshToken": "rt-secret-456",
    }
    body.update(over)
    return resp(200, body)


def me_ok(**over):
    body = {
        "user": {"id": 7, "username": "léa"},
        "resorts": [{"id": 21, "name": "A"}, {"id": 22, "name": "B"}],
        "activeResortId": 22,
        "permissions": ["gis:raster:upload"],
    }
    body.update(over)
    return resp(200, body)


NULL_ME = resp(200, {"user": None, "permissions": []})
REFRESH_OK = resp(200, {"ok": True, "accessToken": "at2-secret-789"})


def make(script):
    transport = FakeTransport(script)
    return EldaApi(SERVER, Caller(transport, sleep=lambda s: None)), transport


def logged(script):
    api, transport = make([login_ok()] + script)
    api.login("léa", "pw")
    return api, transport


class ApiTest(unittest.TestCase):
    def test_login_sends_mobile_header_and_keeps_tokens_in_memory(self):
        api, t = make([login_ok(), login_ok()])
        account = api.login("léa", PASSWORD)
        req = t.requests[0]
        self.assertEqual((req.method, req.url), ("POST", SERVER + "/api/users/login"))
        self.assertEqual(req.headers["X-Client-Type"], "mobile")
        self.assertEqual(req.json, {"username": "léa", "password": PASSWORD})
        self.assertEqual(
            account,
            Account(7, "léa", [Site(21, "A"), Site(22, "B")], 21, frozenset({"gis_operational:manage"})),
        )
        self.assertTrue(api.is_logged_in)
        self.assertNotIn(PASSWORD, repr(api))
        for secret in ("at-secret-123", "rt-secret-456"):
            self.assertNotIn(secret, repr(api))

    def test_wrong_password_is_a_200_with_success_false(self):
        api, t = make([resp(200, {"success": False, "error": "Mot de passe invalide"})])
        with self.assertRaises(AuthError) as ctx:
            api.login("léa", PASSWORD)
        self.assertEqual(ctx.exception.message_fr, "Mot de passe invalide")
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertEqual(len(t.requests), 1)
        self.assertFalse(api.is_logged_in)

    def test_login_is_not_retried_on_500(self):
        api, t = make([resp(500, {})])
        with self.assertRaises(ServerError) as ctx:
            api.login("léa", PASSWORD)
        self.assertNotIn(PASSWORD, str(ctx.exception))
        self.assertEqual(len(t.requests), 1)

    def test_login_is_not_retried_on_network_error(self):
        api, t = make([NetworkError()])
        with self.assertRaises(NetworkError):
            api.login("léa", "pw")
        self.assertEqual(len(t.requests), 1)

    def test_malformed_success_bodies_are_server_errors(self):
        bad = [
            login_ok(accessToken=None),
            resp(200, {k: v for k, v in json.loads(login_ok().body).items() if k != "accessToken"}),
            login_ok(resorts="nope"),
            login_ok(user=None),
            resp(200, ["x"]),
        ]
        for response in bad:
            api, _ = make([response])
            with self.assertRaises(ServerError):
                api.login("léa", "pw")
            self.assertFalse(api.is_logged_in)

    def test_authenticated_calls_carry_bearer_and_site(self):
        api, t = logged([me_ok(), resp(200, {})])
        account = api.select_site(22)
        self.assertEqual(account.active_site_id, 22)
        self.assertEqual(account.permissions, frozenset({"gis:raster:upload"}))
        self.assertEqual(t.requests[1].headers["Authorization"], "Bearer at-secret-123")
        self.assertEqual(t.requests[1].headers["X-Resort-Id"], "22")
        api.request("GET", "/api/anything")
        last = t.requests[-1]
        self.assertEqual(last.url, SERVER + "/api/anything")
        self.assertEqual(last.headers["X-Resort-Id"], "22")

    def test_select_site_unknown_id_fails_before_any_request(self):
        api, t = logged([])
        with self.assertRaises(ValueError):
            api.select_site(999)
        self.assertEqual(len(t.requests), 1)

    def test_super_admin_selects_a_site_it_is_not_linked_to(self):
        api, t = make([login_ok(permissions=["*"]), me_ok(permissions=["*"], activeResortId=999)])
        api.login("léa", "pw")
        self.assertEqual(api.select_site(999).active_site_id, 999)
        self.assertEqual(t.requests[1].headers["X-Resort-Id"], "999")

    def test_me_null_user_refreshes_and_replays(self):
        api, t = logged([NULL_ME, REFRESH_OK, me_ok()])
        account = api.me()
        self.assertEqual(account.username, "léa")
        self.assertEqual(len(t.requests), 4)
        self.assertEqual(t.requests[3].headers["Authorization"], "Bearer at2-secret-789")

    def test_me_null_user_after_refresh_is_session_lost(self):
        api, t = logged([NULL_ME, REFRESH_OK, NULL_ME])
        with self.assertRaises(SessionLost) as ctx:
            api.me()
        self.assertIn("autre appareil", ctx.exception.message_fr)
        self.assertFalse(api.is_logged_in)
        self.assertEqual(len(t.requests), 4)

    def test_me_null_user_with_refused_refresh_is_session_lost(self):
        api, t = logged([NULL_ME, resp(403, {})])
        with self.assertRaises(SessionLost):
            api.me()
        self.assertFalse(api.is_logged_in)
        self.assertTrue(all(not r.url.endswith("/login") for r in t.requests[1:]))

    def test_me_without_user_key_is_malformed(self):
        api, _ = logged([resp(200, {"permissions": []})])
        with self.assertRaises(ServerError):
            api.me()
        self.assertTrue(api.is_logged_in)

    def test_me_active_site_is_the_requested_one(self):
        api, _ = logged([me_ok(activeResortId=21), me_ok(activeResortId=21)])
        self.assertEqual(api.me(22).active_site_id, 22)
        self.assertEqual(api.select_site(22).active_site_id, 22)

    def test_post_is_not_retried_on_500(self):
        api, t = logged([resp(500, {})])
        with self.assertRaises(ServerError):
            api.request("POST", "/api/publish", {"a": 1})
        self.assertEqual(len(t.requests), 2)

    def test_post_replay_after_refresh_is_not_retried(self):
        api, t = logged([resp(401, {}), REFRESH_OK, resp(500, {})])
        with self.assertRaises(ServerError):
            api.request("POST", "/api/publish")
        self.assertEqual(len(t.requests), 4)

    def test_get_is_retried_on_500(self):
        api, t = logged([resp(500, {}), resp(500, {}), resp(200, {"ok": 1})])
        self.assertEqual(api.request("GET", "/api/x").json(), {"ok": 1})
        self.assertEqual(len(t.requests), 4)

    def test_explicit_retry_overrides_the_default(self):
        api, t = logged([resp(500, {})])
        with self.assertRaises(ServerError):
            api.request("GET", "/api/x", retry=False)
        self.assertEqual(len(t.requests), 2)

    def test_bad_paths_are_rejected_before_any_request(self):
        for path in ("@evil.com/x", ".evil.com/x", "//evil.com/x", "/a\\b", "", "/a b", "/a\nb"):
            api, t = logged([])
            with self.assertRaises(ValueError, msg=path):
                api.request("GET", path)
            self.assertEqual(len(t.requests), 1)

    def test_after_logout_authenticated_requests_send_nothing(self):
        api, t = logged([resp(200, {})])
        api.logout()
        n = len(t.requests)
        with self.assertRaises(SessionLost) as ctx:
            api.request("GET", "/api/x")
        self.assertNotIn("autre appareil", ctx.exception.message_fr)
        self.assertIn("pas connecté", ctx.exception.message_fr)
        with self.assertRaises(SessionLost):
            api._auth()
        self.assertEqual(len(t.requests), n)

    def test_login_while_logged_in_logs_out_first(self):
        api, t = logged([resp(200, {}), login_ok()])
        api.login("léa", "pw")
        self.assertEqual(t.requests[1].url, SERVER + "/api/users/logout")
        self.assertEqual(t.requests[1].headers["Authorization"], "Bearer at-secret-123")
        self.assertEqual(t.requests[2].url, SERVER + "/api/users/login")

    def test_failed_refresh_keeps_the_session(self):
        for failure in (resp(429, {}), resp(500, {}), NetworkError()):
            api, _ = logged([resp(401, {}), failure])
            with self.assertRaises((RequestRefused, ServerError, NetworkError)):
                api.request("GET", "/api/x")
            self.assertTrue(api.is_logged_in)

    def test_me_with_site_id_sends_that_site(self):
        api, t = logged([me_ok()])
        api.me(22)
        self.assertEqual(t.requests[1].headers["X-Resort-Id"], "22")

    def test_expired_access_token_is_refreshed_once(self):
        api, t = logged([resp(401, {}), resp(200, {"ok": True, "accessToken": "at2-secret-789"}), resp(200, {"a": 1})])
        out = api.request("GET", "/api/x")
        self.assertEqual(out.json(), {"a": 1})
        self.assertEqual(len(t.requests), 4)
        refresh = t.requests[2]
        self.assertEqual(refresh.url, SERVER + "/api/users/refresh-token")
        self.assertEqual(refresh.json, {"token": "rt-secret-456"})
        self.assertEqual(refresh.headers["X-Client-Type"], "mobile")
        self.assertEqual(t.requests[3].headers["Authorization"], "Bearer at2-secret-789")

    def test_refused_refresh_ends_the_session(self):
        for refusal in (resp(401, {}), resp(403, {})):
            api, t = logged([resp(401, {}), refusal])
            with self.assertRaises(SessionLost):
                api.request("GET", "/api/x")
            self.assertFalse(api.is_logged_in)
            self.assertEqual(len(t.requests), 3)
            self.assertTrue(all(not r.url.endswith("/login") for r in t.requests[1:]))

    def test_bad_refresh_body_is_a_server_error(self):
        api, _ = logged([resp(401, {}), resp(200, {"ok": True})])
        with self.assertRaises(ServerError):
            api.request("GET", "/api/x")

    def test_second_401_after_refresh_is_session_lost(self):
        api, t = logged([resp(401, {}), resp(200, {"ok": True, "accessToken": "at2-secret-789"}), resp(401, {})])
        with self.assertRaises(SessionLost):
            api.request("GET", "/api/x")
        self.assertFalse(api.is_logged_in)
        self.assertEqual(len(t.requests), 4)

    def test_request_when_logged_out_is_session_lost(self):
        api, t = make([])
        with self.assertRaises(SessionLost):
            api.request("GET", "/api/x")
        self.assertEqual(t.requests, [])

    def test_logout_clears_tokens_even_if_the_server_fails(self):
        for outcome in (resp(500, {}), NetworkError(), resp(200, {})):
            api, t = logged([outcome])
            api.logout()
            self.assertFalse(api.is_logged_in)
            self.assertEqual(t.requests[1].url, SERVER + "/api/users/logout")
            self.assertEqual(t.requests[1].headers["Authorization"], "Bearer at-secret-123")
            self.assertEqual(len(t.requests), 2)

    def test_account_without_site(self):
        api, _ = make([login_ok(resorts=[], resortIds=[], activeResortId=None)])
        account = api.login("léa", "pw")
        self.assertEqual(account.sites, [])
        self.assertIsNone(account.active_site_id)

    def test_repr_hides_secrets(self):
        api, _ = logged([])
        text = repr(api)
        for secret in ("at-secret-123", "rt-secret-456", "Bearer"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
