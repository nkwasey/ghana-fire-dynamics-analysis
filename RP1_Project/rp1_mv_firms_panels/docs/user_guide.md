# User guide

This guide describes how to run the repository safely and how to interpret the
principal outputs for the dual-sensor RP1 active-fire export workflow.

---

## 1. What this repository produces

The pipeline can produce monthly fire-panel outputs for:

- VIIRS only
- MODIS only
- both sensors combined

The principal combine-stage outputs are:

1. `panel_monthly` — contracted combined monthly table
2. `panel_monthly_ext` — additive extended monthly table
3. `panel_monthly_qc` — additive QC / coverage sidecar
4. `rp1_af_exports` — additive merger-ready RP1 AF export family

---

## 2. Typical workflow

### 2.1 Full pipeline

```bash
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml --run-id ghana_combined_v2 pipeline --years-modis 2001-2024 --years-viirs 2012-2024
````

### 2.2 One `prepare-year` run

```bash
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml --run-id ghana_combined_v2 prepare-year --sensor viirs --year 2024
```

### 2.3 One `aggregate` run

```bash
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml --run-id ghana_combined_v2 aggregate --sensor modis --start-yyyymm 200101 --end-yyyymm 202412
```

### 2.4 One `combine` run

```bash
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml --run-id ghana_combined_v2 combine --start-yyyymm 200101 --end-yyyymm 202412
```

### 2.5 One `visualise` run

```bash
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml --run-id ghana_combined_v2 visualise
```

---

## 3. Important CLI safety behaviour

### `--skip-existing`

Safe resume.

A stage may be skipped only when:

* its sentinel or manifest exists
* expected outputs exist
* fast contract checks pass

For `combine`, this includes validation of the RP1 AF manifest and the
referenced RP1 AF CSV files.

More specifically, `combine --skip-existing` requires:

* the combined manifest to contain an `rp1_af_exports` block
* the RP1 AF block to record **every configured sensor branch**
* each sensor branch to record the configured sensor-specific RP1 window
* each sensor branch to record the configured sensor-specific base and `_ext`
  schema paths
* every referenced RP1 AF CSV file to exist on disk
* every referenced RP1 AF CSV file to validate against the correct
  sensor-specific schema

If any of those checks fail, `combine` reruns instead of accepting an
incomplete additive-output state.

### `--force`

Force rerun even when outputs and manifests already exist.

### Provenance fail-fast rule

If outputs exist but the sentinel or manifest is missing, the CLI raises.

---

## 4. Output locations

### 4.1 `panel_monthly`

```text
out/runs/<run_id>/panel_monthly/panel_monthly.csv[.gz]
```

This is the balanced, contracted combined monthly panel.

### 4.2 `panel_monthly_ext`

```text
out/runs/<run_id>/panel_monthly/panel_monthly_ext.csv[.gz]
```

This is the additive extended monthly table.

### 4.3 `panel_monthly_qc`

```text
out/runs/<run_id>/panel_monthly/panel_monthly_qc.csv[.gz]
```

This is the additive QC / coverage sidecar.

### 4.4 `rp1_af_exports`

```text
out/runs/<run_id>/rp1_af_exports/
```

This is the additive merger-ready RP1 AF export family.

---

## 5. RP1 AF family contract

### Dual-sensor output

The RP1 AF export family is dual-sensor aware:

* the family still uses the single name `rp1_af_exports`
* both VIIRS and MODIS branches are emitted
* schemas are selected by sensor and export family
* the skip-existing completeness checks treat RP1 AF files as part of the
  expected additive combine state

### Fixed processing semantics

The following processing rules are governed independently of the RP1 AF export family:

* raw FIRMS preparation logic
* TYPE filtering logic
* confidence mapping logic
* deduplication logic
* monthly aggregation logic
* balanced panel semantics

---

## 6. RP1 AF windows

The RP1 AF family is clipped to fixed sensor-specific windows:

* **VIIRS:** `201201`–`202412`
* **MODIS:** `200101`–`202412`

These windows apply only to the dedicated RP1 AF family.

They do **not** redefine:

* the broader processing windows
* the sensor coverage settings used in combined panels
* the month span of `panel_monthly` unless you explicitly combine over the same
  range

---

## 7. RP1 AF path and naming behaviour

Base pattern:

```text
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_<partition_key>_<partition_value>.csv[.gz]
```

`_ext` pattern:

```text
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_ext_<partition_key>_<partition_value>.csv[.gz]
```

Key interpretation points:

* `sensor_mode` is in the path, not in the CSV body
* partition naming is generic and derived from the Stage 1 hierarchy contract
* do not assume the partition key is always `acz_code`

---

## 8. RP1 AF manifest behaviour

`combine_panels_manifest.json` contains an RP1 AF block with:

* family metadata
* source artefacts
* merge keys
* schema version
* `sensor_modes`

  * `partition_basis`
  * `window`
  * `schemas`
  * `levels`

This manifest is the main completeness proof used by `combine --skip-existing`.

If a sensor branch is missing from that manifest, the combine stage is treated as
incomplete even if some RP1 AF files still exist on disk.

---

## 9. Common interpretation cautions

* Do not treat `rp1_af_exports` as the primary contracted repository output.
* Do not expect a `sensor_mode` column inside RP1 AF CSV files.
* Do not assume one shared RP1 AF window for VIIRS and MODIS.
* Do not assume that the existence of `panel_monthly.csv` alone is enough for a
  safe `combine --skip-existing` return.

