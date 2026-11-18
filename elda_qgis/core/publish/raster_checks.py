"""What can be known of a raster before sending it, so a file ELDA would reject is refused at once.

The processing service compresses colour images as JPEG (8-bit only) and every other type with a
predictor that only exists for floating-point data: anything else fails after the whole upload.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple

TYPES = ("dtm", "dsm", "ortho_rgb", "ortho_ir", "custom")
TYPE_LABELS = {
    "dtm": "Modèle de terrain (MNT)",
    "dsm": "Modèle de surface (MNS)",
    "ortho_rgb": "Orthophoto couleur",
    "ortho_ir": "Orthophoto infrarouge",
    "custom": "Autre raster",
}
MAX_FILE_BYTES = 50 * 1024 * 1024 * 1024
_FLOATS = ("Float32", "Float64")

NOT_A_FILE = "Seul un fichier GeoTIFF (.tif ou .tiff) enregistré sur ce poste peut être publié."
EMPTY = "Le fichier du raster est vide ou introuvable."
TOO_BIG = "Raster trop volumineux : 50 Go maximum."
NO_CRS = "Ce raster n'a pas de système de coordonnées : définissez-le dans QGIS et enregistrez le fichier avant de le publier."
NOT_8_BIT = (
    "Une orthophoto couleur doit être en 8 bits par bande. Convertissez ce raster en 8 bits "
    "(Raster > Conversion > Convertir, type de sortie Byte), ou choisissez un autre type."
)
NOT_FLOAT = (
    "Pour ce type, ELDA n'accepte que des valeurs à virgule. Convertissez ce raster "
    "(Raster > Conversion > Convertir, type de sortie Float32), puis publiez le fichier converti."
)
UNKNOWN_TYPE = "Choisissez le type du raster."


@dataclass(frozen=True)
class RasterInfo:
    path: Optional[str]  # the file behind the layer, when it is a plain local file
    bands: int
    data_types: Tuple[str, ...]  # GDAL names, one per band: Byte, UInt16, Float32...
    has_crs: bool
    size: int  # bytes on disk


def suggested_type(info: RasterInfo) -> Optional[str]:
    """The type that needs no question: an 8-bit image with 3 or 4 bands is a colour orthophoto."""
    if info.bands in (3, 4) and all(t == "Byte" for t in info.data_types):
        return "ortho_rgb"
    return None


def problem(info: RasterInfo, raster_type: str) -> Optional[str]:
    """Why ELDA would refuse this raster, in French; None when it can be sent."""
    if raster_type not in TYPES:
        return UNKNOWN_TYPE
    path = info.path or ""
    if not os.path.isabs(path) or os.path.splitext(path)[1].lower() not in (".tif", ".tiff") or "?" in path or path.startswith("/vsi"):
        return NOT_A_FILE
    if info.size <= 0:
        return EMPTY
    if info.size > MAX_FILE_BYTES:
        return TOO_BIG
    if not info.has_crs:
        return NO_CRS
    if raster_type == "ortho_rgb":
        return None if all(t == "Byte" for t in info.data_types) else NOT_8_BIT
    return None if all(t in _FLOATS for t in info.data_types) else NOT_FLOAT
