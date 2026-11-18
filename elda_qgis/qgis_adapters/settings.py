from __future__ import annotations

from typing import Optional

from qgis.core import QgsSettings

from ..core.session.keys import settings_key

_LAST_SERVER = "elda/last_server"
_LAST_SITE = "elda/last_site/"


def last_server() -> str:
    return str(QgsSettings().value(_LAST_SERVER, ""))


def set_last_server(url: str) -> None:
    QgsSettings().setValue(_LAST_SERVER, url)


def last_site(server_url: str) -> Optional[int]:
    value = QgsSettings().value(_LAST_SITE + settings_key(server_url), None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def set_last_site(server_url: str, site_id: int) -> None:
    QgsSettings().setValue(_LAST_SITE + settings_key(server_url), int(site_id))
