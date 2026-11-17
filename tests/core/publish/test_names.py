from __future__ import annotations

import unittest

from elda_qgis.core.publish.names import layer_name, safe_filename


class SafeFilenameTest(unittest.TestCase):
    def test_every_non_ascii_alnum_char_becomes_underscore(self):
        self.assertEqual(safe_filename("Pistes été / 2026 ⛷"), "Pistes__t____2026__.gpkg")

    def test_keeps_dash_and_underscore(self):
        self.assertEqual(safe_filename("a-b_c9"), "a-b_c9.gpkg")

    def test_stem_truncated_to_80(self):
        self.assertEqual(len(safe_filename("x" * 300)), 80 + len(".gpkg"))
        self.assertEqual(safe_filename("x" * 300), "x" * 80 + ".gpkg")

    def test_fallback_when_no_letter_or_digit(self):
        for raw in ("///", "", "---", "___", "⛷⛷"):
            self.assertEqual(safe_filename(raw), "couche.gpkg")

    def test_result_is_ascii_safe(self):
        name = safe_filename("../../etc/passwd é\n")
        self.assertNotIn("/", name)
        self.assertNotIn("..", name[: -len(".gpkg")])


class LayerNameTest(unittest.TestCase):
    def test_trim_and_collapse(self):
        self.assertEqual(layer_name("  Pistes   rouges \n"), "Pistes rouges")

    def test_fallback(self):
        self.assertEqual(layer_name(""), "Couche QGIS")
        self.assertEqual(layer_name("  \n\t "), "Couche QGIS")

    def test_truncated_to_255(self):
        self.assertEqual(len(layer_name("x" * 300)), 255)

    def test_truncation_leaves_no_trailing_space(self):
        self.assertEqual(layer_name("x" * 254 + " y"), "x" * 254)
