"""Publish one GeoTIFF as an ELDA raster: initiate, upload, finalize, then follow the processing."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..errors import EldaError, NetworkError, RequestRefused, ServerError, SessionLost
from . import names, polling, upload
from .gis import TIFF_MIME, GisApi
from .upload import Cancelled
from .vector import INITIATE, PROCESSING, UPLOAD, Outcome

# converting a large raster takes far longer than ingesting a vector layer
MAX_WAIT_SECONDS = 2 * 3600
_GATEWAY = frozenset({502, 503, 504})
_BAD_FILE = "Le fichier du raster est introuvable ou vide."
_CANCELLED = "Import annulé."
_STILL_PROCESSING = "Import interrompu : le raster est toujours en cours de traitement dans ELDA."
_TIMEOUT = "Le traitement par ELDA prend trop de temps. Vérifiez le raster dans ELDA plus tard."
_GONE = "Le raster n'existe plus dans ELDA."
_FAILED = "Le traitement par ELDA a échoué."
_NOT_REMOVED = " Le raster en échec n'a pas pu être supprimé."
_UNEXPECTED = "L'envoi a échoué pour une raison inattendue."
_LEFTOVER = " Un import inachevé peut subsister dans ELDA."


@dataclass(frozen=True)
class RasterJob:
    key: str
    file_path: str
    layer_name: str
    raster_type: str
    folder_id: Optional[int]
    visible_to_users: List[int]
    visible_to_groups: List[int]


def _abort(job: RasterJob, gis: GisApi, raster_id: int, exc: BaseException) -> Outcome:
    clean = True
    try:
        gis.raster_abort(raster_id)
    except SessionLost:
        raise
    except EldaError:
        clean = False
    if not isinstance(exc, Exception):
        raise exc
    if isinstance(exc, Cancelled):
        status, message = "cancelled", _CANCELLED
    else:
        status, message = "failed", exc.message_fr if isinstance(exc, EldaError) else _UNEXPECTED
    return Outcome(job.key, status, None, message if clean else message + _LEFTOVER)


def _follow(job: RasterJob, gis: GisApi, raster_id: int, is_cancelled, sleep, clock) -> Outcome:
    start = clock()
    for wait in polling.waits():
        if is_cancelled():
            return Outcome(job.key, "cancelled", raster_id, _STILL_PROCESSING)
        try:
            status = gis.raster_status(raster_id)
        except SessionLost:
            raise
        except RequestRefused:
            # a refusal will not change: the import goes on, only its follow-up stops
            return Outcome(job.key, "timeout", raster_id, _TIMEOUT)
        except EldaError:
            status = "processing"  # a single failed poll must not fail the import
        if status is None:
            return Outcome(job.key, "failed", raster_id, _GONE)
        if status == "ready":
            return Outcome(job.key, "published", raster_id, None)
        if status == "failed":
            message = _FAILED
            try:
                gis.delete_failed_raster(raster_id)
            except SessionLost:
                raise
            except EldaError:
                message += _NOT_REMOVED
            return Outcome(job.key, "failed", raster_id, message)
        if clock() - start >= MAX_WAIT_SECONDS:
            return Outcome(job.key, "timeout", raster_id, _TIMEOUT)
        sleep(wait)
    raise AssertionError("unreachable")


def publish_raster(
    job: RasterJob,
    gis: GisApi,
    caller,
    on_step: Callable[[str, int, int], None],
    is_cancelled: Callable[[], bool],
    confirm_slow: Callable[[int], bool],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    send_file=upload.send_file,
) -> Outcome:
    try:
        size = os.path.getsize(job.file_path)
    except OSError:
        size = 0
    if size == 0:
        return Outcome(job.key, "failed", None, _BAD_FILE)
    if is_cancelled():
        return Outcome(job.key, "cancelled", None, _CANCELLED)
    on_step(INITIATE, 0, 0)
    try:
        started = gis.raster_initiate(
            os.path.basename(job.file_path),
            names.layer_name(job.layer_name),
            job.raster_type,
            size,
            job.folder_id,
            job.visible_to_users,
            job.visible_to_groups,
        )
    except SessionLost:
        raise
    except EldaError as exc:
        return Outcome(job.key, "failed", None, exc.message_fr)
    raster_id = started.layer_id
    try:
        etags = send_file(
            caller, job.file_path, started.put, TIFF_MIME,
            lambda sent, total: on_step(UPLOAD, sent, total), is_cancelled, confirm_slow,
        )
    except SessionLost:
        raise
    except BaseException as exc:
        return _abort(job, gis, raster_id, exc)
    try:
        gis.raster_finalize(raster_id, etags)
    except SessionLost:
        raise
    except NetworkError:
        pass  # the server may have accepted it and the reply was lost: the status decides
    except ServerError as exc:
        if exc.status not in _GATEWAY:
            return _abort(job, gis, raster_id, exc)
    except BaseException as exc:
        return _abort(job, gis, raster_id, exc)
    on_step(PROCESSING, 0, 0)
    return _follow(job, gis, raster_id, is_cancelled, sleep, clock)
