from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer


@dataclass(frozen=True)
class ProjectLayer:
    layer_id: str
    name: str
    kind: str  # "vector", "raster" or "other"
    feature_count: Optional[int]
    # where the data comes from, credentials removed; tells apart two layers with the same name
    source: str = ""


def _kind(layer) -> str:
    if isinstance(layer, QgsVectorLayer):
        return "vector"
    if isinstance(layer, QgsRasterLayer):
        return "raster"
    return "other"


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
        result.append(ProjectLayer(layer.id(), layer.name(), kind, count, layer.publicSource()))
    return result
