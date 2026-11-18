from __future__ import annotations

from typing import List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QVBoxLayout,
)

from ...core.errors import EldaError, RequestRefused, SessionLost
from ...core.publish.gis import GisApi
from ...qgis_adapters import log
from .. import dialogs, texts, worker

_ID = Qt.ItemDataRole.UserRole


def _plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class VisibilityPicker(QDialog):
    """On accept, `restricted`, `user_ids` and `group_ids` hold the choice; `session_lost` is set when the session died."""

    def __init__(self, gis: GisApi, site_id: int, restricted: bool, user_ids, group_ids, parent=None):
        super().__init__(parent)
        self.restricted = restricted
        self.user_ids: List[int] = list(user_ids)
        self.group_ids: List[int] = list(group_ids)
        self.session_lost: Optional[SessionLost] = None
        self._groups_loaded = False
        self._users_state = "loading"  # loading | loaded | refused | failed
        self.setWindowTitle(texts.VISIBILITY_TITLE)
        self.setModal(True)
        self.setMinimumSize(360, 460)

        self._whole = QRadioButton(texts.WHOLE_SITE)
        self._restrict = QRadioButton(texts.RESTRICT)
        self._groups_title = _plain_label(texts.GROUPS)
        self._groups = QListWidget()
        self._users_title = _plain_label(texts.USERS)
        self._users = QListWidget()
        self._refused = _plain_label(texts.USERS_REFUSED)
        self._refused.setVisible(False)
        self._error = _plain_label()
        buttons = dialogs.ok_cancel_buttons()
        layout = QVBoxLayout(self)
        for widget in (
            self._whole, self._restrict, self._groups_title, self._groups,
            self._users_title, self._users, self._refused, self._error, buttons,
        ):
            layout.addWidget(widget)

        (self._restrict if restricted else self._whole).setChecked(True)
        self._restrict.toggled.connect(lambda _checked: self._sync())
        for source in (self._groups, self._users):
            source.itemChanged.connect(lambda _item: self._sync())
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._sync()

        chosen_groups, chosen_users = set(self.group_ids), set(self.user_ids)
        worker.run(
            texts.TASK_LOADING,
            lambda: gis.groups(site_id),
            worker.guarded(self, lambda rows: self._groups_done([(g.id, g.name) for g in rows], chosen_groups)),
            worker.guarded(self, lambda exc: self._failed(exc, False)),
        )
        worker.run(
            texts.TASK_LOADING,
            lambda: gis.members(site_id),
            worker.guarded(self, lambda rows: self._users_done([(m.id, m.username) for m in rows], chosen_users)),
            worker.guarded(self, lambda exc: self._failed(exc, True)),
        )

    def _sync(self) -> None:
        restricted = self._restrict.isChecked()
        for widget in (self._groups, self._users):
            widget.setEnabled(restricted)
        chosen = len(self._checked(self._groups)) + len(self._checked(self._users))
        self._restrict.setText(texts.restrict_label(restricted, chosen))

    @staticmethod
    def _fill(target: QListWidget, entries, chosen) -> None:
        for entry_id, name in entries:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if entry_id in chosen else Qt.CheckState.Unchecked)
            item.setData(_ID, entry_id)
            target.addItem(item)

    def _groups_done(self, entries, chosen) -> None:
        self._fill(self._groups, entries, chosen)
        self._groups_loaded = True
        self._sync()

    def _users_done(self, entries, chosen) -> None:
        self._fill(self._users, entries, chosen)
        self._users_state = "loaded"
        self._sync()

    def _failed(self, exc: Exception, users: bool) -> None:
        if isinstance(exc, SessionLost):
            self.session_lost = exc
            self.reject()
            return
        if users and isinstance(exc, RequestRefused):
            self._users_state = "refused"
            self._users_title.setVisible(False)
            self._users.setVisible(False)
            self._refused.setVisible(True)
            return
        if users:
            self._users_state = "failed"
        if isinstance(exc, EldaError):
            self._error.setText(exc.message_fr)
        else:
            log.warning("visibility lists: %s" % type(exc).__name__)
            self._error.setText(texts.UNEXPECTED_ERROR)

    @staticmethod
    def _checked(source: QListWidget) -> List[int]:
        out = []
        for row in range(source.count()):
            item = source.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(_ID))
        return out

    def _accept(self) -> None:
        self.restricted = self._restrict.isChecked()
        # a list that never loaded keeps the previous choice; a refused user list means no user picked
        if self._groups_loaded:
            self.group_ids = self._checked(self._groups)
        if self._users_state == "loaded":
            self.user_ids = self._checked(self._users)
        elif self._users_state == "refused":
            self.user_ids = []
        self.accept()
