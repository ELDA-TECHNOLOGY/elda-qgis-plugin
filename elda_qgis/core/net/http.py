from __future__ import annotations

import json as jsonlib
import time
from urllib.parse import urlsplit
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Optional, Protocol

from ...version import VERSION
from .redact import scrub
from ..errors import NetworkError, RequestRefused, ServerError
from ..i18n import tr

USER_AGENT = "ELDA-QGIS/" + VERSION
_BACKOFF = (1, 2, 4)
_RETRY_AFTER_CAP = 60
# longest server-supplied text ever shown or logged
_MESSAGE_MAX = 500


def _header(headers: Dict[str, str], name: str) -> Optional[str]:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


@dataclass(repr=False)
class Request:
    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict, repr=False)
    json: Optional[Any] = field(default=None, repr=False)
    timeout: float = 15.0
    body: Optional[bytes] = field(default=None, repr=False)

    def __repr__(self) -> str:
        # the url may be a signed secret: show the host only
        try:
            host = urlsplit(self.url).hostname
        except ValueError:
            host = None
        return "Request(method=%r, host=%r, timeout=%r)" % (self.method, host, self.timeout)

    def __post_init__(self) -> None:
        if self.json is not None and self.body is not None:
            raise ValueError("a request carries json or body, never both")


@dataclass(repr=False)
class Response:
    status: int
    headers: Dict[str, str]
    body: bytes

    def __repr__(self) -> str:
        # headers and body may carry tokens
        return "Response(status=%r, bytes=%d)" % (self.status, len(self.body))

    def json(self) -> Any:
        try:
            return jsonlib.loads(self.body.decode("utf-8"))
        except (ValueError, RecursionError):
            raise ServerError(self.status, tr("Réponse inattendue du serveur ELDA.")) from None


class Transport(Protocol):
    def send(self, request: Request) -> Response: ...


def _refusal(response: Response) -> RequestRefused:
    message = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            message = str(data.get("message") or data.get("error") or "")
    except ServerError:
        pass
    # cut first: scrubbing cost and the text shown both stay bounded
    return RequestRefused(response.status, scrub(message[:_MESSAGE_MAX]))


def _retry_after(response: Response) -> Optional[int]:
    raw = _header(response.headers, "retry-after")
    text = raw.strip() if raw is not None else ""
    if not (text.isascii() and text.isdigit() and len(text) <= 4):
        return None
    return min(int(text), _RETRY_AFTER_CAP)


class Caller:
    def __init__(self, transport: Transport, sleep: Callable[[float], None] = time.sleep):
        self._transport = transport
        self._sleep = sleep

    def call(self, request: Request, retry: bool = True) -> Response:
        """Non-idempotent requests must pass retry=False."""
        request = replace(
            request,
            headers={**{k: v for k, v in request.headers.items() if k.lower() not in ("user-agent", "x-elda-client")}, "User-Agent": USER_AGENT, "X-Elda-Client": USER_AGENT},
        )
        retries = len(_BACKOFF) if retry else 0
        for attempt in range(retries + 1):
            last = attempt == retries
            try:
                response = self._transport.send(request)
            except NetworkError:
                if last:
                    raise
                self._sleep(_BACKOFF[attempt])
                continue
            status = response.status
            if 300 <= status < 400:
                raise RequestRefused(status, tr("Le serveur ELDA a répondu par une redirection inattendue."))
            if status == 429 and not last:
                wait = _retry_after(response)
                self._sleep(_BACKOFF[attempt] if wait is None else wait)
                continue
            if status >= 500:
                if last:
                    raise ServerError(status)
                self._sleep(_BACKOFF[attempt])
                continue
            if status >= 400 and status != 401:
                raise _refusal(response)
            return response
        raise AssertionError("unreachable")
