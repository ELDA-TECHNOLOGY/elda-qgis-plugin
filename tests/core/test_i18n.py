"""Languages: every text the plugin shows has an English and a Spanish wording, and switching works."""
import ast
import re
from pathlib import Path

import pytest

from elda_qgis.core import errors, i18n
from elda_qgis.locales import en, es
from elda_qgis.ui import texts

ROOT = Path(__file__).resolve().parents[2] / "elda_qgis"
# reads as a sentence or carries a French character
_FRENCH = re.compile(r"[éèàêçùîôû«»…]|[A-Za-zé]{2,} [a-zé]{2,}")
# shown as they are in every language, or not shown at all
NOT_TEXTS = {
    "", "https://…", "#E5484D", "#2DA44E", "<qt>%s</qt>", "%d %s", ", ", "://", "error", "ok", "uploading",
    "failed", "timeout", "unpublished", "published", "\n\n", "\n",
    "a request carries json or body, never both", "Invalid path", "Unknown site", 'SELECT count(*) FROM "%s"', "[…]",
}


def _literals(path: Path):
    """(text, inside a function, wrapped in tr()) for every string literal that is not a docstring or a log line."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        chain, cursor = [], node
        while cursor in parent:
            cursor = parent[cursor]
            chain.append(cursor)
        if isinstance(chain[0], ast.Expr):
            continue  # docstring
        calls = [c.func for c in chain if isinstance(c, ast.Call)]
        if any(isinstance(f, ast.Attribute) and getattr(f.value, "id", "") == "log" for f in calls):
            continue
        if isinstance(chain[0], (ast.Compare, ast.Subscript)):
            continue  # a code compared or looked up, not a wording
        if isinstance(chain[0], ast.Dict) and any(key is node for key in chain[0].keys):
            continue  # the key of a table of texts
        wrapped = isinstance(chain[0], ast.Call) and getattr(chain[0].func, "id", "") == "tr"
        in_function = any(isinstance(c, (ast.FunctionDef, ast.Lambda)) for c in chain)
        yield node.value, in_function, wrapped


def _shown():
    """Every French text of the plugin, with whether it is translated where it is written."""
    for path in sorted(ROOT.rglob("*.py")):
        if "locales" in path.parts:
            continue
        everything = path.name == "texts.py" and path.parent.name == "ui"
        for text, in_function, wrapped in _literals(path):
            if text in NOT_TEXTS or not (wrapped or everything or _FRENCH.search(text)):
                continue
            if not everything and not wrapped and (text.startswith(("http", "^", "elda/")) or "%s:%d" in text):
                continue
            yield text, in_function, wrapped, path.relative_to(ROOT).as_posix()


SHOWN = sorted({text for text, _f, _w, _p in _shown()})


@pytest.fixture(autouse=True)
def back_to_french():
    yield
    i18n.use("fr")


def test_a_text_written_inside_a_function_goes_through_tr():
    # a constant is switched by use(); a literal in a function body is not, unless it is wrapped
    loose = [(path, text) for text, in_function, wrapped, path in _shown() if in_function and not wrapped]
    assert loose == []


@pytest.mark.parametrize("catalogue", [en.TEXTS, es.TEXTS], ids=["en", "es"])
def test_every_text_is_translated_and_nothing_else_is(catalogue):
    assert sorted(set(SHOWN) - set(catalogue)) == []
    assert sorted(set(catalogue) - set(SHOWN)) == []


@pytest.mark.parametrize("catalogue", [en.TEXTS, es.TEXTS], ids=["en", "es"])
def test_a_translation_keeps_the_placeholders_and_the_edges_of_its_source(catalogue):
    holes = re.compile(r"%[sd%]")
    for french, translated in catalogue.items():
        assert translated.strip(), french
        assert holes.findall(translated) == holes.findall(french), french
        # texts are glued together: a leading or trailing space or line break is part of the contract
        assert (french[:1].isspace(), french[-1:].isspace()) == (translated[:1].isspace(), translated[-1:].isspace()), french
        assert french.count("\n") == translated.count("\n"), french


def test_the_language_follows_qgis_and_falls_back_to_english():
    assert [i18n.language_for(x) for x in ("fr_FR", "fr", "es_ES", "es-MX", "en_US", "de_DE", "", None)] == [
        "fr", "fr", "es", "es", "en", "en", "en", "en",
    ]


def test_switching_translates_constants_built_texts_and_errors_then_french_comes_back():
    french = (texts.PUBLISH, texts.status_text("failed", None), texts.column_titles(), texts.site_label("X"))
    i18n.use("en")
    assert texts.PUBLISH == "Publish" and texts.status_text("failed", None) == "Failed"
    assert texts.column_titles()[1] == "Name in ELDA" and texts.site_label("X") == "Site: X"
    assert errors.AuthError().message_fr == en.TEXTS["Identifiants incorrects."]
    i18n.use("es")
    assert texts.PUBLISH == "Publicar" and texts.site_label("X") == "Sitio: X"
    i18n.use("fr")
    assert (texts.PUBLISH, texts.status_text("failed", None), texts.column_titles(), texts.site_label("X")) == french


def test_an_unknown_language_is_english_and_an_unknown_text_stays_as_it_is():
    i18n.use("de")
    assert texts.PUBLISH == "Publish" and i18n.tr("jamais traduit") == "jamais traduit"
