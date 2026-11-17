from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..errors import AuthError, RequestRefused, ServerError, SessionLost
from ..net.http import Caller, Request, Response
from ..net.redact import scrub
from .account import Account, Site

_MOBILE = {"X-Client-Type": "mobile"}
_MALFORMED = "Réponse inattendue du serveur ELDA."
_SESSION_LOST_FR = (
    "Votre session ELDA a été reprise depuis un autre appareil (site web ou tablette). "
    "Reconnectez-vous pour continuer."
)


_NOT_LOGGED_IN_FR = "Vous n'êtes pas connecté à ELDA. Connectez-vous pour continuer."
_IDEMPOTENT = ("GET", "HEAD")


def _check_path(path: str) -> None:
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(c.isspace() for c in path):
        raise ValueError("Invalid path")


def _is_null_user(data: Any) -> bool:
    return isinstance(data, dict) and "user" in data and data["user"] is None


def _malformed(status: int = 200) -> ServerError:
    return ServerError(status, _MALFORMED)


def _account(data: Any, site: Optional[int], forced: bool) -> Account:
    try:
        if not isinstance(data, dict) or not isinstance(data.get("user"), dict):
            raise ValueError
        user = data["user"]
        resorts = data.get("resorts", [])
        permissions = data.get("permissions", [])
        if not isinstance(resorts, list) or not isinstance(permissions, list):
            raise ValueError
        sites = [Site(int(r["id"]), str(r["name"])) for r in resorts]
        active = site if forced else data.get("activeResortId", site)
        return Account(
            int(user["id"]),
            str(user["username"]),
            sites,
            None if active is None else int(active),
            frozenset(str(p) for p in permissions),
        )
    except (ValueError, TypeError, KeyError):
        raise _malformed() from None


@dataclass(frozen=True)
class RawJson:
    """A JSON body already serialised (a large file), with its own timeout."""

    data: bytes = field(repr=False)
    timeout: float = 15.0


class EldaApi:
    def __init__(self, server_url: str, caller: Caller):
        self._server = server_url.rstrip("/")
        self._caller = caller
        self._lock = threading.RLock()
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._site_id: Optional[int] = None
        self._account: Optional[Account] = None

    def __repr__(self) -> str:
        return "EldaApi(server=%r, logged_in=%s)" % (self._server, self.is_logged_in)

    @property
    def server_url(self) -> str:
        return self._server

    @property
    def is_logged_in(self) -> bool:
        return self._access is not None

    def _clear(self) -> None:
        self._access = self._refresh = self._account = None
        self._site_id = None

    def _build(self, method: str, path: str, json: Any, site_id: Optional[int], extra: Dict[str, str]) -> Request:
        headers = dict(extra)
        if site_id is not None:
            headers["X-Resort-Id"] = str(site_id)
        if isinstance(json, RawJson):
            headers["Content-Type"] = "application/json"
            return Request(method, self._server + path, headers, None, json.timeout, json.data)
        return Request(method, self._server + path, headers, json)

    def login(self, username: str, password: str) -> Account:
        with self._lock:
            if self.is_logged_in:
                self.logout()
            self._clear()
            body = {"username": username, "password": password}
            data = self._caller.call(self._build("POST", "/api/users/login", body, None, _MOBILE), retry=False).json()
            if not isinstance(data, dict):
                raise _malformed()
            if data.get("success") is not True:
                raise AuthError(scrub(str(data.get("error") or "")))
            access, refresh = data.get("accessToken"), data.get("refreshToken")
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise _malformed()
            account = _account(data, None, False)
            self._access, self._refresh = access, refresh
            self._site_id = account.active_site_id
            self._account = account
            return account

    def me(self, site_id: Optional[int] = None) -> Account:
        with self._lock:
            site = self._site_id if site_id is None else site_id
            data = self._send("GET", "/api/users/me", None, site, True).json()
            if _is_null_user(data):
                # an expired access token answers 200 with a null user
                self._refresh_access()
                data = self._send("GET", "/api/users/me", None, site, True).json()
                if _is_null_user(data):
                    self._clear()
                    raise SessionLost(_SESSION_LOST_FR)
            account = _account(data, site, site_id is not None)
            self._account = account
            return account

    def select_site(self, site_id: int) -> Account:
        with self._lock:
            account = self._account
            # a Super Admin ("*") may enter any site; the others only their own
            if account is None or ("*" not in account.permissions and site_id not in {s.id for s in account.sites}):
                raise ValueError("Unknown site")
            account = self.me(site_id)
            self._site_id = site_id
            return account

    def logout(self) -> None:
        with self._lock:
            try:
                if self._access is not None:
                    # the server revokes the session only when it gets the refresh token back
                    body = {"token": self._refresh} if self._refresh else None
                    request = self._build("POST", "/api/users/logout", body, None, self._auth())
                    self._caller.call(request, retry=False)
            except Exception:
                pass
            finally:
                self._clear()

    def request(self, method: str, path: str, json: Optional[object] = None, retry: Optional[bool] = None) -> Response:
        _check_path(path)
        with self._lock:
            return self._send(method, path, json, self._site_id, method.upper() in _IDEMPOTENT if retry is None else retry)

    def _send(self, method: str, path: str, json: Any, site_id: Optional[int], retry: bool) -> Response:
        response = self._caller.call(self._build(method, path, json, site_id, self._auth()), retry=retry)
        if response.status != 401:
            return response
        self._refresh_access()
        response = self._caller.call(self._build(method, path, json, site_id, self._auth()), retry=retry)
        if response.status == 401:
            self._clear()
            raise SessionLost(_SESSION_LOST_FR)
        return response

    def _auth(self) -> Dict[str, str]:
        if self._access is None:
            raise SessionLost(_NOT_LOGGED_IN_FR)
        return {"Authorization": "Bearer " + self._access}

    def _refresh_access(self) -> None:
        with self._lock:
            request = self._build("POST", "/api/users/refresh-token", {"token": self._refresh}, None, _MOBILE)
            try:
                response = self._caller.call(request, retry=False)
            except RequestRefused as exc:
                if exc.status != 403:
                    raise
                self._clear()
                raise SessionLost(_SESSION_LOST_FR) from None
            if response.status == 401:
                self._clear()
                raise SessionLost(_SESSION_LOST_FR)
            data = response.json()
            token = data.get("accessToken") if isinstance(data, dict) else None
            if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(token, str) or not token:
                raise _malformed(response.status)
            self._access = token
