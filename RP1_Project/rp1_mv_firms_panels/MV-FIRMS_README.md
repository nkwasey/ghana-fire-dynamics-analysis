# mv_firms_panels

`mv_firms_panels` is the deterministic active-fire panel component in Stage 3 for converting annual
NASA FIRMS active-fire detections into monthly polygon panels for Ghana.

The implementation supports:

- annual canonical preparation of FIRMS detections
- monthly aggregation by configured polygon levels
- combination of VIIRS and MODIS into a balanced monthly panel
- additive extended, QC, split, range-tagged, and RP1 merger-ready outputs
- manifests and QA summaries intended for audit-grade reruns

## Supplied and staged inputs

The upstream workflow stages fire annuals, analysis boundaries and the intake
manifest under this subproject. It also generates `data/metadata/`. The default root workflow selects
`build`: `../rp1_firms_archive` downloads/prepares MODIS and Suomi-NPP SP,
and `geo_data_prep` prepares/stages the boundaries and unit metadata. Use the
automated `geo`, then Stage 3 `archive-plan`, `archive`, `archive-admit`, `firms` stages.
Stage the source geography through
the [data access guide](../../docs/data_access.md). The 370 original Earth Engine
CSV inputs are in the burned-area component. The shared Python 3.13 environment installs all
four projects editably, including `requests` and `pyshp` for the producer. Verify
their origins from the repository root before processing.

`existing` mode runs current whole-archive API validation with QA verification
without changing its source; `build` performs explicit acquisition/preparation.
Optional `bundled` mode requires separately available admitted shared inputs;
it retains recorded source authority where applicable. Original source generation code
and current validator identity remain separate. See the
[Archive integration guide](../../docs/FIRMS_ARCHIVE_INTEGRATION.md).

The selected geography workflow generates boundary and unit-universe inputs.
An explicit read-only `geo-reuse` can verify an unchanged existing handoff and
its original generation evidence, preserving its run identity and QA status.
It does not create new GEE assets. Follow the repository-root README for the
complete handoff and execution sequence.

## Required staged inputs

After the upstream workflow completes, the configured consumer expects these
local paths. The workflow generates them:

- `data/metadata/unit_universe.csv`
- the workflow-selected EPSG:32630 national AOI land-mask shapefile
- `data/raw/boundaries/acz.shp`
- `data/raw/boundaries/districts_within_acz.shp`
- annual fire families selected by the generated run-local input configuration

For Archive admissions, the generated FIRMS configuration selects
annual families under `out/runs/<run-id>/source_inputs/data/raw/<sensor>/`.
`admission_bundle_root` confines the authority and its component/acceptance/QA
references to that run-local bundle. Shared `data/raw` inputs are not replaced.

Input provenance:

- `data/metadata/unit_universe.csv`
  mirrored from `geo_data_prep/out/<run-id>/unit_universe.csv`
- `data/raw/boundaries/acz.*`
  mirrored from `geo_data_prep/out/<run-id>/analysis_boundaries/acz.*`
- `data/raw/boundaries/districts_within_acz.*`
  mirrored from
  `geo_data_prep/out/<run-id>/analysis_boundaries/districts_within_acz.*`
- the workflow-selected national AOI bundle
  transformed from the configured national source and verified in the GEE upload handoff
- `out/runs/<run-id>/source_inputs/data/raw/modis/*.shp`
  yearly MODIS annuals admitted from the producer
- `out/runs/<run-id>/source_inputs/data/raw/viirs/*.shp`
  yearly Suomi-NPP annuals admitted from the producer

## How to stage the FIRMS inputs

After Conda and local NASA key setup, use the default workflow from the RP1
repository root for a fresh extraction. Complete `geo` before `archive-admit`:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study geo
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-plan
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-admit
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study firms
```

`archive-plan` is an offline preview; `archive` performs acquisition and
preparation. Optional existing mode uses the separately documented existing
template and a prepared manifest (an absolute Windows path for PowerShell or
Linux path for WSL). In an occupied checkout, `geo-reuse` is available only
for unchanged verified geography. Run `geo` to prepare geography in a new checkout.
The accepted five ZIP members are extracted
unchanged, with acceptance, selected coverage, provenance, field dictionaries
and QA evidence carried through preparation, reuse, combine and merger inputs.
The upstream district/zone attributes do not replace RP1 analytical joins.
Reporting polygons and the land mask must declare their CRS. Preparation
reprojects them as needed and rejects an undeclared spatial reference.

For the configured 2001–2024 study, admission requires 37 source-year families: MODIS 2001–2024 and
Suomi-NPP 2012–2024. The first supported Suomi-NPP interval begins on
20 January 2012. Missing, unavailable or unchecked required coverage fails.
A verified zero-record year is accepted with empty observed lineage; its
GEE-upload readiness remains false. NOAA products are excluded.

The following manual layout describes the native-format `native_firms_v1`
interface. The optional curated Archive `plan`/`stage`/`activate` interface and
rollback procedure remain documented in
[Archive SP inputs](../../docs/FIRMS_SP_INPUTS.md).

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

A standalone panel configuration may use broader source coverage. The root
workflow sets the study and dedicated RP1 export windows shown above.

## Confidence and fire radiative power

Monthly primary detection counts use nominal- and high-confidence detections.
FRP statistics use nominal/high confidence for both VIIRS and MODIS. VIIRS
selects these observations before independent FRP deduplication; the count
stream keeps its established deduplication. A recovered FRP observation can
therefore occur where the nominal/high count is zero. Low-confidence detections may still be retained in separate
diagnostic counts when configured, but do not enter primary FRP statistics.
A further configurable minimum-FRP gate and valid numeric FRP requirement apply,
so the actual FRP records need not equal the detection-count records.

Within each spatial unit and UTC day, the maximum eligible FRP (MW) is found.
The monthly `frp_mean_mw` is the sum of these daily maxima divided by the
number of UTC days with eligible FRP; it is missing when there are no such
days. It is not the arithmetic mean across detections or calendar days.
Consult `../docs/rq3_frp_method.md` for interpretation and regeneration.

## Pipeline stages

### Processing step 1 - `prepare-year`

Reads one year of raw FIRMS points for a single sensor and writes canonical
annual detections.

### Processing step 2 - `aggregate`

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
retain the in-memory processing.

### Processing step 3 - `combine`

Combines the monthly VIIRS and MODIS panels into a balanced unit-by-month panel
and writes additive sidecars.

### Processing step 4 - `visualise`

Reads the combined panel and writes deterministic summaries and, optionally,
figures.

## Quick start

Use the root workflow above. It writes `configs/generated/<run-id>.yaml`
with the admitted run-local annuals and staged geography before invoking this
component. The standalone `configs/ghana_full.yaml` template
expects separately prepared inputs at its shared paths.

For component-level inspection after a matching admission/configuration has
been generated, consult its CLI help:

```bash
python -m mv_firms_panels.cli.main --help
```

Use the generated configuration and its bound run ID for stage-level work;
existing contracted outputs are protected. Follow the root guide for a fresh
run rather than changing bound inputs or reusing another run's receipt.

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

Root workflow Stage 4 consumes the `rp1_af_exports` family built by `combine`.

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

These Stage 3 outputs are consumed by `RP1_Project/merge_af_ba_panels.py`.

## Installed CLI

Installation exposes `mv-firms-panels`. Common options may be placed before
or after the subcommand. From this subproject directory, these equivalent
commands preview the 2024 stages without creating outputs:

```bash
mv-firms-panels --config configs/ghana_full.yaml pipeline --years 2024 --dry-run
mv-firms-panels pipeline --config configs/ghana_full.yaml --years 2024 --dry-run
```

The module form `python -m mv_firms_panels.cli.main` uses the same parser.
See the [component user guide](docs/user_guide.md) for stage commands that
use the generated configuration and its matching run ID.

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

The root workflow uses `configs/ghana_full.yaml` as an input template for
schema bindings and output families. It writes a run-local configuration
with stage-specific input paths and study windows from the root configuration.
When explicitly using the template as a standalone configuration, supply the
files and coverage declared in it.

## Validation

```bash
python -m pytest -q
python -m mv_firms_panels.cli.main --config configs/ghana_full.yaml pipeline --years 2024 --dry-run
```

## Further documentation

- [Staging inputs](#how-to-stage-the-firms-inputs)
- [External data contract](../docs/external_data_contract.md)
- `configs/ghana_full.yaml`


## Configured study windows

The root workflow propagates its declared study and source support into the
generated consumer configuration and formal AF export windows. Completeness
is checked against the declared study period.
The configured study uses MODIS 2001–2024 and Suomi-NPP 2012–2024. A standalone
configuration can request a different supported period; it must supply complete
source evidence and a consistent export contract. A shorter input archive
cannot satisfy a longer declaration. See
[study configuration](../../docs/STUDY_CONFIGURATION.md).
