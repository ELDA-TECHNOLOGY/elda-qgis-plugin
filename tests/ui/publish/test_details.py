from elda_qgis.ui.publish import state as ps
from tests.ui.publish.test_state import rows, with_status


def test_summary_lists_each_problem_with_its_layer_and_reason():
    r = rows(3)
    r[0] = with_status(r[0], ps.ST_PUBLISHED)
    r[1] = with_status(r[1], ps.ST_FAILED, message="Fichier trop volumineux : 2 Go maximum.")
    r[2] = with_status(r[2], ps.ST_TIMEOUT, message="Le traitement prend trop de temps.")
    text = ps.summary(r)
    assert text.splitlines()[0] == "1 couche publiée, 1 en échec, 1 traitement trop long."
    assert "Couche 1 : Fichier trop volumineux : 2 Go maximum." in text.splitlines()
    assert "Couche 2 : Le traitement prend trop de temps." in text.splitlines()


def test_summary_stays_on_one_line_when_all_went_well():
    r = [with_status(x, ps.ST_PUBLISHED) for x in rows(2)]
    assert ps.summary(r) == "2 couches publiées."


def test_summary_ignores_messages_of_rows_outside_the_batch():
    r = rows(2)
    r[0] = with_status(r[0], ps.ST_PUBLISHED)
    r[1] = with_status(r[1], ps.ST_IDLE, message="vieux message")
    assert ps.summary(r) == "1 couche publiée."
