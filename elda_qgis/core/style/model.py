"""A QGIS symbology described without QGIS: what the reader hands to the converter.

Sizes are screen pixels, colours are "#rrggbb", opacities go from 0 to 1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class Symbol:
    color: str = "#000000"  # fill of a polygon or a point, stroke of a line
    opacity: float = 1.0
    width: float = 1.0  # line width, polygon outline width or point stroke width
    radius: float = 6.0  # points only
    outline_color: str = "#000000"  # polygons and points
    dash: str = "solid"
    shape: str = "circle"  # points only


@dataclass(frozen=True)
class Category:
    value: Any  # None is QGIS's "all other values" class
    label: str
    symbol: Symbol
    hidden: bool = False  # unticked in QGIS: its features are not drawn


@dataclass(frozen=True)
class Range:
    lower: float
    upper: float
    label: str
    symbol: Symbol
    hidden: bool = False  # unticked in QGIS: its features are not drawn


@dataclass(frozen=True)
class Labels:
    field: str
    size: float = 12.0
    color: str = "#000000"
    halo_color: str = "#ffffff"
    halo_width: float = 1.5
    along_line: bool = False


@dataclass(frozen=True)
class LayerStyle:
    geometry: str  # point | line | polygon
    mode: str  # single | categorized | graduated | other
    symbol: Optional[Symbol] = None  # single mode
    attribute: Optional[str] = None  # categorized and graduated modes
    categories: Sequence[Category] = ()
    ranges: Sequence[Range] = ()
    labels: Optional[Labels] = None
    notes: Sequence[str] = ()  # what the reader could not carry over, in French
