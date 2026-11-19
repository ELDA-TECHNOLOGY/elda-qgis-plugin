# Changelog

## 0.8.0 (beta)

- The plugin follows the language of QGIS: French, Spanish, and English for any other language.
- Messages written by the ELDA server itself stay in French.

## 0.7.6 (beta)

- Publish GeoTIFF rasters: terrain and surface models, colour and infrared orthophotos, with the type chosen per layer.
- Check a raster before sending it (GeoTIFF on disk, coordinate system in the file, data type expected by ELDA) and explain how to fix it.
- Detect a raster with the same name already present in the destination folder.
- Refuse a layer that has no feature at all.
- "Check all" box above the layer table.
- Failures stand out in red, in the table and in the summary; the summary scrolls when the window is small.
- The status column keeps a fixed width.

## 0.6.2 (beta)

First public release.

- Log in to ELDA, choose a site, see the publishing rights of the account.
- Publish vector layers with a destination folder and a visibility, with progress and cancellation.
- Detect an existing layer with the same name and replace its content, or create a new layer.
- Optional conversion of the QGIS symbology: single symbol, categorized, graduated, simple labels.
- Refuses to publish a layer whose features QGIS cannot read.
