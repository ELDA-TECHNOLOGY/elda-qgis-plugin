from __future__ import annotations

import unittest

from elda_qgis.core.errors import UnsafeUrl
from elda_qgis.core.publish.gis import SiteRef
from elda_qgis.core.session.account import Account, Site
from elda_qgis.ui.session import state
from elda_qgis.ui import texts

MANAGE, RASTER = "gis_operational:manage", "gis:raster:upload"
A, B = Site(1, "Alpe"), Site(2, "Brèche")


def acc(perms=(), sites=(A,), active=1, name="jean"):
    return Account(7, name, list(sites), active, frozenset(perms))


class ViewOfTest(unittest.TestCase):
    def test_logged_out(self):
        v = state.view_of(None)
        self.assertFalse(v.logged_in)
        self.assertEqual(v.sites, [])
        self.assertFalse(v.site_combo_visible)
        self.assertIsNone(v.selected_site_id)
        self.assertIsNone(v.explanation)

    def test_one_site_shows_its_name_as_label(self):
        self.assertEqual(state.view_of(acc({MANAGE})).site_label, "Site : Alpe")

    def test_several_sites_have_no_label(self):
        self.assertIsNone(state.view_of(acc({MANAGE}, sites=(A, B), active=2)).site_label)

    def test_no_site_or_logged_out_has_no_label(self):
        self.assertIsNone(state.view_of(acc({MANAGE}, sites=(), active=None)).site_label)
        self.assertIsNone(state.view_of(None).site_label)

    def test_one_site_hides_combo(self):
        v = state.view_of(acc({MANAGE, RASTER}))
        self.assertTrue(v.logged_in)
        self.assertEqual(v.username, "jean")
        self.assertFalse(v.site_combo_visible)
        self.assertEqual(v.selected_site_id, 1)

    def test_several_sites_show_combo(self):
        v = state.view_of(acc({MANAGE}, sites=(A, B), active=2))
        self.assertTrue(v.site_combo_visible)
        self.assertEqual(v.sites, [A, B])
        self.assertEqual(v.selected_site_id, 2)

    def test_no_site(self):
        v = state.view_of(acc({MANAGE}, sites=(), active=None))
        self.assertFalse(v.site_combo_visible)
        self.assertIsNone(v.selected_site_id)
        self.assertIn("aucun site", v.explanation)

    def test_active_site_outside_account_falls_back_to_first(self):
        self.assertEqual(state.view_of(acc(sites=(A, B), active=9)).selected_site_id, 1)

    def test_both_rights(self):
        v = state.view_of(acc({MANAGE, RASTER}))
        self.assertEqual(v.vector_line, "Couches vecteur : autorisé")
        self.assertEqual(v.raster_line, "Rasters : autorisé")
        self.assertIsNone(v.explanation)

    def test_one_right(self):
        v = state.view_of(acc({MANAGE}))
        self.assertEqual(v.vector_line, "Couches vecteur : autorisé")
        self.assertEqual(v.raster_line, "Rasters : non autorisé")
        self.assertIn("raster", v.explanation)

    def test_no_right(self):
        v = state.view_of(acc())
        self.assertEqual(v.vector_line, "Couches vecteur : non autorisé")
        self.assertEqual(v.raster_line, "Rasters : non autorisé")
        self.assertIn("vecteur ni raster", v.explanation)


class SiteToSelectTest(unittest.TestCase):
    def test_restorable_last_site_wins(self):
        self.assertEqual(state.site_to_select(acc(sites=(A, B), active=1), 2), 2)

    def test_last_site_already_active(self):
        self.assertIsNone(state.site_to_select(acc(sites=(A, B), active=2), 2))

    def test_last_site_gone(self):
        self.assertIsNone(state.site_to_select(acc(sites=(A, B), active=1), 9))

    def test_no_last_site_and_active_set(self):
        self.assertIsNone(state.site_to_select(acc(sites=(A, B)), None))

    def test_active_none_selects_first(self):
        self.assertEqual(state.site_to_select(acc(sites=(A, B), active=None), None), 1)
        self.assertEqual(state.site_to_select(acc(sites=(A, B), active=None), 9), 1)

    def test_active_none_with_restorable_last_site(self):
        self.assertEqual(state.site_to_select(acc(sites=(A, B), active=None), 2), 2)

    def test_no_site(self):
        self.assertIsNone(state.site_to_select(acc(sites=(), active=None), 1))


class ShouldReloadSavedTest(unittest.TestCase):
    def test_first_time(self):
        self.assertTrue(state.should_reload_saved(None, "https://a.example"))

    def test_same_server_keeps_typed_password(self):
        self.assertFalse(state.should_reload_saved("https://a.example", "https://a.example"))

    def test_other_server(self):
        self.assertTrue(state.should_reload_saved("https://a.example", "https://b.example"))

    def test_server_becomes_unusable(self):
        self.assertTrue(state.should_reload_saved("https://a.example", None))

    def test_still_unusable(self):
        self.assertFalse(state.should_reload_saved(None, None))


class PasswordBelongsToTest(unittest.TestCase):
    def test_same_server(self):
        self.assertTrue(state.password_belongs_to("https://a.example", "https://a.example"))

    def test_other_server(self):
        self.assertFalse(state.password_belongs_to("https://a.example", "https://b.example"))

    def test_nothing_was_filled_for_any_server(self):
        self.assertFalse(state.password_belongs_to(None, "https://b.example"))


class ServerChoiceTest(unittest.TestCase):
    def test_known_needs_no_confirmation(self):
        c = state.server_choice("https://data.eldatechnology.fr/")
        self.assertEqual(c.url, "https://data.eldatechnology.fr")
        self.assertFalse(c.needs_confirmation)

    def test_unknown_needs_confirmation(self):
        c = state.server_choice(" https://example.com ")
        self.assertEqual(c.url, "https://example.com")
        self.assertTrue(c.needs_confirmation)

    def test_unsafe_url_raises_with_french_message(self):
        with self.assertRaises(UnsafeUrl) as ctx:
            state.server_choice("http://example.com")
        self.assertEqual(ctx.exception.message_fr, UnsafeUrl.default_fr)

    def test_server_options_are_known_ones_then_other(self):
        urls = [u for _, u in state.server_options()]
        self.assertEqual(urls, ["https://data.eldatechnology.fr", None])
        self.assertEqual([l for l, _ in state.server_options()][-1], texts.OTHER_SERVER)

    def test_initial_server_index(self):
        self.assertEqual(state.initial_server("https://data.eldatechnology.fr"), (0, ""))
        self.assertEqual(state.initial_server("https://example.com"), (1, "https://example.com"))
        self.assertEqual(state.initial_server(""), (0, ""))



class SitesForTest(unittest.TestCase):
    def test_super_admin_sees_all_sorted(self):
        everything = [SiteRef(3, "zeta"), SiteRef(1, "Alpe"), SiteRef(2, "brèche")]
        got = state.sites_for(acc({"*"}, sites=(A,), active=1), everything)
        self.assertEqual(got, [Site(1, "Alpe"), Site(2, "brèche"), Site(3, "zeta")])

    def test_active_site_stays_present(self):
        got = state.sites_for(acc({"*"}, sites=(A,), active=1), [SiteRef(2, "Brèche")])
        self.assertEqual(got, [Site(1, "Alpe"), Site(2, "Brèche")])

    def test_not_super_admin_keeps_own_sites(self):
        self.assertEqual(state.sites_for(acc({MANAGE}, sites=(A, B)), [SiteRef(9, "X")]), [A, B])

    def test_not_loaded_keeps_own_sites(self):
        for empty in (None, []):
            self.assertEqual(state.sites_for(acc({"*"}, sites=(A,)), empty), [A])


if __name__ == "__main__":
    unittest.main()


class ViewOfAllSitesTest(unittest.TestCase):
    def test_super_admin_lists_every_loaded_site(self):
        v = state.view_of(acc({"*"}, sites=(A,), active=1), [SiteRef(2, "Brèche"), SiteRef(1, "Alpe")])
        self.assertTrue(v.site_combo_visible)
        self.assertEqual(v.sites, [A, B])
        self.assertIsNone(v.site_label)

    def test_not_loaded_falls_back_to_own_sites(self):
        v = state.view_of(acc({"*"}, sites=(A,), active=1), None)
        self.assertFalse(v.site_combo_visible)
        self.assertEqual(v.site_label, "Site : Alpe")
