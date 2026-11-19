from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from ..errors import UnsafeUrl
from ..i18n import tr

KNOWN = {
    "https://data.eldatechnology.fr": "Production",
}

_LOOPBACK = ("localhost", "127.0.0.1")
_DEFAULT_PORT = {"http": 80, "https": 443}
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_LDH = re.compile(r"^%s(\.%s)*$" % (_LABEL, _LABEL))


def _valid_host(host: str) -> bool:
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
            return True
        except ValueError:
            return False
    return bool(_LDH.match(host))


def normalize(raw: str) -> str:
    text = raw.strip()
    if "\\" in text or any(c.isspace() for c in text):
        raise UnsafeUrl()
    try:
        parts = urlsplit(text)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise UnsafeUrl()
    if not host or not host.isascii() or "%" in host or not _valid_host(host):
        raise UnsafeUrl()
    if parts.username is not None or parts.password is not None or port == 0:
        raise UnsafeUrl()
    if parts.scheme == "http":
        if host not in _LOOPBACK:
            raise UnsafeUrl()
    elif parts.scheme != "https":
        raise UnsafeUrl()
    if ":" in host:
        host = "[" + host + "]"
    shown = "" if port is None or port == _DEFAULT_PORT[parts.scheme] else ":%d" % port
    return "%s://%s%s" % (parts.scheme, host, shown)


def is_known(url: str) -> bool:
    try:
        return normalize(url) in KNOWN
    except UnsafeUrl:
        return False


def is_loopback(url: str) -> bool:
    """The (already normalized) server runs on the user's own machine."""
    try:
        return urlsplit(url).hostname in _LOOPBACK
    except ValueError:
        return False


def check_storage(url: str, api_is_loopback: bool) -> None:
    """An upload address given by the server: https only, no credentials; this machine only in local development."""
    refused = UnsafeUrl(tr("Adresse de stockage refusée par sécurité."))
    if not isinstance(url, str) or "\\" in url or any(c.isspace() for c in url):
        raise refused
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port
    except ValueError:
        raise refused from None
    if not host or parts.username is not None or parts.password is not None:
        raise refused
    if parts.scheme == "https":
        return
    if not (parts.scheme == "http" and host in _LOOPBACK and api_is_loopback):
        raise refused
