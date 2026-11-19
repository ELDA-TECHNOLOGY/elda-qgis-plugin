"""Background side of a publish: one QgsTask per layer, talking to the GUI only through queued signals."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional, Set

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ...core.publish import raster, tempfiles, vector
from ...core.publish.gis import GisApi
from ...core.net.http import Caller
from .. import texts

_ASK_POLL_SECONDS = 0.25

# strong references so running tasks are not garbage-collected
_running: Set["PublishTask"] = set()


class SlowQuestion:
    """Asked from the worker, answered on the GUI thread; the answer stays False unless the user says yes."""

    def __init__(self, minutes: int):
        self.minutes = minutes
        self.answer = False
        self.answered = threading.Event()


@dataclass(frozen=True)
class JobEnd:
    key: str
    outcome: Optional[vector.Outcome]  # None when the job raised or never ran
    error: Optional[Exception]


class RunnerSignals(QObject):
    """Created on the GUI thread; the worker only emits, every slot is connected queued."""

    # key, step, sent, total; sizes go as objects since they can exceed a 32-bit int
    step = pyqtSignal(str, str, object, object)
    finished = pyqtSignal(object)  # JobEnd
    ask_slow = pyqtSignal(object)  # SlowQuestion


class PublishTask(QgsTask):
    def __init__(
        self,
        job: vector.Job,
        gis: GisApi,
        caller: Caller,
        cancel: threading.Event,
        folder: str,
        signals: RunnerSignals,
    ):
        super().__init__(texts.publish_task(job.layer_name))
        self._job = job
        self._gis = gis
        self._caller = caller
        self._cancel = cancel
        self._folder = folder
        self._signals = signals
        self._ran = False

    def cancel(self) -> None:
        # a cancel from the QGIS task manager stops the whole batch, like the window button
        self._cancel.set()
        super().cancel()

    def _is_cancelled(self) -> bool:
        return self._cancel.is_set() or self.isCanceled()

    def _on_step(self, step: str, sent: int, total: int) -> None:
        self._signals.step.emit(self._job.key, step, sent, total)

    def _confirm_slow(self, minutes: int) -> bool:
        question = SlowQuestion(minutes)
        self._signals.ask_slow.emit(question)
        while not question.answered.wait(_ASK_POLL_SECONDS):
            if self._is_cancelled():
                return False
        return question.answer and not self._is_cancelled()

    def run(self) -> bool:
        self._ran = True
        try:
            # a raster goes as it is; a vector layer was exported to the temporary folder first
            publish = raster.publish_raster if isinstance(self._job, raster.RasterJob) else vector.publish_vector
            outcome = publish(
                self._job,
                self._gis,
                self._caller,
                self._on_step,
                self._is_cancelled,
                self._confirm_slow,
                sleep=self._cancel.wait,
            )
            end = JobEnd(self._job.key, outcome, None)
        except Exception as exc:
            end = JobEnd(self._job.key, None, exc)
        finally:
            tempfiles.cleanup(self._folder)
        self._signals.finished.emit(end)
        return True

    def finished(self, _result: bool) -> None:
        # GUI thread, after run() or instead of it when the task was dropped before starting
        _running.discard(self)
        tempfiles.cleanup(self._folder)
        if not self._ran:
            self._signals.finished.emit(JobEnd(self._job.key, None, None))


def start(
    job: vector.Job,
    gis: GisApi,
    caller: Caller,
    cancel: threading.Event,
    folder: str,
    signals: RunnerSignals,
) -> None:
    """GUI thread only; the task owns the temporary folder and removes it on every path."""
    task = PublishTask(job, gis, caller, cancel, folder, signals)
    _running.add(task)
    QgsApplication.taskManager().addTask(task)
