# Data dictionary

This document describes the principal repository artefacts and the currently
implemented column contracts most relevant to downstream use.

It focuses on:

- the contracted combined monthly panel
- the additive extended and QC sidecars
- the additive dual-sensor RP1 AF merger-ready export family

---

## 1. Core output artefacts

### 1.1 `panel_monthly`

Path pattern:

```text
out/runs/<run_id>/panel_monthly/panel_monthly.csv[.gz]
````

Role:

* contracted combined monthly output
* balanced across the configured unit universe and requested month span
* validated against `configs/schemas/panel_monthly.schema.json`

Required columns:

1. `run_id`
2. `level`
3. `unit_id`
4. `yyyymm`
5. `year`
6. `month`
7. `viirs_det_low`
8. `viirs_det_nominal`
9. `viirs_det_high`
10. `viirs_det_nh`
11. `viirs_frp_active_days`
12. `viirs_frp_sum_daily_max_mw`
13. `viirs_frp_mean_mw`
14. `modis_det_low`
15. `modis_det_nominal`
16. `modis_det_high`
17. `modis_det_nh`
18. `modis_frp_active_days`
19. `modis_frp_sum_daily_max_mw`
20. `modis_frp_mean_mw`

Notes:

* this is the only formal contracted monthly combined table
* `*_det_nh` is the main harmonised count metric in the contracted panel

### 1.2 `panel_monthly_ext`

Path pattern:

```text
out/runs/<run_id>/panel_monthly/panel_monthly_ext.csv[.gz]
```

Role:

* additive extended combined monthly table
* source table for the RP1 AF exporter together with `panel_monthly_qc` and
  `unit_universe`

Typical additional fields include:

* `*_pct_high_conf`
* `*_days_active_nh`
* `*_streak_max_nh`
* `*_frp_p95_daily_max_mw`

### 1.3 `panel_monthly_qc`

Path pattern:

```text
out/runs/<run_id>/panel_monthly/panel_monthly_qc.csv[.gz]
```

Role:

* additive QC and provenance sidecar
* written only when `qc.write_panel_monthly_qc_sidecar: true`
* used by the RP1 AF `_ext` exporter even when the separate sidecar file is not
  materialised

Per-sensor QC fields:

* `{sensor}_has_any`
* `{sensor}_in_coverage_flag`
* `{sensor}_structural_missing_flag`
* `{sensor}_low_information_month_flag`
* `{sensor}_frp_ok_flag`

Global provenance fields used in RP1 AF `_ext` outputs:

* `sensor_coverage_start_yyyymm`
* `sensor_coverage_end_yyyymm`
* `year_rows_in_panel`
* `year_rows_in_sensor_coverage`
* `year_rows_structural_missing`
* `year_coverage_complete_flag`

---

## 2. RP1 AF merger-ready export family

### 2.1 Family identity

Path root:

```text
out/runs/<run_id>/rp1_af_exports/
```

Family name:

```text
rp1_af_exports
```

Role:

* additive merger-ready export family for downstream RP1 analysis / merger use
* not the repository’s primary contracted monthly table

Source artefacts:

* `panel_monthly_ext`
* `panel_monthly_qc`
* `unit_universe`

Sensor identity is stored in:

* the path branch `<sensor_mode>`
* the RP1 AF manifest
* the configured sensor-specific schema paths

Sensor identity is **not** added as a CSV column.

### 2.2 RP1 AF windows

The dedicated RP1 AF export windows are fixed by sensor:

* **VIIRS:** `201201`–`202412`
* **MODIS:** `200101`–`202412`

These windows apply only to `rp1_af_exports`.

### 2.3 RP1 AF base export

Path pattern:

```text
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_<partition_key>_<partition_value>.csv[.gz]
```

#### VIIRS base columns

1. `run_id`
2. `schema_version`
3. `level`
4. `unit_id`
5. `unit_code`
6. `unit_name`
7. `parent_level`
8. `parent_id`
9. `parent_code`
10. `parent_name`
11. `yyyymm`
12. `year`
13. `month`
14. `viirs_det_low`
15. `viirs_det_nominal`
16. `viirs_det_high`
17. `viirs_det_all`
18. `viirs_det_nh`
19. `viirs_pct_high_conf`
20. `viirs_days_active_nh`
21. `viirs_streak_max_nh`
22. `viirs_frp_active_days`
23. `viirs_frp_sum_daily_max_mw`
24. `viirs_frp_mean_mw`
25. `viirs_frp_p95_daily_max_mw`

Schema:

```text
configs/schemas/rp1_af_monthly_base_viirs.schema.json
```

#### MODIS base columns

1. `run_id`
2. `schema_version`
3. `level`
4. `unit_id`
5. `unit_code`
6. `unit_name`
7. `parent_level`
8. `parent_id`
9. `parent_code`
10. `parent_name`
11. `yyyymm`
12. `year`
13. `month`
14. `modis_det_low`
15. `modis_det_nominal`
16. `modis_det_high`
17. `modis_det_all`
18. `modis_det_nh`
19. `modis_pct_high_conf`
20. `modis_days_active_nh`
21. `modis_streak_max_nh`
22. `modis_frp_active_days`
23. `modis_frp_sum_daily_max_mw`
24. `modis_frp_mean_mw`
25. `modis_frp_p95_daily_max_mw`

Schema:

```text
configs/schemas/rp1_af_monthly_base_modis.schema.json
```

### 2.4 RP1 AF extended export

Path pattern:

```text
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_ext_<partition_key>_<partition_value>.csv[.gz]
```

The `_ext` export begins with the full base contract in identical order and then
appends QC / provenance fields.

#### VIIRS `_ext` additional columns

26. `viirs_has_any`
27. `viirs_in_coverage_flag`
28. `viirs_structural_missing_flag`
29. `viirs_low_information_month_flag`
30. `viirs_frp_ok_flag`
31. `sensor_coverage_start_yyyymm`
32. `sensor_coverage_end_yyyymm`
33. `year_rows_in_panel`
34. `year_rows_in_sensor_coverage`
35. `year_rows_structural_missing`
36. `year_coverage_complete_flag`

Schema:

```text
configs/schemas/rp1_af_monthly_ext_viirs.schema.json
```

#### MODIS `_ext` additional columns

26. `modis_has_any`
27. `modis_in_coverage_flag`
28. `modis_structural_missing_flag`
29. `modis_low_information_month_flag`
30. `modis_frp_ok_flag`
31. `sensor_coverage_start_yyyymm`
32. `sensor_coverage_end_yyyymm`
33. `year_rows_in_panel`
34. `year_rows_in_sensor_coverage`
35. `year_rows_structural_missing`
36. `year_coverage_complete_flag`

Schema:

```text
configs/schemas/rp1_af_monthly_ext_modis.schema.json
```

---

## 3. RP1 AF manifest entries

The RP1 AF block inside `combine_panels_manifest.json` records:

* `family_name`
* `source`
* `merge_keys`
* `families`
* `schema_version`
* `sensor_modes`

  * `<sensor_mode>.partition_basis`
  * `<sensor_mode>.window`
  * `<sensor_mode>.schemas`
  * `<sensor_mode>.levels`

Each partition entry records at least:

* `partition_key`
* `partition_value`
* `partition_level`
* `path`
* `sha256`
* `n_rows`

This manifest is used by the CLI completeness checks for `combine --skip-existing`.

---

## 4. Interpretation cautions

* `rp1_af_exports` is additive, not the repository’s primary contracted table.
* Do not expect a `sensor_mode` column inside RP1 AF CSV files.
* Do not assume the top hierarchy partition is always named `acz`; the path
  helper and manifest are generic.
* The RP1 AF windows are narrower and sensor-specific relative to broader
  processing windows.

