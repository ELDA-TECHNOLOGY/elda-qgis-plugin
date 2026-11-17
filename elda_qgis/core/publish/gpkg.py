"""Look inside the GeoPackage the plugin has just written, before it is sent."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

LAYER_TABLE = "layer"


def feature_count(path: str, table: str = LAYER_TABLE) -> Optional[int]:
    """Number of rows of the exported layer; None when the file cannot be read that way."""
    try:
        # read-only: never create or alter the file
        db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return None
    try:
        return int(db.execute('SELECT count(*) FROM "%s"' % table.replace('"', '""')).fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        db.close()
