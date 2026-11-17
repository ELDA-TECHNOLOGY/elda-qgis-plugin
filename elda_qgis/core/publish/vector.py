from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from . import names, polling, upload
from ..errors import EldaError, NetworkError, RequestRefused, ServerError, SessionLost
from .gis import GPKG_MIME, GisApi
from ..net.http import Caller
from .upload import Cancelled

INITIATE = "initiate"
UPLOAD = "upload"
PROCESSING = "processing"

_PROCESSING_FAILED = "Le traitement par ELDA a échoué."
_NOT_REMOVED = " La couche en échec n'a pas pu être supprimée."
_CANCELLED = "Import annulé."
STILL_PROCESSING_FR = "Import interrompu : la couche est toujours en cours de traitement dans ELDA."
_NO_STATUS = "ELDA refuse l'accès à l'état de la couche. Vérifiez-la dans ELDA."
_FOLDER_GONE = "Le dossier choisi n'existe plus dans ELDA. Choisissez-en un autre."
_TOO_BIG = "Fichier trop volumineux : 2 Go maximum."
# server-side limit of the vector import
MAX_FILE_BYTES = 2048 * 1024 * 1024
# the replace route takes one JSON body, limited to 50 MB by the server
MAX_REPLACE_BYTES = 48 * 1024 * 1024
_REPLACE_TOO_BIG = "Couche trop volumineuse pour un remplacement (50 Mo maximum). Publiez-la comme nouvelle couche."
REPLACE_GONE_FR = "La couche à remplacer n'existe plus dans ELDA. Publiez-la comme nouvelle couche."
_REPLACE_EMPTY = (
    "QGIS n'a pu lire aucune entité de cette couche : son fichier source a peut-être été déplacé, "
    "remplacé ou supprimé. La couche ELDA n'a pas été modifiée."
)
_FEATURE = re.compile(rb'"type"\s*:\s*"Feature"')
_STYLE_NOT_SAVED = "La couche est publiée, mais son style n'a pas pu être enregistré : elle a le style par défaut d'ELDA."
_STYLE_SKIPPED = "Son style QGIS n'a pas été repris."
_REPLACE_UNSURE = "Le remplacement n'a pas pu être confirmé. Vérifiez la couche dans ELDA avant de recommencer."
# gateway answers: the API itself may still have accepted the request
_GATEWAY = frozenset({502, 503, 504})
_TIMEOUT = "Le traitement par ELDA prend trop de temps. Vérifiez la couche dans ELDA plus tard."
_GONE = "La couche n'existe plus dans ELDA."
_UNEXPECTED = "L'envoi a échoué pour une raison inattendue."
_LEFTOVER = " Un import inachevé peut subsister dans ELDA."
_BAD_FILE = "Le fichier à envoyer est introuvable ou vide."


@dataclass(frozen=True)
class Job:
    key: str
    file_path: str
    layer_name: str
    folder_id: Optional[int]
    visible_to_users: List[int]
    visible_to_groups: List[int]
    # id of the ELDA layer whose content is replaced; None publishes a new layer
    replace_layer_id: Optional[int] = None
    # ELDA style object saved once the new layer is ready; None leaves ELDA's default style
    style: Optional[dict] = None
    # what of the QGIS style could not be carried over, shown with the result
    style_notes: tuple = ()


@dataclass(frozen=True)
class Outcome:
    key: str
    status: str  # published | failed | cancelled | timeout
    layer_id: Optional[int]
    message_fr: Optional[str]


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _abort_quietly(gis: GisApi, layer_id: int) -> bool:
    try:
        gis.vector_abort(layer_id)
    except SessionLost:
        raise
    except EldaError:
        return False
    return True


def _abort_outcome(job: Job, gis: GisApi, layer_id: int, exc: BaseException) -> Outcome:
    clean = _abort_quietly(gis, layer_id)
    if not isinstance(exc, Exception):
        raise exc
    if isinstance(exc, Cancelled):
        status, message = "cancelled", _CANCELLED
    else:
        status, message = "failed", exc.message_fr if isinstance(exc, EldaError) else _UNEXPECTED
    return Outcome(job.key, status, None, message if clean else message + _LEFTOVER)


def _poll(job: Job, gis: GisApi, layer_id: int, is_cancelled, sleep, clock) -> Outcome:
    start = clock()
    for wait in polling.waits():
        if is_cancelled():
            return Outcome(job.key, "cancelled", layer_id, STILL_PROCESSING_FR)
        try:
            status = gis.layer_status(layer_id)
        except SessionLost:
            raise
        except RequestRefused as exc:
            if exc.status == 404:
                return Outcome(job.key, "failed", layer_id, _GONE)
            # a refusal will not change: the import goes on, only its follow-up stops
            return Outcome(job.key, "timeout", layer_id, _NO_STATUS)
        except EldaError:
            status = "ingesting"  # a single failed poll must not fail the import
        if status == "ready":
            return Outcome(job.key, "published", layer_id, None)
        if status == "failed":
            return _delete_failed(job, gis, layer_id)
        if clock() - start >= polling.MAX_WAIT_SECONDS:
            return Outcome(job.key, "timeout", layer_id, _TIMEOUT)
        sleep(wait)
    raise AssertionError("unreachable")


def _delete_failed(job: Job, gis: GisApi, layer_id: int) -> Outcome:
    message = _PROCESSING_FAILED
    try:
        gis.delete_failed_vector(layer_id)
    except SessionLost:
        raise
    except EldaError:
        message += _NOT_REMOVED
    return Outcome(job.key, "failed", layer_id, message)


def _replace(job: Job, gis: GisApi, size: int, on_step) -> Outcome:
    if size > MAX_REPLACE_BYTES:
        return Outcome(job.key, "failed", None, _REPLACE_TOO_BIG)
    on_step(PROCESSING, 0, 0)
    try:
        with open(job.file_path, "rb") as handle:
            data = handle.read()
        # an export that read nothing would empty the ELDA layer: never send it
        if not _FEATURE.search(data):
            return Outcome(job.key, "failed", None, _REPLACE_EMPTY)
        gis.replace_features(job.replace_layer_id, data)
    except SessionLost:
        raise
    except OSError:
        return Outcome(job.key, "failed", None, _BAD_FILE)
    except RequestRefused as exc:
        known = {404: REPLACE_GONE_FR, 413: _REPLACE_TOO_BIG}
        return Outcome(job.key, "failed", None, known.get(exc.status, exc.message_fr))
    except EldaError:
        # no answer, or a server error: the content may or may not have been replaced
        return Outcome(job.key, "failed", None, _REPLACE_UNSURE)
    return Outcome(job.key, "published", job.replace_layer_id, None)


def publish_vector(
    job: Job,
    gis: GisApi,
    caller: Caller,
    on_step: Callable[[str, int, int], None],
    is_cancelled: Callable[[], bool],
    confirm_slow: Callable[[int], bool],
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    send_file=upload.send_file,
) -> Outcome:
    size = _file_size(job.file_path)
    if size == 0:
        return Outcome(job.key, "failed", None, _BAD_FILE)
    if size > MAX_FILE_BYTES:
        return Outcome(job.key, "failed", None, _TOO_BIG)
    if is_cancelled():
        return Outcome(job.key, "cancelled", None, _CANCELLED)
    if job.replace_layer_id is not None:
        return _replace(job, gis, size, on_step)
    on_step(INITIATE, 0, 0)
    try:
        initiated = gis.vector_initiate(
            names.safe_filename(job.layer_name),
            names.layer_name(job.layer_name),
            size,
            job.folder_id,
            job.visible_to_users,
            job.visible_to_groups,
        )
    except SessionLost:
        raise
    except EldaError as exc:
        gone = isinstance(exc, RequestRefused) and exc.status == 404
        return Outcome(job.key, "failed", None, _FOLDER_GONE if gone else exc.message_fr)
    layer_id = initiated.layer_id
    try:
        etags = send_file(
            caller,
            job.file_path,
            initiated.put,
            GPKG_MIME,
            lambda sent, total: on_step(UPLOAD, sent, total),
            is_cancelled,
            confirm_slow,
        )
    except SessionLost:
        raise
    except BaseException as exc:
        return _abort_outcome(job, gis, layer_id, exc)
    try:
        gis.vector_finalize(layer_id, etags)
    except SessionLost:
        raise
    except NetworkError:
        pass  # the server may have accepted it and the reply was lost: the status decides
    except ServerError as exc:
        if exc.status not in _GATEWAY:
            return _abort_outcome(job, gis, layer_id, exc)
    except BaseException as exc:
        return _abort_outcome(job, gis, layer_id, exc)
    on_step(PROCESSING, 0, 0)
    outcome = _poll(job, gis, layer_id, is_cancelled, sleep, clock)
    if outcome.status == "published":
        return _styled(job, gis, outcome)
    if job.style is not None and outcome.layer_id is not None and outcome.status in ("timeout", "cancelled"):
        # the layer will get ready later, without this session to style it
        return Outcome(outcome.key, outcome.status, outcome.layer_id, "%s %s" % (outcome.message_fr or "", _STYLE_SKIPPED))
    return outcome


def _styled(job: Job, gis: GisApi, outcome: Outcome) -> Outcome:
    """Save the style on the layer that has just been published; a failure here never undoes the publication."""
    notes = list(job.style_notes)
    if job.style is not None:
        try:
            gis.save_style(outcome.layer_id, job.style)
        except Exception:
            # the layer is published whatever happens here; a lost session shows up on the next request
            notes = [_STYLE_NOT_SAVED]
    return Outcome(outcome.key, outcome.status, outcome.layer_id, " ".join(notes) or None)
