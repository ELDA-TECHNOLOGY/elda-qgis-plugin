# ELDA QGIS plugin

[![Tests](https://github.com/ELDA-TECHNOLOGY/elda-qgis-plugin/actions/workflows/tests.yml/badge.svg)](https://github.com/ELDA-TECHNOLOGY/elda-qgis-plugin/actions/workflows/tests.yml)
[![Licence: GPL v2+](https://img.shields.io/badge/licence-GPL--2.0--or--later-blue.svg)](LICENSE)

Publish layers from a QGIS project to the ELDA platform, without leaving QGIS.

The plugin is a client of the ELDA API: it needs an ELDA account and does nothing without one.
It is in beta and flagged experimental in QGIS.

## What it does

- Log in to ELDA, pick a site, and see what your account is allowed to publish.
- Publish vector layers: choose the destination folder and who can see the layer, then follow the upload and the processing.
- Detect a layer with the same name already present in the destination folder, and either replace its content or create a new layer.
- Optionally carry the QGIS symbology over: single symbol, categorized, graduated and simple labels.
- Available in French, English and Spanish: the plugin follows the language of QGIS.
- Publish GeoTIFF rasters (terrain models, orthophotos); each file is checked before it is sent, with the fix spelled out when ELDA would refuse it.

## Install

Requires QGIS 3.34 or later.

1. Download `elda_qgis-<version>.zip` from the [latest release](https://github.com/ELDA-TECHNOLOGY/elda-qgis-plugin/releases). Each release also carries the SHA-256 of its zip.
2. In QGIS: Plugins > Manage and Install Plugins > Install from ZIP.
3. Enable "ELDA", then click the ELDA button in the toolbar.

Only install a zip that comes from this repository's releases.

## Security

- Passwords are stored only if you ask for it, in the QGIS authentication database, protected by its master password.
- Session tokens stay in memory and are never written to disk, to QGIS settings or to the log.
- Requests go to the server you logged in to, over HTTPS only; redirects and certificate errors are refused.
- Files are uploaded straight to storage through short-lived signed addresses that carry no ELDA credential.

The QGIS network logger (debugging tools) records request headers and bodies, password and token included, as soon as it is open: keep it closed while logging in.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Development

    make venv    # once: create .venv and install the development tools
    make test    # run the test suite
    make zip     # build dist/elda_qgis-<version>.zip and its .sha256
    make link    # symlink the plugin into the local QGIS profile

Anything after `--` goes to pytest: `make test -- -k upload -x`.

The development tools are never shipped: the plugin depends on nothing but Python and QGIS.
Without `make` (Windows): `.venv\Scripts\python -m pytest`, `python scripts/package.py`, `python scripts/link_dev.py`.

After `make link`, restart QGIS and enable "ELDA" in Plugins > Manage and Install Plugins.

### Layout

    elda_qgis/
      core/            pure Python, no QGIS import: tested outside QGIS
        net/           HTTP calls, server address checks, secret redaction
        session/       login, tokens, account and rights
        publish/       upload, publishing flow, status polling
        style/         QGIS symbology to ELDA style
        i18n.py        languages: French is the source, looked up by its wording
      locales/         English and Spanish wording of every text
      qgis_adapters/   everything that touches QGIS: network, credentials, export, layers
      ui/              windows; their decisions live in pure modules next to them

QGIS's Python cannot run in a terminal, so the code under `core/` and the pure UI modules carry the tests, and static checks cover the rest (imports resolve, no undefined name).

### Adapting to another backend

The plugin speaks the ELDA API, not a generic protocol. Every call to it lives in two files, `core/session/api.py` and `core/publish/gis.py`; the windows, the export and the upload do not depend on the API shape. A fork for another server rewrites those two files.

## Licence

GPL-2.0-or-later, like QGIS itself. See [LICENSE](LICENSE).
