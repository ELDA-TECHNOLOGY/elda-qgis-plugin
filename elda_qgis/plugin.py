from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .core import i18n
from .core.net.http import Caller
from .core.session.api import EldaApi
from .qgis_adapters.language import qgis_locale
from .qgis_adapters.transport import QgisTransport
from .ui.main_dialog import MainDialog

ICON = Path(__file__).parent / "resources" / "icon.svg"


class EldaPlugin:
    def __init__(self, iface):
        self.iface = iface
        # every module is imported by now and no window exists yet: the texts can switch language
        i18n.use(i18n.language_for(qgis_locale()))
        self.action = None
        self.dialog = None

    def initGui(self):
        self.action = QAction(QIcon(str(ICON)), "ELDA", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dialog is not None:
            self.dialog.shutdown()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        # one window for the whole session so the login survives closing it
        if self.dialog is None:
            self.dialog = MainDialog(self.iface, lambda server: EldaApi(server, Caller(QgisTransport())))
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
