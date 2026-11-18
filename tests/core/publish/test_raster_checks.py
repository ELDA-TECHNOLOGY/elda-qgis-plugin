import pytest

from elda_qgis.core.publish import raster_checks as rc
from elda_qgis.core.publish.raster_checks import RasterInfo


def info(**kw):
    base = dict(path="/data/mnt.tif", bands=1, data_types=("Float32",), has_crs=True, size=10_000)
    base.update(kw)
    return RasterInfo(**base)


@pytest.mark.parametrize(
    "bands, types, expected",
    [
        (3, ("Byte",) * 3, "ortho_rgb"),
        (4, ("Byte",) * 4, "ortho_rgb"),
        (1, ("Float32",), None),
        (1, ("Byte",), None),
        (3, ("UInt16",) * 3, None),
    ],
)
def test_only_an_8_bit_colour_image_gets_a_type_without_asking(bands, types, expected):
    assert rc.suggested_type(info(bands=bands, data_types=types)) == expected


def test_a_float_terrain_model_passes():
    assert rc.problem(info(), "dtm") is None


@pytest.mark.parametrize("raster_type", ["dtm", "dsm", "ortho_ir", "custom"])
@pytest.mark.parametrize("data_type", ["Byte", "Int16", "UInt16", "Int32"])
def test_whole_number_data_is_refused_for_every_type_but_colour_images(raster_type, data_type):
    text = rc.problem(info(data_types=(data_type,)), raster_type)
    assert text and "virgule" in text and "Float32" in text


@pytest.mark.parametrize("data_type", ["UInt16", "Float32"])
def test_a_colour_image_must_be_8_bit(data_type):
    text = rc.problem(info(bands=3, data_types=(data_type,) * 3), "ortho_rgb")
    assert text and "8 bits" in text


def test_a_colour_image_in_8_bit_passes_with_1_3_or_4_bands():
    for bands in (1, 3, 4):
        assert rc.problem(info(bands=bands, data_types=("Byte",) * bands), "ortho_rgb") is None


def test_no_coordinate_system_is_refused():
    assert "coordonnées" in rc.problem(info(has_crs=False), "dtm")


@pytest.mark.parametrize("path", ["/data/mnt.jp2", "/data/mnt", "", None, "/vsicurl/https://x/mnt.tif?token=1"])
def test_only_a_geotiff_file_on_disk_can_be_sent(path):
    assert "GeoTIFF" in rc.problem(info(path=path), "dtm")


def test_size_limits():
    assert "vide" in rc.problem(info(size=0), "dtm")
    assert "50 Go" in rc.problem(info(size=rc.MAX_FILE_BYTES + 1), "dtm")
    assert rc.problem(info(size=rc.MAX_FILE_BYTES), "dtm") is None


def test_unknown_type_is_refused():
    assert rc.problem(info(), "snow_depth") is not None


def test_every_type_has_a_french_label():
    assert set(rc.TYPE_LABELS) == set(rc.TYPES)
