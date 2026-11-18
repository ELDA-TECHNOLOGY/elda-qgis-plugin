"""Run a blocking call in a QgsTask; the callbacks come back on the GUI thread."""
from __future__ import annotations

from typing import Callable, Optional, Set, TypeVar

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt import sip

from ..core.errors import EldaError
from ..qgis_adapters import log

T = TypeVar("T")

# strong references so running tasks are not garbage-collected
_running: Set[QgsTask] = set()


def run(
    task_name: str,
    fn: Callable[[], T],
    on_done: Callable[[T], None],
    on_error: Callable[[Exception], None],
    on_finally: Optional[Callable[[], None]] = None,
) -> None:
    box = {}

    def job(task):
        try:
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        return True

    def finished(exception, value=None):
        _running.discard(task)
        try:
            if "error" in box:
                on_error(box["error"])
            elif "value" in box:
                on_done(box["value"])
            else:
                # task cancelled before it ran (QGIS shutting down)
                on_error(EldaError())
        except Exception as exc:
            log.warning("%s: %s" % (type(exc).__name__, exc))
        finally:
            if on_finally is not None:
                try:
                    on_finally()
                except Exception as exc:
                    log.warning("%s: %s" % (type(exc).__name__, exc))

    task = QgsTask.fromFunction(task_name, job, on_finished=finished)
    _running.add(task)
    QgsApplication.taskManager().addTask(task)


def guarded(owner, callback: Callable) -> Callable:
    """Wrap a callback so it does nothing once the owner widget is deleted."""

    def call(*args):
        if not sip.isdeleted(owner):
            callback(*args)

    return call
