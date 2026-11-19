from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsVectorLayer

from ..core.publish.raster_checks import RasterInfo
from . import log


@dataclass(frozen=True)
class ProjectLayer:
    layer_id: str
    name: str
    kind: str  # "vector", "raster" or "other"
    feature_count: Optional[int]
    # where the data comes from, credentials removed; tells apart two layers with the same name
    source: str = ""
    # rasters only: what must be known of the file before sending it
    raster: Optional[RasterInfo] = None


def _kind(layer) -> str:
    if isinstance(layer, QgsVectorLayer):
        return "vector"
    if isinstance(layer, QgsRasterLayer):
        return "raster"
    return "other"


def _type_name(data_type) -> str:
    """GDAL name of a band data type, as the pre-upload checks expect it."""
    types = Qgis.DataType
    return {
        types.Byte: "Byte", types.Int8: "Int8", types.UInt16: "UInt16", types.Int16: "Int16",
        types.UInt32: "UInt32", types.Int32: "Int32", types.Float32: "Float32", types.Float64: "Float64",
    }.get(data_type, "Other")


def _raster_info(layer) -> Optional[RasterInfo]:
    try:
        provider = layer.dataProvider()
        path = None
        if provider is not None and provider.name() == "gdal":
            # a plain file path; sub-dataset and option suffixes come after "|"
            candidate = layer.source().split("|")[0]
            if os.path.isfile(candidate):
                path = candidate
        bands = layer.bandCount()
        # the type on disk, not the one QGIS shows after applying a scale factor
        types = tuple(_type_name(provider.sourceDataType(band)) for band in range(1, bands + 1)) if provider else ()
        size = os.path.getsize(path) if path else 0
        return RasterInfo(path, bands, types, layer.crs().isValid(), size)
    except Exception as exc:
        log.warning("raster not read: %s" % type(exc).__name__)
        return None


def list_project_layers() -> List[ProjectLayer]:
    """GUI thread only; layers in layer-tree order."""
    result = []
    for node in QgsProject.instance().layerTreeRoot().findLayers():
        layer = node.layer()
        if layer is None:
            continue
        kind = _kind(layer)
        count = None
        if kind == "vector" and layer.isValid():
            raw = layer.featureCount()
            count = raw if raw >= 0 else None
        raster = _raster_info(layer) if kind == "raster" and layer.isValid() else None
        result.append(ProjectLayer(layer.id(), layer.name(), kind, count, layer.publicSource(), raster))
    return result
