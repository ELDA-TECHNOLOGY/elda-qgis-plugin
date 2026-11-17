from __future__ import annotations

import re

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_HAS_ALNUM = re.compile(r"[A-Za-z0-9]")
_STEM_MAX = 80
_NAME_MAX = 255


def safe_filename(layer_name: str) -> str:
    stem = _UNSAFE.sub("_", layer_name)[:_STEM_MAX]
    if not _HAS_ALNUM.search(stem):
        stem = "couche"
    return stem + ".gpkg"


def layer_name(raw: str) -> str:
    name = " ".join(raw.split())[:_NAME_MAX].rstrip()
    return name or "Couche QGIS"
