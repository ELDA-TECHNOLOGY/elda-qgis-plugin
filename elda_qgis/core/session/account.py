from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional


@dataclass(frozen=True)
class Site:
    id: int
    name: str


@dataclass(frozen=True)
class Account:
    user_id: int
    username: str
    sites: List[Site]
    active_site_id: Optional[int]
    permissions: FrozenSet[str]
