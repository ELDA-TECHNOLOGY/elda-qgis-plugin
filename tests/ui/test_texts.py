from __future__ import annotations

import unittest

from elda_qgis.ui import texts


class TextsTest(unittest.TestCase):
    def constants(self):
        return {n: v for n, v in vars(texts).items() if n.isupper() and not n.startswith("_")}

    def test_every_constant_is_a_non_empty_string(self):
        found = self.constants()
        self.assertGreater(len(found), 10)
        for name, value in found.items():
            self.assertIsInstance(value, str, name)
            self.assertTrue(value.strip(), name)
            self.assertNotIn("{password}", value, name)
            self.assertNotIn("{token}", value, name)

    def test_rights_line(self):
        self.assertEqual(texts.rights_line("vector", True), "Couches vecteur : autorisé")
        self.assertEqual(texts.rights_line("vector", False), "Couches vecteur : non autorisé")
        self.assertEqual(texts.rights_line("raster", True), "Rasters : autorisé")
        self.assertEqual(texts.rights_line("raster", False), "Rasters : non autorisé")

    def test_rights_line_unknown_kind(self):
        with self.assertRaises(KeyError):
            texts.rights_line("other", True)

    def test_connected_as(self):
        self.assertEqual(texts.connected_as("jean", "https://elda.example"), "Connecté : jean (elda.example)")

    def test_site_label(self):
        self.assertEqual(texts.site_label("Alpe"), "Site : Alpe")

    def test_login_and_status_busy_texts_differ(self):
        self.assertEqual(texts.BUSY, "Connexion en cours…")
        self.assertEqual(texts.WAIT, "Patientez…")

    def test_forget_message(self):
        self.assertEqual(texts.forget_message(True), (texts.ACCOUNT_FORGOTTEN, False))
        self.assertEqual(texts.forget_message(False), (texts.CREDENTIALS_NOT_FORGOTTEN, True))

    def test_server_label(self):
        self.assertEqual(texts.OTHER_SERVER, "Autre adresse…")
        self.assertIn("Continuer ?", texts.unknown_server("https://elda.example"))


class PublishTextsTest(unittest.TestCase):
    def test_summary_parts(self):
        self.assertEqual(texts.summary_published(0), "Aucune couche publiée")
        self.assertEqual(texts.summary_published(1), "1 couche publiée")
        self.assertEqual(texts.summary_published(2), "2 couches publiées")
        self.assertEqual(texts.summary_cancelled(2), "2 annulées")
        self.assertEqual(texts.summary_unpublished(1), "1 non publiée")

    def test_status_text(self):
        expected = {"": "", "waiting": "En attente", "preparing": "Préparation…", "uploading": "Envoi…",
                    "processing": "Traitement par ELDA…", "published": "Publiée", "failed": "Échec",
                    "cancelled": "Annulée", "timeout": "Traitement trop long", "unpublished": "Non publiée"}
        for code, text in expected.items():
            self.assertEqual(texts.status_text(code, None), text)
        self.assertEqual(texts.status_text("uploading", 42), "Envoi… 42 %")


def test_only_failures_and_successes_stand_out():
    assert [texts.status_tone(code) for code in ("failed", "timeout", "unpublished")] == ["error"] * 3
    assert texts.status_tone("published") == "ok"
    assert [texts.status_tone(code) for code in ("", "uploading", "processing", "cancelled")] == [None] * 4
    assert texts.tone_color("error") == texts.ERROR_COLOR and texts.tone_color(None) is None


def test_the_status_column_is_sized_for_every_text_it_can_show():
    samples = texts.status_samples()
    assert "Traitement par ELDA…" in samples and "Envoi… 100 %" in samples and "Échec" in samples
    assert all(texts.status_text(code, None) in samples for code in ("published", "failed", "timeout", "uploading"))
