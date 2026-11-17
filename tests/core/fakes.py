from __future__ import annotations

import json

from elda_qgis.core.session.api import EldaApi
from elda_qgis.core.net.http import Caller, Request, Response


class FakeTransport:
    """Replays a scripted list of Response objects or exceptions and records every Request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[Request] = []

    def send(self, request: Request) -> Response:
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(status, body):
    return Response(status, {}, json.dumps(body).encode("utf-8"))


def logged(script):
    """A logged-in EldaApi over a FakeTransport scripted with the login reply then `script`."""
    login = resp(
        200,
        {
            "success": True,
            "user": {"id": 7, "username": "lea"},
            "resorts": [{"id": 21, "name": "A"}],
            "activeResortId": 21,
            "permissions": [],
            "accessToken": "at-secret-123",
            "refreshToken": "rt-secret-456",
        },
    )
    transport = FakeTransport([login] + list(script))
    api = EldaApi("https://elda.example", Caller(transport, sleep=lambda s: None))
    api.login("lea", "pw")
    return api, transport
