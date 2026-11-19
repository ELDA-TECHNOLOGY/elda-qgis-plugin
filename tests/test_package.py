import configparser
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from elda_qgis.version import VERSION
from scripts import package

ROOT = Path(__file__).resolve().parent.parent


class PackageTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = package.build(tmp.name)

    def test_zip_holds_only_the_plugin(self):
        with zipfile.ZipFile(self.path) as z:
            names = z.namelist()
        self.assertIn("elda_qgis/metadata.txt", names)
        self.assertIn("elda_qgis/LICENSE", names)
        self.assertIn("elda_qgis/__init__.py", names)
        for required in (
            "elda_qgis/core/session/api.py",
            "elda_qgis/qgis_adapters/transport.py",
            "elda_qgis/ui/main_dialog.py",
            "elda_qgis/resources/icon.svg",
        ):
            self.assertIn(required, names)
        self.assertFalse([n for n in names if any(part.startswith(".") for part in n.split("/"))])
        self.assertFalse([n for n in names if "tests" in n or "__pycache__" in n or n.endswith(".pyc")])

    def test_checksum_file_matches_the_zip(self):
        expected = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        self.assertEqual(Path(self.path + ".sha256").read_text().split()[0], expected)

    def test_metadata_has_required_fields(self):
        meta = configparser.ConfigParser()
        meta.read(ROOT / "elda_qgis" / "metadata.txt", encoding="utf-8")
        general = meta["general"]
        self.assertEqual(general["qgisMinimumVersion"], "3.34")
        self.assertEqual(general["version"], VERSION)
        # the last four are required by the official QGIS repository
        for key in ("name", "description", "author", "email", "about", "repository", "tracker", "homepage"):
            self.assertTrue(general[key])


if __name__ == "__main__":
    unittest.main()
