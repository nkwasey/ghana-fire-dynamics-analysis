# RP1 burned-area viewer and monthly CSV exporter

These standalone Google Earth Engine (GEE) applications support visualization and extraction of Ghana's monthly burned-area data:

- `scripts/01_ghana_viewer_c3.js` displays Ghana and supports ACZ and district inspection, burned-area and land-cover diagnostics, and MOD11A1 land-surface temperature (LST) raster exports.
- `scripts/02_monthly_csv_exporter_c3.js` exports one 69-column extended CSV per reporting scope and year. It supports ACZ and district tables for the BA2001 and BA2012 fixed-union domains.

Each script includes the same scientific core and can be pasted into the GEE Code Editor without a module import. The Ghana map is a visual and raster scope; it does not generate a national analytical reporting row. The `src/` files and `build.py` maintain and regenerate the standalone scripts.

## Configure the scripts

1. In each script, review the `C3` settings. Set `ghanaAsset`, `zoneAsset`, and `districtAsset` to the intended accessible asset IDs and use consistent values between scripts. The viewer's `driveFolder` controls its outputs; the exporter uses the domain folder function in its configuration.
2. The zone asset requires `zone_id`, `zone_code`, and `zone_name`; the district asset requires `dist_id`, `dist_name`, `zone_id`, `zone_code`, and `zone_name`. District `dist_code` is optional. IDs must be unique and zone assignments valid.
3. Verify project/account access to the configured assets, MODIS collections, and intended Drive destination. Keep the affine grid, union periods, eligibility classes and QA rules aligned with the study method. See `METHOD_AND_OUTPUT_NOTES.md`.
4. Open a standalone script in the Code Editor and run it. No exports are created at initialization. Task creation adds a definition to the Tasks tab; inspect and start each intended task manually.

## Viewer operation

Choose BA2001 or BA2012, the date and visual scope (`ghana`, `acz` or `district`) in Controls. Use **Load district names for selected ACZ** when selecting a district by name. **Inspect selected month** checks sources and prepares evidence layers. Use the Layers tab, the map layer control and legend to inspect boundaries, eligibility, QA and evidence. The accepted-pixel layer is evidence and does not certify a unit–month result; inspect its row status.

The Exports tab provides BA and LST monthly and yearly raster tasks, selected-year LC/LW and union/annual eligibility rasters, and a selected-unit monthly CSV. A standard monthly bundle has BA and LST tasks; the annual standard bundle has 12 BA, 12 LST and one LC/LW task. Inspect the matching plan before creating a standard bundle. Domain diagnostics and unit CSV are separate. With Ghana selected, CSV output is unavailable because no national reporting row is defined; select an ACZ or district.

The viewer does not perform the exporter's full unfiltered boundary inventory and nonzero Ghana-clipped geometry preflight. Its CSV action also lacks the exporter's session-level duplicate-prefix block. Raster prefix reuse produces a warning, not a block. Check selected units, geometry and prior Tasks and Drive outputs before using viewer exports; source admission alone does not establish boundary equivalence.

## Monthly CSV exporter operation

1. Choose the fixed-union domain, reporting level, one ACZ or all ACZs, and an optional district filter. The filter applies to preview and export; it requires one selected ACZ.
2. Choose a preview month and an export year mode: selected year, bounded range or full domain. Choosing fewer output years does not change the fixed-union period.
3. **Inspect selected-month preview** checks inputs and reports the selected rows. The selected-month CSV action uses the preview ACZ; a blank district filter selects that zone's districts.
4. Open Exports and choose **Inspect export plan (no tasks)**. Review its scope, period, output folder, prefixes and count in the panel and Console. If settings change, inspect the plan again before creating tasks.
5. Choose **Create planned annual CSV tasks**. After identity, clipped vector-area, source and grid metadata checks pass, each annual analytical task writes one extended table. The BA BurnDate and QA projections are compared with the configured grid; annual LC/LW projection metadata are required and reported, but are not compared for equality with the BA grid. Start the intended tasks manually and retain task receipts.
6. To record the optional district unit-inventory QA receipt, enable **Also create district unit-inventory QA receipt(s)** before inspecting the plan. It is off by default. If a zero clipped-area issue blocks an action, the separate boundary exception record can be created from the Exports tab. It records that condition only and does not imply units were dropped.

Source preflight checks each requested BA month and every required annual land-cover source. Full-period plans can require hundreds of sequential metadata calls; begin with one year or a bounded range. Task creation is not transactional: if creation stops partway, inspect the Tasks tab and the Console's created-prefix list before retrying. Session duplicate checks cannot see files or tasks from earlier sessions.

The annual district and operational task names use the compact convention in `docs/EXPORT_LAYOUT.md`. An 80-character project-local guard is not a documented Earth Engine maximum. If a dialog rejects a description, verify the Drive folder and filename prefix, record the task ID and name, and inspect Tasks and Drive before retrying. See `VERIFICATION.md`.

## CSV output and interpretation

Each extended CSV has 69 columns and one row per unit and month. The ordered fields define the analytical export contract; matching names in other datasets do not establish equivalent methods or missing-value semantics. `ba_*` columns provide the study domain, status, source, grid, evidence, anomaly and other diagnostics. See `docs/CSV_DICTIONARY.md`. The key is `(ba_domain, level, unit_id, yyyymm)`; `run_id` alone is not a guaranteed unique key.

The BA2001 and BA2012 fixed unions are distinct and are used for numerator and primary denominator. Unaccepted evidence contributes zero to the primary numerator under the study scenario unless a higher-priority guard withholds the primary result. Unknown evidence is not proof of physical absence of fire. Consult `ba_status`, `ba_coverage_status` and the reason fields. A blank numerical value is undefined or withheld; do not fill it with zero without a separately justified rule. A zero union is a resolved empty-domain result, not proof that the entire district had no fire.

The annual ratio uses the fixed-union numerator and annual eligible denominator and can exceed one. It is not a proportion of annual-domain land burned. Evidence-state areas partition the known union; reason areas overlap. `ba_supported_fraction` is restricted to qualifying supported evidence and is not overall observation coverage.

## Exports and further information

For separate annual ACZ files, select `acz`, `Selected ACZ`, and each of the five zones in turn. The ACZ `All ACZs` selection remains available and creates one combined annual ACZ table. All-zone district output creates one annual file per ACZ, not one national district table. With separate ACZ files and one district file per zone, BA2001 has 120 ACZ and 120 district files and BA2012 has 65 of each: 370 analytical CSVs total. This assumes a blank district filter and excludes optional operational records. See `docs/EXPORT_LAYOUT.md` for filenames, task counts and operational-record fields. A blocked action can leave no analytical row in which to record a source or boundary failure.

Admit the annual exports through the project's c3 consolidator and verify the resulting merger handoff before analysis.

Use `python tests/run_offline.py` from the package root for local checks (Python 3 and Node.js required). Its deterministic build check uses a temporary copy. Check an extended CSV with `python tools/check_extended_csv.py FILE.csv`; use `--compare OTHER.csv` for matched outputs. Retain evidence for each new research run separately. See `VERIFICATION.md` and `docs/SOURCE_REPRESENTATION_AND_SENSITIVITY.md` for further checks.
