import sqlite3

from elda_qgis.core.publish import gpkg


def make(path, rows, table="layer"):
    with sqlite3.connect(str(path)) as db:
        db.execute('CREATE TABLE "%s" (fid INTEGER PRIMARY KEY, name TEXT)' % table)
        db.executemany('INSERT INTO "%s" (name) VALUES (?)' % table, [("x",)] * rows)


def test_counts_the_features_written(tmp_path):
    make(tmp_path / "a.gpkg", 3)
    assert gpkg.feature_count(str(tmp_path / "a.gpkg")) == 3


def test_an_empty_export_is_seen_as_zero(tmp_path):
    make(tmp_path / "a.gpkg", 0)
    assert gpkg.feature_count(str(tmp_path / "a.gpkg")) == 0


def test_unreadable_or_unexpected_file_gives_no_verdict(tmp_path):
    (tmp_path / "junk.gpkg").write_bytes(b"not a database")
    make(tmp_path / "other.gpkg", 2, table="autre")
    assert gpkg.feature_count(str(tmp_path / "junk.gpkg")) is None
    assert gpkg.feature_count(str(tmp_path / "other.gpkg")) is None
    assert gpkg.feature_count(str(tmp_path / "missing.gpkg")) is None


def test_the_file_is_not_modified_nor_created(tmp_path):
    gpkg.feature_count(str(tmp_path / "missing.gpkg"))
    assert not (tmp_path / "missing.gpkg").exists()
