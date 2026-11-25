# Geography handoff

See [source geography admission](SOURCE_GEOGRAPHY.md) for the included study shapefiles and separately obtained FIRMS reference files.

The geography handoff prepares the district and zone files required by the FIRMS preparation and analysis subprojects from one completed `geo_data_prep` run. It verifies the source run manifest and hashes, crosswalk and parent identities, CRS, spatial identities, valid geometries, and district-to-zone unions. Projected districts must have no pairwise overlap above the run's recorded numerical area tolerance. Their coordinates must also agree with a transformation of the native districts within a 0.0001-metre numerical tolerance. It stages files and records their hashes without running active-fire preparation, Earth Engine, the merger or the statistical analyses.

The supplied climatic configuration retains source-CRS boundaries within the geography run and constructs EPSG:32630 district and zone bundles. The handoff delivers these same projected bundles to FIRMS and analysis. The national `gha_admin0` source is a separately configured input. The workflow packages its EPSG:32630 derivative for GEE upload and FIRMS land-mask use after confirming that both refer to the configured national source.

The c3 GEE upload bundle uses schema `rp1-gee-c3-upload-bundle-v2` and contains
exactly three combined layers: `gha_admin0`, `acz`, and `districts_within_acz`.
Upload the three ZIPs as table assets and set `C3.ghanaAsset`, `C3.zoneAsset`, and
`C3.districtAsset` using `asset_name_mapping.csv`. No per-zone split assets are
required by c3.
The EPSG:32630 vector delivery does not replace the native MODIS sinusoidal
raster grid. Local identity/union/ZIP checks establish the retained local
delivery identities. The workflow uses a manual GEE upload and export handoff;
it does not require Python to connect to GEE and verify asset content on each
local run. Retain the selected asset identifiers and operator handoff record
with the c3 export delivery. Such a record does not independently certify
remote geometry or native-grid centre equivalence.

## Manual GEE upload and export handoff

For a new replication delivery, run the configured `geo` workflow with a fresh
run ID. Its `out/workflows/<run_id>/gee_upload/` directory contains the three
upload bundles and `asset_name_mapping.csv`.

1. Upload the generated `gha_admin0`, `acz` and `districts_within_acz` ZIPs as
   GEE table assets. Use the generated combined layers; no per-zone split asset
   is required. Use distinct asset names for a new geography delivery so an
   archived delivery's assets are not silently replaced.
2. Record the completed upload identifiers. In both pinned c3 applications,
   set `C3.ghanaAsset`, `C3.zoneAsset` and `C3.districtAsset` from
   `asset_name_mapping.csv` and those uploaded identifiers.
3. Run the pinned exporter for the selected study configuration. Its existing
   source-count and native-projection checks remain active. Download the
   original analytical CSVs and retain export/task identifiers where available.
4. Admit those retained CSVs through the local c3 preparation and merger route.
   Subsequent local processing reuses the recorded files, source lock and
   receipts; it does not repeat a remote asset-content check.

Keep a small operator-declared handoff record outside the source tree with the
following fields. A table or JSON record is sufficient; this is a manual
provenance declaration, not an automated remote-verification result.

| Record item | Content to retain |
|---|---|
| Geography identity | Run ID, configuration identity and local handoff/upload manifest hashes |
| Uploaded bundles | The three layer names, original filenames and SHA-256 hashes |
| Remote identifiers | The three GEE asset identifiers; version/creation information where available |
| Pinned applications | Viewer/exporter source versions or hashes and their configured asset references |
| Operator declaration | Upload completion date/time and confirmation that the recorded bundles were uploaded |
| Export delivery | Study/export selection, export/task IDs where available, download location and c3 admission identity |

The current GEE `c3Units` function applies `buffer(0,1)` to each reporting unit
and intersects it with the national geometry buffered with the same settings.
This GEE selection behavior is retained. The local component's whole-district
assignment and the GEE reduction geometry are separate documented steps;
uploading the generated polygons does not remove that transformation.

Record upload evidence with the delivery and preserve the declaration as made.
Independent remote-geometry and native-raster comparisons require separately
recorded observations.

From the repository root with the shared environment active:

```bash
conda activate rp_ghana_fire
python -m geo_data_prep validate --config geo_data_prep/configs/example_acz.yaml
python -m geo_data_prep run --config geo_data_prep/configs/example_acz.yaml --run-id example_acz
python tools/stage_geo_handoff.py build --run geo_data_prep/out/example_acz --bundle out/handoffs/example_acz
```

A completed run with warnings may still pass structural checks. Inspect its `qa/qa_summary.json` and `qa/reference_coverage.csv`; decide whether the reference geography is scientifically suitable for the intended study. The tool will reject input files whose recorded hashes, CRS, keys or geometry checks fail. It requires the analysis derivative to use EPSG:32630 for the current analysis geometry contract.

The bundle has the same relative paths as the destinations:

| Run artifact | Project destination |
|---|---|
| `unit_universe.csv` | `RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv` |
| `analysis_boundaries/acz.*` | `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/acz.*` |
| `analysis_boundaries/districts_within_acz.*` | `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/districts_within_acz.*` |
| `analysis_boundaries/acz.*` | `RP1_Project/rp1_analysis/data/geo/acz.*` |
| `analysis_boundaries/districts_within_acz.*` | `RP1_Project/rp1_analysis/data/geo/districts_within_acz.*` |
| `crosswalks/district_to_acz_max_overlap.csv` and `.provenance.json` | `RP1_Project/rp1_analysis/data/reference/` |

Each shapefile bundle includes `.shp`, `.shx`, `.dbf`, `.prj`, and `.cpg`. `handoff_manifest.json` records source run identity, the Stage 1 output manifest hash, QA status, target paths and per-file hashes.

## Applying to a project copy

An active-fire source update can reuse the current handoff when its original
source run, input fingerprint, configuration, output/contract authorities and
staged target hashes still verify. From the repository root, with the four
local packages installed in the shared environment:

```bash
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study geo-reuse
```

This is a read-only check of the existing geography and its original generation
evidence. It records a new workflow receipt while retaining the original source
run and QA status; it does not recompute boundaries, rewrite data or claim that
old files were generated under `archive_study`. It creates no new GEE assets or
upload bundle. `gee-inputs` rejects this reused-geography route; generate a fresh
`geo` run if a new upload bundle is required.

Use the same configuration/run ID for `archive`, `archive-admit` and `firms`.
The new Archive admission separately checks compatibility of the pinned upstream
country/source-population geography and current RP1 district/parent mapping.
RP1 retains authority for analytical spatial assignment. These checks do not
assert identical reporting geometries or qualify remote GEE assets. See the
[Archive integration guide](FIRMS_ARCHIVE_INTEGRATION.md).

The following apply/replace operations are for preparing a new handoff.

For a project whose handoff target files are all absent, apply the bundle using:

```bash
python tools/stage_geo_handoff.py apply --bundle out/handoffs/example_acz --project-root .
```

The default preflights every destination and refuses to overwrite any existing file. For a working project with existing target files, explicitly supply a **new** backup directory and request replacement:

```bash
python tools/stage_geo_handoff.py apply --bundle out/handoffs/example_acz --project-root . --replace --backup out/handoff_backups/example_acz
```

This option first copies and hash-verifies the existing handoff target files in the backup directory, records which targets were originally absent, and stages all new bytes. It verifies every target again before replacing files. On an ordinary failure it attempts rollback from the backup; the backup remains available. Work on a copy and avoid concurrent writers. File changes across several directories are not one filesystem transaction: abrupt process termination or a machine failure may require restoring from the backup manifest manually.

The tool writes `RP1_Project/geo_handoff_manifest.json` after the other files; it does not change `gha_admin0.*`, `combined_manifest.json`, `rp1_analysis/data/input_sha256.json`, panel inputs, or analytical results. Consequently, existing hash inventories and panel manifests may no longer match the newly staged geography. Do not rewrite them to claim those inputs were regenerated. Create and validate a separately governed input manifest for a new analysis run under the project policy.

## Before downstream use

1. Review the Stage 1 warnings, provenance and intended boundary vintage. The `handoff_eligible` flag establishes structural checks only.
2. Confirm the configured FIRMS polygons and national-source land mask represent the intended geography. The workflow uses the projected national AOI from its verified GEE upload bundle. The production profile is `RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml`; example configurations can reference different input names and fields.
3. For a new replication, upload the generated geography and retain the manual handoff record, configured GEE geometry rule and export identities described above. Keep the BA delivery and FIRMS assignment geographies consistent with that declared procedure. When the geography or export selection actually changes, prepare a new identified delivery. Recurring Python-to-GEE asset verification and a new independent geometry-validation campaign are not required local execution gates. Record any unresolved remote-content limitations with the delivery.
4. Run the relevant downstream loaders and geometry/identity validators, then use the intended merger profile to generate a new output with provenance. The merger normally reads the selected Stage 1 run's `unit_universe.csv`; configure that source consistently with the staged universe.
5. Review and govern the resulting panel and model inputs before analysis. Staging the geometry is not a publication, analytical or scientific validity approval.
