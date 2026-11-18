"""Pure decisions behind the windows: what to show, which server, which site."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ...core.session import rights
from ...core.net import server_url
from ...core.publish.gis import SiteRef
from ...core.session.account import Account, Site
from .. import texts


@dataclass(frozen=True)
class ViewState:
    logged_in: bool
    username: str = ""
    sites: List[Site] = field(default_factory=list)
    site_combo_visible: bool = False
    selected_site_id: Optional[int] = None
    vector_line: str = ""
    raster_line: str = ""
    explanation: Optional[str] = None
    site_label: Optional[str] = None


@dataclass(frozen=True)
class ServerChoice:
    url: str
    needs_confirmation: bool


def view_of(account: Optional[Account], all_sites: Optional[List[SiteRef]] = None) -> ViewState:
    if account is None:
        return ViewState(logged_in=False)
    sites = sites_for(account, all_sites)
    ids = [s.id for s in sites]
    if account.active_site_id in ids:
        selected = account.active_site_id
    else:
        selected = ids[0] if ids else None
    granted = rights.of(account)
    combo_visible = len(ids) > 1
    label = None
    if not combo_visible and selected is not None:
        label = texts.site_label(next(s.name for s in sites if s.id == selected))
    return ViewState(
        logged_in=True,
        username=account.username,
        sites=sites,
        site_combo_visible=combo_visible,
        selected_site_id=selected,
        vector_line=texts.rights_line("vector", granted.vector),
        raster_line=texts.rights_line("raster", granted.raster),
        explanation=rights.explain(account),
        site_label=label,
    )


def site_to_select(account: Account, last_site: Optional[int]) -> Optional[int]:
    """Site to switch to after login: the remembered one if still valid, else the first when none is active."""
    ids = [s.id for s in account.sites]
    if last_site in ids and last_site != account.active_site_id:
        return last_site
    if account.active_site_id is None and ids:
        return ids[0]
    return None


def should_reload_saved(previous: Optional[str], new: Optional[str]) -> bool:
    """Saved credentials are reloaded (password cleared) only when the server really changed; None = unusable."""
    return previous != new


def password_belongs_to(filled_for: Optional[str], chosen_url: str) -> bool:
    """A password typed or loaded for one server must never be sent to another."""
    return filled_for == chosen_url


def server_choice(raw: str) -> ServerChoice:
    """Raises UnsafeUrl (message_fr ready to show) for an unusable address."""
    url = server_url.normalize(raw)
    return ServerChoice(url, not server_url.is_known(url))


def server_options() -> List[Tuple[str, Optional[str]]]:
    """Combo entries as (label, url); url None means the free-text entry."""
    return [(label, url) for url, label in server_url.KNOWN.items()] + [(texts.OTHER_SERVER, None)]


def initial_server(last: str) -> Tuple[int, str]:
    """(combo index, free text) to preselect from the last used server."""
    urls = list(server_url.KNOWN)
    if last in urls:
        return urls.index(last), ""
    return (len(urls), last) if last else (0, "")


def sites_for(account: Account, all_sites: Optional[List[SiteRef]]) -> List[Site]:
    """A Super Admin ("*") sees every loaded site; the active site always stays listed."""
    if "*" not in account.permissions or not all_sites:
        return list(account.sites)
    found = {s.id: Site(s.id, s.name) for s in all_sites}
    for own in account.sites:
        if own.id == account.active_site_id:
            found.setdefault(own.id, own)
    return sorted(found.values(), key=lambda s: s.name.casefold())
