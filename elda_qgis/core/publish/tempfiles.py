from __future__ import annotations

import shutil
import tempfile

PREFIX = "elda_qgis_"


def temp_dir() -> str:
    return tempfile.mkdtemp(prefix=PREFIX)


def cleanup(path: str) -> None:
    # only ever removes directories this plugin created
    try:
        if path and path.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1].startswith(PREFIX):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
