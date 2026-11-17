import pytest

from elda_qgis.core.net.redact import without_paths


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Cannot create /var/folders/ab/T/elda-x1/layer.gpkg: no space", "Cannot create […]: no space"),
        (r"Echec C:\Users\Léa Martin\AppData\Local\Temp\elda\layer.gpkg", "Echec […]"),
        ("failed to execute insert : UNIQUE constraint failed: layer.fid", "failed to execute insert : UNIQUE constraint failed: layer.fid"),
        ("ratio 3/4 kept", "ratio 3/4 kept"),
        ("", ""),
    ],
)
def test_file_paths_are_removed_and_the_reason_kept(text, expected):
    assert without_paths(text) == expected
