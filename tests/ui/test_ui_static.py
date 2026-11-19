from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent / "elda_qgis"
UI = ROOT / "ui"
NEW_QT = ("publish/panel.py", "publish/table.py", "publish/folder_picker.py", "publish/visibility_picker.py", "publish/runner.py")
QT_FILES = [UI / n for n in ("session/login_dialog.py", "main_dialog.py", "worker.py", "dialogs.py") + NEW_QT] + [ROOT / "plugin.py"]
ALLOWED = {"qgis", "elda_qgis", "__future__", "typing", "html", "pathlib", "os", "threading", "time", "traceback", "dataclasses"}
BACKGROUND = ("worker.py", "publish/runner.py")
WIDGET_LEVEL = (
    "QtWidgets", "QWidget", "QDialog", "QMessageBox", "QLabel", "QPushButton", "QTableWidget",
    "QTreeWidget", "QListWidget", "QgsMessageBar", "iface",
)


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), str(path))


class UiLintTest(unittest.TestCase):
    def test_qt_files_parse_and_import_only_qgis_or_plugin(self):
        for path in QT_FILES:
            for node in ast.walk(parse(path)):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    self.assertIn(root, ALLOWED, "%s imports %s" % (path.name, root))
                    self.assertFalse(root.startswith("PyQt"), path.name)

    def test_pure_modules_import_no_qt(self):
        for name in ("texts.py", "session/state.py", "publish/state.py"):
            source = (UI / name).read_text(encoding="utf-8")
            self.assertNotIn("qgis", source, name)
            self.assertNotIn("PyQt", source, name)

    def test_new_qt_files_exist(self):
        for name in NEW_QT:
            self.assertTrue((UI / name).exists(), name)

    def test_background_files_never_touch_credentials_or_widgets(self):
        for name in BACKGROUND:
            source = (UI / name).read_text(encoding="utf-8")
            self.assertNotIn("credentials", source, name)
            for word in WIDGET_LEVEL:
                self.assertNotIn(word, source, "%s references %s" % (name, word))

    def test_no_blocking_queued_connection(self):
        for path in UI.rglob("*.py"):
            self.assertNotIn("BlockingQueuedConnection", path.read_text(encoding="utf-8"), path.name)

    def test_no_return_pressed_connection(self):
        # Enter is handled by the default button; a second connection submits twice
        for path in UI.rglob("*.py"):
            self.assertNotIn("returnPressed", path.read_text(encoding="utf-8"), path.name)
