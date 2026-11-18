import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent / "elda_qgis"
ADAPTERS = ROOT / "qgis_adapters"
CORE = ROOT / "core"
FORBIDDEN = (
    "QgsBlockingNetworkRequest",
    "ignoreSslErrors",
    "QNetworkRequest.RedirectPolicyAttribute",
    "QNetworkRequest.ManualRedirectPolicy",
    "QNetworkRequest.HttpStatusCodeAttribute",
    "Qgis.Info",
    "Qgis.Warning",
)

REQUIRED_IN_TRANSPORT = (
    "ManualRedirectPolicy",
    "CookieLoadControlAttribute",
    "CookieSaveControlAttribute",
    "setTransferTimeout",
    "sslErrors.connect",
    "CacheSaveControlAttribute",
    "AlwaysNetwork",
    "MAX_REPLY_BYTES",
    "sslCertCustomConfigByHost",
)


def absolute_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield (node.module or "").split(".")[0]


class QgisAdaptersStaticTest(unittest.TestCase):
    def test_adapters_are_valid_and_safe(self):
        files = sorted(ADAPTERS.glob("*.py"))
        self.assertGreaterEqual(len(files), 5)
        for path in files:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, str(path))
            for word in FORBIDDEN:
                self.assertNotIn(word, source, "%s uses %s" % (path.name, word))
            for root in absolute_imports(tree):
                self.assertIn(root, {"qgis", "elda_qgis", "__future__", "json", "typing", "dataclasses"}, "%s imports %s" % (path.name, root))

    def test_layers_and_export_exist(self):
        for name in ("layers.py", "export.py"):
            path = ADAPTERS / name
            self.assertTrue(path.exists(), name)
            ast.parse(path.read_text(encoding="utf-8"), str(path))
        source = (ADAPTERS / "export.py").read_text(encoding="utf-8")
        self.assertIn("QgsVectorFileWriterTask", source)
        self.assertIn('"GPKG"', source)

    def test_transport_has_its_safeguards(self):
        source = (ADAPTERS / "transport.py").read_text(encoding="utf-8")
        for word in REQUIRED_IN_TRANSPORT:
            self.assertIn(word, source)

    def test_core_never_imports_qt_or_qgis(self):
        for path in sorted(CORE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for root in absolute_imports(tree):
                self.assertFalse(root == "qgis" or root.startswith("PyQt"), "%s imports %s" % (path.name, root))
