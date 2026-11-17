def classFactory(iface):
    from .plugin import EldaPlugin

    return EldaPlugin(iface)
