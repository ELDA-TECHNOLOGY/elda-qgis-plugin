from elda_qgis.ui import texts


def test_restricting_to_nobody_says_only_you():
    assert texts.restrict_label(True, 0) == "Restreindre à… (vous seulement)"


def test_plain_label_once_someone_is_chosen_or_whole_site():
    assert texts.restrict_label(True, 2) == "Restreindre à…"
    assert texts.restrict_label(False, 0) == "Restreindre à…"
