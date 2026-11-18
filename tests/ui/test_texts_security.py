from elda_qgis.ui import texts


def test_unknown_server_question_names_the_host_that_gets_the_password():
    text = texts.unknown_server("https://elda.exemple.fr:8443")
    assert "elda.exemple.fr:8443" in text and "identifiants" in text


def test_connected_line_names_the_server():
    assert texts.connected_as("lea", "https://data.eldatechnology.fr") == "Connecté : lea (data.eldatechnology.fr)"


def test_tooltip_shows_markup_as_text_instead_of_rendering_it():
    assert texts.plain_tooltip("<img src=x> & co") == "<qt>&lt;img src=x&gt; &amp; co</qt>"
    assert texts.plain_tooltip("") == "" and texts.plain_tooltip(None) == ""
