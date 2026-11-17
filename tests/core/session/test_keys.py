import unittest

from elda_qgis.core.session.keys import settings_key


class SettingsKeyTest(unittest.TestCase):
    def test_no_separator_characters(self):
        key = settings_key("https://elda.example:8443/a?b=c")
        for char in "/:=\\":
            self.assertNotIn(char, key)

    def test_distinct_and_stable(self):
        a, b = "https://a.example.com", "https://a.example.com/"
        self.assertNotEqual(settings_key(a), settings_key(b))
        self.assertEqual(settings_key(a), settings_key(a))
