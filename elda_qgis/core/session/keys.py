from __future__ import annotations

import base64


def settings_key(server_url: str) -> str:
    """Encode a URL as one QgsSettings key segment (no '/', ':' or '=')."""
    return base64.urlsafe_b64encode(server_url.encode("utf-8")).decode("ascii").rstrip("=")
