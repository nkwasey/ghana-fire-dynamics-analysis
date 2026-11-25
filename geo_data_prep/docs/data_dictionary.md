# Data dictionary and handoff contract

All analytical CSVs have one header and no index column. Areas ending `_sq_km` and `area_sqkm` are square kilometres. Shares are dimensionless proportions. Empty district codes and zone-parent fields are blank, not missing spatial assignments. UTF-8 text and full double-precision CSV values are used. Shapefile DBF decimal precision is lower; the CSV is the detailed overlap authority.

## Unit universe

One row per district or constructed zone. The exact ordered header is:

```text
unit_type,level,unit_id,unit_code,unit_name,parent_level,parent_id,parent_code,parent_name,area_sqkm
```

| Fields | Meaning |
|---|---|
| `unit_type`, `level` | Unit type and RP1 role (`zone`/`acz` or `district`/`district`) |
| `unit_id`, `unit_name` | Identity unique within `level`, and display name; the relational key is `(level, unit_id)` |
| `unit_code` | Unit-owned code; blank district codes are permitted |
| `parent_level`, `parent_id`, `parent_code`, `parent_name` | Assigned reporting zone for districts; blank for zones |
| `area_sqkm` | Area of the source-CRS `boundaries/` geometry calculated in `crs.area` |

`acz` is the RP1-compatible reporting-zone role even in the agro-ecological example. It does not mean that every configured zone system is agro-climatic. The selected input profile defines the scientific meaning.

## Boundary fields

Zone shapefiles contain `zone_id`, `zone_name` and `zone_code`. District shapefiles contain:

| Physical DBF field | Meaning |
|---|---|
| `dist_id`, `dist_name`, `dist_code` | District key, display label and optional code |
| `zone_id`, `zone_name`, `zone_code` | Assigned reporting-zone identity |
| `ovl_share` | Reference-zone overlap share used in assignment |
| `cov_share` | Whole-district coverage by the constructed reporting zone; validated as 1 |

The three district fields are DBF aliases for logical `district_id`, `district_name` and `district_code`. GeoJSON and attribute CSV counterparts retain the physical output fields. GeoJSON uses EPSG:4326; read the shapefile `.prj` for its actual CRS. District shapefile coordinates under `boundaries/` are preserved exactly, allowing only ring orientation and component ordering to differ. GeoJSON coordinates are transformed when the district source uses another CRS.

When `crs.analysis` is configured, `analysis_boundaries/districts_within_acz.*` and `analysis_boundaries/acz.*` provide corresponding projected shapefile bundles with the same identifiers and attributes. Their coordinates are transformed rather than source-coordinate identical. The projected zone geometry is constructed from the serialized projected district members. The source CRS geometry, assignment and `area_sqkm` conventions remain authoritative as documented; inspect the run configuration, contract and manifest for the selected derivative and its identity.

Geographic export coordinates must be finite, within the WGS84 horizontal coordinate range and valid polygon geometry. Invalid transformations are rejected rather than serialized as `NaN` or `Infinity`. This does not repair a wrongly assigned CRS; correct the source definition before processing.

## Selected assignment and crosswalk

`crosswalks/district_zone_crosswalk.csv` is serialized and read back to construct boundaries. `district_to_acz_max_overlap.csv` contains the same selected-assignment content for the analysis handoff. They contain:

- District and zone identities and metadata.
- `original_district_area_sq_km`: whole source district area in the assignment CRS.
- `dominant_overlap_area_sq_km`, `dominant_overlap_share`: selected intersection area and proportion of whole district area.
- `assignment_method`, `working_crs`: assignment rule and area CRS.
- `runner_up_share`, `assignment_margin`: competing overlap and selected-minus-runner-up share. A tolerance tie-break can select a share below the numeric maximum by up to `tie_tolerance`; the margin can then be negative. Keep this tolerance small when using it solely for floating-point ties.
- `tie_candidate_count`, `assignment_status`: number of tied candidates and whether the deterministic tie-break was applied.

District IDs must be unique. Shares remain bounded in [0,1] after only numerical overshoot normalization. The provenance JSON binds `crosswalk.sha256` to its CSV and records reference geometries, implementation, tie rule and CRS. It does not claim that the pairing is independently confirmed ground truth.

## QA

`qa/district_zone_overlap.csv` retains all positive intersections, their area/share, rank and `is_assigned` selection. The key is `(district_id, zone_id)`. `qa/reference_coverage.csv` records coverage by the union of reference zones, uncovered district area in m², and the sum of individual reference overlap shares. Overlapping reference zones can make that sum exceed one.

`qa/constructed_hierarchy.csv` records parent union equality and district containment. These checks concern constructed boundaries, not the independent reference polygons. `qa/qa_summary.json` records counts, warnings and checks. Structural handoff eligibility means geometry/keys/exports completed successfully; it does not approve a source profile for all scientific uses.

When an analysis CRS is configured, `qa/analysis_hierarchy.csv` records the same constructed-parent checks for the projected handoff, and `qa/qa_summary.json` records `analysis_crs` and `analysis_exact_parent_district_union`. The run contract's `analysis_handoff` describes the chosen CRS, relative paths, native district source, method, component hashes and union check. It is null when the derivative is disabled. As with the native hierarchy, these checks establish constructed geometry relationships rather than independent reference accuracy.

## Provenance and reproducibility

`inputs_fingerprint.json` records exact observed source-component and config hashes, together with each resolved source `layer`. Input fingerprints are captured before reading and checked after reading and before publishing; the configuration hash covers the bytes actually parsed. `run_configuration.json` is the portable run configuration. `environment.json` records Python and native/geospatial-library versions. The contract records schema meanings and implementation identity. `outputs_manifest.json` inventories output hashes and sizes and explicitly excludes itself.

Hash matches establish file identity, not independent source accuracy. Keep manifests with their run and do not edit source or output files while treating their recorded hashes as current.

## District numbers and map keys

Each `plots/per_zone/<zone_id>_labels.csv` links every district to its map number and name-key entry. `dist_id` is the administrative key; duplicate display names do not merge districts. Numbers are assigned alphabetically within each zone and are not administrative codes. `label_text` retains the full district name for the key. The geographic position, rendering panel and font size describe the printed number, including detail-panel placement for small districts. Number placement does not change the geometry, assignment crosswalk or area fields. The accompanying plot checks distinguish full printed number-box containment from centre-point containment.

`anchor_lon`/`anchor_lat` are reproducible reference points inside each district. `number_lon`/`number_lat` are the actual printed number positions in EPSG:4326. `panel` identifies the main map or an enlarged detail panel. The padded number rectangle is recorded by `bbox_min_lon`, `bbox_min_lat`, `bbox_max_lon`, and `bbox_max_lat`; these geographic bounds are checked against the displayed district polygon. `font_size_pt` records the rendered type size. `number_inside` and `bbox_overlap_count` report containment and overlap checks for the appropriate panel. Numbers start at one separately in each zone.

`plots/district_label_checks.json` also records key-column count, detail-panel count and whether details were placed in the main-map space. Embedded details are permitted only where their expanded frames do not intersect district geometry. If there is no suitable empty map area, a separate compact detail panel is used. The same geographic coordinates can occur in a main map and in an enlarged panel; overlap checks are therefore evaluated within each rendering panel rather than between different views.
