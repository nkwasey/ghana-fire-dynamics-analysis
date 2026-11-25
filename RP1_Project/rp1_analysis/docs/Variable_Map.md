# Variable map

| Scientific construct | Governed field | Use |
|---|---|---|
| MCD64A1 burned area, long-run | `modis_ba_km2_ba2001` | RQ1/RQ2 mapped burned surface |
| Fixed BA-2001 burnable area | `modis_burnable_km2_union_ba2001` | RQ1/RQ2 fixed denominator; MCD SaTScan exposure |
| Annual BA-2001 burnable area | `modis_burnable_km2_annual_ba2001` | governed source field retained in the dataset; not used by final RQ2 |
| MCD64A1 burned pixels | `modis_burned_pixel_count_ba2001` | MCD64A1 SaTScan cases |
| BA-2012 presence | `modis_ba_any_ba2012` | RQ3 outcome component |
| VIIRS primary detections | `viirs_det_primary` | RQ3 focal predictor; VIIRS SaTScan cases |
| VIIRS mean daily-maximum FRP | `viirs_frp_mean_mw` | RQ3 focal predictor: sum of eligible nominal/high-confidence UTC daily maxima divided by FRP-supported days |
| Fixed BA-2012 burnable area | `modis_burnable_km2_union_ba2012` | RQ3 adjustment predictor |
| Month | `month` | categorical RQ3 adjustment |
| Year | `year` | categorical RQ3 adjustment |
| Parent ACZ | `parent_code` | ecological-stratum adjustment/reporting |

RQ3 model predictors exclude VIIRS active-day count and MODIS active-fire co-detection. The fields may remain in the governed panel for other descriptive/data-provenance purposes.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

