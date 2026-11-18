"""Small dialog helpers shared by the windows."""
from __future__ import annotations

import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialogButtonBox, QMessageBox

from ..qgis_adapters import log
from . import texts


def confirm(parent, text: str) -> bool:
    """Yes/no question in French; "Non" is the default and the Escape answer."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(texts.TITLE)
    # layer and server names appear in questions: never rendered as rich text
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    yes = box.addButton(texts.YES, QMessageBox.ButtonRole.YesRole)
    no = box.addButton(texts.NO, QMessageBox.ButtonRole.NoRole)
    box.setDefaultButton(no)
    box.setEscapeButton(no)
    run = getattr(box, "exec", None) or box.exec_
    run()
    return box.clickedButton() is yes


def choose(parent, text: str, labels) -> int:
    """Question with one button per label plus « Annuler »; returns the label index, or -1 when cancelled."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(texts.TITLE)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(text)
    buttons = [box.addButton(label, QMessageBox.ButtonRole.AcceptRole) for label in labels]
    cancel = box.addButton(texts.CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    run = getattr(box, "exec", None) or box.exec_
    run()
    clicked = box.clickedButton()
    return next((index for index, button in enumerate(buttons) if button is clicked), -1)


def ok_cancel_buttons() -> QDialogButtonBox:
    """Standard OK / Cancel row with a French label on Cancel."""
    standard = QDialogButtonBox.StandardButton
    buttons = QDialogButtonBox(standard.Ok | standard.Cancel)
    buttons.button(standard.Cancel).setText(texts.CANCEL)
    return buttons


def guarded(report, fn):
    """Slot wrapper for buttons: an unexpected error is logged and reported in French, never as a Python traceback."""

    def slot(*_args) -> None:
        try:
            fn()
        except Exception as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            # file name and line only: the full path names the user's home
            log.warning("unexpected %s at %s:%d" % (type(exc).__name__, os.path.basename(frame.filename), frame.lineno))
            report(texts.UNEXPECTED_ERROR)

    return slot
