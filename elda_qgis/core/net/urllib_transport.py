from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

from ..errors import NetworkError
from .http import Request, Response


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Hand the 3xx response back as is instead of following it
    def http_error_301(self, req, fp, code, msg, headers):
        return fp

    http_error_302 = http_error_303 = http_error_307 = http_error_308 = http_error_301


class UrllibTransport:
    def __init__(self) -> None:
        # the default handlers hold no HTTPCookieProcessor: tokens must never ride on cookies
        self._opener = urllib.request.build_opener(_NoRedirect)

    def send(self, request: Request) -> Response:
        data = request.body
        headers = dict(request.headers)
        if request.json is not None:
            data = json.dumps(request.json).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(request.url, data=data, headers=headers, method=request.method)
        try:
            with self._opener.open(req, timeout=request.timeout) as resp:
                return Response(resp.getcode(), dict(resp.headers.items()), resp.read())
        except urllib.error.HTTPError as exc:
            # urllib raises 4xx/5xx as HTTPError carrying the response
            try:
                with exc:
                    return Response(exc.code, dict(exc.headers.items()), exc.read())
            except (OSError, ValueError, http.client.HTTPException):
                raise NetworkError() from None
        except (OSError, ValueError, http.client.HTTPException):
            raise NetworkError() from None
