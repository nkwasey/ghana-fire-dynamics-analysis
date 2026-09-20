# User guide — geo_data_prep Stage 1

This guide explains how to use the current Stage 1 pipeline and how to interpret
its outputs.

It is written against the repository as currently uploaded.

## 1. What this tool is for

`geo_data_prep` prepares canonical Stage 1 geodata and metadata for Ghana zone
and district boundaries.

At a high level, it:

1. validates a strict YAML config
2. reads zone, district, and optional AOI Shapefile inputs
3. reprojects them to the working CRS
4. optionally clips them to the AOI
5. derives deterministic identifiers and labels
6. assigns each district to one parent zone by maximum overlap share
7. writes canonical outputs plus QA, crosswalk, contract, and audit sidecars

Stage 1 is the canonical upstream contract. Downstream consumers are expected to
adapt later.

## 2. Installation

Use the provided environment file.

```bash
conda env update -n geo_data_prep -f environment.yml --prune
conda activate geo_data_prep
python -m pip install -e .
```

Sanity checks:

```bash
pytest -q
python -m geo_data_prep --help
geo-prep --help
```

## 3. The two main CLI commands

## 3.1 Validate a config

```bash
geo-prep validate --config configs/example_acz.yaml
```

This command:

- parses the YAML
- enforces the strict schema
- resolves repo-relative paths
- checks that required input files exist
- prints key settings, area policy, contract metadata, and QA thresholds

It does **not** process data and does **not** write outputs.

## 3.2 Run the full Stage 1 pipeline

```bash
geo-prep run --config configs/example_acz.yaml --run-id example_acz
```

This command writes outputs under:

```text
<outputs.out_dir>/<run_id>/
```

If `--run-id` is omitted, the runtime uses a UTC timestamp.

## 3.3 Print the installed package version

```bash
geo-prep version
```

## 4. Bundled example configs

The repository includes example configs for the bundled Ghana workflows:

- `configs/example.yaml`
- `configs/example_acz.yaml`
- `configs/example_aez.yaml`

Examples:

```bash
geo-prep validate --config configs/example.yaml
geo-prep validate --config configs/example_acz.yaml
geo-prep validate --config configs/example_aez.yaml
```

```bash
geo-prep run --config configs/example.yaml --run-id example
geo-prep run --config configs/example_acz.yaml --run-id example_acz
geo-prep run --config configs/example_aez.yaml --run-id example_aez
```

## 5. Config structure

The current config sections are:

- `schema_version`
- `inputs`
- `levels`
- `crs`
- `outputs`
- `derivations`
- `area_policy`
- `qa`
- `contract`

All configured paths must be relative to the repo root.

## 5.1 Inputs

`inputs.zones` and `inputs.districts` require:

- `path`
- `label_field`

`inputs.aoi` supports:

- `enabled`
- `path` when enabled is `true`

Current input support is Shapefile only.

## 5.2 Levels

`levels.zone.level` is the zone level label written into outputs, for example:

- `acz`
- `aez`

`levels.district.level` is typically:

- `district`

## 5.3 CRS settings

`crs.working_crs` is binding for:

- reprojection during read
- AOI clipping
- district→zone overlay
- overlap-area calculations and overlap-share denominators

`crs.plot_crs` is used only for plot outputs.

## 5.4 Area policy

`area_policy` governs reported area metadata, especially `unit_universe.csv` and
the manifests.

The config surface accepts:

- `method`: `projected`, `geodesic`, `both`
- `projected_crs`
- `geodesic_ellipsoid`
- `units`: `sq_km`, `sq_m`
- `include_method_metadata`

Current Stage 1 export contract is narrower:

- `unit_universe.csv` exposes exactly one `area_sqkm` column
- therefore Stage 1 can only faithfully export one area method in square
  kilometres
- `method: both` fails fast at runtime
- `units: sq_m` fails fast at runtime

This is deliberate contract protection.

## 5.5 QA settings

`qa.enabled` controls whether runtime assignment-threshold evaluation is written
to JSON sidecars.

The current threshold blocks are:

- `overlap_share`
- `area_relative_difference`
- `unassigned_units`
- `legacy_assignment_disagreement`
- `invalid_geometries`

`invalid_geometries` is emitted from the runtime-validated canonical geometry
layers into the shared QA payload. It remains separate from the legacy
assignment disagreement diagnostic, which has its own governed threshold
block.

The current descriptive QA diagnostic blocks are:

- `sliver_diagnostics`
- `crs_sensitivity`

Important operational point:

- fail-fast validation can stop a run
- assignment QA reports do not automatically stop output writing
- a run can therefore complete while `qa/qa_summary.json` reports `status: fail`

Interpret that as: outputs exist, but review is required.

Stage 1 release-control rule:

- do not change `unit_universe.csv` or canonical boundary schemas casually
- if those schemas change, update `contract.version`
- revalidate known downstream consumers before release, including
  `RP1_Project/merge_af_ba_panels.py`

## 5.6 Contract metadata

`contract` records:

- `stage`
- `name`
- `version`
- `canonical_upstream`
- `downstreams_adapt_later`

These values are copied into:

- `inputs_fingerprint.json`
- `outputs_manifest.json`
- `contract/stage1_contract_manifest.json`

## 6. A critical versioning distinction

Two versions matter, and they are not the same thing.

### `schema_version`
Tracks the YAML config schema.

### `contract.version`
Tracks the logical Stage 1 output contract.

These may diverge legitimately.

In the bundled example configs:

- `schema_version` remains `1.0`
- `contract.version` is set to `1.1.0`

That means:

- the YAML structure is unchanged
- the logical Stage 1 contract has been revised explicitly

## 7. The current `unit_universe.csv` contract

This is the most important Stage 1 table for many downstream users.

Fixed logical column order:

1. `unit_type`
2. `level`
3. `unit_id`
4. `unit_code`
5. `unit_name`
6. `parent_level`
7. `parent_id`
8. `parent_code`
9. `parent_name`
10. `area_sqkm`

## 7.1 Logical schema

The logical schema includes:

- `unit_code`
- `parent_code`

## 7.2 Binding spatial semantics

The following are still binding:

- `unit_id` and `parent_id` are the canonical relational keys
- `unit_code` and `parent_code` are metadata only
- canonical Shapefile schemas were not widened as part of this revision
- geometry, overlay, parent assignment and area semantics follow the governed contract

## 7.3 How to interpret the code fields

- zone rows use `unit_code = zone_code`
- zone rows leave parent fields blank
- district rows use `parent_id = zone_id`
- district rows use `parent_code = zone_code`
- district rows use `district_code` as `unit_code` only where that value exists
  upstream; otherwise `unit_code` is blank

## 7.4 A practical CSV-reading note

Blank parent cells for zone rows are written as blank cells in the CSV.

If you read the file with pandas default NA parsing, you will usually see those
blanks as `NaN`. That is a reader behaviour, not a contract change.

If you want empty strings preserved on read, use:

```python
import pandas as pd
df = pd.read_csv("unit_universe.csv", keep_default_na=False)
```

## 8. Canonical Shapefile outputs

## 8.1 Zone Shapefile

Logical fields:

- `zone_id`
- `zone_name`
- `zone_code`

## 8.2 District Shapefile

Logical fields:

- `district_id`
- `district_name`
- `district_code`
- `zone_id`
- `zone_name`
- `zone_code`
- `ovl_share`

Current physical DBF aliases:

- `district_id` → `dist_id`
- `district_name` → `dist_name`
- `district_code` → `dist_code`
- `zone_id` → `zone_id`
- `zone_name` → `zone_name`
- `zone_code` → `zone_code`
- `ovl_share` → `ovl_share`

Important nuance:

- the alias map is fixed at the logical-contract level
- a realised district Shapefile only includes `dist_code` when the upstream
  district layer already contains `district_code`

For the bundled Ghana example outputs, the realised
district Shapefiles do not contain `dist_code`, and the realised
`unit_universe.csv` district rows have blank `unit_code`, because the upstream
district layer does not expose `district_code`.

## 9. Output tree and what to inspect first

A run writes under:

```text
<out_dir>/<run_id>/
```

Core artefacts:

- `unit_universe.csv`
- `boundaries/`
- `crosswalks/`
- `qa/`
- `contract/stage1_contract_manifest.json`
- `inputs_fingerprint.json`
- `outputs_manifest.json`

Optional artefacts:

- `splits/`
- `plots/`

Recommended reading order for audit:

1. `outputs_manifest.json`
2. `contract/stage1_contract_manifest.json`
3. `unit_universe.csv`
4. `crosswalks/shapefile_field_crosswalk.json`
5. `qa/qa_summary.json`
6. `qa/district_zone_overlap.csv`

## 10. How to interpret QA outputs

## 10.1 `qa/district_zone_overlap.csv`
This is the detailed diagnostic table of candidate overlaps and chosen
assignments.

`ovl_share` is written as computed for audit. The QA layer may apply a small
machine-precision tolerance when interpreting shares near 0 or 1, but it does
not rewrite the stored overlap values.

## 10.2 `qa/district_zone_overlap_summary.json`
This summarises the overlap table.

Its validator results are drawn from the same assignment-validation payload used
by `qa/runtime_assignment_validations.json` and referenced by
`qa/qa_summary.json`.

## 10.3 `qa/runtime_assignment_validations.json`
This evaluates the configured thresholds.

## 10.4 `qa/qa_summary.json`
This is the top-level QA pointer file.

A `fail` status in the QA JSON means review is required. It does not mean that
the run directory is missing or incomplete.

## 10.5 `qa/district_zone_overlap_sliver_summary.json`
This is a descriptive audit sidecar for very small overlap candidates.

It reports counts of overlap rows below configured share and area cutoffs and
includes a short list of the smallest examples. It does not impose a
sliver-specific pass/fail threshold.

## 10.6 `qa/working_crs_sensitivity_summary.json`
This records a short sensitivity study for `crs.working_crs`.

The runtime reruns max-overlap assignment under an alternative equal-area
projection and records whether district assignment identities change.

The assignment rule should be retained when the study reports no identity
changes.

## 10.7 `qa/working_crs_sensitivity_comparison.csv`
This is the district-level comparison table behind the sensitivity summary.

It records baseline and alternative assigned parents plus the absolute change in
assigned share.

## 11. Common troubleshooting

## 11.1 Config validation fails

Check that:

- the path is relative to the repo root
- `schema_version` is present
- unknown keys are not present
- AOI path is supplied when AOI is enabled

## 11.2 Read fails

Check that:

- `.shp`, `.dbf`, `.shx`, and `.prj` all exist
- the layer CRS is defined
- the label field exists
- the geometry type is Polygon or MultiPolygon

## 11.3 Runtime fails while building `unit_universe.csv`

The common current causes are:

- `area_policy.method: both`
- `area_policy.units: sq_m`

These fail because the fixed canonical Stage 1 schema exposes only one
`area_sqkm` column.

## 11.4 Run completes but QA status is fail

Inspect:

- `qa/qa_summary.json`
- `qa/district_zone_overlap_summary.json`
- `qa/district_zone_overlap_metrics.csv`
- `qa/district_zone_overlap_issues.csv`
- `qa/district_zone_overlap_sliver_summary.json`
- `qa/working_crs_sensitivity_summary.json`

That is normal current behaviour when threshold review is required.

## 12. Recommended operating pattern

1. validate the config
2. run with a clear `run_id`
3. inspect `outputs_manifest.json`
4. inspect `contract/stage1_contract_manifest.json`
5. inspect `unit_universe.csv`
6. inspect `qa/qa_summary.json`
7. inspect the detailed overlap sidecars if QA requires review

## 13. What this guide does not assume

This guide does not assume:

- GeoPackage input support
- automatic derivation of missing district codes
- widened canonical Shapefile schemas
- that a QA `fail` status blocks output writing

Those behaviours are not demonstrated by the uploaded code and tests and are not
part of the current documented contract.
