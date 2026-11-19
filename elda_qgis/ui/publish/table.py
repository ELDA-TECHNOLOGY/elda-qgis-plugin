"""The table of project layers. The panel owns the rows; the table shows them and reports edits (GUI thread)."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFontMetrics
from qgis.PyQt.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QTableWidget, QTableWidgetItem

from ...core.publish import raster_checks
from .. import texts
from . import state as ps

CHECK, NAME, KIND, COUNT, STATUS = range(5)


class _TypeChoice(QComboBox):
    def wheelEvent(self, event) -> None:
        # scrolling the table over the box must not change a raster's type behind the user's back
        event.ignore()


def _tint(cell: QTableWidgetItem, status: str) -> None:
    """A failure must catch the eye: coloured and bold; a neutral status goes back to the default look."""
    color = texts.tone_color(texts.status_tone(status))
    cell.setForeground(QBrush(QColor(color)) if color else QBrush())
    font = cell.font()
    font.setBold(color is not None)
    cell.setFont(font)


class LayerTable(QTableWidget):
    def __init__(
        self,
        on_checked: Callable[[str, bool], None],
        on_renamed: Callable[[str, str], str],
        on_raster_type: Callable[[str, Optional[str]], None],
        parent=None,
    ):
        """`on_renamed` returns the name actually kept, which may differ from what was typed."""
        super().__init__(0, len(texts.column_titles()), parent)
        self._on_checked = on_checked
        self._on_renamed = on_renamed
        self._on_raster_type = on_raster_type
        self._keys: List[str] = []
        # set while the table writes its own cells, so those writes are not taken for user edits
        self._filling = False
        self.setHorizontalHeaderLabels(texts.column_titles())
        self.verticalHeader().setVisible(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        # sized once for its widest text, in bold: the table must not shift while a layer goes through its states
        header.setSectionResizeMode(STATUS, QHeaderView.ResizeMode.Fixed)
        bold = self.font()
        bold.setBold(True)
        metrics = QFontMetrics(bold)
        self.setColumnWidth(STATUS, max(metrics.horizontalAdvance(text) for text in texts.status_samples()) + 24)
        self.setMinimumHeight(160)
        self.itemChanged.connect(self._item_changed)

    def fill(self, rows: List[ps.Row], counts: Dict[str, Optional[int]], sources: Dict[str, str], editing: bool) -> None:
        """Rebuild every row; `editing` is False while a batch runs."""
        self._filling = True
        try:
            self._keys = [row.key for row in rows]
            self.setRowCount(len(rows))
            for index, row in enumerate(rows):
                self._fill_row(index, row, counts.get(row.key), sources.get(row.key), editing)
        finally:
            self._filling = False

    def _fill_row(self, index: int, row: ps.Row, count: Optional[int], source: Optional[str], editing: bool) -> None:
        enabled, selectable = Qt.ItemFlag.ItemIsEnabled, Qt.ItemFlag.ItemIsSelectable
        check = QTableWidgetItem()
        check.setCheckState(Qt.CheckState.Checked if row.checked else Qt.CheckState.Unchecked)
        cells = [
            check,
            QTableWidgetItem(row.name),
            QTableWidgetItem(texts.kind_text(row.kind)),
            QTableWidgetItem(texts.feature_count(count)),
            QTableWidgetItem(texts.status_text(row.status, row.percent)),
        ]
        if row.selectable:
            check.setFlags((enabled | Qt.ItemFlag.ItemIsUserCheckable) if editing else enabled)
            cells[NAME].setFlags((enabled | selectable | Qt.ItemFlag.ItemIsEditable) if editing else (enabled | selectable))
            for cell in cells[KIND:]:
                cell.setFlags(enabled | selectable)
            cells[STATUS].setToolTip(texts.plain_tooltip(row.message))
            cells[NAME].setToolTip(texts.plain_tooltip(source))
        else:
            # disabled items render greyed; the reason stays readable as a tooltip
            for cell in cells:
                cell.setFlags(Qt.ItemFlag.NoItemFlags)
                cell.setToolTip(texts.plain_tooltip(row.reason))
        _tint(cells[STATUS], row.status)
        for column, cell in enumerate(cells):
            self.setItem(index, column, cell)
        if row.kind == "raster" and row.selectable:
            self.setCellWidget(index, KIND, self._type_choice(row, editing))
        else:
            self.removeCellWidget(index, KIND)

    def _type_choice(self, row: ps.Row, editing: bool) -> QComboBox:
        """ELDA needs the type of a raster; only a colour image can be guessed."""
        combo = _TypeChoice()
        combo.addItem(texts.RASTER_TYPE_PLACEHOLDER, None)
        for raster_type in raster_checks.TYPES:
            combo.addItem(raster_checks.TYPE_LABELS[raster_type], raster_type)
        combo.setCurrentIndex(max(0, combo.findData(row.raster_type)))
        combo.setEnabled(editing)
        key = row.key
        combo.currentIndexChanged.connect(lambda _index: self._on_raster_type(key, combo.currentData()))
        return combo

    def render_statuses(self, rows: List[ps.Row]) -> None:
        """Refresh the status column only, without rebuilding the rows."""
        self._filling = True
        try:
            for index, row in enumerate(rows):
                cell = self.item(index, STATUS)
                if cell is not None:
                    cell.setText(texts.status_text(row.status, row.percent))
                    _tint(cell, row.status)
                    if row.selectable:
                        cell.setToolTip(texts.plain_tooltip(row.message))
        finally:
            self._filling = False

    def _item_changed(self, item) -> None:
        if self._filling or not 0 <= item.row() < len(self._keys):
            return
        key = self._keys[item.row()]
        if item.column() == CHECK:
            self._on_checked(key, item.checkState() == Qt.CheckState.Checked)
        elif item.column() == NAME:
            kept = self._on_renamed(key, item.text())
            if item.text() != kept:
                self._filling = True
                try:
                    item.setText(kept)
                finally:
                    self._filling = False
