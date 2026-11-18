from __future__ import annotations

import json
from typing import Dict

from qgis.core import QgsApplication, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QEventLoop, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..core.errors import NetworkError
from ..core.net.http import Request, Response
from . import log


# largest reply ever read: API answers are small JSON, storage answers are empty
MAX_REPLY_BYTES = 16 * 1024 * 1024
# a request without a file to send must end within this many times its inactivity timeout
_DEADLINE_FACTOR = 4
_SSL_EXCEPTION_FR = (
    "Une exception de certificat est enregistrée dans QGIS pour ce serveur. "
    "Supprimez-la dans Préférences > Options > Authentification, puis réessayez."
)


def _wait(reply, deadline_ms=None) -> bool:
    """False when the deadline passed before the reply ended."""
    if reply.isFinished():
        return True
    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    if deadline_ms is not None:
        QTimer.singleShot(int(deadline_ms), loop.quit)
    # PyQt5 exposes exec_(), PyQt6 exec()
    run = getattr(loop, "exec", None) or loop.exec_
    run()
    return reply.isFinished()


def _has_ssl_exception(url) -> bool:
    """A saved QGIS exception would accept a bad certificate without any error reaching the plugin."""
    try:
        manager = QgsApplication.authManager()
        if manager is None or manager.isDisabled():
            return False
        config = manager.sslCertCustomConfigByHost("%s:%d" % (url.host(), url.port(443)))
        return config is not None and not config.isNull()
    except Exception as exc:
        log.warning("ssl exception lookup: %s" % type(exc).__name__)
        return False


def _private(qrequest) -> None:
    # account data must not be written to, or served from, QGIS's network disk cache
    qrequest.setAttribute(QNetworkRequest.Attribute.CacheSaveControlAttribute, False)
    qrequest.setAttribute(
        QNetworkRequest.Attribute.CacheLoadControlAttribute, QNetworkRequest.CacheLoadControl.AlwaysNetwork
    )


def _no_cookies(qrequest) -> None:
    # the shared cookie jar must neither send nor store the ELDA token cookies
    qrequest.setAttribute(QNetworkRequest.Attribute.CookieLoadControlAttribute, QNetworkRequest.LoadControl.Manual)
    qrequest.setAttribute(QNetworkRequest.Attribute.CookieSaveControlAttribute, QNetworkRequest.LoadControl.Manual)


class QgisTransport:
    """Blocking; prefer a QgsTask worker; on the GUI thread it spins a nested event loop."""

    def send(self, request: Request) -> Response:
        url = QUrl(request.url)
        if url.scheme() == "https" and _has_ssl_exception(url):
            raise NetworkError(_SSL_EXCEPTION_FR)
        qrequest = QNetworkRequest(url)
        qrequest.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        _no_cookies(qrequest)
        _private(qrequest)
        qrequest.setTransferTimeout(int(request.timeout * 1000))
        headers = dict(request.headers)
        body = QByteArray(request.body) if request.body is not None else QByteArray()
        if request.json is not None:
            body = QByteArray(json.dumps(request.json).encode("utf-8"))
            headers.setdefault("Content-Type", "application/json")
        for name, value in headers.items():
            qrequest.setRawHeader(QByteArray(name.encode("utf-8")), QByteArray(value.encode("utf-8")))

        nam = QgsNetworkAccessManager.instance()
        method = request.method.upper()
        if method == "GET":
            reply = nam.get(qrequest)
        elif method == "POST":
            reply = nam.post(qrequest, body)
        elif method == "PUT":
            reply = nam.put(qrequest, body)
        elif method == "DELETE":
            reply = nam.deleteResource(qrequest)
        else:
            reply = nam.sendCustomRequest(qrequest, QByteArray(method.encode("ascii")), body)
        tls_failed = []

        def on_ssl_errors(*_errors) -> None:
            # a certificate error is final, never offer to ignore it
            tls_failed.append(True)
            reply.abort()

        too_big = []

        def on_progress(received, _total) -> None:
            # a hostile server must not fill the memory with an endless answer
            if received > MAX_REPLY_BYTES and not too_big:
                too_big.append(True)
                reply.abort()

        reply.sslErrors.connect(on_ssl_errors)
        reply.downloadProgress.connect(on_progress)
        # uploads are bounded by their own speed check; other requests get an overall deadline
        deadline = None if request.body is not None else request.timeout * 1000 * _DEADLINE_FACTOR
        try:
            if not _wait(reply, deadline):
                reply.abort()
                raise NetworkError()
            if tls_failed or too_big:
                raise NetworkError()
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            # No HTTP status means no response (connection, TLS, timeout, abort)
            if status is None:
                raise NetworkError()
            headers_out: Dict[str, str] = {
                bytes(name).decode("utf-8", "replace"): bytes(value).decode("utf-8", "replace")
                for name, value in reply.rawHeaderPairs()
            }
            return Response(int(status), headers_out, bytes(reply.readAll()))
        finally:
            reply.deleteLater()
