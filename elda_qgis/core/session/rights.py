from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..i18n import tr
from .account import Account

_VECTOR = "gis_operational:manage"
_RASTER = "gis:raster:upload"


@dataclass(frozen=True)
class Rights:
    vector: bool
    raster: bool


def of(account: Account) -> Rights:
    perms = account.permissions
    everything = "*" in perms
    return Rights(vector=everything or _VECTOR in perms, raster=everything or _RASTER in perms)


def explain(account: Account) -> Optional[str]:
    if not account.sites:
        return tr("Votre compte n'a accès à aucun site ELDA. Contactez votre administrateur.")
    rights = of(account)
    if rights.vector and rights.raster:
        return None
    missing = []
    if not rights.vector:
        missing.append(tr("vecteur"))
    if not rights.raster:
        missing.append(tr("raster"))
    return tr("Votre compte n'a pas le droit de publier des données %s sur ce site.") % tr(" ni ").join(missing)
