"""Read the symbology of a project layer and describe it without QGIS types.

GUI thread only. Nothing here may stop a publication: whatever cannot be read becomes a note.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from qgis.core import NULL, Qgis, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt

from ..core.style.convert import to_elda
from ..core.style.model import Category, Labels, LayerStyle, Range, Symbol
from . import log

NOT_READ_FR = "Le style de la couche n'a pas pu être lu : elle a le style par défaut d'ELDA."
SEVERAL_LAYERS_FR = "Symbole à plusieurs couches : seule la première est reprise."
SYMBOL_KIND_FR = "Ce type de symbole (image, motif, effet) n'est pas converti : seule sa couleur est reprise."
UNITS_FR = "Une taille exprimée en unités de carte a été lue comme des millimètres."
EXPRESSION_FR = "Un style ou des étiquettes fondés sur une expression ne sont pas convertis."
LABELS_FR = "Les étiquettes par règles ne sont pas converties."
DASH_FR = "Un motif de tirets personnalisé est remplacé par des tirets simples."
HATCH_FR = "Un remplissage hachuré ou à motif devient un remplissage uni."
DATA_DEFINED_FR = "Les réglages définis par les données (taille ou couleur calculées) ne sont pas repris."

# CSS pixels per unit, at the 96 dpi the web map assumes
_PX_PER_MM = 96 / 25.4
_PX_PER_POINT = 96 / 72


def _px(value, unit, notes: List[str]) -> float:
    units = Qgis.RenderUnit
    if unit == units.Pixels:
        return float(value)
    if unit == units.Points:
        return float(value) * _PX_PER_POINT
    if unit == units.Inches:
        return float(value) * 96
    if unit != units.Millimeters and UNITS_FR not in notes:
        notes.append(UNITS_FR)
    return float(value) * _PX_PER_MM


def _dash(pen_style, custom: bool, notes: List[str]) -> str:
    if custom:
        if DASH_FR not in notes:
            notes.append(DASH_FR)
        return "dashed"
    pens = Qt.PenStyle
    return {pens.DashLine: "dashed", pens.DotLine: "dotted", pens.DashDotLine: "dash-dot", pens.DashDotDotLine: "dash-dot"}.get(
        pen_style, "solid"
    )


def _shape(marker_shape) -> str:
    shapes = Qgis.MarkerShape
    return {
        shapes.Circle: "circle", shapes.Square: "square", shapes.Triangle: "triangle",
        shapes.Diamond: "diamond", shapes.Star: "star", shapes.Hexagon: "hexagon",
    }.get(marker_shape, "other")


def _stroke(value, unit, pen_style, notes: List[str]) -> float:
    if pen_style == Qt.PenStyle.NoPen:
        return 0.0
    # a width of 0 is a hairline in QGIS (always one pixel), but invisible on the web map
    return _px(value, unit, notes) if value > 0 else 1.0


def _symbol(symbol, geometry: str, layer_opacity: float, notes: List[str]) -> Symbol:
    """The first symbol layer of a QGIS symbol, as a neutral Symbol."""
    if symbol is None or symbol.symbolLayerCount() == 0:
        return Symbol()
    if symbol.symbolLayerCount() > 1 and SEVERAL_LAYERS_FR not in notes:
        notes.append(SEVERAL_LAYERS_FR)
    part = symbol.symbolLayer(0)
    kind = part.layerType()
    colour = part.color()
    opacity = layer_opacity * symbol.opacity() * colour.alphaF()
    if part.dataDefinedProperties().hasActiveProperties() and DATA_DEFINED_FR not in notes:
        notes.append(DATA_DEFINED_FR)
    if kind == "SimpleMarker":
        return Symbol(
            color=colour.name(),
            opacity=opacity,
            width=_stroke(part.strokeWidth(), part.strokeWidthUnit(), part.strokeStyle(), notes),
            radius=_px(part.size(), part.sizeUnit(), notes) / 2,
            outline_color=part.strokeColor().name(),
            shape=_shape(part.shape()),
        )
    if kind == "SimpleLine":
        width = _stroke(part.width(), part.widthUnit(), part.penStyle(), notes)
        dash = _dash(part.penStyle(), part.useCustomDashPattern(), notes)
        if geometry == "polygon":
            # an outline-only polygon: no fill, the line is the outline
            return Symbol(opacity=0.0, width=width, outline_color=colour.name(), dash=dash)
        return Symbol(color=colour.name(), opacity=opacity, width=width, dash=dash)
    if kind == "SimpleFill":
        brush = part.brushStyle()
        if brush not in (Qt.BrushStyle.SolidPattern, Qt.BrushStyle.NoBrush) and HATCH_FR not in notes:
            notes.append(HATCH_FR)
        return Symbol(
            color=colour.name(),
            opacity=0.0 if brush == Qt.BrushStyle.NoBrush else opacity,
            width=_stroke(part.strokeWidth(), part.strokeWidthUnit(), part.strokeStyle(), notes),
            outline_color=part.strokeColor().name(),
            dash=_dash(part.strokeStyle(), False, notes),
        )
    if SYMBOL_KIND_FR not in notes:
        notes.append(SYMBOL_KIND_FR)
    return Symbol(color=symbol.color().name(), opacity=layer_opacity * symbol.opacity())


def _typed(value, field):
    """A category value in the type of its field: the web map compares values strictly by type."""
    if isinstance(value, bool):
        return value
    if field.isNumeric() and isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        return int(number) if number.is_integer() else number
    if not field.isNumeric() and not isinstance(value, str):
        return str(value)
    return value


def _is_else(value) -> bool:
    # QGIS keeps "all other values" as a null or empty category value
    return value is None or value == NULL or value == ""


def _geometry(layer) -> Optional[str]:
    kinds = Qgis.GeometryType
    return {kinds.Point: "point", kinds.Line: "line", kinds.Polygon: "polygon"}.get(layer.geometryType())


def _labels(layer, notes: List[str]) -> Optional[Labels]:
    if not layer.labelsEnabled() or layer.labeling() is None:
        return None
    labeling = layer.labeling()
    if labeling.type() != "simple":
        notes.append(LABELS_FR)
        return None
    settings = labeling.settings()
    if settings.isExpression or layer.fields().lookupField(settings.fieldName) < 0:
        notes.append(EXPRESSION_FR)
        return None
    text = settings.format()
    halo = text.buffer()
    placements = Qgis.LabelPlacement
    return Labels(
        field=settings.fieldName,
        size=_px(text.size(), text.sizeUnit(), notes),
        color=text.color().name(),
        halo_color=halo.color().name(),
        halo_width=_px(halo.size(), halo.sizeUnit(), notes) if halo.enabled() else 0.0,
        along_line=settings.placement in (placements.Line, placements.Curved, placements.PerimeterCurved),
    )


def _describe(layer) -> Optional[LayerStyle]:
    geometry = _geometry(layer)
    renderer = layer.renderer()
    if geometry is None or renderer is None:
        return None
    notes: List[str] = []
    kind = renderer.type()
    opacity = layer.opacity()
    style = LayerStyle(geometry, "other")
    if kind == "singleSymbol":
        style = LayerStyle(geometry, "single", symbol=_symbol(renderer.symbol(), geometry, opacity, notes))
    elif kind in ("categorizedSymbol", "graduatedSymbol"):
        attribute = renderer.classAttribute()
        index = layer.fields().lookupField(attribute)
        if index < 0:
            notes.append(EXPRESSION_FR)
        elif kind == "categorizedSymbol":
            field = layer.fields().at(index)
            categories = []
            for category in renderer.categories():
                symbol = _symbol(category.symbol(), geometry, opacity, notes)
                value = category.value()
                # merged categories hold a list of values sharing one symbol
                values = value if isinstance(value, (list, tuple)) else [value]
                for one in values:
                    typed = None if _is_else(one) else _typed(one, field)
                    categories.append(Category(typed, category.label(), symbol, not category.renderState()))
            style = LayerStyle(geometry, "categorized", attribute=attribute, categories=categories)
        else:
            ranges = [
                Range(r.lowerValue(), r.upperValue(), r.label(), _symbol(r.symbol(), geometry, opacity, notes), not r.renderState())
                for r in renderer.ranges()
            ]
            style = LayerStyle(geometry, "graduated", attribute=attribute, ranges=ranges)
    labels = _labels(layer, notes)
    return LayerStyle(style.geometry, style.mode, style.symbol, style.attribute, style.categories, style.ranges, labels, notes)


def read(layer_id: str) -> Tuple[Optional[dict], List[str]]:
    """ELDA style object of a project layer and the notes for the user; (None, notes) when it cannot be read."""
    try:
        layer = QgsProject.instance().mapLayer(layer_id)
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid() or not layer.isSpatial():
            return None, []
        described = _describe(layer)
        if described is None:
            return None, [NOT_READ_FR]
        return to_elda(described)
    except Exception as exc:
        log.warning("style not read: %s" % type(exc).__name__)
        return None, [NOT_READ_FR]
