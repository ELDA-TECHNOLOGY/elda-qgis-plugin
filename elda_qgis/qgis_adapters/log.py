from __future__ import annotations

from qgis.core import Qgis, QgsMessageLog

from ..core.net.redact import scrub

_TAB = "ELDA"


def info(text: str) -> None:
    QgsMessageLog.logMessage(scrub(text), _TAB, Qgis.MessageLevel.Info)


def warning(text: str) -> None:
    QgsMessageLog.logMessage(scrub(text), _TAB, Qgis.MessageLevel.Warning)
