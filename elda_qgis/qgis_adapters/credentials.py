"""One Basic auth config per server in the QGIS auth manager; the password never reaches QgsSettings.

load() and save() may prompt for the master password: call them from the GUI thread only.
"""
from __future__ import annotations

from typing import Optional, Tuple

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from ..core.session.keys import settings_key

_PREFIX = "elda/auth/"


def _key(server_url: str) -> str:
    return _PREFIX + settings_key(server_url)


def _unlocked_manager():
    manager = QgsApplication.authManager()
    if manager is None or manager.isDisabled():
        return None
    # Tries the keychain, then prompts the user
    if not manager.masterPasswordIsSet() and not manager.setMasterPassword(True):
        return None
    return manager


def _first(result):
    return result[0] if isinstance(result, tuple) else result


def save(server_url: str, username: str, password: str) -> bool:
    manager = _unlocked_manager()
    if manager is None:
        return False
    settings = QgsSettings()
    config = QgsAuthMethodConfig("Basic")
    config_id = settings.value(_key(server_url), "")
    existing = False
    if config_id:
        res = manager.loadAuthenticationConfig(config_id, config, True)
        existing = bool(_first(res))
        if isinstance(res, tuple):
            config = res[1] if len(res) > 1 and res[1] is not None else config
    config.setName("ELDA " + server_url)
    # tie the entry to its server so it is not offered for another one
    config.setUri(server_url)
    config.setConfigMap({"username": username, "password": password, "realm": ""})
    if existing:
        ok = _first(manager.updateAuthenticationConfig(config))
    else:
        if not config.id():
            config.setId(manager.uniqueConfigId())
        ok = _first(manager.storeAuthenticationConfig(config))
    if ok:
        settings.setValue(_key(server_url), config.id())
    return bool(ok)


def load(server_url: str) -> Optional[Tuple[str, str]]:
    config_id = QgsSettings().value(_key(server_url), "")
    if not config_id:
        return None
    manager = _unlocked_manager()
    if manager is None:
        return None
    config = QgsAuthMethodConfig()
    res = manager.loadAuthenticationConfig(config_id, config, True)
    ok, config = res if isinstance(res, tuple) else (res, config)
    if not ok:
        return None
    values = config.configMap()
    if not values.get("username") or not values.get("password"):
        return None
    return values["username"], values["password"]


def forget(server_url: str) -> bool:
    """False when a stored config could not be erased; the settings key is then kept so it can be retried."""
    settings = QgsSettings()
    config_id = settings.value(_key(server_url), "")
    removed = True
    if config_id:
        manager = QgsApplication.authManager()
        removed = manager is not None and not manager.isDisabled() and bool(_first(manager.removeAuthenticationConfig(config_id)))
    if removed:
        settings.remove(_key(server_url))
    return removed
