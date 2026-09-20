# Data Dictionary - Consolidated RP1 Fire Panels

This document defines the maintained data contract for the consolidated monthly
fire panels written by `RP1_Project/merge_af_ba_panels.py` and consumed by the
live `RP1_Project/rp1_analysis/RP1_Analysis_v1.ipynb` workflow.

Source of truth:
- `RP1_Project/merge_af_ba_panels.py`
- `RP1_Project/rp1_analysis/data/raw/fire_panel_manifest.json`
- `RP1_Project/rp1_analysis/data/raw/fire_panel_merge_summary.json`
- `RP1_Project/rp1_analysis/data/raw/fire_panel_key_audit.csv`

## Output inventory

The merger writes the following maintained raw-panel artefacts under
`RP1_Project/rp1_analysis/data/raw/`:

| Path | Level | Rows | Columns | Locked month window |
| --- | --- | ---: | ---: | --- |
| `fire_panel_acz_monthly_consolidated_2001_2024.csv` | `acz` | 1,440 | 111 | `200101` to `202412` |
| `fire_panel_district_monthly_consolidated_2001_2024.csv` | `district` | 74,880 | 111 | `200101` to `202412` |
| `fire_panel_manifest.json` | metadata | n/a | n/a | exact ordered schema, upstream source inventory, schema hash |
| `fire_panel_merge_summary.json` | metadata | n/a | n/a | row counts, unique-unit counts, structural-missing totals |
| `fire_panel_key_audit.csv` | metadata | 2 | 9 | row-count and key-uniqueness audit by level |

The maintained schema version is `rp1_fire_panel_consolidated_v2`.

## Purpose and analytical role

These consolidated panels join four governed upstream families onto one
canonical monthly unit spine:

1. Stage 1 geography from `geo_data_prep`
2. MODIS active-fire base exports from `rp1_mv_firms_panels`
3. VIIRS active-fire base exports from `rp1_mv_firms_panels`
4. MODIS burned-area base exports from the BA-2001 and BA-2012 GEE families

`RP1_Analysis_v1.ipynb` uses these panels as its raw monthly fire inputs:
- long-run burned-area analysis uses the BA-2001 family
- overlap-era paired analysis uses BA-2012 together with VIIRS primary activity

## Locked design decisions

### Canonical balanced spine

The governing row key is:
- `level`
- `unit_id`
- `yyyymm`

The spine is balanced across:
- every governed unit in `geo_data_prep/out/example_acz/unit_universe.csv`
- every month from `200101` through `202412`, inclusive

### BA family preservation

The merger preserves both burned-area families explicitly:
- BA-2001 support window: `200101` to `202412`
- BA-2012 support window: `201201` to `202412`

No unsuffixed shared BA analytical columns are emitted. Burned-area fields are
kept family-specific because the realized monthly BA numerator can differ
between the BA-2001 and BA-2012 exports.

### No `*_preferred` BA fields

The merged contract does not choose a preferred burned-area family. Consumers
must select the correct family explicitly for the analytical question.

### AF primary count rule

The science-facing active-fire primary count is locked to nominal-plus-high
detections:
- `modis_det_primary = modis_det_nh`
- `viirs_det_primary = viirs_det_nh`

### Structural missingness is preserved

Unsupported months remain missing in the corresponding analytical fields rather
than being coerced to zero:
- VIIRS is unsupported before `201201`
- BA-2012 is unsupported before `201201`

The support and structural-missingness flags below are the maintained way to
distinguish unsupported months from observed zero activity.

## Support-window semantics

| Source family | Supported window | Notes |
| --- | --- | --- |
| MODIS active fire | `200101` to `202412` | Full project window |
| VIIRS active fire | `201201` to `202412` | Pre-201201 rows are structurally unsupported |
| BA-2001 | `200101` to `202412` | Long-run burned-area family |
| BA-2012 | `201201` to `202412` | Overlap-era burned-area family |

## Schema overview

The final consolidated schema contains 111 columns:

| Block | Columns |
| --- | ---: |
| Governance, identity, and time | 13 |
| MODIS AF base fields | 12 |
| VIIRS AF base fields | 12 |
| BA-2001 base fields | 10 |
| BA-2012 base fields | 10 |
| AF primary and summary derivations | 6 |
| BA area-rate derivations | 4 |
| AF density derivations | 8 |
| FRP density derivations | 8 |
| Within-sensor intensity derivations | 6 |
| Support flags | 3 |
| Concordance flags | 9 |
| Merge and provenance QC | 10 |

For the exact ordered 111-column list, use `fire_panel_manifest.json` under the
`final_schema_columns` key.

## Governance, identity, and time columns

| Column | Meaning |
| --- | --- |
| `run_id` | Merge run identifier written by `merge_af_ba_panels.py` |
| `schema_version` | Locked merged-panel schema version |
| `level` | Unit level: `acz` or `district` |
| `unit_id` | Canonical unit identifier from Stage 1 geography |
| `unit_code` | Canonical unit code |
| `unit_name` | Canonical unit name |
| `parent_level` | Canonical parent level; null for ACZ rows |
| `parent_id` | Canonical parent identifier; null for ACZ rows |
| `parent_code` | Canonical parent code; null for ACZ rows |
| `parent_name` | Canonical parent name; null for ACZ rows |
| `yyyymm` | Monthly key in `YYYYMM` form |
| `year` | Calendar year extracted from `yyyymm` |
| `month` | Calendar month extracted from `yyyymm` |

## Active-fire base fields

The following 12 stems appear for both `modis_` and `viirs_` sensor prefixes:

| Stem | Meaning |
| --- | --- |
| `det_low` | Low-confidence detection count |
| `det_nominal` | Nominal-confidence detection count |
| `det_high` | High-confidence detection count |
| `det_all` | Total detections across confidence classes |
| `det_nh` | Nominal-plus-high detections |
| `pct_high_conf` | Percent of detections that are high confidence |
| `days_active_nh` | Number of days with at least one nominal-plus-high detection |
| `streak_max_nh` | Longest run of active days using nominal-plus-high detections |
| `frp_active_days` | Number of days with positive FRP support |
| `frp_sum_daily_max_mw` | Sum of daily maximum FRP values in MW |
| `frp_mean_mw` | Mean FRP in MW |
| `frp_p95_daily_max_mw` | 95th percentile of daily maximum FRP in MW |

These fields are the direct governed inputs from the AF merger-ready base
exports.

## Burned-area base fields

The following 10 stems appear twice, once with `_ba2001` and once with
`_ba2012`:

| Stem | Meaning |
| --- | --- |
| `modis_ba_km2_*` | Burned-area extent in square kilometers |
| `modis_burned_pixel_count_*` | Burned-pixel count from the source export |
| `modis_ba_any_*` | Binary burned-area presence indicator |
| `modis_aoi_area_land_km2_*` | Land area in square kilometers for the unit |
| `modis_burnable_km2_union_*` | Fixed burnable-union denominator for the family |
| `modis_burnable_km2_annual_*` | Annual burnable denominator for the family |
| `modis_burned_frac_union_*` | Burned fraction using the family union denominator |
| `modis_burned_frac_annual_*` | Burned fraction using the family annual denominator |
| `modis_zero_union_den_flag_*` | Union denominator equals zero |
| `modis_zero_annual_den_flag_*` | Annual denominator equals zero |

Use `_ba2001` for long-run burned-area analysis and `_ba2012` for overlap-era
paired analysis.

## Derived AF summary fields

| Column | Meaning |
| --- | --- |
| `modis_det_primary` | MODIS primary count, equal to `modis_det_nh` |
| `modis_det_nh_share_of_all` | Share of MODIS detections that are nominal-plus-high |
| `modis_det_primary_any` | Binary indicator that MODIS primary activity is positive |
| `viirs_det_primary` | VIIRS primary count, equal to `viirs_det_nh` |
| `viirs_det_nh_share_of_all` | Share of VIIRS detections that are nominal-plus-high |
| `viirs_det_primary_any` | Binary indicator that VIIRS primary activity is positive, preserving unsupported months as missing |

## Rate and density derivations

### Burned-area rates

| Column pattern | Meaning |
| --- | --- |
| `modis_ba_km2_per100km2_union_[ba2001|ba2012]` | Burned area per 100 km2 using the family union denominator |
| `modis_ba_km2_per100km2_annual_[ba2001|ba2012]` | Burned area per 100 km2 using the family annual denominator |

### AF density rates

| Column pattern | Meaning |
| --- | --- |
| `[modis|viirs]_det_primary_per100km2_burnable_union_[ba2001|ba2012]` | Primary detections per 100 km2 using the family union denominator |
| `[modis|viirs]_det_primary_per100km2_burnable_annual_[ba2001|ba2012]` | Primary detections per 100 km2 using the family annual denominator |

### FRP density rates

| Column pattern | Meaning |
| --- | --- |
| `[modis|viirs]_frp_sum_daily_max_mw_per_km2_burnable_union_[ba2001|ba2012]` | FRP density using the family union denominator |
| `[modis|viirs]_frp_sum_daily_max_mw_per_km2_burnable_annual_[ba2001|ba2012]` | FRP density using the family annual denominator |

### Within-sensor intensity fields

| Column | Meaning |
| --- | --- |
| `modis_det_primary_per_active_day` | MODIS primary detections per active day |
| `modis_frp_sum_daily_max_mw_per_active_day` | MODIS summed daily-max FRP per active day |
| `modis_frp_sum_daily_max_mw_per_primary_det` | MODIS summed daily-max FRP per primary detection |
| `viirs_det_primary_per_active_day` | VIIRS primary detections per active day |
| `viirs_frp_sum_daily_max_mw_per_active_day` | VIIRS summed daily-max FRP per active day |
| `viirs_frp_sum_daily_max_mw_per_primary_det` | VIIRS summed daily-max FRP per primary detection |

## Support flags

| Column | Meaning |
| --- | --- |
| `viirs_supported_flag` | `1` where VIIRS is within its supported window |
| `ba2012_supported_flag` | `1` where BA-2012 is within its supported window |
| `full_overlap_supported_flag` | `1` where both VIIRS and BA-2012 are simultaneously supported |

## Concordance flags

These fields are family-specific wherever burned-area participation is involved.

| Column | Meaning |
| --- | --- |
| `ba_any_ba2001_and_viirs_primary_any_flag` | BA-2001 presence and VIIRS primary presence occur together |
| `ba_any_ba2012_and_viirs_primary_any_flag` | BA-2012 presence and VIIRS primary presence occur together |
| `ba_any_ba2001_and_modis_primary_any_flag` | BA-2001 presence and MODIS primary presence occur together |
| `ba_any_ba2012_and_modis_primary_any_flag` | BA-2012 presence and MODIS primary presence occur together |
| `ba_any_ba2001_without_viirs_primary_flag` | BA-2001 is present while VIIRS primary activity is absent |
| `ba_any_ba2012_without_viirs_primary_flag` | BA-2012 is present while VIIRS primary activity is absent |
| `viirs_primary_without_ba_any_ba2001_flag` | VIIRS primary activity is present while BA-2001 is absent |
| `viirs_primary_without_ba_any_ba2012_flag` | VIIRS primary activity is present while BA-2012 is absent |
| `viirs_primary_any_and_modis_primary_any_flag` | VIIRS primary activity and MODIS primary activity occur together |

## Merge and provenance QC fields

| Column | Meaning |
| --- | --- |
| `af_modis_source_present` | MODIS AF base source row was present for the merge key |
| `af_viirs_source_present` | VIIRS AF base source row was present for the merge key |
| `ba2001_source_present` | BA-2001 base source row was present for the merge key |
| `ba2012_source_present` | BA-2012 base source row was present for the merge key |
| `row_in_canonical_spine` | Row belongs to the governed balanced unit-month spine |
| `merge_key_complete_flag` | Merge key fields are populated |
| `merge_duplicate_resolved_flag` | Duplicate-key repair was applied before final output |
| `viirs_structural_missing_flag` | Row is before the VIIRS support window |
| `ba2012_structural_missing_flag` | Row is before the BA-2012 support window |
| `merge_note` | Sparse row-level note for merge audit diagnostics |

## Consumer guidance for `RP1_Analysis_v1`

- Use `BA-2001` columns for long-run burned-area sections.
- Use `BA-2012` columns together with `viirs_det_primary` fields for overlap-era
  paired sections.
- Respect `viirs_supported_flag`, `ba2012_supported_flag`, and
  `full_overlap_supported_flag` when constructing overlap-era inference samples.
- Do not recreate unsuffixed shared burned-area columns in downstream analysis.
- When exact column order matters for validation or exports, rely on
  `fire_panel_manifest.json` rather than handwritten column lists.
