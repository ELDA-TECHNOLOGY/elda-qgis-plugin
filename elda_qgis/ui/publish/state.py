"""Pure state of the publish window: rows, limits, progress, summary and folder picking; no Qt import."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Collection, List, Optional, Sequence, Tuple

from ...core.publish import names, raster_checks
from ...core.publish.vector import REPLACE_GONE_FR, STILL_PROCESSING_FR
from .. import texts

MAX_LAYERS = 20

ST_IDLE = ""
ST_WAITING = "waiting"
ST_PREPARING = "preparing"
ST_UPLOADING = "uploading"
ST_PROCESSING = "processing"
ST_PUBLISHED = "published"
ST_FAILED = "failed"
ST_CANCELLED = "cancelled"
ST_TIMEOUT = "timeout"
ST_UNPUBLISHED = "unpublished"

_ACTIVE = frozenset({ST_WAITING, ST_PREPARING, ST_UPLOADING, ST_PROCESSING})
_FINISHED = frozenset({ST_PUBLISHED, ST_FAILED, ST_CANCELLED, ST_TIMEOUT, ST_UNPUBLISHED})
_OUTCOME_CODE = {"published": ST_PUBLISHED, "cancelled": ST_CANCELLED, "timeout": ST_TIMEOUT}


@dataclass(frozen=True)
class Row:
    key: str
    name: str
    kind: str
    selectable: bool
    reason: Optional[str]
    checked: bool
    status: str  # one of the ST_* codes; French text via texts.status_text
    percent: Optional[int]
    message: Optional[str]
    # rasters only: dtm, dsm, ortho_rgb, ortho_ir or custom; None until known or chosen
    raster_type: Optional[str] = None


def rows_for(layers, rights) -> List[Row]:
    """One unticked row per project layer; layers expose layer_id, name, kind and, for rasters, raster."""
    out = []
    for layer in layers:
        raster_type = None
        if layer.kind == "vector":
            selectable = rights.vector
            reason = None if selectable else texts.NO_VECTOR_RIGHT
        elif layer.kind == "raster":
            selectable = rights.raster
            reason = None if selectable else texts.NO_RASTER_RIGHT
            info = getattr(layer, "raster", None)
            raster_type = raster_checks.suggested_type(info) if info is not None else None
        else:
            selectable, reason = False, texts.COMING_SOON
        out.append(Row(layer.layer_id, names.layer_name(layer.name), layer.kind,
                       selectable, reason, False, "", None, None, raster_type))
    return out


def can_publish(rows: List[Row], logged_in: bool, busy: bool) -> Tuple[bool, Optional[str]]:
    ticked = sum(1 for r in rows if r.checked and r.selectable)
    if not logged_in:
        return False, texts.NOT_LOGGED_IN
    if busy:
        return False, texts.PUBLISH_BUSY
    if ticked == 0:
        return False, texts.TICK_AT_LEAST_ONE
    if ticked > MAX_LAYERS:
        return False, texts.MAX_LAYERS
    if any(r.checked and r.selectable and r.kind == "raster" and r.raster_type is None for r in rows):
        return False, texts.CHOOSE_RASTER_TYPE
    return True, None


def visibility(restricted: bool, user_ids, group_ids, own_user_id: int) -> Tuple[List[int], List[int]]:
    if not restricted:
        return [], []
    users = list(user_ids)
    if own_user_id not in users:
        users.append(own_user_id)
    return users, list(group_ids)


def apply_step(row: Row, step: str, sent: int, total: int) -> Row:
    if row.status in _FINISHED:
        return row  # a late progress event never resurrects a finished row
    if step == "upload":
        percent = max(0, min(100, int(sent * 100 / total))) if total > 0 else None
        return replace(row, status=ST_UPLOADING, percent=percent)
    if step == "processing":
        return replace(row, status=ST_PROCESSING, percent=None)
    return replace(row, status=ST_PREPARING, percent=None)


def reached_elda(outcome) -> bool:
    """The layer exists, or is still being processed, on ELDA after this outcome."""
    return outcome.status in ("published", "timeout") or (outcome.status == "cancelled" and outcome.layer_id is not None)


def apply_outcome(row: Row, outcome) -> Row:
    status = _OUTCOME_CODE.get(outcome.status, ST_FAILED)
    # a published layer may still carry remarks, about its style for instance
    message = outcome.message_fr
    # a layer that reached ELDA is unticked, so the next batch cannot send it twice by accident
    return replace(row, status=status, percent=None, message=message, checked=row.checked and not reached_elda(outcome))


class SentLayers:
    """What this QGIS session published: layer key -> ELDA layer id, per (server, user id, site id).

    The scope is part of every lookup, so an id learnt on one server, account or site
    can never be offered as a replace target on another.
    """

    def __init__(self) -> None:
        self._by_scope: dict = {}

    def clear(self) -> None:
        self._by_scope.clear()

    def known(self, scope) -> dict:
        """Layer key -> ELDA layer id, or None while ELDA still processes that layer."""
        return dict(self._by_scope.get(scope, {}))

    def record(self, scope, key: str, outcome) -> None:
        layers = self._by_scope.setdefault(scope, {})
        if outcome.status == "published":
            layers[key] = outcome.layer_id
        elif reached_elda(outcome):
            layers[key] = None
        elif outcome.message_fr == REPLACE_GONE_FR:
            # the ELDA layer was deleted: stop offering to replace it
            layers.pop(key, None)


@dataclass(frozen=True)
class DuplicatePlan:
    names: List[str]  # ticked layers and rasters that already exist in ELDA, by the name about to be published
    targets: Optional[dict]  # vector layer key -> ELDA layer id to replace; None when replacing cannot be offered
    why: str = ""  # why not: "several" layers carry the name, one is "busy", or only a "raster" is concerned
    raster_names: Sequence[str] = ()  # the rasters among `names`: a raster can only be created again

    @property
    def several(self) -> bool:
        return self.why == "several"


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def duplicate_plan(rows: List[Row], layers, folder_id: Optional[int], sent, rasters=None) -> DuplicatePlan:
    """Compare the ticked rows with what the destination folder already holds, then with this session's memory.

    `layers` and `rasters` are None when the site lists could not be read; `sent` maps a layer key to the
    ELDA id this session published it to (None while ELDA still processes it). A vector layer is only ever
    compared with vector layers, a raster with rasters.
    """
    names, raster_names, targets, blocked = [], [], {}, ""
    for row in rows:
        if not (row.checked and row.selectable):
            continue
        existing = rasters if row.kind == "raster" else layers
        found = [e for e in existing or [] if e.folder_id == folder_id and _same_name(e.name, row.name)]
        if not found and row.key not in sent:
            continue
        names.append(row.name)
        if row.kind == "raster":
            # ELDA has no way to replace the file of a raster
            raster_names.append(row.name)
        elif len(found) > 1:
            blocked = "several"
        elif found:
            # only a layer ELDA has finished processing can take new content
            if found[0].status == "ready":
                targets[row.key] = found[0].id
            else:
                blocked = blocked or "busy"
        elif sent[row.key] is None:
            blocked = blocked or "busy"
        else:
            targets[row.key] = sent[row.key]
    if blocked:
        return DuplicatePlan(names, None, blocked, raster_names)
    if raster_names and len(raster_names) == len(names):
        return DuplicatePlan(names, None, "raster", raster_names)
    return DuplicatePlan(names, targets, "", raster_names)


def mark_waiting(rows: List[Row]) -> List[Row]:
    """Start a batch: ticked selectable rows wait, every other row goes back to idle."""
    return [
        replace(r, status=ST_WAITING if r.checked and r.selectable else ST_IDLE, percent=None, message=None)
        for r in rows
    ]


def _mark_from(rows: List[Row], from_key: str, status: str) -> List[Row]:
    """Rows from from_key on (all rows if the key is unknown) that are still waiting or running."""
    start = next((i for i, r in enumerate(rows) if r.key == from_key), 0)
    return [
        replace(r, status=status, percent=None) if i >= start and r.status in _ACTIVE else r
        for i, r in enumerate(rows)
    ]


def mark_unpublished(rows: List[Row], from_key: str) -> List[Row]:
    return _mark_from(rows, from_key, ST_UNPUBLISHED)


def mark_session_lost(rows: List[Row], key: str) -> List[Row]:
    """The row being processed by ELDA carries on there; the rows after it were never sent."""

    def detach(row: Row) -> Row:
        if row.status != ST_PROCESSING:
            return row
        return replace(row, status=ST_CANCELLED, percent=None, message=STILL_PROCESSING_FR, checked=False)

    return mark_unpublished(update_row(rows, key, detach), key)


def mark_cancelled(rows: List[Row], from_key: str) -> List[Row]:
    return _mark_from(rows, from_key, ST_CANCELLED)


def summary(rows: List[Row]) -> str:
    def count(code: str) -> int:
        return sum(1 for r in rows if r.status == code)

    parts = [texts.summary_published(count(ST_PUBLISHED))]
    for code, make in (
        (ST_FAILED, texts.summary_failed),
        (ST_CANCELLED, texts.summary_cancelled),
        (ST_TIMEOUT, texts.summary_timeout),
        (ST_UNPUBLISHED, texts.summary_unpublished),
    ):
        if count(code):
            parts.append(make(count(code)))
    lines = [", ".join(parts) + "."]
    # the reason of each problem is shown in full, not only as a tooltip
    lines += ["%s : %s" % (r.name, r.message) for r in rows if r.status in _FINISHED and r.message]
    return "\n".join(lines)


# share of one layer's bar: export, then upload (real), then processing by ELDA (estimated)
_AFTER_EXPORT = 0.05
_AFTER_UPLOAD = 0.60
_PROCESSING_CEILING = 0.97
# seconds after which the estimated processing share is about two thirds done
_PROCESSING_PACE = 20.0


def _share(row: Row, processing_seconds: float) -> float:
    if row.status in _FINISHED:
        return 1.0
    if row.status == ST_UPLOADING:
        return _AFTER_EXPORT + (_AFTER_UPLOAD - _AFTER_EXPORT) * (row.percent or 0) / 100
    if row.status == ST_PROCESSING:
        # ELDA gives no progress while it processes: the bar eases towards the ceiling with time
        done = 1 - math.exp(-max(0.0, processing_seconds) / _PROCESSING_PACE)
        return _AFTER_UPLOAD + (_PROCESSING_CEILING - _AFTER_UPLOAD) * done
    return 0.0


def progress(rows: List[Row], processing_seconds: float) -> Optional[int]:
    """Percent of the whole batch, every layer weighing the same; None when no layer is in a batch."""
    batch = [r for r in rows if r.status != ST_IDLE]
    if not batch:
        return None
    return int(100 * sum(_share(r, processing_seconds) for r in batch) / len(batch))


def update_row(rows: List[Row], key: str, change: Callable[[Row], Row]) -> List[Row]:
    return [change(r) if r.key == key else r for r in rows]


def set_checked(rows: List[Row], key: str, checked: bool) -> List[Row]:
    return update_row(rows, key, lambda r: replace(r, checked=checked and r.selectable))


def set_all_checked(rows: List[Row], checked: bool) -> List[Row]:
    return [replace(r, checked=checked and r.selectable) for r in rows]


def all_checked(rows: List[Row]) -> bool:
    """True when every layer that can be published is checked, and there is at least one."""
    selectable = [r for r in rows if r.selectable]
    return bool(selectable) and all(r.checked for r in selectable)


def set_raster_type(rows: List[Row], key: str, raster_type: Optional[str]) -> List[Row]:
    return update_row(rows, key, lambda r: replace(r, raster_type=raster_type) if r.kind == "raster" else r)


def rename(rows: List[Row], key: str, raw: str) -> List[Row]:
    return update_row(rows, key, lambda r: replace(r, name=names.layer_name(raw)) if r.selectable else r)


def fail_row(rows: List[Row], key: str, message: str) -> List[Row]:
    return update_row(rows, key, lambda r: replace(r, status=ST_FAILED, percent=None, message=message))


def merge_rows(previous: List[Row], fresh: List[Row], edited: Collection[str]) -> List[Row]:
    """Reloaded rows keep the tick, the edited name and the last status of layers still present."""
    old = {r.key: r for r in previous}
    out = []
    for row in fresh:
        before = old.get(row.key)
        if before is not None:
            keep_name = row.selectable and row.key in edited
            row = replace(
                row,
                name=before.name if keep_name else row.name,
                checked=before.checked and row.selectable,
                status=before.status,
                percent=before.percent,
                message=before.message,
                raster_type=before.raster_type or row.raster_type,
            )
        out.append(row)
    return out


def next_waiting(rows: List[Row]) -> Optional[str]:
    return next((r.key for r in rows if r.status == ST_WAITING), None)


def advance(rows: List[Row], key: str, cancelled: bool) -> Tuple[List[Row], Optional[str]]:
    """After row `key` ended: on cancel the rest is marked cancelled and the batch stops, else the next key."""
    if cancelled:
        return mark_cancelled(rows, key), None
    return rows, next_waiting(rows)


class FolderNode:
    """Bookkeeping of one folder picker node: its path and whether its children are loaded."""

    _IDLE, _LOADING, _LOADED = "idle", "loading", "loaded"

    def __init__(self, folder_id: Optional[int], path: Optional[str]):
        self.folder_id = folder_id  # None is the site root
        self.path = path
        self._state = self._IDLE

    def child(self, folder_id: int, name: str) -> "FolderNode":
        name = name.strip() or texts.UNNAMED_FOLDER
        return FolderNode(folder_id, name if self.path is None else self.path + " / " + name)

    def label(self) -> str:
        return self.path or texts.SITE_ROOT

    def start_load(self) -> bool:
        """True when the children must be fetched now."""
        if self._state != self._IDLE:
            return False
        self._state = self._LOADING
        return True

    def loaded(self) -> None:
        self._state = self._LOADED

    def load_failed(self) -> None:
        self._state = self._IDLE
