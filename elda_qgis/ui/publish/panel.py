"""Publish panel: layer table, folder, visibility, and the one-layer-at-a-time batch (GUI thread)."""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, List, Optional

from qgis.core import QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.publish import gpkg, raster, raster_checks, tempfiles, vector
from ...core.session import rights
from ...core.errors import EldaError, SessionLost
from ...core.publish.gis import GisApi
from ...core.net.http import Caller
from ...qgis_adapters import export, layers, log, raster_file, style_reader
from ...qgis_adapters.transport import QgisTransport
from . import runner
from .. import dialogs, texts, worker
from . import state as ps
from .folder_picker import FolderPicker
from .table import LayerTable
from .visibility_picker import VisibilityPicker

_EXPORT_FILE = "layer.gpkg"
_REPLACE_FILE = "layer.geojson"
# how long the full bar stays visible once a batch has ended
_DONE_MS = 1200


def _exec(dialog) -> int:
    run = getattr(dialog, "exec", None) or dialog.exec_
    return run()


def _plain_label() -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class _FittingScroll(QScrollArea):
    """As tall as its text when there is room, scrollable when the window is too small to show it all."""

    def __init__(self, label: QLabel):
        super().__init__()
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(label)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def sizeHint(self):
        return self.widget().sizeHint()

    def minimumSizeHint(self):
        hint = self.widget().minimumSizeHint()
        # two lines stay visible however small the window gets
        hint.setHeight(min(hint.height(), 2 * self.fontMetrics().lineSpacing()))
        return hint


class _Batch:
    """Everything one « Publier » click needs; `current` is the key of the row being exported or sent."""

    def __init__(self, gis: GisApi, folder_id: Optional[int], users: List[int], groups: List[int]):
        self.gis = gis
        self.cancel = threading.Event()
        # pauses between retries end at once when the batch is cancelled
        self.caller = Caller(QgisTransport(), sleep=self.cancel.wait)
        self.folder_id = folder_id
        self.users = users
        self.groups = groups
        self.current: Optional[str] = None
        # layer key -> id of the ELDA layer whose content it replaces
        self.replace: dict = {}
        # carry the QGIS symbology over to the new ELDA layers
        self.with_style = True
        # (server, user id, site id) the batch publishes to
        self.scope = None
        self.signals = runner.RunnerSignals()


class PublishPanel(QWidget):
    def __init__(self, on_busy_changed: Callable[[bool], None], on_session_lost: Callable[[Exception], None], parent=None):
        super().__init__(parent)
        self._on_busy_changed = on_busy_changed
        self._on_session_lost = on_session_lost
        self._api = None
        self._account = None
        self._site_id: Optional[int] = None
        self._rows: List[ps.Row] = []
        self._counts = {}
        self._sources = {}
        # layer key -> what is known of the raster file, read when the table is filled
        self._rasters = {}
        # what this session published, to warn before a duplicate and offer a replacement
        self._sent = ps.SentLayers()
        # layer ids are saved in project files: a copy of a project must not inherit replace targets
        for signal in (QgsProject.instance().cleared, QgsProject.instance().readProject):
            signal.connect(lambda *_args: self._sent.clear())
        # the table follows the project: a layer added or removed in QGIS shows up without « Actualiser »
        for signal in (QgsProject.instance().layersAdded, QgsProject.instance().layersRemoved):
            signal.connect(worker.guarded(self, lambda *_args: self._reload()))
        self._edited = set()
        self._folder = ps.FolderNode(None, None)
        self._restricted = False
        self._user_ids: List[int] = []
        self._group_ids: List[int] = []
        self._batch: Optional[_Batch] = None
        self._blocked = False
        # the list of existing ELDA layers is being read before a batch starts
        self._checking = False

        self._table = LayerTable(self._row_checked, self._row_renamed, self._row_raster_type)
        self._refresh = QPushButton(texts.REFRESH)
        self._folder_button = QPushButton()
        self._visibility_button = QPushButton()
        self._publish = QPushButton(texts.PUBLISH)
        self._check_all = QCheckBox(texts.CHECK_ALL)
        self._with_style = QCheckBox(texts.WITH_STYLE)
        # off by default: an untouched QGIS layer has a random opaque colour that would hide the map
        self._with_style.setChecked(False)
        self._with_style.setToolTip(texts.WITH_STYLE_HINT)
        self._cancel = QPushButton(texts.CANCEL)
        self._hint = _plain_label()
        self._summary = _plain_label()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.hide()
        self._processing_since: Optional[float] = None
        # the processing share of the bar is estimated from elapsed time
        self._ticker = QTimer(self)
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._render_progress)

        target = QHBoxLayout()
        target.addWidget(QLabel(texts.FOLDER_LABEL))
        target.addWidget(self._folder_button, 1)
        target.addWidget(QLabel(texts.VISIBILITY_LABEL))
        target.addWidget(self._visibility_button, 1)
        actions = QHBoxLayout()
        actions.addWidget(self._refresh)
        actions.addWidget(self._with_style)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._publish)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._check_all)
        layout.addWidget(self._table)
        layout.addLayout(target)
        layout.addLayout(actions)
        layout.addWidget(self._progress)
        layout.addWidget(self._hint)
        self._summary_area = _FittingScroll(self._summary)
        layout.addWidget(self._summary_area)

        self._refresh.clicked.connect(dialogs.guarded(self._report_error, self._reload))
        self._folder_button.clicked.connect(dialogs.guarded(self._report_error, self._pick_folder))
        self._visibility_button.clicked.connect(dialogs.guarded(self._report_error, self._pick_visibility))
        self._publish.clicked.connect(dialogs.guarded(self._report_error, self._start_batch))
        # clicked, not toggled: only the user's own click counts, not the box following the rows
        self._check_all.clicked.connect(dialogs.guarded(self._report_error, self._all_clicked))
        self._cancel.clicked.connect(dialogs.guarded(self._report_error, self.cancel))
        self._sync()

    # session and table

    @property
    def busy(self) -> bool:
        return self._batch is not None

    def set_session(self, api, account) -> None:
        """Called on every main window refresh; the table is left alone while a batch runs."""
        if api is not self._api:
            # another login (or none): ids learnt before must never be replaced through this session
            self._sent.clear()
        self._api, self._account = api, account
        if self.busy:
            return
        site_id = account.active_site_id if account is not None else None
        if site_id != self._site_id:
            self._site_id = site_id
            self._folder = ps.FolderNode(None, None)
            self._restricted, self._user_ids, self._group_ids = False, [], []
        if account is not None:
            self._reload()
        else:
            self._sync()

    def set_blocked(self, blocked: bool) -> None:
        """The main window is busy (site switch, logout): nothing may start meanwhile."""
        self._blocked = blocked
        self._sync()

    def _reload(self) -> None:
        if self.busy or self._account is None:
            return
        project = layers.list_project_layers()
        self._counts = {layer.layer_id: layer.feature_count for layer in project}
        self._sources = {layer.layer_id: layer.source for layer in project}
        self._rasters = {layer.layer_id: layer.raster for layer in project if layer.kind == "raster"}
        fresh = ps.rows_for(project, rights.of(self._account))
        self._rows = ps.merge_rows(self._rows, fresh, self._edited)
        self._edited &= {row.key for row in self._rows}
        self._fill()

    def _fill(self) -> None:
        self._table.fill(self._rows, self._counts, self._sources, editing=not self.busy)
        self._sync()

    def _render_statuses(self) -> None:
        self._table.render_statuses(self._rows)
        self._render_progress()

    def _render_progress(self) -> None:
        since = self._processing_since
        seconds = time.monotonic() - since if since is not None else 0.0
        value = ps.progress(self._rows, seconds) if self.busy else None
        if value is not None:
            self._progress.setVisible(True)
            self._progress.setValue(value)
        elif not self._progress.isHidden():
            # the batch has ended: show a full bar for a moment instead of vanishing mid-way
            self._progress.setValue(100)
            QTimer.singleShot(_DONE_MS, self._hide_progress)

    def _hide_progress(self) -> None:
        if not sip.isdeleted(self) and not self.busy:
            self._progress.hide()

    def _row_checked(self, key: str, checked: bool) -> None:
        if not self.busy:
            self._rows = ps.set_checked(self._rows, key, checked)
            self._sync()

    def _all_clicked(self) -> None:
        if not self.busy:
            self._rows = ps.set_all_checked(self._rows, self._check_all.isChecked())
            self._fill()

    def _row_renamed(self, key: str, text: str) -> str:
        if not self.busy:
            self._rows = ps.rename(self._rows, key, text)
            self._edited.add(key)
            self._sync()
        return next((row.name for row in self._rows if row.key == key), text)

    def _row_raster_type(self, key: str, raster_type: Optional[str]) -> None:
        if not self.busy:
            self._rows = ps.set_raster_type(self._rows, key, raster_type)
            self._sync()

    def _sync(self) -> None:
        busy = self.busy
        ok, reason = ps.can_publish(self._rows, self._account is not None, busy or self._blocked or self._checking)
        self._publish.setEnabled(ok)
        self._hint.setText("" if ok or busy or self._blocked or self._checking else (reason or ""))
        self._cancel.setVisible(busy)
        self._cancel.setEnabled(busy and not self._batch.cancel.is_set())
        idle = not busy and not self._blocked and not self._checking
        for widget in (self._refresh, self._with_style, self._folder_button, self._visibility_button):
            widget.setEnabled(idle)
        self._check_all.setEnabled(idle and any(row.selectable for row in self._rows))
        self._check_all.setChecked(ps.all_checked(self._rows))
        self._folder_button.setText(self._folder.label())
        self._visibility_button.setText(
            texts.visibility_summary(self._restricted, len(self._group_ids), len(self._user_ids))
        )

    # pickers

    def _pick_folder(self) -> None:
        if self._api is None or self.busy:
            return
        picker = FolderPicker(GisApi(self._api), self)
        try:
            if _exec(picker) and picker.chosen is not None:
                self._folder = picker.chosen
            lost = picker.session_lost
        finally:
            picker.deleteLater()
        self._after_picker(lost)

    def _pick_visibility(self) -> None:
        if self._api is None or self.busy or self._site_id is None:
            return
        picker = VisibilityPicker(
            GisApi(self._api), self._site_id, self._restricted, self._user_ids, self._group_ids, self
        )
        try:
            if _exec(picker):
                self._restricted = picker.restricted
                self._user_ids, self._group_ids = picker.user_ids, picker.group_ids
            lost = picker.session_lost
        finally:
            picker.deleteLater()
        self._after_picker(lost)

    def _after_picker(self, lost) -> None:
        if lost is not None:
            self._on_session_lost(lost)
        else:
            self._sync()

    # batch

    def cancel(self) -> None:
        """Window button, window close and plugin unload; never blocks."""
        batch = self._batch
        if batch is None:
            return
        batch.cancel.set()
        export.cancel_all()
        self._sync()

    def _say(self, text: str, tone: Optional[str] = None) -> None:
        """Write under the table; an error is coloured and bold so that it cannot be missed."""
        color = texts.tone_color(tone)
        self._summary.setStyleSheet("color: %s; font-weight: bold;" % color if color else "")
        self._summary.setText(text)
        # the scroll area takes its height from the text: tell the layout it has changed
        self._summary_area.updateGeometry()

    def _report_error(self, text: str) -> None:
        self._say(text, "error")

    def _alive(self, batch: _Batch) -> bool:
        return not sip.isdeleted(self) and batch is self._batch

    def _scope(self):
        return (self._api.server_url, self._account.user_id, self._account.active_site_id)

    def _can_start(self) -> bool:
        blocked = self.busy or self._blocked or self._checking
        return ps.can_publish(self._rows, self._account is not None, blocked)[0] and self._api is not None

    def _start_batch(self) -> None:
        """Read the layers that already exist in ELDA, then ask about duplicates and start."""
        if not self._can_start():
            return
        scope, gis, site = self._scope(), GisApi(self._api), self._account.active_site_id
        self._checking = True
        self._say(texts.CHECKING_EXISTING)
        self._sync()

        def read_existing():
            """(layers, rasters) of the site; None for a list this account cannot read.

            Both are always read: the ticks may still change while the answer is on its way.
            """

            def listed(fetch):
                try:
                    return fetch()
                except SessionLost:
                    raise
                except EldaError:
                    return None

            return listed(lambda: gis.site_layers(site)), listed(lambda: gis.site_rasters(site))

        def done(existing) -> None:
            layers_found, rasters_found = existing

            def resume() -> None:
                self._existing_known(scope, gis, layers_found, rasters_found)

            dialogs.guarded(self._report_error, resume)()

        def failed(exc: Exception) -> None:
            if isinstance(exc, SessionLost):
                self._checking = False
                self._say("")
                self._sync()
                self._on_session_lost(exc)
                return
            # no read right, or no network: fall back on what this session remembers
            log.info("existing layers not read: %s" % type(exc).__name__)
            done((None, None))

        worker.run(texts.TASK_LOADING, read_existing, worker.guarded(self, done), worker.guarded(self, failed))

    def _existing_known(self, scope, gis: GisApi, layers, rasters) -> None:
        self._checking = False
        self._say("")
        self._sync()
        # the login, the site or the ticks may have changed while the list was loading
        if not self._can_start() or self._scope() != scope:
            return
        plan = ps.duplicate_plan(self._rows, layers, self._folder.folder_id, self._sent.known(scope), rasters)
        replace = {}
        if plan.names and not plan.targets:
            if not dialogs.confirm(self, texts.confirm_duplicate(plan.names, plan.why, plan.raster_names)):
                return
        elif plan.names:
            text = texts.choose_duplicate(plan.names, plan.raster_names)
            choice = dialogs.choose(self, text, [texts.REPLACE_CONTENT, texts.CREATE_NEW])
            if choice < 0:
                return
            replace = plan.targets if choice == 0 else {}
        users, groups = ps.visibility(self._restricted, self._user_ids, self._group_ids, self._account.user_id)
        batch = _Batch(gis, self._folder.folder_id, users, groups)
        batch.replace = replace
        batch.with_style = self._with_style.isChecked()
        batch.scope = scope
        queued = Qt.ConnectionType.QueuedConnection
        batch.signals.step.connect(lambda *args: self._on_step(batch, *args), type=queued)
        batch.signals.finished.connect(lambda end: self._on_job_end(batch, end), type=queued)
        batch.signals.ask_slow.connect(lambda question: self._on_ask_slow(batch, question), type=queued)
        self._batch = batch
        self._rows = ps.mark_waiting(self._rows)
        self._say("")
        self._busy_changed()
        self._safely(batch, self._next, batch, ps.next_waiting(self._rows))

    def _busy_changed(self) -> None:
        self._fill()
        if self.busy:
            self._ticker.start()
        else:
            self._ticker.stop()
        self._render_progress()
        self._on_busy_changed(self.busy)

    def _safely(self, batch: _Batch, fn, *args) -> None:
        """A bug in the wiring ends the batch instead of leaving the window busy forever."""
        try:
            fn(*args)
        except Exception as exc:
            log.warning("publish window: %s" % type(exc).__name__)
            if self._alive(batch):
                batch.cancel.set()
                self._rows = ps.mark_unpublished(self._rows, "")
                self._end_batch()

    def _next(self, batch: _Batch, key: Optional[str]) -> None:
        if key is None:
            self._end_batch()
            return
        batch.current = key
        self._rows = ps.update_row(self._rows, key, lambda r: ps.apply_step(r, vector.INITIATE, 0, 0))
        self._render_statuses()
        row = next(r for r in self._rows if r.key == key)
        if row.kind == "raster":
            self._send_raster(batch, row)
            return
        try:
            folder = tempfiles.temp_dir()
        except OSError as exc:
            log.warning("temporary folder: %s" % type(exc).__name__)
            self._export_failed(batch, key, "", export.EXPORT_FAILED_FR)
            return
        replacing = key in batch.replace
        path = os.path.join(folder, _REPLACE_FILE if replacing else _EXPORT_FILE)

        def done() -> None:
            if not self._alive(batch) or batch.cancel.is_set():
                tempfiles.cleanup(folder)
                if self._alive(batch):
                    self._safely(batch, self._row_done, batch, key)
                return
            if not replacing and not self._export_looks_complete(key, path):
                self._export_failed(batch, key, folder, texts.EXPORT_EMPTY)
                return
            self._safely(batch, self._send, batch, key, folder, path)

        def failed(message: str) -> None:
            self._export_failed(batch, key, folder, message)

        export.export_layer(key, path, done, failed, as_geojson=replacing)

    def _send_raster(self, batch: _Batch, row: ps.Row) -> None:
        """A raster is sent as it is: no export, but a check first, since ELDA rejects many files after the upload."""
        listed = self._rasters.get(row.key)
        # read the file itself, now: what QGIS shows (a CRS set on the layer, a scaled type) is not what ELDA gets
        info = raster_file.read(listed.path) if listed is not None and listed.path else None
        problem = raster_checks.problem(info, row.raster_type) if info is not None else raster_checks.NOT_A_FILE
        if problem is not None:
            self._rows = ps.fail_row(self._rows, row.key, problem)
            self._row_done(batch, row.key)
            return
        job = raster.RasterJob(row.key, info.path, row.name, row.raster_type, batch.folder_id, batch.users, batch.groups)
        # no temporary folder to clean: the file sent is the user's own
        runner.start(job, batch.gis, batch.caller, batch.cancel, "", batch.signals)

    def _export_looks_complete(self, key: str, path: str) -> bool:
        """False when QGIS wrote no feature for a layer that has some: such a file must never be published."""
        expected = self._counts.get(key)
        written = gpkg.feature_count(path)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = -1
        log.info("export: %s features in the layer, %s written, %d bytes" % (expected, written, size))
        return not (written == 0 and expected)

    def _export_failed(self, batch: _Batch, key: str, folder: str, message: str) -> None:
        tempfiles.cleanup(folder)
        if not self._alive(batch):
            return
        if not batch.cancel.is_set():
            # a cancelled export also ends here; advance() then marks the row cancelled
            self._rows = ps.fail_row(self._rows, key, message)
        self._safely(batch, self._row_done, batch, key)

    def _send(self, batch: _Batch, key: str, folder: str, path: str) -> None:
        try:
            row = next(r for r in self._rows if r.key == key)
            replaced = batch.replace.get(key)
            style, notes = (None, [])
            if replaced is None and batch.with_style:
                # a replaced layer keeps the style it has in ELDA
                style, notes = style_reader.read(key)
            job = vector.Job(key, path, row.name, batch.folder_id, batch.users, batch.groups, replaced, style, tuple(notes))
            runner.start(job, batch.gis, batch.caller, batch.cancel, folder, batch.signals)
        except Exception:
            tempfiles.cleanup(folder)
            raise

    def _on_step(self, batch: _Batch, key: str, step: str, sent, total) -> None:
        # a step from another row (late or stray) is dropped
        if not self._alive(batch) or key != batch.current:
            return
        if step == vector.PROCESSING and self._processing_since is None:
            self._processing_since = time.monotonic()
        self._rows = ps.update_row(self._rows, key, lambda r: ps.apply_step(r, step, sent, total))
        self._render_statuses()

    def _on_ask_slow(self, batch: _Batch, question) -> None:
        try:
            if self._alive(batch) and not batch.cancel.is_set():
                question.answer = dialogs.confirm(self, texts.confirm_slow(question.minutes))
        finally:
            question.answered.set()

    def _on_job_end(self, batch: _Batch, end) -> None:
        if not self._alive(batch) or end.key != batch.current:
            return
        self._safely(batch, self._job_ended, batch, end)

    def _job_ended(self, batch: _Batch, end) -> None:
        key = end.key
        name = next((r.name for r in self._rows if r.key == key), "")
        if isinstance(end.error, SessionLost):
            log.info("publish of %s: session lost" % name)
            self._rows = ps.mark_session_lost(self._rows, key)
            self._end_batch()
            self._on_session_lost(end.error)
            return
        if end.error is not None:
            log.warning("publish of %s: unexpected %s" % (name, type(end.error).__name__))
            self._rows = ps.fail_row(self._rows, key, texts.UNEXPECTED_ERROR)
        elif end.outcome is None:
            # the task manager dropped the job before it ran (QGIS closing)
            batch.cancel.set()
        else:
            log.info("publish of %s: %s" % (name, end.outcome.status))
            self._sent.record(batch.scope, key, end.outcome)
            self._rows = ps.update_row(self._rows, key, lambda r: ps.apply_outcome(r, end.outcome))
        self._row_done(batch, key)

    def _row_done(self, batch: _Batch, key: str) -> None:
        self._rows, following = ps.advance(self._rows, key, batch.cancel.is_set())
        self._processing_since = None
        self._render_statuses()
        self._next(batch, following)

    def _end_batch(self) -> None:
        self._batch = None
        failed = any(texts.status_tone(row.status) == "error" for row in self._rows)
        self._say(ps.summary(self._rows), "error" if failed else None)
        self._busy_changed()
