from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Union

from ..session.api import EldaApi, RawJson
from ..errors import ServerError, UnsafeUrl
from ..net import server_url

GPKG_MIME = "application/geopackage+sqlite3"
TIFF_MIME = "image/tiff"
_MALFORMED = "Réponse inattendue du serveur ELDA."
_MAX_DIGITS = 18
_MAX_PARTS = 10000
# the server cuts files in 50 MiB parts; anything far above is not a genuine answer
MAX_CHUNK_BYTES = 128 * 1024 * 1024
# the server answers only once every feature is rewritten
REPLACE_TIMEOUT = 600.0
_STATUSES = ("ingesting", "ready", "failed")


@dataclass(frozen=True)
class Folder:
    id: int
    name: str
    parent_id: Optional[int]


@dataclass(frozen=True)
class Group:
    id: int
    name: str


@dataclass(frozen=True)
class Member:
    id: int
    username: str


@dataclass(frozen=True)
class SiteRef:
    id: int
    name: str


@dataclass(frozen=True)
class LayerRef:
    """An existing ELDA layer, as far as duplicate detection needs it."""

    id: int
    name: str
    folder_id: Optional[int]  # None is the site root
    status: str


@dataclass(frozen=True)
class RasterRef:
    """An existing ELDA raster, as far as duplicate detection needs it."""

    id: int
    name: str
    folder_id: Optional[int]  # None is the site root
    status: str


@dataclass(frozen=True)
class SinglePut:
    url: str = field(repr=False)


@dataclass(frozen=True)
class MultipartPut:
    chunk_size: int
    parts: List[Tuple[int, str]] = field(repr=False)  # (part_number, signed url)


@dataclass(frozen=True)
class VectorUpload:
    layer_id: int
    put: Union[SinglePut, MultipartPut]


def _malformed(status: int) -> ServerError:
    return ServerError(status, _MALFORMED)


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= _MAX_DIGITS:
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _visibility(ids: List[int]) -> Optional[List[int]]:
    return list(ids) if ids else None


class GisApi:
    def __init__(self, api: EldaApi):
        self._api = api

    def _rows(self, path: str) -> List[dict]:
        response = self._api.request("GET", path)
        data = response.json()
        if not isinstance(data, list):
            raise _malformed(response.status)
        return [row for row in data if isinstance(row, dict) and _int(row.get("id")) is not None]

    def all_sites(self) -> List[SiteRef]:
        return [SiteRef(_int(r["id"]), _text(r.get("name"))) for r in self._rows("/api/resort/resorts")]

    def _folders(self, path: str) -> List[Folder]:
        return [Folder(_int(r["id"]), _text(r.get("name")), _int(r.get("parentId"))) for r in self._rows(path)]

    def root_folders(self) -> List[Folder]:
        return self._folders("/api/operational-folders/")

    def subfolders(self, folder_id: int) -> List[Folder]:
        return self._folders("/api/operational-folders/subfolder/%d" % folder_id)

    def groups(self, site_id: int) -> List[Group]:
        return [Group(_int(r["id"]), _text(r.get("nom"))) for r in self._rows("/api/groupes/resort/%d" % site_id)]

    def members(self, site_id: int) -> List[Member]:
        return [Member(_int(r["id"]), _text(r.get("username"))) for r in self._rows("/api/users/userResort/%d" % site_id)]

    def site_layers(self, site_id: int) -> List[LayerRef]:
        """Every layer of the site the account may see, in any state; one request, no per-layer call."""
        rows = self._rows("/api/operational-layers/resort/%d" % site_id)
        return [LayerRef(_int(r["id"]), _text(r.get("name")), _int(r.get("folder_id")), _text(r.get("status"))) for r in rows]

    def vector_initiate(
        self,
        filename: str,
        layer_name: str,
        size: int,
        folder_id: Optional[int],
        visible_to_users: List[int],
        visible_to_groups: List[int],
    ) -> VectorUpload:
        body = {
            "filename": filename,
            "layer_name": layer_name,
            "size": size,
            "mime": GPKG_MIME,
            "description": None,
            "folder_id": folder_id,
            "visible_to_users": _visibility(visible_to_users),
            "visible_to_groups": _visibility(visible_to_groups),
        }
        response = self._api.request("POST", "/api/gis/vector/initiate", body, retry=False)
        data = response.json()
        layer_id = _int(data.get("layer_id")) if isinstance(data, dict) else None
        if layer_id is None:
            raise _malformed(response.status)
        return VectorUpload(layer_id, self._put(data, response.status))

    def _storage_url(self, url: Any, status: int) -> str:
        try:
            server_url.check_storage(url, server_url.is_loopback(self._api.server_url))
        except UnsafeUrl:
            raise _malformed(status) from None
        return url

    def _put(self, data: dict, status: int) -> Union[SinglePut, MultipartPut]:
        has_url, has_parts = "put_url" in data, "presigned_part_urls" in data
        if has_url == has_parts:
            raise _malformed(status)
        mode = data.get("mode")
        if mode is not None and mode != ("single" if has_url else "multipart"):
            raise _malformed(status)
        if has_url:
            return SinglePut(self._storage_url(data["put_url"], status))
        chunk_size, rows = _int(data.get("chunk_size")), data["presigned_part_urls"]
        if chunk_size is None or chunk_size > MAX_CHUNK_BYTES or not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_PARTS:
            raise _malformed(status)
        if data.get("total_chunks") is not None and _int(data["total_chunks"]) != len(rows):
            raise _malformed(status)
        parts = []
        for row in rows:
            number = _int(row.get("part_number")) if isinstance(row, dict) else None
            url = row.get("url") if isinstance(row, dict) else None
            if number is None:
                raise _malformed(status)
            parts.append((number, self._storage_url(url, status)))
        parts.sort()
        if [n for n, _ in parts] != list(range(1, len(parts) + 1)):
            raise _malformed(status)
        return MultipartPut(chunk_size, parts)

    def vector_finalize(self, layer_id: int, etags: Optional[List[Tuple[int, str]]]) -> None:
        if etags is None:
            body: dict = {"mode": "single"}
        else:
            body = {"mode": "multipart", "parts": [{"part_number": n, "etag": e} for n, e in etags]}
        self._api.request("POST", "/api/gis/vector/finalize/%d" % layer_id, body, retry=False)

    def vector_abort(self, layer_id: int) -> None:
        self._api.request("POST", "/api/gis/vector/abort/%d" % layer_id, retry=False)

    def layer_status(self, layer_id: int) -> str:
        response = self._api.request("GET", "/api/operational-layers/%d" % layer_id)
        data = response.json()
        status = data.get("status") if isinstance(data, dict) else None
        if status not in _STATUSES:
            raise _malformed(response.status)
        return status

    def replace_features(self, layer_id: int, geojson: bytes) -> None:
        """Swap the whole content of an existing layer for this GeoJSON (EPSG:4326); the layer itself is kept."""
        body = RawJson(geojson, REPLACE_TIMEOUT)
        self._api.request("PUT", "/api/operational-layers/%d/features" % layer_id, body, retry=False)

    # rasters: same upload shape as vector layers, their own routes, table and statuses

    def raster_initiate(
        self,
        filename: str,
        layer_name: str,
        raster_type: str,
        size: int,
        folder_id: Optional[int],
        visible_to_users: List[int],
        visible_to_groups: List[int],
    ) -> VectorUpload:
        body = {
            "filename": filename,
            "layer_name": layer_name,
            "raster_type": raster_type,
            "size": size,
            "mime": TIFF_MIME,
            "description": None,
            "folder_id": folder_id,
            "visible_to_users": _visibility(visible_to_users),
            "visible_to_groups": _visibility(visible_to_groups),
        }
        response = self._api.request("POST", "/api/gis/raster/initiate", body, retry=False)
        data = response.json()
        raster_id = _int(data.get("raster_id")) if isinstance(data, dict) else None
        if raster_id is None:
            raise _malformed(response.status)
        return VectorUpload(raster_id, self._put(data, response.status))

    def raster_finalize(self, raster_id: int, etags: Optional[List[Tuple[int, str]]]) -> None:
        if etags is None:
            body: dict = {"mode": "single"}
        else:
            body = {"mode": "multipart", "parts": [{"part_number": n, "etag": e} for n, e in etags]}
        self._api.request("POST", "/api/gis/raster/finalize/%d" % raster_id, body, retry=False)

    def raster_abort(self, raster_id: int) -> None:
        self._api.request("POST", "/api/gis/raster/abort/%d" % raster_id, retry=False)

    def _rasters(self) -> List[dict]:
        # the server has no route for one raster: the list is the only way to read a status
        response = self._api.request("GET", "/api/gis/raster")
        data = response.json()
        rows = data.get("rasters") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise _malformed(response.status)
        return [row for row in rows if isinstance(row, dict) and _int(row.get("id")) is not None]

    def raster_status(self, raster_id: int) -> Optional[str]:
        """pending, processing, ready or failed; None when the raster is no longer listed."""
        for row in self._rasters():
            if _int(row["id"]) == raster_id:
                return _text(row.get("status"))
        return None

    def site_rasters(self, site_id: int) -> List[RasterRef]:
        """Rasters of one site; a Super Admin is sent those of every site, hence the filter."""
        return [
            RasterRef(_int(r["id"]), _text(r.get("layerName")), _int(r.get("folderID")), _text(r.get("status")))
            for r in self._rasters()
            if _int(r.get("resort_id")) == site_id
        ]

    def delete_failed_raster(self, raster_id: int) -> None:
        self._api.request("DELETE", "/api/gis/raster/%d" % raster_id, retry=False)

    def save_style(self, layer_id: int, style: dict) -> None:
        """Replace the layer's style; only `style` is sent, so every other field of the layer is kept."""
        self._api.request("PUT", "/api/operational-layers/%d" % layer_id, {"style": style}, retry=True)

    def delete_failed_vector(self, layer_id: int) -> None:
        self._api.request("DELETE", "/api/gis/vector/%d" % layer_id, retry=False)
