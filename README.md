# ELDA QGIS plugin

Publish layers from a QGIS project to the ELDA platform.

Requires QGIS 3.34 or later and an ELDA account.

## Development

    make venv    # once: create .venv and install the development tools
    make test    # run the test suite
    make zip     # build dist/elda_qgis-<version>.zip and its .sha256
    make link    # symlink the plugin into the local QGIS profile

Anything after `--` goes to pytest: `make test -- -k upload -x`.

The development tools are never shipped: the plugin depends on nothing but Python and QGIS.
Without `make` (Windows): `.venv\Scripts\python -m pytest`, `python scripts/package.py`, `python scripts/link_dev.py`.

After `make link`, restart QGIS and enable "ELDA" in Plugins > Manage and Install Plugins.

## Privacy

The QGIS network logger (debugging tools) records request headers and bodies, password and token included, as soon as it is open: keep it closed while logging in.

## Licence

GPL-2.0-or-later, like QGIS itself. See [LICENSE](LICENSE).
