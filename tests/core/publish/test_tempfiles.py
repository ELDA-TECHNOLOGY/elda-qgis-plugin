import os
import tempfile
import unittest

from elda_qgis.core.publish import tempfiles


class TempFilesTest(unittest.TestCase):
    def test_temp_dir_is_private_under_system_temp(self):
        path = tempfiles.temp_dir()
        self.addCleanup(tempfiles.cleanup, path)
        self.assertTrue(os.path.isdir(path))
        self.assertTrue(os.path.basename(path).startswith("elda_qgis_"))
        self.assertEqual(os.path.realpath(os.path.dirname(path)), os.path.realpath(tempfile.gettempdir()))

    def test_cleanup_removes_the_directory_and_content(self):
        path = tempfiles.temp_dir()
        open(os.path.join(path, "a.gpkg"), "w").close()
        tempfiles.cleanup(path)
        self.assertFalse(os.path.exists(path))

    def test_cleanup_refuses_another_prefix(self):
        path = tempfile.mkdtemp(prefix="other_")
        self.addCleanup(os.rmdir, path)
        tempfiles.cleanup(path)
        self.assertTrue(os.path.isdir(path))

    def test_cleanup_of_missing_path_does_not_raise(self):
        tempfiles.cleanup(os.path.join(tempfile.gettempdir(), "elda_qgis_missing"))
        tempfiles.cleanup("")
