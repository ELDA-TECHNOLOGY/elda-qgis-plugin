from __future__ import annotations

import unittest

from elda_qgis.core.session.rights import Rights, explain, of
from elda_qgis.core.session.account import Account, Site


def acc(perms, sites=(Site(1, "A"),)):
    return Account(1, "u", list(sites), 1 if sites else None, frozenset(perms))


class RightsTest(unittest.TestCase):
    def test_of(self):
        self.assertEqual(of(acc({"gis_operational:manage"})), Rights(vector=True, raster=False))
        self.assertEqual(of(acc({"gis:raster:upload"})), Rights(vector=False, raster=True))
        self.assertEqual(of(acc({"*"})), Rights(True, True))
        self.assertEqual(of(acc({"gis_operational:view"})), Rights(False, False))

    def test_explain(self):
        self.assertIn("raster", explain(acc({"gis_operational:manage"})))
        self.assertNotIn("vecteur", explain(acc({"gis_operational:manage"})))
        self.assertIn("vecteur", explain(acc({"gis:raster:upload"})))
        self.assertIsNone(explain(acc({"*"})))
        self.assertIn("aucun site", explain(acc(set(), sites=[])))

    def test_no_permission_mentions_both(self):
        text = explain(acc(set()))
        self.assertIn("vecteur", text)
        self.assertIn("raster", text)


if __name__ == "__main__":
    unittest.main()
