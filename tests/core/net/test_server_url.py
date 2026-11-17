import unittest

from elda_qgis.core.errors import UnsafeUrl
from elda_qgis.core.net.server_url import is_known, normalize


class NormalizeTest(unittest.TestCase):
    def test_lowercases_and_strips_path(self):
        self.assertEqual(normalize(" HTTPS://Data.EldaTechnology.fr/app/ "), "https://data.eldatechnology.fr")

    def test_http_allowed_on_loopback(self):
        self.assertEqual(normalize("http://localhost:8888/"), "http://localhost:8888")
        self.assertEqual(normalize("http://127.0.0.1:3000"), "http://127.0.0.1:3000")

    def test_keeps_https_port(self):
        self.assertEqual(normalize("https://x.fr:8443/a"), "https://x.fr:8443")

    def test_drops_default_port(self):
        self.assertEqual(normalize("https://data.eldatechnology.fr:443"), "https://data.eldatechnology.fr")
        self.assertEqual(normalize("http://localhost:80"), "http://localhost")
        self.assertTrue(is_known("https://data.eldatechnology.fr:443"))

    def test_accepts_ip_literals(self):
        self.assertEqual(normalize("https://192.168.1.5:8443"), "https://192.168.1.5:8443")
        self.assertEqual(normalize("https://[::1]:8443"), "https://[::1]:8443")

    def test_refuses_unsafe(self):
        bad = (
            "http://data.eldatechnology.fr", "ftp://x.fr", "data.eldatechnology.fr", "https://",
            "https://user:pw@x.fr", "https://user@x.fr", "", "   ", "https:///path", "http://",
            "https://data.eldatechnology.fr\\evil.com", "https://evil.com\\data.eldatechnology.fr",
            "https://a b.fr", "https://ex%61mple.com", "https://b\u00fccher.de", "https://x.fr:0",
            "https://-a.fr", "https://a-.fr", "https://a..fr", "https://a_b.fr", "http://[::1]",
        )
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(UnsafeUrl):
                    normalize(raw)

    def test_is_known(self):
        self.assertTrue(is_known("https://data.eldatechnology.fr"))
        self.assertTrue(is_known("HTTPS://data.eldatechnology.fr/x"))
        self.assertFalse(is_known("https://elda.example.com"))
        self.assertFalse(is_known("not a url"))


if __name__ == "__main__":
    unittest.main()
