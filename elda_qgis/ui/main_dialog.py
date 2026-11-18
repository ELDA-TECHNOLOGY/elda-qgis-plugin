from __future__ import annotations

import html
from typing import Callable

from qgis.core import Qgis
from qgis.gui import QgsMessageBar
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..core.errors import EldaError, SessionLost
from ..core.publish.gis import GisApi
from ..qgis_adapters import credentials, log, settings
from .session import state
from . import dialogs, texts, worker
from ..version import VERSION
from .session.login_dialog import LoginDialog
from .publish.panel import PublishPanel

_BAR_SECONDS = 8
# minimum window size (width, height): the layer table must show all its columns
_LOGGED_IN_SIZE = (720, 560)
_LOGGED_OUT_SIZE = (380, 0)


def exec_dialog(dialog) -> int:
    # PyQt5 and PyQt6 both expose exec() on QDialog; exec_() is the old PyQt5 spelling
    run = getattr(dialog, "exec", None) or dialog.exec_
    return run()


def _plain_label() -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class MainDialog(QDialog):
    """Login state, site choice, publishing rights and the publish panel."""

    def __init__(self, iface, api_factory: Callable[[str], object]):
        super().__init__(iface.mainWindow())
        self._api_factory = api_factory
        self._api = None
        self._server = ""
        self._account = None
        self._all_sites = None
        self._loading = False
        self._refreshing = False
        self.setWindowTitle("%s %s" % (texts.TITLE, VERSION))
        self.setMinimumSize(*_LOGGED_OUT_SIZE)

        self._bar = QgsMessageBar()
        self._status = _plain_label()
        self._site = QComboBox()
        self._site_name = _plain_label()
        self._vector = _plain_label()
        self._raster = _plain_label()
        self._explanation = _plain_label()
        self._busy = _plain_label()
        self._login = QPushButton(texts.CONNECT)
        self._logout = QPushButton(texts.LOGOUT)
        self._forget = QPushButton(texts.FORGET)
        self._panel = PublishPanel(lambda _busy: self._sync_enabled(), self._failed, self)

        buttons = QHBoxLayout()
        for button in (self._login, self._logout, self._forget):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        for widget in (self._bar, self._status, self._site, self._site_name, self._vector, self._raster, self._explanation, self._busy):
            layout.addWidget(widget)
        layout.addWidget(self._panel)
        layout.addLayout(buttons)

        self._login.clicked.connect(dialogs.guarded(self._message, self._open_login))
        self._logout.clicked.connect(dialogs.guarded(self._message, self._do_logout))
        self._forget.clicked.connect(dialogs.guarded(self._message, self._do_forget))
        self._site.currentIndexChanged.connect(self._on_site_picked)
        self._on_account = worker.guarded(self, self._site_changed)
        self._on_error = worker.guarded(self, self._failed)
        self._on_finally = worker.guarded(self, lambda: self._set_busy(False))
        self._refresh()

    def _refresh(self) -> None:
        view = state.view_of(self._account, self._all_sites)
        self._refreshing = True
        self._site.clear()
        for site in view.sites:
            self._site.addItem(site.name, site.id)
        index = self._site.findData(view.selected_site_id)
        if index >= 0:
            self._site.setCurrentIndex(index)
        self._refreshing = False
        self._status.setText(texts.connected_as(view.username, self._server) if view.logged_in else texts.LOGGED_OUT)
        self._site.setVisible(view.site_combo_visible)
        self._site_name.setText(view.site_label or "")
        self._site_name.setVisible(view.site_label is not None)
        self._vector.setText(view.vector_line)
        self._raster.setText(view.raster_line)
        self._explanation.setText(view.explanation or "")
        for widget in (self._vector, self._raster):
            widget.setVisible(view.logged_in)
        self._explanation.setVisible(bool(view.explanation))
        self._login.setVisible(not view.logged_in)
        self._logout.setVisible(view.logged_in)
        self._forget.setVisible(view.logged_in)
        self._panel.setVisible(view.logged_in)
        # the layer table needs room: Qt grows the window to the new minimum by itself
        self.setMinimumSize(*(_LOGGED_IN_SIZE if view.logged_in else _LOGGED_OUT_SIZE))
        self._panel.set_session(self._api, self._account)

    def _set_busy(self, busy: bool) -> None:
        self._loading = busy
        self._busy.setText(texts.WAIT if busy else "")
        self._panel.set_blocked(busy)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        # no site switch or logout while a call or a publish batch runs
        idle = not self._loading and not self._panel.busy
        for widget in (self._login, self._logout, self._forget, self._site):
            widget.setEnabled(idle)

    def _message(self, text: str) -> None:
        # the bar renders rich text, server messages must not be read as markup
        self._bar.pushMessage(texts.TITLE, html.escape(text), Qgis.MessageLevel.Warning, _BAR_SECONDS)

    def _open_login(self) -> None:
        dialog = LoginDialog(self._api_factory, self)
        try:
            if not exec_dialog(dialog) or dialog.api is None:
                return
            api, server, account = dialog.api, dialog.server_url, dialog.account
        finally:
            dialog.deleteLater()
        self._api, self._server, self._account = api, server, account
        self._all_sites = None
        self._refresh()
        if "*" in account.permissions:
            self._load_all_sites(api)
        target = state.site_to_select(account, settings.last_site(server))
        if target is not None:
            self._pick_site(target)

    def _load_all_sites(self, api) -> None:
        def done(sites) -> None:
            if self._api is api:
                self._all_sites = sites
                self._refresh()

        def failed(exc: Exception) -> None:
            # the account's own sites stay listed
            log.warning("site list not loaded: %s" % type(exc).__name__)

        worker.run(texts.TASK_LOADING, GisApi(api).all_sites, worker.guarded(self, done), worker.guarded(self, failed))

    def _on_site_picked(self, _index: int) -> None:
        site_id = self._site.currentData()
        if self._refreshing or site_id is None or self._account is None:
            return
        if site_id != self._account.active_site_id:
            self._pick_site(site_id)

    def _pick_site(self, site_id: int) -> None:
        api = self._api
        self._set_busy(True)
        worker.run(
            "ELDA : changement de site",
            lambda: api.select_site(site_id),
            self._on_account,
            self._on_error,
            self._on_finally,
        )

    def _site_changed(self, account) -> None:
        self._account = account
        if account.active_site_id is not None:
            settings.set_last_site(self._server, account.active_site_id)
        self._refresh()

    def _do_logout(self) -> None:
        api = self._api
        self._set_busy(True)
        # logout never raises: it clears the session even when the server is unreachable
        done = worker.guarded(self, lambda _result: self._logged_out())
        worker.run("ELDA : déconnexion", api.logout, done, self._on_error, self._on_finally)

    def _logged_out(self) -> None:
        self._api = None
        self._account = None
        self._all_sites = None
        self._refresh()

    def _do_forget(self) -> None:
        forgotten = credentials.forget(self._server)
        self._do_logout()
        text, warning = texts.forget_message(forgotten)
        level = Qgis.MessageLevel.Warning if warning else Qgis.MessageLevel.Info
        self._bar.pushMessage(texts.TITLE, text, level, _BAR_SECONDS)

    def reject(self) -> None:
        # Esc and the close button both land here (QDialog.closeEvent calls reject)
        if self._panel.busy:
            if not dialogs.confirm(self, texts.CLOSE_DURING_BATCH):
                return
            # the window only hides: the running job ends cancelled in the background
            self._panel.cancel()
        super().reject()

    def shutdown(self) -> None:
        """Plugin unload: cancel any publish, then a best-effort logout; never blocks, never raises."""
        try:
            self._panel.cancel()
        except Exception as exc:
            log.warning("cancel on unload: %s" % type(exc).__name__)
        try:
            api = self._api
            # a job still winding down needs the session to abort its import on ELDA
            if api is not None and api.is_logged_in and not self._panel.busy:
                worker.run("ELDA : déconnexion", api.logout, lambda _r: None, lambda _e: None)
        except Exception as exc:
            log.warning("%s: %s" % (type(exc).__name__, exc))

    def _failed(self, exc: Exception) -> None:
        if isinstance(exc, SessionLost):
            self._api = None
            self._account = None
            self._all_sites = None
            self._refresh()
            self._message(exc.message_fr)
        elif isinstance(exc, EldaError):
            self._refresh()
            self._message(exc.message_fr)
        else:
            log.warning("%s: %s" % (type(exc).__name__, exc))
            self._refresh()
            self._message(texts.UNEXPECTED_ERROR)
