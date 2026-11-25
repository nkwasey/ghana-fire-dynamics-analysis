# Local testing

Use the shared RP1 `rp_ghana_fire` conda environment with a supported Python version. Activate it and install this subproject into the intended RP1 checkout as shown in README.md. The commands below use the activated environment's Python and `geo-prep` entry point. Confirm the active interpreter and package location before testing.

## Automated checks

From the `geo_data_prep` directory, run:

```bash
python -m pytest
```

Tests create analytic projected polygons and isolated temporary files. They do not need existing output runs, stored acceptance reports or an RP1 installation. Tests cover known overlap shares, deterministic ties, gaps and overlapping reference zones, multiple features per zone, boundary touches, missing CRS, invalid geometry, duplicate identifiers, leading-zero keys, source immutability, whole-district preservation, dissolve and serialization, output schemas and hashes, failed-run cleanup, interruption, no overwrite and relocated CLI operation. A small non-Ghana example prevents study counts from becoming processing assumptions.

Configuration tests cover unsupported and duplicate YAML keys, incorrect value types, changes while parsing or reading, ambiguous multilayer sources, and platform-aliased identifiers. Geometry tests reject loss of collinear vertices during serialization. Identity tests retain the `(level, unit_id)` relational key when local identifiers repeat across levels.

Export tests reject invalid geographic transformations and nonportable run IDs. They also parse generated GeoJSON with strict finite-number checks and verify that a failed run is not published.

Plot tests cover stable alphabetical numbering, a dense 110-district layout, multipart districts, holes and duplicate names. They independently check padded number rectangles against district polygons and other numbers in the same panel. A tiny district exercises detail-panel fallback. They also verify PNG/PDF creation, complete name keys, clipping checks and output manifests.

Pytest uses its temporary-directory facilities for generated test data. Python and pytest can create ignored bytecode and cache directories locally. No generated files are needed in the distributed repository.

If native Windows reports missing files during writes under a deeply nested temporary path, choose a short, dedicated, unused temporary path. For example, in PowerShell:

```powershell
python -m pytest --basetemp "$env:LOCALAPPDATA\Temp\rp1-geo-tests"
```

## Validate supplied inputs

```bash
geo-prep validate --config configs/example_acz.yaml
geo-prep validate --config configs/example_ecological.yaml
```

Validation reads the inputs, calculates assignments and prints QA without creating an analytical output run. Review the returned status and warnings. `WARN` can accompany exit code zero because structural success and source-data qualifications are separate.

Read the climatic profile's realised unit counts, uncovered areas, overlap shares and assignment margins from its validation output. Apply the configured thresholds to those observations; no stored district count or QA report is an acceptance authority. A numerical gap tolerance reports geometry differences and does not authorize trimming or moving districts.

The ecological configuration is an additional functional example. Review its own reference coverage, overlaps and assignment margins independently. Structural success does not establish one reference profile as scientifically interchangeable with another.

## Generate and inspect a local run

```bash
geo-prep run --config configs/example_acz.yaml --run-id local_acz
```

This creates `out/local_acz/`. Use a new run ID for another run. Inspect the following files in that completed run:

| Generated path | Review |
|---|---|
| `qa/qa_summary.json` | Counts, source warnings and structural checks |
| `qa/reference_coverage.csv` | Reference gaps and coverage shares |
| `crosswalks/district_zone_crosswalk.csv` | Selected zone, reference overlap and assignment margin |
| `qa/constructed_hierarchy.csv` | Exact parent union and whole-district containment |
| `qa/analysis_hierarchy.csv` | Projected parent union and whole-district containment when `crs.analysis` is configured |
| `boundaries/` | Original source-CRS district and constructed zone shapefile bundles |
| `analysis_boundaries/` | Optional projected district and zone bundles when `crs.analysis` is configured |
| `unit_universe.csv` | Unit keys, parent relationships and projected areas |
| `plots/per_zone/` | Numbered maps, district-name keys and placement inventories |
| `plots/district_label_checks.json` | Measured number and name-key checks |
| `inputs_fingerprint.json`, `environment.json` | Source identities, selected layers and runtime versions |
| `outputs_manifest.json` | File sizes and SHA-256 hashes |

To test the ecological profile, run its configuration with a separate ID such as `local_ecological` and review its own QA. The `out/` directory is ignored by Git and is created by processing; it is not shipped in the project ZIP.

## Dependencies and scope

`pyproject.toml` defines supported dependency ranges. `requirements-tested.txt` records a standalone test environment snapshot; it is not a complete cross-platform lockfile or a recipe for the shared RP1 environment. Some snapshot pins can conflict with the parent project's environment constraints. Do not replace or upgrade packages in the shared environment merely to reproduce that snapshot. Check compatibility with the RP1 environment requirements before making dependency changes.

Repeat the tests when changing Python, geospatial/native libraries, configuration or source data. Each completed run records its actual environment and fingerprints. The input component inventory is `data/inputs_manifest.json`; it records file identity, not ground accuracy or redistribution permission.

The supported processing interfaces are `geo_data_prep.pipeline.validate(config_path)`, `geo_data_prep.pipeline.run(config_path, run_id)` and the `geo-prep` CLI. RP1 integration requires a deliberately selected completed run; follow integration.md. This test procedure does not execute live GEE exports, full FIRMS preprocessing, AF/BA merging, SaTScan or statistical models. Native Windows behavior should be checked locally; Linux/WSL execution alone does not establish that result.
