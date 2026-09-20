# Data Schema Contract

This document is generated from `config/data_schema_contract.yml`. The YAML contract is the machine-readable authority; this file is a derived human-readable registry and must not be edited as an independent 111-field authority.

- Analysis schema: `rp1-analysis-v1.1`
- Data schema: `rp1-data-schema-v1.1`
- Panel schema: `rp1_fire_panel_consolidated_v2`
- Governed panel fields: **111**

## Panel authorities

| Panel | Path | Primary key | Rows | Units | Frequency | Start | End |
|---|---|---|---:|---:|---|---|---|
| `acz_monthly` | `data/raw/fire_panel_acz_monthly_consolidated_2001_2024.csv` | `unit_id, yyyymm` | 1440 | 5 | monthly | 2001-01 | 2024-12 |
| `district_monthly` | `data/raw/fire_panel_district_monthly_consolidated_2001_2024.csv` | `unit_id, yyyymm` | 74880 | 260 | monthly | 2001-01 | 2024-12 |

## Analytical-population validation authorities

Scientific analysis-population choices are owned by `config/analysis_contract.yml`; the data schema owns only field and support semantics.

| Population | Units | Rows | Start | End | Eligibility rule |
|---|---:|---:|---|---|---|
| `acz_monthly` | 5 | 1440 | 2001-01 | 2024-12 | `complete_balanced_panel` |
| `district_monthly` | 260 | 74880 | 2001-01 | 2024-12 | `complete_balanced_panel` |
| `long_run_district` | 250 | 72000 | 2001-01 | 2024-12 | `positive_fixed_ba2001_burnable_area_all_months` |
| `paired_overlap` | 249 | 38595 | 2012-02 | 2024-12 | `paired_supported_positive_fixed_ba2012_burnable_area` |
| `rq3_model` | 249 | 22939 | 2012-02 | 2024-12 | `viirs_detection_count_positive` |

## Geometry authorities

| Geometry | Path | Features | CRS | Identifier | Parent field | Required members |
|---|---|---:|---|---|---|---:|
| `acz` | `data/geo/acz.shp` | 5 | EPSG:32630 | `zone_id` | `—` | 5 |
| `district` | `data/geo/districts_within_acz.shp` | 260 | EPSG:32630 | `dist_id` | `zone_id` | 5 |

## Relationships

| ID | From | To | Cardinality |
|---|---|---|---|
| `district_panel_parent_id_to_acz_unit_id` | `district_monthly.parent_id` | `acz_monthly.unit_id` | `many_to_one` |
| `district_panel_parent_code_to_acz_unit_code` | `district_monthly.parent_code` | `acz_monthly.unit_code` | `many_to_one` |
| `district_geometry_parent_to_acz_geometry` | `district_geometry.zone_id` | `acz_geometry.zone_id` | `many_to_one` |
| `district_panel_to_district_geometry` | `district_monthly.unit_id` | `district_geometry.dist_id` | `many_to_one` |
| `acz_panel_to_acz_geometry` | `acz_monthly.unit_id` | `acz_geometry.zone_id` | `many_to_one` |

## Field registry

| # | Field | Dtype | Semantic type | Unit | Nullable | Structural support | Source family | Additive | Min | Max | Domain | Relationship role |
|---:|---|---|---|---|---|---|---|---|---:|---:|---|---|
| 1 | `run_id` | string | identifier_or_governance | text | no | `canonical_spine` | merge_governance | no | — | — | — | — |
| 2 | `schema_version` | string | identifier_or_governance | text | no | `canonical_spine` | merge_governance | no | — | — | panel_schema_version | — |
| 3 | `level` | string | identifier_or_governance | text | no | `canonical_spine` | merge_governance | no | — | — | level | — |
| 4 | `unit_id` | string | identifier_or_governance | text | no | `canonical_spine` | merge_governance | no | — | — | — | panel_primary_unit_identifier |
| 5 | `unit_code` | string | identifier_or_governance | text | yes | `canonical_spine` | merge_governance | no | — | — | acz_code | — |
| 6 | `unit_name` | string | identifier_or_governance | text | no | `canonical_spine` | merge_governance | no | — | — | — | — |
| 7 | `parent_level` | string | identifier_or_governance | text | yes | `canonical_spine` | merge_governance | no | — | — | — | — |
| 8 | `parent_id` | string | identifier_or_governance | text | yes | `canonical_spine` | merge_governance | no | — | — | acz_unit_id | foreign_key_to_acz_unit_id |
| 9 | `parent_code` | string | identifier_or_governance | text | yes | `canonical_spine` | merge_governance | no | — | — | acz_code | foreign_key_to_acz_unit_code |
| 10 | `parent_name` | string | identifier_or_governance | text | yes | `canonical_spine` | merge_governance | no | — | — | acz_name | — |
| 11 | `yyyymm` | integer | monthly_key | YYYYMM | no | `canonical_spine` | merge_governance | no | 200101 | 202412 | — | panel_primary_temporal_identifier |
| 12 | `year` | integer | calendar_year | year | no | `canonical_spine` | merge_governance | no | 2001 | 2024 | year | — |
| 13 | `month` | integer | calendar_month | month | no | `canonical_spine` | merge_governance | no | 1 | 12 | month | — |
| 14 | `modis_det_low` | integer | count | count | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 15 | `modis_det_nominal` | integer | count | count | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 16 | `modis_det_high` | integer | count | count | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 17 | `modis_det_all` | integer | count | count | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 18 | `modis_det_nh` | integer | count | count | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 19 | `modis_pct_high_conf` | number | percentage | percent | yes | `canonical_spine` | derived_multi_source | no | 0 | 100 | — | — |
| 20 | `modis_days_active_nh` | integer | duration_days | day | yes | `modis_af_full` | modis_active_fire | no | 0 | 31 | — | — |
| 21 | `modis_streak_max_nh` | integer | duration_days | day | yes | `modis_af_full` | modis_active_fire | no | 0 | 31 | — | — |
| 22 | `modis_frp_active_days` | integer | duration_days | day | no | `modis_af_full` | modis_active_fire | no | 0 | 31 | — | — |
| 23 | `modis_frp_sum_daily_max_mw` | number | radiative_power_mw | MW | no | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 24 | `modis_frp_mean_mw` | number | radiative_power_mw | MW | yes | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 25 | `modis_frp_p95_daily_max_mw` | number | radiative_power_mw | MW | yes | `modis_af_full` | modis_active_fire | no | 0 | — | — | — |
| 26 | `viirs_det_low` | integer | count | count | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 27 | `viirs_det_nominal` | integer | count | count | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 28 | `viirs_det_high` | integer | count | count | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 29 | `viirs_det_all` | integer | count | count | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 30 | `viirs_det_nh` | integer | count | count | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 31 | `viirs_pct_high_conf` | number | percentage | percent | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 100 | — | — |
| 32 | `viirs_days_active_nh` | integer | duration_days | day | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 31 | — | — |
| 33 | `viirs_streak_max_nh` | integer | duration_days | day | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 31 | — | — |
| 34 | `viirs_frp_active_days` | integer | duration_days | day | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 31 | — | — |
| 35 | `viirs_frp_sum_daily_max_mw` | number | radiative_power_mw | MW | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 36 | `viirs_frp_mean_mw` | number | radiative_power_mw | MW | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 37 | `viirs_frp_p95_daily_max_mw` | number | radiative_power_mw | MW | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 38 | `modis_ba_km2_ba2001` | number | area_km2 | km2 | no | `ba2001_full` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 39 | `modis_burned_pixel_count_ba2001` | integer | count | count | no | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 40 | `modis_ba_any_ba2001` | number | numeric_measure | 1 | no | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 41 | `modis_aoi_area_land_km2_ba2001` | number | area_km2 | km2 | no | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 42 | `modis_burnable_km2_union_ba2001` | number | area_km2 | km2 | no | `ba2001_full` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 43 | `modis_burnable_km2_annual_ba2001` | number | area_km2 | km2 | no | `ba2001_full` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 44 | `modis_burned_frac_union_ba2001` | number | proportion | 1 | yes | `ba2001_full` | mcd64a1_burned_area | no | 0 | 1 | — | — |
| 45 | `modis_burned_frac_annual_ba2001` | number | proportion | 1 | yes | `ba2001_full` | mcd64a1_burned_area | no | 0 | 1 | — | — |
| 46 | `modis_zero_union_den_flag_ba2001` | number | numeric_measure | 1 | no | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 47 | `modis_zero_annual_den_flag_ba2001` | number | numeric_measure | 1 | no | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 48 | `modis_ba_km2_ba2012` | number | area_km2 | km2 | yes | `ba2012_native` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 49 | `modis_burned_pixel_count_ba2012` | integer | count | count | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 50 | `modis_ba_any_ba2012` | number | numeric_measure | 1 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 51 | `modis_aoi_area_land_km2_ba2012` | number | area_km2 | km2 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 52 | `modis_burnable_km2_union_ba2012` | number | area_km2 | km2 | yes | `ba2012_native` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 53 | `modis_burnable_km2_annual_ba2012` | number | area_km2 | km2 | yes | `ba2012_native` | mcd64a1_burned_area | yes | 0 | — | — | — |
| 54 | `modis_burned_frac_union_ba2012` | number | proportion | 1 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | 1 | — | — |
| 55 | `modis_burned_frac_annual_ba2012` | number | proportion | 1 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | 1 | — | — |
| 56 | `modis_zero_union_den_flag_ba2012` | number | numeric_measure | 1 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 57 | `modis_zero_annual_den_flag_ba2012` | number | numeric_measure | 1 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 58 | `modis_det_primary` | number | count | count | no | `modis_af_full` | modis_active_fire | yes | 0 | — | — | — |
| 59 | `modis_det_nh_share_of_all` | number | proportion | 1 | yes | `modis_af_full` | modis_active_fire | no | 0 | 1 | — | — |
| 60 | `modis_det_primary_any` | integer | binary_flag | 1 | no | `modis_af_full` | modis_active_fire | no | 0 | 1 | — | — |
| 61 | `viirs_det_primary` | number | count | count | yes | `viirs_native` | snpp_viirs_active_fire | yes | 0 | — | — | — |
| 62 | `viirs_det_nh_share_of_all` | number | proportion | 1 | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 1 | — | — |
| 63 | `viirs_det_primary_any` | integer | binary_flag | 1 | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 1 | — | — |
| 64 | `modis_ba_km2_per100km2_union_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 65 | `modis_ba_km2_per100km2_annual_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `ba2001_full` | mcd64a1_burned_area | no | 0 | — | — | — |
| 66 | `modis_ba_km2_per100km2_union_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 67 | `modis_ba_km2_per100km2_annual_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `ba2012_native` | mcd64a1_burned_area | no | 0 | — | — | — |
| 68 | `modis_det_primary_per100km2_burnable_union_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 69 | `modis_det_primary_per100km2_burnable_annual_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 70 | `modis_det_primary_per100km2_burnable_union_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `ba2012_native` | derived_multi_source | no | 0 | — | — | — |
| 71 | `modis_det_primary_per100km2_burnable_annual_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `ba2012_native` | derived_multi_source | no | 0 | — | — | — |
| 72 | `viirs_det_primary_per100km2_burnable_union_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `viirs_native` | derived_multi_source | no | 0 | — | — | — |
| 73 | `viirs_det_primary_per100km2_burnable_annual_ba2001` | number | rate_per_100km2 | per_100_km2 | yes | `viirs_native` | derived_multi_source | no | 0 | — | — | — |
| 74 | `viirs_det_primary_per100km2_burnable_union_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `full_overlap_native` | derived_multi_source | no | 0 | — | — | — |
| 75 | `viirs_det_primary_per100km2_burnable_annual_ba2012` | number | rate_per_100km2 | per_100_km2 | yes | `full_overlap_native` | derived_multi_source | no | 0 | — | — | — |
| 76 | `modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 77 | `modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 78 | `modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `ba2012_native` | derived_multi_source | no | 0 | — | — | — |
| 79 | `modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `ba2012_native` | derived_multi_source | no | 0 | — | — | — |
| 80 | `viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `viirs_native` | derived_multi_source | no | 0 | — | — | — |
| 81 | `viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `viirs_native` | derived_multi_source | no | 0 | — | — | — |
| 82 | `viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `full_overlap_native` | derived_multi_source | no | 0 | — | — | — |
| 83 | `viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012` | number | radiative_power_density_mw_per_km2 | MW_per_km2 | yes | `full_overlap_native` | derived_multi_source | no | 0 | — | — | — |
| 84 | `modis_det_primary_per_active_day` | number | rate_per_active_day | per_day | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 85 | `modis_frp_sum_daily_max_mw_per_active_day` | number | rate_per_active_day | per_day | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 86 | `modis_frp_sum_daily_max_mw_per_primary_det` | number | radiative_power_per_detection | MW_per_detection | yes | `modis_af_full` | derived_multi_source | no | 0 | — | — | — |
| 87 | `viirs_det_primary_per_active_day` | number | rate_per_active_day | per_day | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 88 | `viirs_frp_sum_daily_max_mw_per_active_day` | number | rate_per_active_day | per_day | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 89 | `viirs_frp_sum_daily_max_mw_per_primary_det` | number | radiative_power_per_detection | MW_per_detection | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | — | — | — |
| 90 | `viirs_supported_flag` | integer | binary_flag | 1 | no | `canonical_spine` | snpp_viirs_active_fire | no | 0 | 1 | — | — |
| 91 | `ba2012_supported_flag` | integer | binary_flag | 1 | no | `canonical_spine` | derived_multi_source | no | 0 | 1 | — | — |
| 92 | `full_overlap_supported_flag` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 93 | `ba_any_ba2001_and_viirs_primary_any_flag` | integer | binary_flag | 1 | yes | `viirs_native` | derived_multi_source | no | 0 | 1 | — | — |
| 94 | `ba_any_ba2012_and_viirs_primary_any_flag` | integer | binary_flag | 1 | yes | `full_overlap_native` | derived_multi_source | no | 0 | 1 | — | — |
| 95 | `ba_any_ba2001_and_modis_primary_any_flag` | integer | binary_flag | 1 | no | `canonical_spine` | derived_multi_source | no | 0 | 1 | — | — |
| 96 | `ba_any_ba2012_and_modis_primary_any_flag` | integer | binary_flag | 1 | yes | `ba2012_native` | derived_multi_source | no | 0 | 1 | — | — |
| 97 | `ba_any_ba2001_without_viirs_primary_flag` | integer | binary_flag | 1 | yes | `viirs_native` | derived_multi_source | no | 0 | 1 | — | — |
| 98 | `ba_any_ba2012_without_viirs_primary_flag` | integer | binary_flag | 1 | yes | `full_overlap_native` | derived_multi_source | no | 0 | 1 | — | — |
| 99 | `viirs_primary_without_ba_any_ba2001_flag` | integer | binary_flag | 1 | yes | `viirs_native` | derived_multi_source | no | 0 | 1 | — | — |
| 100 | `viirs_primary_without_ba_any_ba2012_flag` | integer | binary_flag | 1 | yes | `full_overlap_native` | derived_multi_source | no | 0 | 1 | — | — |
| 101 | `viirs_primary_any_and_modis_primary_any_flag` | integer | binary_flag | 1 | yes | `viirs_native` | snpp_viirs_active_fire | no | 0 | 1 | — | — |
| 102 | `af_modis_source_present` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 103 | `af_viirs_source_present` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 104 | `ba2001_source_present` | integer | binary_flag | 1 | no | `canonical_spine` | derived_multi_source | no | 0 | 1 | — | — |
| 105 | `ba2012_source_present` | integer | binary_flag | 1 | no | `canonical_spine` | derived_multi_source | no | 0 | 1 | — | — |
| 106 | `row_in_canonical_spine` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 107 | `merge_key_complete_flag` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 108 | `merge_duplicate_resolved_flag` | integer | binary_flag | 1 | no | `canonical_spine` | merge_governance | no | 0 | 1 | — | — |
| 109 | `viirs_structural_missing_flag` | integer | binary_flag | 1 | no | `canonical_spine` | snpp_viirs_active_fire | no | 0 | 1 | — | — |
| 110 | `ba2012_structural_missing_flag` | integer | binary_flag | 1 | no | `canonical_spine` | derived_multi_source | no | 0 | 1 | — | — |
| 111 | `merge_note` | string | audit_note | text | yes | `canonical_spine` | merge_governance | no | — | — | — | — |

## Additive reconciliation

District-to-ACZ reconciliation is governed by the YAML contract. The configured additive fields are:

- `modis_ba_km2_ba2001`
- `modis_ba_km2_ba2012`
- `modis_burnable_km2_annual_ba2001`
- `modis_burnable_km2_annual_ba2012`
- `modis_burnable_km2_union_ba2001`
- `modis_burnable_km2_union_ba2012`
- `modis_det_primary`
- `viirs_det_primary`

## Structural missingness

A valid numerical zero is permitted only on product-supported unit-months. For fields tied to a structural-support rule, unsupported rows must remain null. Supported rows declared `required_when_supported: true` must be non-null. These semantics are validated from the machine-readable contract rather than from a second Python field list.
