from __future__ import annotations

import math
import os
import time
from typing import Callable, List, Optional, Tuple, Union

from ..errors import EldaError, NetworkError, RequestRefused, ServerError
from ..net import server_url
from .gis import MultipartPut, SinglePut
from ..net.http import Caller, Request

UPLOAD_TIMEOUT = 300.0
SINGLE_MAX_BYTES = 8 * 1024 * 1024
_ASK_AFTER = 3000.0
_GIVE_UP_AFTER = 3600.0
_REFUSED = "Le stockage a refusé l'envoi du fichier."


class Cancelled(Exception):
    pass


class TooSlow(EldaError):
    default_fr = "L'envoi est trop lent (plus d'une heure). Réessayez avec une meilleure connexion."


def _check_url(url: str) -> None:
    # second look, in case an upload plan was built without the checks of the API layer
    server_url.check_storage(url, api_is_loopback=True)


def _put(caller: Caller, url: str, data: bytes, mime: str) -> dict:
    _check_url(url)
    request = Request("PUT", url, {"Content-Type": mime}, body=data, timeout=UPLOAD_TIMEOUT)
    try:
        response = caller.call(request, retry=True)
    except RequestRefused as exc:
        # the refusal text comes from the storage body and may echo the signed url
        raise RequestRefused(exc.status, _REFUSED) from None
    except ServerError as exc:
        raise ServerError(exc.status, "Le stockage est momentanément indisponible. Réessayez plus tard.") from None
    except NetworkError:
        raise NetworkError("Impossible de joindre le stockage. Vérifiez votre connexion.") from None
    if not 200 <= response.status < 300:
        raise RequestRefused(response.status, _REFUSED)
    return dict(response.headers)


def _etag(headers: dict) -> str:
    for key, value in headers.items():
        if key.lower() == "etag" and value:
            return value
    raise ServerError(0, "Le stockage n'a pas confirmé la réception du fichier.")


def send_file(
    caller: Caller,
    path: str,
    put: Union[SinglePut, MultipartPut],
    mime: str,
    on_progress: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
    confirm_slow: Callable[[int], bool],
    clock: Callable[[], float] = time.monotonic,
) -> Optional[List[Tuple[int, str]]]:
    size = os.path.getsize(path)
    if size == 0:
        raise ServerError(0, "Le fichier à envoyer est vide.")
    if isinstance(put, SinglePut):
        if size > SINGLE_MAX_BYTES:
            raise ServerError(0, "Le fichier est trop volumineux pour un envoi simple.")
        _check_url(put.url)
        if is_cancelled():
            raise Cancelled()
        with open(path, "rb") as handle:
            _put(caller, put.url, handle.read(), mime)
        on_progress(size, size)
        return None
    if math.ceil(size / put.chunk_size) != len(put.parts):
        raise ServerError(0, "Le fichier a changé depuis la préparation de l'envoi. Recommencez.")
    for _, url in put.parts:
        _check_url(url)
    etags: List[Tuple[int, str]] = []
    start, asked, sent = clock(), False, 0
    with open(path, "rb") as handle:
        for index, (number, url) in enumerate(put.parts):
            if is_cancelled():
                raise Cancelled()
            handle.seek(index * put.chunk_size)
            data = handle.read(put.chunk_size)
            etags.append((number, _etag(_put(caller, url, data, mime))))
            sent += len(data)
            on_progress(sent, size)
            remaining = len(put.parts) - index - 1
            if not remaining:
                break
            # the hour counts from the start: signed urls expire one hour after initiate (dialog time included)
            elapsed = clock() - start
            if elapsed > _GIVE_UP_AFTER:
                raise TooSlow()
            estimate = elapsed / (index + 1) * remaining
            if not asked and estimate > _ASK_AFTER:
                asked = True
                if not confirm_slow(round(estimate / 60)):
                    raise Cancelled()
    return etags
