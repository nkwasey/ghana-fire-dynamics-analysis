# Variable map

| Scientific construct | Governed field | Use |
|---|---|---|
| MCD64A1 burned area, long-run | `modis_ba_km2_ba2001` | RQ1/RQ2 mapped burned surface |
| Fixed BA-2001 burnable area | `modis_burnable_km2_union_ba2001` | RQ1/RQ2 fixed denominator; MCD SaTScan exposure |
| Annual BA-2001 burnable area | `modis_burnable_km2_annual_ba2001` | governed source field retained in the dataset; not used by final RQ2 |
| MCD64A1 burned pixels | `modis_burned_pixel_count_ba2001` | MCD64A1 SaTScan cases |
| BA-2012 presence | `modis_ba_any_ba2012` | RQ3 outcome component |
| VIIRS primary detections | `viirs_det_primary` | RQ3 focal predictor; VIIRS SaTScan cases |
| VIIRS mean FRP | `viirs_frp_mean_mw` | RQ3 focal predictor |
| Fixed BA-2012 burnable area | `modis_burnable_km2_union_ba2012` | RQ3 adjustment predictor |
| Month | `month` | categorical RQ3 adjustment |
| Year | `year` | categorical RQ3 adjustment |
| Parent ACZ | `parent_code` | ecological-stratum adjustment/reporting |

RQ3 model predictors exclude VIIRS active-day count and MODIS active-fire co-detection. The fields may remain in the governed panel for other descriptive/data-provenance purposes.
