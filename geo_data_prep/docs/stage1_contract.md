# Stage 1 contract — geo_data_prep

This document states the current canonical Stage 1 upstream contract in plain
language.

It is intentionally concise and binding.

## 1. What Stage 1 is

Stage 1 is the canonical upstream boundary-preparation contract for this
repository.

Stage 1 produces:

- deterministic zone identifiers, labels, and codes
- deterministic district identifiers and labels
- one assigned parent zone per district
- a fixed logical `unit_universe.csv` schema
- lean canonical boundary Shapefiles
- richer QA, crosswalk, provenance, and contract sidecars

Downstream consumers adapt later.

Stage 1 does not silently retrofit itself to downstream convenience.

## 2. Contract scope and binding semantics

### 2.1 Explicit contract revision

The logical `unit_universe.csv` contract was widened to include:

- `unit_code`
- `parent_code`

This revision is explicit. It is not a silent behavioural change.

### 2.2 Frozen semantics that remain unchanged

The following remain binding:

- `unit_id` and `parent_id` are the canonical relational keys
- `unit_code` is row-owned code metadata only
- `parent_code` is parent-owned code metadata only
- zone rows must have `unit_code = zone_code` and blank `parent_code`
- district rows must have `parent_code = zone_code`
- district rows may use `district_code` as `unit_code` only where that code
  exists upstream; otherwise `unit_code` is blank
- deterministic output ordering is preserved
- geometry, overlay, parent assignment, and area semantics are unchanged
- canonical Shapefile field contracts are unchanged
- Shapefile schema widening is not part of this revision

## 3. Canonical outputs

The canonical Stage 1 outputs are:

- `unit_universe.csv`
- `boundaries/<zones_basename>.shp`
- `boundaries/<districts_basename>.shp`
- `qa/district_zone_overlap.csv`

The machine-readable statement of the contract is:

- `contract/stage1_contract_manifest.json`

The run inventory is:

- `outputs_manifest.json`

The input/config audit record is:

- `inputs_fingerprint.json`

## 4. Canonical logical schemas

## 4.1 `unit_universe.csv`

The logical column order is fixed to:

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

Interpretation:

- `unit_type` is `zone` or `district`
- `level` is the configured level label for that row
- `unit_id` is the canonical row key
- `unit_code` is the row’s own code metadata
- `parent_level` is blank for zones and populated for districts
- `parent_id` is blank for zones and populated for districts
- `parent_code` is blank for zones and populated for districts
- `parent_name` is blank for zones and populated for districts
- `area_sqkm` is the reported single-method area value

Important key distinction:

- `unit_id` and `parent_id` are keys
- `unit_code` and `parent_code` are metadata
- code fields do not replace the key fields

Important CSV nuance:

- the file is written with blank parent cells for zone rows
- some readers, including pandas with default NA parsing, may display those
  blanks as `NaN`
- that does not change the contract; the underlying CSV cells are blank

## 4.2 Zone Shapefile

Canonical logical fields:

- `zone_id`
- `zone_name`
- `zone_code`

## 4.3 District Shapefile

Canonical logical fields:

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

Important realised-output nuance:

- the logical contract reserves `district_code`
- the current runtime only materialises physical `dist_code` when the upstream
  district layer already contains `district_code`
- therefore the logical contract can remain stable while a realised Shapefile
  omits `dist_code` in a particular run

## 5. Assignment contract

Stage 1 assigns districts to zones by polygon overlay in `crs.working_crs`.

The chosen parent zone is the candidate with the maximum overlap share of
district area.

Tie-breaking is deterministic.

The chosen district parent is written into the canonical district output.

Candidate-level and diagnostic detail are written to QA sidecars.

## 6. Sidecar policy

Stage 1 keeps canonical Shapefiles lean.

The following live in sidecars instead of being pushed into canonical DBF
schemas:

- detailed overlap QA
- issue registers
- validator metrics
- logical↔physical field crosswalks
- contract metadata
- input hashes
- output hashes

This is deliberate.

## 7. Area-policy contract

The runtime distinguishes between:

- the working CRS used for overlay and assignment-share denominators
- the reported area policy used for exported metadata

Current binding behaviour:

- overlay and overlap-area diagnostics use `crs.working_crs`
- `unit_universe.csv` exposes one fixed `area_sqkm` column
- Stage 1 can therefore represent only a single reported area method in square
  kilometres
- `area_policy.method: both` is not representable in the fixed Stage 1 CSV
  schema and fails fast at runtime
- `area_policy.units: sq_m` is not representable in the fixed Stage 1 CSV
  schema and fails fast at runtime

This is contract protection, not silent coercion.

## 8. QA policy

Structural validation is fail-fast.

That includes, for example:

- missing required fields
- unresolved parent linkage needed for export
- invalid or unusable geometries in fail-fast validation paths

Assignment QA reporting is non-blocking.

Overlap-share QA applies an explicit machine-precision tolerance at the closed
interval bounds:

- raw `ovl_share` values remain preserved in realised outputs for audit
- QA evaluation may clamp values lying within a small tolerance of 0 or 1 into
  `[0, 1]`
- material excursions outside that tolerance remain failures

That means:

- a run can complete
- outputs can be written
- `qa/qa_summary.json` can still report `status: fail`

That is current code behaviour and is part of the observable Stage 1 contract.

Assignment-threshold QA status is computed once and then reused across:

- `qa/district_zone_overlap_summary.json`
- `qa/district_zone_overlap_validations.json`
- `qa/runtime_assignment_validations.json`
- `qa/qa_summary.json`

Stage 1 may also emit descriptive scientific-defensibility sidecars:

- `qa/district_zone_overlap_sliver_summary.json`
- `qa/working_crs_sensitivity_summary.json`
- `qa/working_crs_sensitivity_comparison.csv`

These artefacts:

- do not replace the configured `crs.working_crs`
- do not change the max-overlap assignment rule on their own
- document whether tiny candidate overlaps are present and whether assignment
  identities remain stable under an alternative equal-area projection

The assignment rule remains max-overlap unless the sensitivity study reports
district identity changes under the alternative equal-area rerun.

## 9. Determinism policy

The runtime is designed to be deterministic with respect to:

- identifier derivation
- exported row ordering
- parent assignment tie-handling
- split-file naming
- manifest ordering

For `unit_universe.csv`, the current exported row order is:

- zones first, sorted by `unit_id`
- districts next, sorted by `parent_id`, then `unit_id`

## 10. Versioning policy

Two version concepts are intentionally separate:

- `schema_version` tracks the YAML configuration schema
- `contract.version` tracks the logical Stage 1 output contract

These can diverge legitimately.

In the bundled example configs:

- `schema_version` remains `1.0`
- `contract.version` is set to `1.1.0`

That documents the logical Stage 1 contract revision without implying a YAML
schema change.

## 11. What Stage 1 does not promise

Stage 1 does not promise:

- downstream-ready schemas for every later consumer
- automatic widening of canonical DBF schemas for provenance convenience
- parallel multi-method area exports in the canonical CSV
- non-Shapefile input support
- that a QA `fail` status prevents writing outputs
- that `district_code` is derivable when the upstream district layer does not
  contain it

## 12. Release control for downstream consumers

The current Stage 1 interface is consumed downstream as a governed contract.

In particular, `RP1_Project/merge_af_ba_panels.py` expects the current
`unit_universe.csv` schema and row semantics directly.

Operational rule:

- do not change `unit_universe.csv` or canonical boundary schemas informally
- if either schema changes, update `contract.version`
- revalidate known downstream consumers before release

## 12. Where to inspect the contract for a specific run

For any realised run, inspect:

1. `contract/stage1_contract_manifest.json`
2. `outputs_manifest.json`
3. `crosswalks/shapefile_field_crosswalk.json`
4. `unit_universe.csv`
5. `qa/qa_summary.json`

Together these tell you:

- what Stage 1 promises logically
- what that run wrote physically
- what field aliasing applies
- whether QA review is required
