"""Turn a LayerStyle into the style object stored on an ELDA layer.

The server stores this object without checking it and the web map reads it key by key:
every family and every key is written, and anything the map cannot draw falls back to a
plain value with a note, never to a guess.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .model import LayerStyle, Symbol

DASHES = ("solid", "dashed", "dotted", "dash-dot", "long-dash")
SHAPES = ("circle", "square", "triangle", "diamond", "star", "hexagon")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# what the web map draws when a key is missing; written explicitly so map and editor agree
DEFAULTS: Dict[str, Dict[str, Any]] = {
    "polygon": {"fillColor": "#4d80ff", "fillOpacity": 0.5, "outlineColor": "#000000", "outlineWidth": 1, "outlineStyle": "solid"},
    "line": {"color": "#888888", "width": 2, "opacity": 1, "style": "solid"},
    "point": {"color": "#ff4d4d", "radius": 6, "opacity": 1, "strokeColor": "#ffffff", "strokeWidth": 1, "shape": "circle", "icon": None},
    "label": {
        "enabled": False, "mode": "properties", "properties": [], "display": "inline", "separator": " – ", "template": "",
        "size": 12, "color": "#000000", "haloColor": "#ffffff", "haloWidth": 1.5, "placement": "point", "minZoom": 0, "maxZoom": 24,
    },
}
# the only keys the web map accepts as varying with an attribute
_VARYING = {
    "polygon": ("fillColor", "fillOpacity", "outlineColor", "outlineWidth"),
    "line": ("color", "width", "opacity"),
    "point": ("color", "radius", "opacity"),
}

NOTE_DEFAULT = "Ce type de style n'est pas converti : la couche prend le style par défaut d'ELDA."
NOTE_CATEGORIES = "Les catégories ne peuvent pas être reprises telles quelles (valeurs en double, décimales ou de types mélangés) : un seul symbole est utilisé."
NOTE_RANGES = "Les classes graduées ne peuvent pas être reprises (bornes en double ou illisibles) : un seul symbole est utilisé."
NOTE_CIRCLE = "Dans ELDA, des points dont la couleur ou la taille varie sont dessinés en cercle."
NOTE_SHAPE = "Cette forme de point n'existe pas dans ELDA : un cercle est utilisé."
NOTE_DASH = "Ce type de tirets n'existe pas dans ELDA : un trait plein est utilisé."
NOTE_COLOUR = "Une couleur n'a pas pu être lue : la couleur par défaut d'ELDA est utilisée."


def _number(value: Any, low: float, high: float) -> float:
    try:
        return round(min(high, max(low, float(value))), 2)
    except (TypeError, ValueError):
        return low


def _values(geometry: str, symbol: Symbol, notes: List[str]) -> Dict[str, Any]:
    """The keys of one family for one symbol."""

    def colour(text: str, fallback: str) -> str:
        if isinstance(text, str) and _HEX.match(text):
            return text.lower()
        _note(notes, NOTE_COLOUR)
        return fallback

    def dash() -> str:
        if symbol.dash in DASHES:
            return symbol.dash
        _note(notes, NOTE_DASH)
        return "solid"

    base = DEFAULTS[geometry]
    if geometry == "polygon":
        return {
            "fillColor": colour(symbol.color, base["fillColor"]),
            "fillOpacity": _number(symbol.opacity, 0, 1),
            "outlineColor": colour(symbol.outline_color, base["outlineColor"]),
            "outlineWidth": _number(symbol.width, 0, 50),
            "outlineStyle": dash(),
        }
    if geometry == "line":
        return {
            "color": colour(symbol.color, base["color"]),
            "width": _number(symbol.width, 0, 50),
            "opacity": _number(symbol.opacity, 0, 1),
            "style": dash(),
        }
    shape = symbol.shape
    if shape not in SHAPES:
        _note(notes, NOTE_SHAPE)
        shape = "circle"
    stroke = _number(symbol.width, 0, 50)
    radius = symbol.radius
    if shape != "circle":
        # the web map draws a shape from a 64 px image inset by (stroke + 3) px, scaled by radius / 6:
        # give it the radius that makes it as wide as the QGIS marker
        radius = 2 * _number(radius, 0, 100) * 6 / max(10.0, 64 - 2 * (stroke + 3))
    return {
        "color": colour(symbol.color, base["color"]),
        "radius": _number(radius, 0, 100),
        "opacity": _number(symbol.opacity, 0, 1),
        "strokeColor": colour(symbol.outline_color, base["strokeColor"]),
        "strokeWidth": stroke,
        "shape": shape,
        "icon": None,
    }


def _note(notes: List[str], text: str) -> None:
    if text not in notes:
        notes.append(text)


def _category_values(raw: List[Any]) -> Optional[List[Any]]:
    """Values the web map can match: unique, all text, all whole numbers, or all booleans written as text."""
    if not raw:
        return None
    if all(isinstance(v, bool) for v in raw):
        values: List[Any] = ["true" if v else "false" for v in raw]
    elif any(isinstance(v, bool) for v in raw):
        return None
    elif all(isinstance(v, str) for v in raw):
        values = list(raw)
    elif all(isinstance(v, (int, float)) and float(v).is_integer() for v in raw):
        values = [int(v) for v in raw]
    else:
        return None
    return values if len(set(values)) == len(values) else None


def _varying(geometry: str, per_class: List[Dict[str, Any]], default: Dict[str, Any],
             head: Dict[str, Any], entry: Callable[[int, Any], Dict[str, Any]]) -> Dict[str, Any]:
    """Family keys for a classified layer: a key becomes attribute-driven only when its values differ.

    `entry` builds one class; `default` holds the values of features that fall in no class.
    """
    family = dict(per_class[0])
    for key in _VARYING[geometry]:
        column = [values[key] for values in per_class]
        if all(v == column[0] for v in column) and default[key] == column[0]:
            continue
        family[key] = dict(head, classes=[entry(i, v) for i, v in enumerate(column)], default=default[key])
    if geometry == "point" and any(isinstance(family[k], dict) for k in ("color", "radius")):
        family["shape"] = "circle"
    return family


def _hidden(geometry: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """The same family values, made invisible: what QGIS does not draw must not appear on the web map."""
    out = dict(values)
    if geometry == "polygon":
        # the outline has no opacity key of its own
        out.update(fillOpacity=0, outlineWidth=0)
    else:
        out.update(opacity=0)
    return out


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _family(style: LayerStyle, notes: List[str]) -> Dict[str, Any]:
    geometry = style.geometry
    if style.mode == "single" and style.symbol is not None:
        return _values(geometry, style.symbol, notes)

    if style.mode == "categorized" and style.attribute and style.categories:
        classes = [c for c in style.categories if c.value is not None]
        others = next((c for c in style.categories if c.value is None), None)
        if not classes and others is not None:
            return _values(geometry, others.symbol, notes)
        values = _category_values([c.value for c in classes])
        if values is None:
            _note(notes, NOTE_CATEGORIES)
            return _values(geometry, style.categories[0].symbol, notes)
        per_class = [_values(geometry, c.symbol, notes) for c in classes]
        per_class = [_hidden(geometry, v) if c.hidden else v for c, v in zip(classes, per_class)]
        if others is not None and not others.hidden:
            default = _values(geometry, others.symbol, notes)
        else:
            # QGIS draws nothing for a value that has no category
            default = _hidden(geometry, per_class[0])
        head = {"mode": "categorical", "property": style.attribute}
        family = _varying(geometry, per_class, default, head,
                          lambda i, v: {"value": values[i], "label": classes[i].label or str(values[i]), "v": v})
        return _circle_note(style, family, notes)

    if style.mode == "graduated" and style.attribute and style.ranges:
        if not all(_finite(r.lower) and _finite(r.upper) for r in style.ranges):
            _note(notes, NOTE_RANGES)
            return _values(geometry, style.ranges[0].symbol, notes)
        ranges = sorted(style.ranges, key=lambda r: r.lower)
        if len({r.lower for r in ranges}) != len(ranges):
            _note(notes, NOTE_RANGES)
            return _values(geometry, ranges[0].symbol, notes)
        per_class = [_values(geometry, r.symbol, notes) for r in ranges]
        per_class = [_hidden(geometry, v) if r.hidden else v for r, v in zip(ranges, per_class)]
        # QGIS draws nothing for a value that is not a number
        default = _hidden(geometry, per_class[0])
        head = {"mode": "graduated", "property": style.attribute}
        family = _varying(geometry, per_class, default, head,
                          lambda i, v: {"min": ranges[i].lower, "max": ranges[i].upper, "v": v, "label": ranges[i].label})
        return _circle_note(style, family, notes)

    _note(notes, NOTE_DEFAULT)
    return dict(DEFAULTS[geometry])


def _circle_note(style: LayerStyle, family: Dict[str, Any], notes: List[str]) -> Dict[str, Any]:
    if style.geometry != "point" or not any(isinstance(family[k], dict) for k in ("color", "radius")):
        return family
    symbols = [c.symbol for c in style.categories] + [r.symbol for r in style.ranges]
    if any(s.shape != "circle" for s in symbols):
        _note(notes, NOTE_CIRCLE)
    return family


def _label(style: LayerStyle) -> Dict[str, Any]:
    label = dict(DEFAULTS["label"])
    labels = style.labels
    if labels is None or not labels.field:
        return label

    def colour(text: str, fallback: str) -> str:
        return text.lower() if isinstance(text, str) and _HEX.match(text) else fallback

    label.update(
        enabled=True,
        properties=[labels.field],
        size=_number(labels.size, 4, 72),
        color=colour(labels.color, label["color"]),
        haloColor=colour(labels.halo_color, label["haloColor"]),
        haloWidth=_number(labels.halo_width, 0, 20),
        placement="line" if labels.along_line and style.geometry != "point" else "point",
    )
    return label


def to_elda(style: LayerStyle) -> Tuple[Dict[str, Any], List[str]]:
    """The ELDA style object, and what could not be carried over (in French, for the user)."""
    notes = list(style.notes)
    result = {family: dict(DEFAULTS[family]) for family in ("point", "line", "polygon")}
    if style.geometry in result:
        result[style.geometry] = _family(style, notes)
    else:
        _note(notes, NOTE_DEFAULT)
    result["label"] = _label(style)
    return result, notes
