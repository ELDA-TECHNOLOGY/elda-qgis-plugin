"""Languages of the plugin. French is the source: a text is looked up by its French wording and stays
French when it has no translation, so a missing entry never breaks a window."""
from __future__ import annotations

import importlib
import sys
from typing import Dict, Tuple

LANGUAGES = ("fr", "en", "es")
_PACKAGE = __name__.split(".")[0]
_LOCALES = _PACKAGE + ".locales"

_texts: Dict[str, str] = {}
# the French value of every module constant seen, so that switching language twice starts from French again
_french: Dict[Tuple[str, str], object] = {}


def language_for(locale) -> str:
    """French and Spanish for their speakers, English for everyone else. `locale` looks like "es_ES" or "fr"."""
    code = str(locale or "").replace("-", "_").split("_")[0].lower()
    return code if code in ("fr", "es") else "en"


def tr(text: str) -> str:
    """The text in the active language. For wording built inside a function; constants are switched by `use`."""
    return _texts.get(text, text)


def use(language: str) -> None:
    """Switch the plugin to a language: `tr`, and the text constants of every module already imported.

    Call it once every module is loaded, before any window is built.
    """
    global _texts
    if language not in LANGUAGES:
        language = "en"
    _texts = {} if language == "fr" else dict(importlib.import_module("%s.%s" % (_LOCALES, language)).TEXTS)
    for name, module in list(sys.modules.items()):
        # neither the catalogues nor this module: their dictionaries are the translations themselves
        if module is None or not name.startswith(_PACKAGE + ".") or name.startswith(_LOCALES) or name == __name__:
            continue
        for attribute, value in list(vars(module).items()):
            if attribute.startswith("__") or not _holds_text(value):
                continue
            french = _french.setdefault((name, attribute), _copy(value))
            if isinstance(value, dict):
                # in place: other modules may hold the same dictionary
                for key, text in french.items():
                    value[key] = tr(text) if isinstance(text, str) else text
            elif isinstance(french, tuple):
                setattr(module, attribute, tuple(tr(text) if isinstance(text, str) else text for text in french))
            else:
                setattr(module, attribute, tr(french))


def _holds_text(value) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, dict):
        return any(isinstance(text, str) for text in value.values())
    return isinstance(value, tuple) and any(isinstance(text, str) for text in value)


def _copy(value):
    return dict(value) if isinstance(value, dict) else value
