"""Read a GeoTIFF file itself, with GDAL, just before it is sent.

ELDA's processing only sees the file: a coordinate system set on the QGIS layer, kept in a
sidecar file, or a data type changed by a scale factor are not what it gets.
"""
from __future__ import annotations

import os
from typing import Optional

from osgeo import gdal

from ..core.publish.raster_checks import RasterInfo
from . import log


def read(path: str) -> Optional[RasterInfo]:
    """What the file holds; None when it is not a GeoTIFF GDAL can open."""
    try:
        dataset = gdal.OpenEx(
            path,
            gdal.OF_RASTER,
            allowed_drivers=["GTiff"],
            # only what is written inside the file counts, not sidecar files
            open_options=["GEOREF_SOURCES=INTERNAL"],
        )
        if dataset is None:
            return None
        try:
            count = dataset.RasterCount
            types = tuple(gdal.GetDataTypeName(dataset.GetRasterBand(band).DataType) for band in range(1, count + 1))
            has_crs = bool(dataset.GetProjection())
        finally:
            dataset = None  # GDAL closes the file when the object is released
        return RasterInfo(path, count, types, has_crs, os.path.getsize(path))
    except Exception as exc:
        log.warning("raster file not read: %s" % type(exc).__name__)
        return None
