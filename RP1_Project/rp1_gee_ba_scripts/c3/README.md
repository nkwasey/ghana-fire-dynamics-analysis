# Ghana burned-area extraction

This package provides the burned-area viewer and annual export method.
Use `scripts/01_ghana_viewer_c3.js` and `scripts/02_monthly_csv_exporter_c3.js`.
Configure `C3.ghanaAsset`, `C3.zoneAsset` and `C3.districtAsset` from the approved
three-layer geography upload bundle. The vector CRS is EPSG:32630; the raster
reducer keeps the declared native MODIS grid.

Run `python tests/run_offline.py` here with Python 3 and Node.js. The runner
builds in a temporary directory and verifies checked-in generated products.
`build.py` regenerates those products from the single shared `src` authority.
Run `python tools/check_extended_csv.py FILE.csv` for structural/arithmetic CSV
checks; full delivery, geography and lineage admission belongs to the analysis
preparer. Separate annual ACZ and district files use all 69 extended fields.

`UPSTREAM_IDENTITY.json` records source identities and implementation hashes.
Checker tests use synthetic records. The original Earth Engine export inputs
are in `downloads/c3_release/` beside this source directory.

Keep operational CSV downloads outside this pinned tree, in the parent
`downloads/c3_release/`, and generated bundles/results under the workspace `out/`.

The configured observation period is 2001–2024, with BA2012 observations starting
in 2012. BA2001 and BA2012 use fixed land-cover eligibility unions for 2001–2024
and 2012–2024 respectively. Selecting or extending observation years does not
change these unions. See [observation-period configuration](docs/OBSERVATION_PERIOD.md)
for complete-source requirements and the additional annual-source evidence
required when observing a year outside a fixed union period.
