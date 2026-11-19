from __future__ import annotations

from typing import Callable

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorFileWriterTask,
    QgsVectorLayer,
)

from ..core.net.redact import without_paths
from . import log

LAYER_GONE_FR = "La couche n'existe plus dans le projet."
NOT_VECTOR_FR = "Seules les couches vectorielles peuvent être publiées."
EMPTY_LAYER_FR = "La couche ne contient aucune entité."
EXPORT_FAILED_FR = "L'export de la couche a échoué."
UNSAVED_FR = "Enregistrez les modifications de la couche avant de la publier."
NO_GEOMETRY_FR = "Une table sans géométrie ne peut pas remplacer le contenu d'une couche. Publiez-la comme nouvelle couche."

__all__ = ["export_layer", "cancel_all"]

# strong references so running tasks are not garbage-collected
_running = set()


def export_layer(
    layer_id: str,
    dest_path: str,
    on_done: Callable[[], None],
    on_error: Callable[[str], None],
    as_geojson: bool = False,
):
    """GUI thread only; callbacks also run on the GUI thread. Returns the task, or None when refused.

    GeoPackage for a new layer; GeoJSON in EPSG:4326 when the content of an existing layer is replaced.
    """
    layer = QgsProject.instance().mapLayer(layer_id)
    if layer is None or not layer.isValid():
        on_error(LAYER_GONE_FR)
        return None
    if not isinstance(layer, QgsVectorLayer):
        on_error(NOT_VECTOR_FR)
        return None
    if layer.isEditable() and layer.isModified():
        on_error(UNSAVED_FR)
        return None
    # an empty file has no geometry type either: QGIS reports it as a table, so the count alone decides
    if layer.featureCount() == 0:
        on_error(EMPTY_LAYER_FR)
        return None

    if as_geojson and not layer.isSpatial():
        # the server drops features without geometry: replacing would empty the layer
        on_error(NO_GEOMETRY_FR)
        return None

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.fileEncoding = "UTF-8"
    options.layerName = "layer"
    if as_geojson:
        options.driverName = "GeoJSON"
        # RFC 7946 refuses coordinates that are not degrees; full precision, like a normal import
        options.layerOptions = ["RFC7946=YES", "COORDINATE_PRECISION=15"]
        # a GeoPackage row id is not an attribute: a normal import does not carry it either
        row_ids = [i for i in layer.primaryKeyAttributes() if layer.fields().at(i).name().lower() == "fid"]
        if row_ids:
            options.attributes = [i for i in range(layer.fields().count()) if i not in row_ids]
        if layer.crs().isValid():
            target = QgsCoordinateReferenceSystem("EPSG:4326")
            options.ct = QgsCoordinateTransform(layer.crs(), target, QgsProject.instance().transformContext())
    else:
        options.driverName = "GPKG"

    task = QgsVectorFileWriterTask(layer, dest_path, options)
    finished = []

    def settle(callback, *args) -> None:
        if finished:
            return
        finished.append(True)
        _running.discard(task)
        callback(*args)

    def failed(*args) -> None:
        reason = without_paths(str(args[1])).strip() if len(args) > 1 else ""
        log.warning("layer export failed: code %s" % (args[0] if args else "?",))
        settle(on_error, "%s Détail : %s" % (EXPORT_FAILED_FR, reason) if reason else EXPORT_FAILED_FR)

    task.completed.connect(lambda *args: settle(on_done))
    task.errorOccurred.connect(failed)
    task.taskTerminated.connect(lambda: settle(on_error, EXPORT_FAILED_FR))
    _running.add(task)
    QgsApplication.taskManager().addTask(task)
    return task


def cancel_all() -> None:
    """GUI thread only; each cancelled export ends through its on_error callback."""
    for task in list(_running):
        try:
            task.cancel()
        except RuntimeError:
            _running.discard(task)  # already deleted by the task manager
