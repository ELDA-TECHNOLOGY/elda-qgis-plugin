"""Cases found in review: what QGIS hides must stay hidden, and odd inputs must stay valid JSON."""
import json

import pytest

from elda_qgis.core.style.convert import to_elda
from elda_qgis.core.style.model import Category, LayerStyle, Range, Symbol


def dumps(style):
    return json.dumps(style, allow_nan=False)


def cat(value, color, **kw):
    return Category(value, str(value), Symbol(color), **kw)


def test_features_in_no_category_stay_hidden_when_qgis_has_no_symbol_for_them():
    style, _ = to_elda(LayerStyle("polygon", "categorized", attribute="t", categories=[cat("a", "#0000ff"), cat("b", "#ff0000")]))
    polygon = style["polygon"]
    assert polygon["fillOpacity"]["default"] == 0 and [c["v"] for c in polygon["fillOpacity"]["classes"]] == [1.0, 1.0]
    assert polygon["outlineWidth"]["default"] == 0
    dumps(style)


def test_an_unticked_category_is_kept_as_a_hidden_class():
    cats = [cat("a", "#0000ff"), cat("b", "#ff0000", hidden=True), cat(None, "#999999")]
    style, _ = to_elda(LayerStyle("line", "categorized", attribute="t", categories=cats))
    opacity = style["line"]["opacity"]
    assert [(c["value"], c["v"]) for c in opacity["classes"]] == [("a", 1.0), ("b", 0)]
    assert opacity["default"] == 1.0


def test_graduated_hides_values_that_are_not_numbers_and_unticked_ranges():
    ranges = [Range(0, 10, "a", Symbol("#00ff00")), Range(10, 20, "b", Symbol("#ff0000"), hidden=True)]
    style, _ = to_elda(LayerStyle("point", "graduated", attribute="n", ranges=ranges))
    opacity = style["point"]["opacity"]
    assert opacity["default"] == 0 and [c["v"] for c in opacity["classes"]] == [1.0, 0]
    assert [c["min"] for c in opacity["classes"]] == [0, 10]


def test_only_the_all_other_values_class_is_a_plain_symbol_without_a_note():
    style, notes = to_elda(LayerStyle("polygon", "categorized", attribute="t", categories=[cat(None, "#123456")]))
    assert style["polygon"]["fillColor"] == "#123456" and notes == []


@pytest.mark.parametrize("bound", [float("nan"), float("inf"), None, "dix"])
def test_range_bounds_that_are_not_finite_numbers_fall_back(bound):
    ranges = [Range(0, 10, "a", Symbol("#00ff00")), Range(bound, 20, "b", Symbol("#ff0000"))]
    style, notes = to_elda(LayerStyle("polygon", "graduated", attribute="n", ranges=ranges))
    assert isinstance(style["polygon"]["fillColor"], str) and notes
    dumps(style)


def test_a_square_is_sized_to_look_like_qgis_not_several_times_bigger():
    circle, _ = to_elda(LayerStyle("point", "single", symbol=Symbol("#000000", radius=4.0, width=1.0)))
    square, _ = to_elda(LayerStyle("point", "single", symbol=Symbol("#000000", radius=4.0, width=1.0, shape="square")))
    assert circle["point"]["radius"] == 4.0
    # the web map draws a shape 56/6 times its radius wide (64 px image, 4 px inset each side at stroke 1)
    assert square["point"]["radius"] == pytest.approx(8.0 * 6 / 56, abs=0.01)


def test_every_output_is_strict_json():
    cats = [cat(1, "#0000ff"), cat(2, "#ff0000")]
    for style in (
        LayerStyle("polygon", "other"),
        LayerStyle("point", "categorized", attribute='a"b{c}', categories=cats),
        LayerStyle("volume", "single", symbol=Symbol()),
    ):
        dumps(to_elda(style)[0])
