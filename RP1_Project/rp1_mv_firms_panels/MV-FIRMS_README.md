# mv_firms_panels

`mv_firms_panels` is the deterministic Stage 2 pipeline for converting annual
NASA FIRMS active-fire detections into monthly polygon panels for Ghana.

The implementation supports:

- annual canonical preparation of FIRMS detections
- monthly aggregation by configured polygon levels
- combination of VIIRS and MODIS into a balanced monthly panel
- additive extended, QC, split, range-tagged, and RP1 merger-ready outputs
- manifests and QA summaries intended for audit-grade reruns

## Clean-clone assumption

Treat raw FIRMS inputs, mirrored boundary files, and mirrored unit-universe
files as expected local staging destinations rather than bundled repository
assets.

Use:

- `docs/data_access.md`
- `RP1_Project/docs/external_data_contract.md`

for the authoritative access, licensing, staging, and regeneration rules.

## Required staged inputs

The promoted Stage 2 config expects these local paths:

- `data/metadata/unit_universe.csv`
- `data/raw/boundaries/gha_admin0.shp`
- `data/raw/boundaries/acz.shp`
- `data/raw/boundaries/districts_within_acz.shp`
- `data/raw/modis/*.shp`
- `data/raw/viirs/*.shp`

Input provenance:

- `data/metadata/unit_universe.csv`
  mirrored from `geo_data_prep/out/example_acz/unit_universe.csv`
- `data/raw/boundaries/acz.*`
  mirrored from `geo_data_prep/out/example_acz/boundaries/acz.*`
- `data/raw/boundaries/districts_within_acz.*`
  mirrored from
  `geo_data_prep/out/example_acz/boundaries/districts_within_acz.*`
- `data/raw/boundaries/gha_admin0.*`
  staged Ghana admin-0 boundary family used as the land mask / AOI surface
- `data/raw/modis/*.shp`
  yearly MODIS FIRMS archive shapefile families
- `data/raw/viirs/*.shp`
  yearly VIIRS FIRMS archive shapefile families

## How to stage the FIRMS inputs

Source portal:
- `https://firms.modaps.eosdis.nasa.gov/download/`

Product overview:
- `https://www.earthdata.nasa.gov/data/tools/firms`

Stage the yearly files under separate sensor folders:

- `data/raw/modis/`
- `data/raw/viirs/`

Required project rename convention:

- `MODIS_<YYYY>.{shp,shx,dbf,prj,cpg}`
- `VIIRS_<YYYY>.{shp,shx,dbf,prj,cpg}`

Sensor split and RP1 windows:

- MODIS archive files feed the long-run RP1 window:
  `200101` to `202412`
- VIIRS archive files feed the overlap RP1 window:
  `201201` to `202412`

The current local checkout may contain broader yearly surfaces, but the
supported RP1 export windows remain the ones above.

## Pipeline stages

### Stage 1 - `prepare-year`

Reads one year of raw FIRMS points for a single sensor and writes canonical
annual detections.

### Stage 2 - `aggregate`

Aggregates canonical annual detections into monthly sensor panels.


### Bounded-memory full-window aggregation

The production `aggregate` stage processes canonical `prepare-year` outputs one annual
partition at a time when they follow the governed
`fires_canonical_<sensor>_<YYYY>.csv` naming contract. Monthly scientific metrics are
computed with the same algorithms as the in-memory path and the annual results are then
concatenated deterministically. Because the annual partitions have disjoint calendar-month
support, this changes peak memory use rather than the estimand or metric definitions. The
stage fails closed if annual partitions overlap at the `(level, unit_id, yyyymm)` grain.
Arbitrary caller-supplied file lists that do not follow the canonical annual naming contract
retain the legacy in-memory behaviour.

### Stage 3 - `combine`

Combines the monthly VIIRS and MODIS panels into a balanced unit-by-month panel
and writes additive sidecars.

### Stage 4 - `visualise`

Reads the combined panel and writes deterministic summaries and, optionally,
figures.

## Quick start

Run the promoted RP1 pipeline from the repository root:

```bash
python -m mv_firms_panels.cli.main --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml --run-id ghana_full pipeline --years-modis 2001-2024 --years-viirs 2012-2024
```

Useful stage-specific commands:

```bash
python -m mv_firms_panels.cli.main --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml --run-id ghana_full prepare-year --sensor viirs --year 2024
python -m mv_firms_panels.cli.main --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml --run-id ghana_full aggregate --sensor viirs --start-yyyymm 201201 --end-yyyymm 202412
python -m mv_firms_panels.cli.main --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml --run-id ghana_full combine --start-yyyymm 200101 --end-yyyymm 202412
```

## Contracted and additive outputs

Formal contracted combined output:

```text
out/runs/<run_id>/panel_monthly/panel_monthly.csv[.gz]
```

Important additive outputs:

```text
out/runs/<run_id>/panel_monthly/panel_monthly_ext.csv[.gz]
out/runs/<run_id>/panel_monthly/panel_monthly_qc.csv[.gz]
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/...
out/runs/<run_id>/qa/*.json
```

These additive artefacts do not replace the contracted `panel_monthly` table.

## RP1 merger-ready interface

Stage 3 consumes the `rp1_af_exports` family built by `combine`.

Family name:

```text
rp1_af_exports
```

Output path patterns:

```text
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_<partition_key>_<partition_value>.csv[.gz]
out/runs/<run_id>/rp1_af_exports/<level>/<sensor_mode>/rp1_af_<level>_ext_<partition_key>_<partition_value>.csv[.gz]
```

Current partition basis:

- `<ACZ>` is one of `CZ`, `FZ`, `GS`, `SS`, or `TZ`

These Stage 2 outputs are consumed by `RP1_Project/merge_af_ba_panels.py`.

## Installed CLI

Installation exposes `mv-firms-panels`. Common operational options, including `--config`, may be placed before or after the subcommand. Both of the following forms are supported:

```bash
mv-firms-panels --config configs/ghana_full.yaml pipeline --dry-run
mv-firms-panels pipeline --config configs/ghana_full.yaml --dry-run
```

Stage-specific forms follow the same rule:

```bash
mv-firms-panels prepare-year --config configs/ghana_full.yaml --sensor viirs --year 2024
mv-firms-panels aggregate --config configs/ghana_full.yaml --sensor viirs
mv-firms-panels combine --config configs/ghana_full.yaml
mv-firms-panels visualise --config configs/ghana_full.yaml
mv-firms-panels pipeline --config configs/ghana_full.yaml
```

The module form `python -m mv_firms_panels.cli.main` uses the same parser and remains available.

## CLI safety behavior

### `--skip-existing`

Safe resume is not a simple file-exists shortcut. A stage may be skipped only
when the sentinel or manifest exists and the expected outputs pass contract
checks.

### `--force`

Forces rerun even when outputs and manifests already exist.

### Fail-fast provenance rule

If outputs exist but the sentinel or manifest is missing, the CLI raises
instead of silently reusing artefacts with unknown provenance.

## Configuration note

The promoted RP1 config is:

```text
configs/ghana_full.yaml
```

That config is authoritative for:

- local input path expectations
- sensor windows
- RP1 export windows
- schema bindings
- additive output families

## Validation

```bash
pytest -q
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml pipeline --dry-run
```

## Further documentation

- `docs/data_access.md`
- `RP1_Project/docs/external_data_contract.md`
- `configs/ghana_full.yaml`
