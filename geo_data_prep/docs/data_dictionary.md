# Data dictionary — geo_data_prep Stage 1

This document defines the current user-visible Stage 1 data contract and its
supporting sidecars.

It covers:

- canonical concepts and derivations
- the output tree
- per-file schemas
- current runtime nuances that affect realised outputs

## 1. Contract principles

Stage 1 is the canonical upstream contract.

The project therefore separates:

- **canonical lean outputs**
  - `unit_universe.csv`
  - zone and district Shapefiles
- **rich sidecars**
  - QA tables and JSON summaries
  - crosswalks
  - contract manifest
  - input and output manifests

The widened `unit_universe.csv` schema is explicit and documented. The project
does not treat it as a silent change.

## 2. Core derived concepts

## 2.1 Zone identifiers

### `zone_id`
Deterministic lower snake_case identifier derived from the configured zone label
field.

Example:

- `Coastal Zone` → `coastal_zone`

### `zone_name`
Deterministic upper-case canonical zone label.

Example:

- `Coastal Zone` → `COASTAL ZONE`

### `zone_code`
Deterministic zone code.

Priority:

1. mapping-first (`derivations.zone_code.mapping`)
2. fallback initials with deterministic collision handling

Examples for the bundled ACZ workflow:

- `Coastal Zone` → `CZ`
- `Forest Zone` → `FZ`
- `Guinea Savannah` → `GS`
- `Sudan Savannah` → `SS`
- `Transition Zone` → `TZ`

## 2.2 District identifiers

### `district_id`
Deterministic title-token identifier derived from the configured district label
field.

Example:

- `Ablekuma Central Municipal` → `Ablekuma_Central_Municipal`

### `district_name`
Deterministic upper-case canonical district label.

### `district_code`
Optional upstream field.

Current runtime behaviour:

- preserved only when already present in the district input layer
- not derived by Stage 1 when missing

## 2.3 Parent-link semantics

### `parent_id`
Canonical parent key written for district rows in `unit_universe.csv`.

For current Stage 1 outputs, this is the assigned `zone_id`.

### `parent_code`
Parent-owned code metadata written for district rows in `unit_universe.csv`.

For current Stage 1 outputs, this is the assigned `zone_code`.

### Key distinction
The following distinction is binding:

- `unit_id` and `parent_id` are canonical relational keys
- `unit_code` and `parent_code` are metadata only

## 2.4 Assignment quantities

### `ovl_share`
District→zone overlap share.

Current implementation basis:

- intersection area divided by district area
- computed in `crs.working_crs`

### `intersection_area_sq_m`
Intersection area in square metres for a district×zone candidate overlap row.

### `district_area_sq_m`
District area in square metres used for the overlap-share denominator.

### `district_intersection_sum_sq_m`
Sum of all positive district×zone intersection areas for a district.

### `district_uncovered_area_sq_m`
District area not covered by the union of intersecting zones.

### `district_uncovered_frac`
`district_uncovered_area_sq_m / district_area_sq_m`

## 2.5 Area-policy metadata

### `area_policy.method`
Declared reported area method:

- `projected`
- `geodesic`
- `both`

Current Stage 1 export constraint:

- `unit_universe.csv` can only represent one `area_sqkm` column
- therefore `both` fails fast at runtime for the canonical Stage 1 export path

### `area_policy.projected_crs`
Projected CRS used for reported area when method is projected.

### `area_policy.geodesic_ellipsoid`
Ellipsoid used when method is geodesic.

### `area_policy.units`
Declared reported units:

- `sq_km`
- `sq_m`

Current Stage 1 export constraint:

- `unit_universe.csv` is fixed as `area_sqkm`
- therefore `sq_m` fails fast at runtime for the canonical Stage 1 export path

## 3. Output tree

A typical run writes:

```text
<run_dir>/
├── boundaries/
│   ├── combined_manifest.json
│   ├── <zones_basename>.shp + sidecars
│   └── <districts_basename>.shp + sidecars
├── contract/
│   └── stage1_contract_manifest.json
├── crosswalks/
│   ├── crosswalks_manifest.json
│   ├── district_zone_crosswalk.csv
│   ├── shapefile_field_crosswalk.json
│   └── zone_lookup.csv
├── qa/
│   ├── district_zone_overlap.csv
│   ├── district_zone_overlap_issues.csv
│   ├── district_zone_overlap_metrics.csv
│   ├── district_zone_overlap_summary.json
│   ├── district_zone_overlap_validations.json
│   ├── qa_summary.json
│   └── runtime_assignment_validations.json
├── inputs_fingerprint.json
├── outputs_manifest.json
└── unit_universe.csv
```

Optional directories when enabled:

```text
plots/
splits/
```

## 4. Canonical core file schemas

## 4.1 `unit_universe.csv`

Purpose:

single audit-friendly table of zone and district units plus parent linkage.

Fixed logical column order:

| Column | Type | Meaning |
|---|---|---|
| `unit_type` | string | `zone` or `district` |
| `level` | string | Configured level label for the row |
| `unit_id` | string | Canonical Stage 1 row key |
| `unit_code` | string / blank | Row-owned code metadata |
| `unit_name` | string | Canonical display name |
| `parent_level` | string / blank | Blank for zones; parent level for districts |
| `parent_id` | string / blank | Blank for zones; assigned parent zone ID for districts |
| `parent_code` | string / blank | Blank for zones; assigned parent zone code for districts |
| `parent_name` | string / blank | Blank for zones; assigned parent zone name for districts |
| `area_sqkm` | float | Reported area in square kilometres under the declared single-method area policy |

Binding row rules:

- zone rows must have `unit_code = zone_code`
- zone rows must have blank `parent_level`, `parent_id`, `parent_code`,
  and `parent_name`
- district rows must have `parent_id = zone_id`
- district rows must have `parent_code = zone_code`
- district rows may use `district_code` as `unit_code` only when it exists
  upstream; otherwise `unit_code` is blank

Ordering rules:

- zones first, sorted by `unit_id`
- districts next, sorted by `parent_id`, then `unit_id`

CSV-reading nuance:

- blank cells are written as blanks on disk
- CSV readers may display those blanks as null values
- pandas will often show those blanks as `NaN` unless `keep_default_na=False`

## 4.2 `boundaries/<zones_basename>.shp`

Purpose:

canonical enriched zone boundaries.

Current logical fields:

| Logical field | Meaning |
|---|---|
| `zone_id` | Deterministic zone ID |
| `zone_name` | Canonical zone label |
| `zone_code` | Deterministic zone code |

Current physical fields:

| Physical field | Meaning |
|---|---|
| `zone_id` | Deterministic zone ID |
| `zone_name` | Canonical zone label |
| `zone_code` | Deterministic zone code |

## 4.3 `boundaries/<districts_basename>.shp`

Purpose:

canonical enriched district boundaries with assigned parent zone.

Current canonical logical fields:

| Logical field | Meaning |
|---|---|
| `district_id` | Deterministic district ID |
| `district_name` | Canonical district label |
| `district_code` | Optional upstream district code slot |
| `zone_id` | Assigned parent zone ID |
| `zone_name` | Assigned parent zone name |
| `zone_code` | Assigned parent zone code |
| `ovl_share` | Assigned overlap share |

Current physical DBF aliases:

| Physical field | Logical field |
|---|---|
| `dist_id` | `district_id` |
| `dist_name` | `district_name` |
| `dist_code` | `district_code` |
| `zone_id` | `zone_id` |
| `zone_name` | `zone_name` |
| `zone_code` | `zone_code` |
| `ovl_share` | `ovl_share` |

Realised-output nuance:

- the alias map is fixed at the logical-contract level
- the current runtime only materialises physical `dist_code` when the upstream
  district layer already contains `district_code`
- a specific realised Shapefile can therefore omit `dist_code` even though the
  crosswalk sidecar still documents the reserved logical slot and its alias

## 5. Crosswalk sidecars

## 5.1 `crosswalks/zone_lookup.csv`

Purpose:

one-row-per-zone lookup table.

Current columns:

| Column | Type | Meaning |
|---|---|---|
| `zone_id` | string | Zone ID |
| `zone_name` | string | Canonical zone name |
| `zone_code` | string | Zone code |

## 5.2 `crosswalks/district_zone_crosswalk.csv`

Purpose:

one-row-per-district parent-zone crosswalk.

Current columns:

| Column | Type | Meaning |
|---|---|---|
| `district_id` | string | District ID |
| `district_name` | string | District name |
| `district_code` | string, optional | Upstream district code when present |
| `zone_id` | string | Assigned zone ID |
| `zone_name` | string | Assigned zone name |
| `zone_code` | string | Assigned zone code |
| `ovl_share` | float | Assigned overlap share |

Ordering:

- rows are de-duplicated on `district_id`
- rows are sorted by `zone_id`, then `district_id`

## 5.3 `crosswalks/shapefile_field_crosswalk.json`

Purpose:

logical-to-physical and physical-to-logical field alias map for zones and
districts.

Top-level keys:

- `zones`
- `districts`

Each contains:

- `logical_to_physical`
- `physical_to_logical`

Important nuance:

- this file records the canonical alias map
- it should not be interpreted as proof that every mapped physical column is
  present in a particular realised Shapefile

## 5.4 `crosswalks/crosswalks_manifest.json`

Purpose:

small manifest for crosswalk artefacts.

Current keys:

| Key | Type | Meaning |
|---|---|---|
| `zone_lookup_csv` | string | Relative path to `zone_lookup.csv` |
| `district_zone_crosswalk_csv` | string | Relative path to `district_zone_crosswalk.csv` |
| `shapefile_field_crosswalk_json` | string | Relative path to `shapefile_field_crosswalk.json` |
| `zone_rows` | integer | Number of zones |
| `district_rows` | integer | Number of districts |

## 6. QA files

## 6.1 `qa/district_zone_overlap.csv`

Purpose:

candidate-level and assigned-row overlap diagnostics.

Current columns written by the runtime include:

| Column | Meaning |
|---|---|
| `district_id` | District ID |
| `legacy_zone_id` | Upstream legacy zone ID when supplied |
| `legacy_zone_name` | Upstream legacy zone name when supplied |
| `legacy_zone_code` | Upstream legacy zone code when supplied |
| `legacy_assignment_present` | Whether legacy assignment fields were present |
| `zone_id` | Candidate zone ID |
| `zone_name` | Candidate zone name |
| `zone_code` | Candidate zone code |
| `intersection_area_sq_m` | Candidate intersection area |
| `district_area_sq_m` | District denominator area |
| `ovl_share` | Candidate overlap share |
| `district_area` | District area alias used by validators |
| `intersection_area` | Intersection area alias used by validators |
| `area_method` | Current assignment-area method |
| `area_units` | Current assignment-area units |
| `working_crs` | Working CRS used for overlay |
| `share_basis` | Current overlap-share basis |
| `assignment_method` | Current assignment method |
| `district_intersection_sum_sq_m` | Sum of district intersections |
| `district_uncovered_area_sq_m` | District uncovered area |
| `district_uncovered_frac` | District uncovered share |
| `tie_candidate_count` | Number of tied candidates |
| `tie_break_applied` | Whether tie-breaking was applied |
| `is_assigned` | Whether this row is the chosen assignment |
| `rank` | Candidate rank within district |
| `assignment_status` | Assigned/candidate/unassigned status |
| `assigned_share` | Chosen share on assigned row |
| `legacy_assignment_match` | Whether legacy and recomputed assignments match |
| `legacy_assignment_disagreement` | Whether legacy and recomputed assignments disagree |

This table is richer than the canonical boundary outputs by design.

## 6.2 `qa/district_zone_overlap_summary.json`

Purpose:

summary statistics and run-level interpretation for the overlap table.

## 6.3 `qa/district_zone_overlap_validations.json`

Purpose:

threshold evaluation details for overlap-related QA checks.

## 6.4 `qa/district_zone_overlap_issues.csv`

Purpose:

issue register derived from overlap diagnostics.

## 6.5 `qa/district_zone_overlap_metrics.csv`

Purpose:

metric summary table derived from overlap diagnostics.

## 6.6 `qa/runtime_assignment_validations.json`

Purpose:

run-level evaluation of assignment thresholds.

Current behaviour:

- this is a reporting sidecar
- it does not by itself prevent outputs being written

## 6.7 `qa/qa_summary.json`

Purpose:

top-level QA pointer file.

It records:

- overall QA status
- whether QA was enabled
- overlap row count
- thresholds used
- relative paths to the overlap report and sidecars

A `fail` status means review is required. It does not mean the run directory is
absent or incomplete.

## 7. Audit and contract manifests

## 7.1 `inputs_fingerprint.json`

Purpose:

audit-friendly fingerprint of the inputs and governing settings.

It includes:

- package metadata
- config path and SHA-256
- input bundle paths, sizes, and SHA-256 hashes
- schema version
- contract metadata
- area policy
- QA settings
- CRS settings
- levels
- output root and toggles
- run ID and repo-relative run directory

## 7.2 `outputs_manifest.json`

Purpose:

authoritative inventory of what the run wrote.

It includes:

- run metadata
- contract metadata
- area policy
- QA settings
- a logical output index
- a sorted file inventory with path, byte size, and SHA-256

This file excludes itself from its own hashed file inventory.

## 7.3 `contract/stage1_contract_manifest.json`

Purpose:

machine-readable Stage 1 contract snapshot for the run.

It records:

- contract metadata
- schema version
- level labels
- CRS settings
- area policy
- QA settings
- canonical logical outputs
- canonical logical schema
- notes about lean canonical outputs and sidecars
- extra runtime-discovered outputs

Observed current note semantics include an explicit statement that the
`unit_universe.csv` contract revision adds `unit_code` and `parent_code` while
preserving `unit_id` and `parent_id` as canonical relational keys.

## 8. Current constraints and non-promises

Current Stage 1 constraints:

- input support is Shapefile only
- inputs must include CRS metadata
- polygon geometry is required
- `unit_universe.csv` cannot represent `area_policy.method: both`
- `unit_universe.csv` cannot represent `area_policy.units: sq_m`

Current non-promises:

- Stage 1 does not derive missing district codes
- Stage 1 does not widen canonical Shapefile DBF schemas to carry rich
  provenance or QA detail
- Stage 1 does not guarantee that QA `fail` prevents output writing

## 9. Practical reading order

For a new run, inspect files in this order:

1. `outputs_manifest.json`
2. `contract/stage1_contract_manifest.json`
3. `unit_universe.csv`
4. `crosswalks/shapefile_field_crosswalk.json`
5. `qa/qa_summary.json`
6. `qa/district_zone_overlap.csv`

That sequence gives:

- what was written
- what the contract says
- the canonical tabular unit view
- how logical/physical field aliasing works
- whether QA review is required
- the detailed assignment diagnostics
