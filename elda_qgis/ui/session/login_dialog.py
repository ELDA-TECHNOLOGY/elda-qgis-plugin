from __future__ import annotations

from typing import Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...core.errors import EldaError, UnsafeUrl
from ...qgis_adapters import credentials, log, settings
from . import state
from .. import dialogs, texts, worker


def _plain_label() -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class LoginDialog(QDialog):
    """Asks for server and credentials; on accept, `api`, `account` and `server_url` are set."""

    def __init__(self, api_factory: Callable[[str], object], parent=None):
        super().__init__(parent)
        self._api_factory = api_factory
        self.api = None
        self.account = None
        self.server_url = ""
        self._busy = False
        self._filled_for = None
        self.setWindowTitle(texts.LOGIN_TITLE)
        self.setModal(True)

        self._server = QComboBox()
        for label, url in state.server_options():
            self._server.addItem(label, url)
        self._other = QLineEdit()
        self._other.setPlaceholderText(texts.OTHER_SERVER_PLACEHOLDER)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._remember = QCheckBox(texts.REMEMBER)
        self._warning = _plain_label()
        self._warning.setText(texts.SINGLE_SESSION_WARNING)
        self._error = _plain_label()
        self._busy_text = _plain_label()
        self._connect = QPushButton(texts.CONNECT)
        self._connect.setDefault(True)

        form = QFormLayout()
        form.addRow(texts.SERVER, self._server)
        form.addRow("", self._other)
        form.addRow(texts.USERNAME, self._username)
        form.addRow(texts.PASSWORD, self._password)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._remember)
        layout.addWidget(self._warning)
        layout.addWidget(self._error)
        layout.addWidget(self._busy_text)
        layout.addWidget(self._connect)

        index, text = state.initial_server(settings.last_server())
        self._server.setCurrentIndex(index)
        self._other.setText(text)
        self._sync_other()
        self._fill_saved()

        self._server.currentIndexChanged.connect(self._on_server_changed)
        self._other.editingFinished.connect(self._fill_saved)
        self._connect.clicked.connect(dialogs.guarded(self._error.setText, self._submit))
        self._on_error = worker.guarded(self, self._login_failed)
        self._on_finally = worker.guarded(self, lambda: self._set_busy(False))

    def _raw_server(self) -> str:
        url = self._server.currentData()
        return url if url is not None else self._other.text()

    def _sync_other(self) -> None:
        self._other.setVisible(self._server.currentData() is None)

    def _on_server_changed(self, _index: int) -> None:
        self._sync_other()
        self._fill_saved()

    def _fill_saved(self) -> None:
        try:
            url = state.server_choice(self._raw_server()).url
        except UnsafeUrl:
            url = None
        if not state.should_reload_saved(self._filled_for, url):
            return
        self._filled_for = url
        # a password saved for one server must never travel to another
        self._password.clear()
        self._remember.setChecked(False)
        if url is None:
            return
        saved = credentials.load(url)
        if saved is not None:
            self._username.setText(saved[0])
            self._password.setText(saved[1])
            self._remember.setChecked(True)

    def reject(self) -> None:
        # a login in flight cannot be cancelled; the transport timeout bounds the wait
        if not self._busy:
            super().reject()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self._server, self._other, self._username, self._password, self._remember, self._connect):
            widget.setEnabled(not busy)
        self._busy_text.setText(texts.BUSY if busy else "")

    def _submit(self) -> None:
        if self._busy:
            return
        self._error.setText("")
        username = self._username.text().strip()
        password = self._password.text()
        if not username or not password:
            self._error.setText(texts.MISSING_FIELDS)
            return
        try:
            choice = state.server_choice(self._raw_server())
        except UnsafeUrl as exc:
            self._error.setText(exc.message_fr)
            return
        if not state.password_belongs_to(self._filled_for, choice.url):
            # editingFinished may not have fired (clicking the button does not take focus on macOS)
            self._fill_saved()
            self._error.setText(texts.SERVER_CHANGED)
            return
        if choice.needs_confirmation and not dialogs.confirm(self, texts.unknown_server(choice.url)):
            return
        # the field is emptied now: success or failure, the password lives only in the call below
        self._password.clear()
        api = self._api_factory(choice.url)
        remember = self._remember.isChecked()
        self._set_busy(True)

        def done(account):
            self._login_done(api, account, choice.url, username, password, remember)

        worker.run(
            texts.TASK_LOGIN,
            lambda: api.login(username, password),
            worker.guarded(self, done),
            self._on_error,
            self._on_finally,
        )

    def _login_done(self, api, account, url, username, password, remember) -> None:
        if remember and not credentials.save(url, username, password):
            QMessageBox.warning(self, texts.TITLE, texts.CREDENTIALS_NOT_SAVED)
        settings.set_last_server(url)
        self.api, self.account, self.server_url = api, account, url
        self.accept()

    def _login_failed(self, exc: Exception) -> None:
        if isinstance(exc, EldaError):
            self._error.setText(exc.message_fr)
        else:
            log.warning("%s: %s" % (type(exc).__name__, exc))
            self._error.setText(texts.UNEXPECTED_ERROR)
