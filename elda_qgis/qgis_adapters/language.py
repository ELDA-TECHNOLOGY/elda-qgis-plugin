"""The language QGIS itself runs in: the plugin follows it instead of asking."""
from qgis.core import QgsApplication, QgsSettings


def qgis_locale() -> str:
    """Something like "fr", "es_ES" or "en_US"; empty when QGIS does not say."""
    try:
        return QgsApplication.locale() or ""
    except AttributeError:
        # older builds: the same choice, as stored by the options dialog
        return str(QgsSettings().value("locale/userLocale", "") or "")
