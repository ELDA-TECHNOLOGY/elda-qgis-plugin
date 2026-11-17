from __future__ import annotations

from typing import Iterator

MAX_WAIT_SECONDS = 1800
_RAMP = (2, 3, 5, 8, 12)
_STEADY = 15


def waits() -> Iterator[float]:
    yield from _RAMP
    while True:
        yield _STEADY
