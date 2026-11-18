"""What the session remembers of published layers must never cross a server, an account or a site."""
from elda_qgis.core.publish.vector import REPLACE_GONE_FR, Outcome
from elda_qgis.ui import texts
from elda_qgis.ui.publish import state as ps

PREPROD = ("https://preprod.example", 7, 3)
PROD = ("https://prod.example", 7, 3)


def published(layer_id=120):
    return Outcome("pistes", "published", layer_id, None)


def test_a_layer_published_on_one_server_is_unknown_on_another():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", published(120))
    assert sent.known(PREPROD) == {"pistes": 120}
    assert sent.known(PROD) == {}


def test_another_account_or_another_site_starts_empty():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", published())
    assert sent.known(("https://preprod.example", 8, 3)) == {}
    assert sent.known(("https://preprod.example", 7, 4)) == {}


def test_clear_forgets_everything():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", published())
    sent.clear()
    assert sent.known(PREPROD) == {}


def test_a_layer_still_processed_by_elda_is_known_but_not_replaceable():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", Outcome("pistes", "timeout", 120, "long"))
    assert sent.known(PREPROD) == {"pistes": None}


def test_a_failed_publish_is_not_remembered():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", Outcome("pistes", "failed", None, "boom"))
    assert sent.known(PREPROD) == {}


def test_a_failed_replace_keeps_the_target_unless_the_layer_is_gone():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", published(120))
    sent.record(PREPROD, "pistes", Outcome("pistes", "failed", None, "Le remplacement n'a pas pu être confirmé."))
    assert sent.known(PREPROD) == {"pistes": 120}
    sent.record(PREPROD, "pistes", Outcome("pistes", "failed", None, REPLACE_GONE_FR))
    assert sent.known(PREPROD) == {}


def test_a_successful_replace_keeps_the_same_target():
    sent = ps.SentLayers()
    sent.record(PREPROD, "pistes", published(120))
    sent.record(PREPROD, "pistes", published(120))
    assert sent.known(PREPROD) == {"pistes": 120}


def test_unselectable_rows_are_never_replace_targets():
    from tests.ui.publish.test_state import rows

    r = rows(1)
    r[0] = r[0].__class__(**{**r[0].__dict__, "selectable": False})
    assert ps.duplicate_plan(r, None, None, {"id0": 41}).targets == {}


def test_question_says_what_is_lost_and_what_is_kept():
    text = texts.choose_duplicate(["Pistes"])
    for word in ("efface", "perdues", "nom", "dossier", "visibilité", "style", "annulé"):
        assert word in text, word
