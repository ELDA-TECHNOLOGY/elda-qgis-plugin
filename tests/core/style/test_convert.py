"""QGIS symbology, described neutrally, turned into the style object the ELDA web map reads."""
import pytest

from elda_qgis.core.style.convert import to_elda
from elda_qgis.core.style.model import Category, Labels, LayerStyle, Range, Symbol

FAMILIES = {"point", "line", "polygon", "label"}


def fill(color="#00aa00", **kw):
    return Symbol(color=color, **kw)


def single(symbol, geometry="polygon", **kw):
    return LayerStyle(geometry=geometry, mode="single", symbol=symbol, **kw)


def test_every_family_and_every_key_is_always_written():
    style, notes = to_elda(single(fill()))
    assert set(style) == FAMILIES and notes == []
    assert set(style["polygon"]) == {"fillColor", "fillOpacity", "outlineColor", "outlineWidth", "outlineStyle"}
    assert set(style["line"]) == {"color", "width", "opacity", "style"}
    assert set(style["point"]) == {"color", "radius", "opacity", "strokeColor", "strokeWidth", "shape", "icon"}
    assert style["label"]["enabled"] is False


def test_single_polygon():
    symbol = fill("#112233", opacity=0.4, outline_color="#445566", width=2.0, dash="dashed")
    style, _ = to_elda(single(symbol))
    assert style["polygon"] == {
        "fillColor": "#112233", "fillOpacity": 0.4, "outlineColor": "#445566", "outlineWidth": 2.0, "outlineStyle": "dashed",
    }


def test_single_line_and_point():
    line, _ = to_elda(single(Symbol(color="#ff0000", opacity=0.5, width=3.0, dash="dotted"), "line"))
    assert line["line"] == {"color": "#ff0000", "width": 3.0, "opacity": 0.5, "style": "dotted"}
    point, _ = to_elda(single(Symbol(color="#0000ff", radius=4.0, shape="square", outline_color="#000000", width=0.5), "point"))
    # a square is rescaled so that it is as wide on the web map as in QGIS
    assert point["point"]["color"] == "#0000ff" and point["point"]["radius"] == pytest.approx(48 / 57, abs=0.01)
    assert point["point"]["shape"] == "square" and point["point"]["strokeColor"] == "#000000"
    assert point["point"]["strokeWidth"] == 0.5 and point["point"]["icon"] is None


def test_unknown_dash_and_shape_fall_back_with_a_note():
    style, notes = to_elda(single(Symbol(color="#000000", shape="cross", dash="zigzag"), "point"))
    assert style["point"]["shape"] == "circle"
    assert any("forme" in n for n in notes)


def test_colours_must_be_plain_hex():
    style, notes = to_elda(single(fill("rgba(1,2,3,0.5)")))
    assert style["polygon"]["fillColor"] == "#4d80ff" and notes


def test_categorized_by_text_only_varies_what_differs():
    cats = [
        Category("bleue", "Bleue", fill("#0000ff")),
        Category("rouge", "Rouge", fill("#ff0000")),
        Category(None, "Autres", fill("#999999")),
    ]
    style, notes = to_elda(LayerStyle("polygon", "categorized", attribute="couleur", categories=cats))
    assert style["polygon"]["fillColor"] == {
        "mode": "categorical",
        "property": "couleur",
        "classes": [{"value": "bleue", "label": "Bleue", "v": "#0000ff"}, {"value": "rouge", "label": "Rouge", "v": "#ff0000"}],
        "default": "#999999",
    }
    assert style["polygon"]["fillOpacity"] == 1.0 and notes == []


def test_categorized_numbers_stay_numbers_and_integral_floats_become_integers():
    cats = [Category(1, "Un", fill("#0000ff")), Category(2.0, "Deux", fill("#ff0000"))]
    style, _ = to_elda(LayerStyle("polygon", "categorized", attribute="n", categories=cats))
    assert [c["value"] for c in style["polygon"]["fillColor"]["classes"]] == [1, 2]


@pytest.mark.parametrize(
    "values",
    [[1, "deux"], [1.5, 2.5], ["a", "a"], [True, "x"]],
)
def test_categories_the_web_map_cannot_match_fall_back_to_one_symbol_with_a_note(values):
    cats = [Category(v, str(v), fill("#0000ff" if i == 0 else "#ff0000")) for i, v in enumerate(values)]
    style, notes = to_elda(LayerStyle("polygon", "categorized", attribute="x", categories=cats))
    assert style["polygon"]["fillColor"] == "#0000ff"
    assert any("catégor" in n for n in notes)


def test_boolean_categories_are_written_as_text():
    cats = [Category(True, "Oui", fill("#00ff00")), Category(False, "Non", fill("#ff0000"))]
    style, _ = to_elda(LayerStyle("polygon", "categorized", attribute="ouvert", categories=cats))
    assert [c["value"] for c in style["polygon"]["fillColor"]["classes"]] == ["true", "false"]


def test_graduated_is_sorted_and_keeps_both_bounds():
    ranges = [Range(10, 20, "10-20", fill("#ff0000")), Range(0, 10, "0-10", fill("#00ff00"))]
    style, notes = to_elda(LayerStyle("polygon", "graduated", attribute="pente", ranges=ranges))
    assert style["polygon"]["fillColor"] == {
        "mode": "graduated",
        "property": "pente",
        "classes": [{"min": 0, "max": 10, "v": "#00ff00", "label": "0-10"}, {"min": 10, "max": 20, "v": "#ff0000", "label": "10-20"}],
        "default": "#00ff00",
    }
    assert notes == []


def test_graduated_with_twice_the_same_lower_bound_falls_back():
    ranges = [Range(0, 10, "a", fill("#00ff00")), Range(0, 20, "b", fill("#ff0000"))]
    style, notes = to_elda(LayerStyle("polygon", "graduated", attribute="pente", ranges=ranges))
    assert style["polygon"]["fillColor"] == "#00ff00" and notes


def test_points_that_vary_are_drawn_as_circles_and_say_so():
    cats = [Category("a", "A", Symbol("#0000ff", shape="square")), Category("b", "B", Symbol("#ff0000", shape="square"))]
    style, notes = to_elda(LayerStyle("point", "categorized", attribute="t", categories=cats))
    assert style["point"]["shape"] == "circle" and isinstance(style["point"]["color"], dict)
    assert any("cercle" in n for n in notes)


def test_line_width_can_vary_too():
    cats = [Category("a", "A", Symbol("#000000", width=1.0)), Category("b", "B", Symbol("#000000", width=4.0))]
    style, _ = to_elda(LayerStyle("line", "categorized", attribute="t", categories=cats))
    assert style["line"]["color"] == "#000000"
    assert [c["v"] for c in style["line"]["width"]["classes"]] == [1.0, 4.0]


def test_unsupported_renderer_keeps_elda_defaults_and_explains():
    style, notes = to_elda(LayerStyle("polygon", "other"))
    assert style["polygon"]["fillColor"] == "#4d80ff"
    assert any("par défaut" in n for n in notes)


def test_labels_on_one_field():
    labels = Labels(field="nom", size=14.0, color="#111111", halo_color="#ffffff", halo_width=2.0, along_line=True)
    style, _ = to_elda(single(Symbol("#000000"), "line", labels=labels))
    assert style["label"]["enabled"] is True and style["label"]["properties"] == ["nom"]
    assert style["label"]["mode"] == "properties" and style["label"]["placement"] == "line"
    assert (style["label"]["size"], style["label"]["color"], style["label"]["haloWidth"]) == (14.0, "#111111", 2.0)


def test_labels_along_a_line_make_no_sense_on_points():
    style, _ = to_elda(single(Symbol("#000000"), "point", labels=Labels(field="nom", along_line=True)))
    assert style["label"]["placement"] == "point"


def test_notes_from_the_reader_are_kept_first():
    _, notes = to_elda(single(fill(), notes=["Symbole à plusieurs couches : seule la première est reprise."]))
    assert notes[0].startswith("Symbole à plusieurs couches")


def test_numbers_are_bounded_and_rounded():
    style, _ = to_elda(single(fill(opacity=1.7, width=-3.0)))
    assert style["polygon"]["fillOpacity"] == 1.0 and style["polygon"]["outlineWidth"] == 0.0
    style, _ = to_elda(single(Symbol("#000000", radius=3.14159), "point"))
    assert style["point"]["radius"] == 3.14
