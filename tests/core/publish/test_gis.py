from __future__ import annotations

import unittest

from elda_qgis.core.errors import RequestRefused, ServerError
from elda_qgis.core.publish.gis import GPKG_MIME, Folder, GisApi, Group, Member, MultipartPut, SinglePut, SiteRef, VectorUpload
from tests.core.fakes import logged, resp

SIGNED = "https://s3.example/b/k?X-Amz-Signature=deadbeef"


def gis(script):
    api, transport = logged(script)
    del transport.requests[:]
    return GisApi(api), transport


def single_ok(layer_id=41):
    return resp(200, {"layer_id": layer_id, "s3_key": "k", "mode": "single", "put_url": SIGNED, "expires_in": 900})


def multipart_body(**over):
    body = {
        "layer_id": 42,
        "s3_key": "k",
        "mode": "multipart",
        "multipart_upload_id": "u",
        "chunk_size": 8,
        "total_chunks": 2,
        "presigned_part_urls": [{"part_number": 2, "url": SIGNED + "2"}, {"part_number": 1, "url": SIGNED + "1"}],
        "expires_in": 900,
    }
    body.update(over)
    return resp(200, body)


class InitiateTest(unittest.TestCase):
    def test_initiate_single(self):
        g, t = gis([single_ok()])
        up = g.vector_initiate("pistes.gpkg", "Pistes", 1024, 7, [], [])
        self.assertEqual(up, VectorUpload(41, SinglePut(SIGNED)))
        self.assertEqual(len(t.requests), 1)
        r = t.requests[0]
        self.assertEqual((r.method, r.url), ("POST", "https://elda.example/api/gis/vector/initiate"))
        self.assertEqual(
            r.json,
            {
                "filename": "pistes.gpkg",
                "layer_name": "Pistes",
                "size": 1024,
                "mime": GPKG_MIME,
                "description": None,
                "folder_id": 7,
                "visible_to_users": None,
                "visible_to_groups": None,
            },
        )

    def test_post_is_never_retried(self):
        g, t = gis([resp(503, {}), single_ok()])
        with self.assertRaises(ServerError):
            g.vector_initiate("a.gpkg", "A", 1, None, [], [])
        self.assertEqual(len(t.requests), 1)

    def test_initiate_multipart(self):
        g, _ = gis([multipart_body()])
        up = g.vector_initiate("a.gpkg", "A", 99, None, [], [])
        self.assertEqual(up, VectorUpload(42, MultipartPut(8, [(1, SIGNED + "1"), (2, SIGNED + "2")])))

    def test_restricted_visibility_sends_lists(self):
        g, t = gis([single_ok()])
        g.vector_initiate("a.gpkg", "A", 1, None, [329], [4])
        self.assertEqual(t.requests[0].json["visible_to_users"], [329])
        self.assertEqual(t.requests[0].json["visible_to_groups"], [4])

    def test_ids_as_strings_and_numeric_layer_id(self):
        g, _ = gis([single_ok("41")])
        self.assertEqual(g.vector_initiate("a.gpkg", "A", 1, None, [], []).layer_id, 41)

    def test_malformed_initiate_is_server_error(self):
        bad = [
            resp(200, {"layer_id": 1, "mode": "single"}),
            resp(200, {"layer_id": 1, "mode": "single", "put_url": ""}),
            resp(200, {"layer_id": "x", "mode": "single", "put_url": SIGNED}),
            resp(200, {"layer_id": None, "mode": "single", "put_url": SIGNED}),
            resp(200, {"layer_id": 1, "mode": "weird", "put_url": SIGNED}),
            multipart_body(presigned_part_urls="nope"),
            multipart_body(presigned_part_urls=[{"part_number": 1}]),
            multipart_body(presigned_part_urls=[]),
            multipart_body(chunk_size=0),
            multipart_body(chunk_size="big"),
            resp(200, []),
            resp(200, None),
        ]
        for item in bad:
            g, _ = gis([item])
            with self.assertRaises(ServerError):
                g.vector_initiate("a.gpkg", "A", 1, None, [], [])

    def test_multipart_numbering_and_sizes_are_validated(self):
        def parts(*numbers):
            return [{"part_number": n, "url": SIGNED} for n in numbers]

        bad = [
            multipart_body(presigned_part_urls=parts(1, 3), total_chunks=2),
            multipart_body(presigned_part_urls=parts(1, 1), total_chunks=2),
            multipart_body(presigned_part_urls=parts(0, 1), total_chunks=2),
            multipart_body(presigned_part_urls=parts(2, 3), total_chunks=2),
            multipart_body(chunk_size=-5),
            multipart_body(chunk_size=0),
            multipart_body(total_chunks=3),
            multipart_body(presigned_part_urls=parts(*range(1, 10002)), total_chunks=10001),
        ]
        for item in bad:
            g, _ = gis([item])
            with self.assertRaises(ServerError):
                g.vector_initiate("a.gpkg", "A", 1, None, [], [])

    def test_total_chunks_optional(self):
        body = {"layer_id": 42, "chunk_size": 8, "presigned_part_urls": [{"part_number": 1, "url": SIGNED}]}
        g, _ = gis([resp(200, body)])
        self.assertEqual(g.vector_initiate("a.gpkg", "A", 1, None, [], []).put, MultipartPut(8, [(1, SIGNED)]))

    def test_shape_decides_mode(self):
        part = [{"part_number": 1, "url": SIGNED}]
        ok = [
            ({"layer_id": 1, "put_url": SIGNED}, SinglePut(SIGNED)),
            ({"layer_id": 1, "put_url": SIGNED, "mode": "single"}, SinglePut(SIGNED)),
            ({"layer_id": 1, "chunk_size": 4, "presigned_part_urls": part}, MultipartPut(4, [(1, SIGNED)])),
            ({"layer_id": 1, "chunk_size": 4, "presigned_part_urls": part, "mode": "multipart"}, MultipartPut(4, [(1, SIGNED)])),
        ]
        for body, put in ok:
            g, _ = gis([resp(200, body)])
            self.assertEqual(g.vector_initiate("a.gpkg", "A", 1, None, [], []).put, put)
        bad = [
            {"layer_id": 1},
            {"layer_id": 1, "put_url": SIGNED, "chunk_size": 4, "presigned_part_urls": part},
            {"layer_id": 1, "put_url": SIGNED, "mode": "multipart"},
            {"layer_id": 1, "chunk_size": 4, "presigned_part_urls": part, "mode": "single"},
        ]
        for body in bad:
            g, _ = gis([resp(200, body)])
            with self.assertRaises(ServerError):
                g.vector_initiate("a.gpkg", "A", 1, None, [], [])

    def test_bad_layer_ids_are_server_error(self):
        for value in ("9" * 5000, "9" * 19, 0, -3, True, "0", "-3"):
            g, _ = gis([resp(200, {"layer_id": value, "put_url": SIGNED})])
            with self.assertRaises(ServerError):
                g.vector_initiate("a.gpkg", "A", 1, None, [], [])

    def test_unknown_folder_is_request_refused(self):
        g, _ = gis([resp(404, {"message": "Dossier introuvable"})])
        with self.assertRaises(RequestRefused):
            g.vector_initiate("a.gpkg", "A", 1, 9, [], [])

    def test_repr_hides_signed_urls(self):
        for up in (VectorUpload(1, SinglePut(SIGNED)), VectorUpload(2, MultipartPut(8, [(1, SIGNED)]))):
            for text in (repr(up), str(up), repr(up.put), str(up.put)):
                self.assertNotIn("X-Amz-Signature", text)
                self.assertNotIn("s3.example", text)

    def test_malformed_error_has_no_url(self):
        g, _ = gis([resp(200, {"layer_id": 1, "mode": "single", "put_url": 5, "x": SIGNED})])
        with self.assertRaises(ServerError) as cm:
            g.vector_initiate("a.gpkg", "A", 1, None, [], [])
        self.assertNotIn("Signature", str(cm.exception))


class FinalizeTest(unittest.TestCase):
    def test_finalize_bodies(self):
        g, t = gis([resp(200, {}), resp(200, {})])
        g.vector_finalize(41, None)
        g.vector_finalize(42, [(1, "a"), (2, "b")])
        self.assertEqual((t.requests[0].method, t.requests[0].url), ("POST", "https://elda.example/api/gis/vector/finalize/41"))
        self.assertEqual(t.requests[0].json, {"mode": "single"})
        self.assertEqual(
            t.requests[1].json,
            {"mode": "multipart", "parts": [{"part_number": 1, "etag": "a"}, {"part_number": 2, "etag": "b"}]},
        )

    def test_abort_sends_post_without_body_once(self):
        g, t = gis([resp(503, {})])
        with self.assertRaises(ServerError):
            g.vector_abort(41)
        self.assertEqual(len(t.requests), 1)
        self.assertEqual((t.requests[0].method, t.requests[0].url), ("POST", "https://elda.example/api/gis/vector/abort/41"))
        self.assertIsNone(t.requests[0].json)

    def test_no_other_delete_route_is_called(self):
        g, t = gis([resp(200, {})])
        g.delete_failed_vector(41)
        self.assertEqual([(r.method, r.url) for r in t.requests], [("DELETE", "https://elda.example/api/gis/vector/41")])

    def test_delete_is_never_retried(self):
        g, t = gis([resp(503, {})])
        with self.assertRaises(ServerError):
            g.delete_failed_vector(41)
        self.assertEqual(len(t.requests), 1)


class StatusTest(unittest.TestCase):
    def test_layer_status(self):
        g, t = gis([resp(200, {"status": "ready"}), resp(200, {"status": "ingesting"}), resp(200, {"status": "failed"})])
        self.assertEqual([g.layer_status(1), g.layer_status(1), g.layer_status(1)], ["ready", "ingesting", "failed"])
        self.assertEqual(t.requests[0].url, "https://elda.example/api/operational-layers/1")

    def test_unknown_status_is_server_error(self):
        for item in (resp(200, {"status": "weird"}), resp(200, {}), resp(200, []), resp(200, {"status": None})):
            g, _ = gis([item])
            with self.assertRaises(ServerError):
                g.layer_status(1)


class ListsTest(unittest.TestCase):
    def test_folders_groups_members(self):
        g, t = gis(
            [
                resp(200, [{"id": "3", "name": "Root", "parentId": None}, {"name": "no id"}, {"id": None, "name": "x"}, "junk"]),
                resp(200, [{"id": 4, "name": "Sub", "parentId": "3"}]),
                resp(200, [{"id": "5", "nom": "Pisteurs"}, {"nom": "x"}]),
                resp(200, [{"id": 6, "username": "léa"}, {"username": "x"}]),
                resp(200, [{"id": 21, "name": "A"}, {"id": "22", "name": "B"}, {"name": "C"}]),
            ]
        )
        self.assertEqual(g.root_folders(), [Folder(3, "Root", None)])
        self.assertEqual(g.subfolders(3), [Folder(4, "Sub", 3)])
        self.assertEqual(g.groups(21), [Group(5, "Pisteurs")])
        self.assertEqual(g.members(21), [Member(6, "léa")])
        self.assertEqual(g.all_sites(), [SiteRef(21, "A"), SiteRef(22, "B")])
        self.assertEqual(
            [r.url.replace("https://elda.example", "") for r in t.requests],
            [
                "/api/operational-folders/",
                "/api/operational-folders/subfolder/3",
                "/api/groupes/resort/21",
                "/api/users/userResort/21",
                "/api/resort/resorts",
            ],
        )

    def test_bool_zero_negative_and_huge_ids_are_skipped(self):
        rows = [{"id": True, "name": "b"}, {"id": 0, "name": "z"}, {"id": -3, "name": "n"}, {"id": "9" * 5000, "name": "h"}, {"id": 8, "name": "ok"}]
        g, _ = gis([resp(200, rows)])
        self.assertEqual(g.root_folders(), [Folder(8, "ok", None)])

    def test_non_list_is_server_error(self):
        g, _ = gis([resp(200, {"a": 1})])
        with self.assertRaises(ServerError):
            g.root_folders()

    def test_subfolder_404_is_request_refused(self):
        g, _ = gis([resp(404, {"message": "Dossier introuvable"})])
        with self.assertRaises(RequestRefused):
            g.subfolders(99)


if __name__ == "__main__":
    unittest.main()
