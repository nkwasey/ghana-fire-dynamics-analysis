# c3 burned-area source

`rp1_gee_ba_scripts/c3/` is the pinned operational source. Its shared `src/`
core and `build.py` generate the viewer, monthly exporter and synthetic fixture.
Run `python tests/run_offline.py` from that directory with Python 3 and Node.js.
The canonical source-qualification environment declares Node.js 24. These local
checks do not run Earth Engine or qualify the full study delivery.

The exporter writes one 69-field `rp1_ba_c3_extended_v2` table per year, level and
selected zone. Use separate ACZ and district files for CZ, FZ, GS, SS and TZ,
with names such as `rp1_ba_district_monthly_c3_TZ_BA2012_2024_ext.csv`. The full
BA2001 (2001–2024) and BA2012 (2012–2024) delivery has 370 analytical files.
There is no required base/extended pair. Keep downloads under
`rp1_gee_ba_scripts/downloads/c3_release/` and preserve original bytes.

Upload the three combined geography layers and configure `C3.ghanaAsset`,
`C3.zoneAsset`, and `C3.districtAsset`. The vector CRS is EPSG:32630; reductions
retain the declared MODIS native grid. Asset paths do not freeze asset content.

`UPSTREAM_IDENTITY.json` records upstream source hashes and documented local
adaptations. Checker tests use synthetic records, so the source distribution
does not require prior research outputs. The c3 CSV
dictionary and methods notes define guarded nulls, scenario zeros, shortened
positives and the annual mixed-domain ratio; downstream preparation must retain
all evidence and admit the complete requested inventory before merging.
