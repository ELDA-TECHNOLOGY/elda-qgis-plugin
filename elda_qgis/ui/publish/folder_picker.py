from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ...core.errors import EldaError, SessionLost
from ...core.publish.gis import GisApi
from ...qgis_adapters import log
from .. import dialogs, texts, worker
from .state import FolderNode

_NODE = Qt.ItemDataRole.UserRole


class FolderPicker(QDialog):
    """Lazy folder tree; on accept `chosen` is the FolderNode picked. `session_lost` is set when the session died."""

    def __init__(self, gis: GisApi, parent=None):
        super().__init__(parent)
        self._gis = gis
        self.chosen = None
        self.session_lost = None
        self.setWindowTitle(texts.FOLDER_TITLE)
        self.setModal(True)
        self.setMinimumSize(360, 400)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._error = QLabel()
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._buttons = dialogs.ok_cancel_buttons()
        layout = QVBoxLayout(self)
        layout.addWidget(self._tree)
        layout.addWidget(self._error)
        layout.addWidget(self._buttons)

        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        self._tree.itemExpanded.connect(self._expanded)
        self._tree.currentItemChanged.connect(lambda *_args: self._sync_ok())

        root = self._add(None, FolderNode(None, None), texts.SITE_ROOT)
        self._tree.setCurrentItem(root)
        root.setExpanded(True)
        # setExpanded may or may not emit itemExpanded; start_load makes the second call a no-op
        self._expanded(root)

    def _add(self, parent, node: FolderNode, text: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, _NODE, node)
        placeholder = QTreeWidgetItem([texts.LOADING])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        item.addChild(placeholder)
        if parent is None:
            self._tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def _expanded(self, item) -> None:
        node = item.data(0, _NODE)
        if node is None or not node.start_load():
            return
        self._error.setText("")
        gis = self._gis
        if node.folder_id is None:
            fetch = gis.root_folders
        else:
            folder_id = node.folder_id

            def fetch():
                return gis.subfolders(folder_id)

        worker.run(
            texts.TASK_LOADING,
            fetch,
            worker.guarded(self, lambda folders: self._loaded(item, node, folders)),
            worker.guarded(self, lambda exc: self._load_failed(item, node, exc)),
        )

    def _loaded(self, item, node: FolderNode, folders) -> None:
        node.loaded()
        item.takeChildren()
        for folder in folders:
            child = node.child(folder.id, folder.name)
            self._add(item, child, folder.name.strip() or texts.UNNAMED_FOLDER)

    def _load_failed(self, item, node: FolderNode, exc: Exception) -> None:
        node.load_failed()
        # collapsed again so expanding it retries the load
        item.setExpanded(False)
        if isinstance(exc, SessionLost):
            self.session_lost = exc
            self.reject()
            return
        if isinstance(exc, EldaError):
            message = exc.message_fr
        else:
            log.warning("folder list: %s" % type(exc).__name__)
            message = texts.UNEXPECTED_ERROR
        self._error.setText(message + " " + texts.RETRY_FOLDER)

    def _sync_ok(self) -> None:
        item = self._tree.currentItem()
        ok = item is not None and item.data(0, _NODE) is not None
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _accept(self) -> None:
        item = self._tree.currentItem()
        node = item.data(0, _NODE) if item is not None else None
        if node is None:
            return
        self.chosen = node
        self.accept()
