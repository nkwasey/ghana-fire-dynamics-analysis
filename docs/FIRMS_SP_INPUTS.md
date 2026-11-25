# Archive SP active-fire inputs

The production FIRMS configuration reads annual MODIS Terra/Aqua and VIIRS
Suomi-NPP standard-processing exports prepared by Ghana Fire Archive. NOAA-20
and NOAA-21 are separate products and are not part of this study input. Preserve
the admitted numerical values and complete shapefile families. The Archive
country-filters, validates and measurement-deduplicates these exports before handoff;
they are analytical inputs rather than untouched NASA downloads.

## Environment and working directory

Run the following commands from the RP1 repository root in a dedicated Conda
environment. RP1 and its embedded Archive producer use the same Python 3.13
environment, including the declared `requests` and `pyshp` dependencies.

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
python tools/qualify_source_checkout.py --origins-only
```

All four project package origins (`geo_data_prep`, `mv_firms_panels`,
`rp1_analysis_v1`, `ghana_fire_archive`) and `rp1_ba_contracts.c3` must identify this
checkout. Do not switch another checkout's editable installation in the same
environment during a run. Use a matching notebook kernel and repeat the origin
check before processing. The commands below use relative paths so they work from
the same checkout in PowerShell and WSL; when using absolute paths, use Windows
paths in PowerShell and `/mnt/c/...` paths in WSL.

For an existing environment, follow the
[dependency update and editable installation commands](ENVIRONMENT_AND_RECOVERY.md#conda-environment-and-editable-packages).
See [analysis input validation and kernel setup](ANALYSIS_EXECUTION.md#input-validation)
when starting Stage 5. Windows and WSL/Linux require separate environments and
kernels.

## Automated Archive workflow

The [root runbook](../README.md) starts with geography and burned-area
admission. In Stage 3, run `archive-plan`, `archive`, `archive-admit` and
`firms` with the same `configs/workflow.json` and workflow run ID used for
geography. The consumer `data/raw/` is empty in the ZIP. The producers create
its inputs. Follow the [Archive integration guide](FIRMS_ARCHIVE_INTEGRATION.md)
for mode selection, prerequisites and downstream commands.

`firms_archive.mode` selects one of three routes:

| Mode | Source and operation |
|---|---|
| `build` (default) | Acquire and prepare MODIS and Suomi-NPP SP using the native producer, then validate and admit its annuals. The default workflow is suitable for the empty consumer tree. |
| `existing` | Read an existing whole Archive and run the current producer API's full archive validation with QA verification. The source archive remains unchanged. |
| `bundled` (optional) | Verify separately available, already admitted shared inputs. It requires an explicitly configured populated tree; the fresh ZIP supplies none. Recorded source authority is preserved rather than claiming new producer validation. |

The native producer lives in `RP1_Project/rp1_firms_archive`: `src/` holds the
package, `configs/rp1.yaml` selects MODIS and Suomi-NPP, `data/reference/` holds
the admitted reference geography, `data/raw/` is the local acquisition cache, and
`out/runs/<run-id>/` holds generated Archive products. Keep acquired inputs, metadata and outputs local, and store any NASA key
outside the repository; see the integration guide for build setup.

For an existing whole Archive, run from the repository root:

```bash
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study archive-plan --archive-manifest '/absolute/path/archive-manifest.json'
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study archive
```

Use an absolute Windows path, such as `C:/Archive/study/archive-manifest.json`,
in PowerShell; use the corresponding Linux path in WSL. The first command is
a local preview. The second validates the selected archive, its exports,
coverage, source bytes and QA sidecars through the current producer API.
It records current validator identity separately from the archive's original
generation code identity. An old `verification.json` alone is insufficient.

Before admission, complete a verified `geo` handoff or explicitly reuse the
unchanged current handoff. The reuse route verifies the original generation
authorities and staged files, writes only a new workflow receipt, and preserves
the original geography run and QA status:

```bash
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study geo-reuse
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study archive-admit
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study firms
```

The manifest override is bound by the first Archive request and reused by later
stages. `geo-reuse` creates no new GEE upload assets; a fresh `geo` run is required
to generate a new upload bundle. Reuse does not establish new scientific
approval of the geography or remote assets.

Admission extracts the accepted five ZIP members unchanged into
`RP1_Project/rp1_mv_firms_panels/out/runs/archive_study/source_inputs/` and binds
the generated FIRMS configuration to that bundle. It copies the acceptance,
selected coverage, original provenance, field dictionaries and QA evidence.
It does not replace shared `data/raw/modis` or `data/raw/viirs`.

The full January 2001–December 2024 study requires **37 source-year families**:
24 MODIS years and 13 Suomi-NPP years. Suomi-NPP starts on **20 January 2012**;
that checked partial first month is accepted. Missing, unavailable or unchecked
required intervals fail, and a later partial interval cannot become a complete
study year. An explicitly validated zero-record year remains distinct from
unavailable coverage and from GEE upload readiness. NOAA-20/21 remain excluded.

## Prepare standard-processing inputs

The source ZIP contains no consumer fire annuals, staged boundaries or intake
authority under `rp1_mv_firms_panels/data/raw/`. It retains the geography
source references and all 370 c3 GEE CSV exports. Complete Stages 1 and 2 in
the [root runbook](../README.md). Configure a NASA MAP_KEY locally as described
in the integration guide, then run Stage 3 from the RP1 root using the same ID:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-plan
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-admit
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study firms
```

`archive-plan` is offline. `archive` downloads/verifies NASA originals and
prepares annuals plus QA. `geo` stages boundaries and unit metadata. Admission
writes the 37 required fire annual families to the run-local bundle and
configures the consumer; `firms` then produces monthly inputs. The shared raw
folder acquires boundaries through `geo`, rather than starting with precomputed
files. On an occupied working copy, `geo-reuse` is an optional read-only route
for an unchanged verified handoff. A fresh extraction must run `geo`.
Packaging does not remove existing working data.

The remaining intake sections describe the optional curated-input
plan/stage/activate interface. They are not needed by the automated workflow. Select
fresh staging/backup paths and retain a matching baseline before activating
different source bytes.

## Verify a replacement curated source

The intake tool uses the Archive's `annual-export.json`, annual ZIP hashes,
yearly provenance and field dictionaries. It requires every curated component
to match its accepted ZIP member. Only `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg`
are admitted; unrelated temporary files fail admission. Source/product,
processing, satellite, instrument, version and DBF record count are checked.

For the sibling-folder layout used by this project, review the source without
writing or activating data:

```bash
python tools/import_firms_archive_sp.py plan --curated ../raw --archive-annual ../Ghana_Fire_Archive/output/annual
```

The curated layout is:

```text
raw/MODIS_SP/Ghana_MODIS_SP_YYYY.{shp,shx,dbf,prj,cpg}
raw/VIIRS_SP/Ghana_VIIRS_SNPP_SP_YYYY.{shp,shx,dbf,prj,cpg}
```

This verifies delivery identity. Preparation performs the additional geometry,
CRS, acquisition date/time, observation identity and scientific field checks.
Source authenticity does not independently establish physical validity of an
observation or qualify a scientific result.

## Stage a fresh input bundle

Choose a staging directory that does not exist and is outside the active FIRMS
subproject. The stage command preserves source bytes and copies only the two
selected products and their governed provenance companions.

```bash
python tools/import_firms_archive_sp.py stage --curated ../raw --archive-annual ../Ghana_Fire_Archive/output/annual --destination ../firms_sp_staged
python tools/import_firms_archive_sp.py verify --staged ../firms_sp_staged
```

The staged bundle uses the FIRMS subproject layout:

```text
data/raw/modis/Ghana_MODIS_SP_YYYY.*
data/raw/viirs/Ghana_VIIRS_SNPP_SP_YYYY.*
data/raw/source_provenance/archive_sp_intake.json
data/raw/source_provenance/annual-export.json
data/raw/source_provenance/modis/*_{provenance,fields}.json
data/raw/source_provenance/viirs/*_{provenance,fields}.json
```

The intake manifest binds every family and component, record count, native
versions and source lineage. Referenced provenance/dictionaries are local,
hash-verified source authorities retained with that staged runtime bundle.
They are excluded from the upstream-first source ZIP along with its fire inputs.
NASA keys, caches and original large download inputs are not copied.

## Activate and preserve rollback

Before activation, preserve a complete matching baseline of project code,
configuration, source manifests, workflow/analysis inputs, generated authorities
and accepted runs. Quiesce processing jobs that use the active inputs. The
intake tool's backup covers the active sensor/provenance directories; it is not
a substitute for that full baseline.

Choose a new backup directory outside the FIRMS subproject:

```bash
python tools/import_firms_archive_sp.py activate --staged ../firms_sp_staged --backup ../firms_sp_raw_backup
```

The tool re-verifies the stage, records the old directory inventories, moves the
complete old sensor/provenance directories to the backup, activates the verified
directories and checks the result. A detected activation failure restores the
old directories and returns the new directories to staging. Existing stage and
backup destinations are never overwritten. Retain `activation.json` and
`activation_complete.json` with the baseline. No scientific pipeline runs as a
side effect of activation.

For a later rollback, quiesce processing, move the new active directories to a
fresh quarantine directory, and restore the saved directories at the recorded
active root. Restore the matching old source/configuration/analysis authorities
from the full baseline, then verify hashes and package origins. Keep failed new
run diagnostics. Do not mix restored old data with new input authorities.

## Configuration and scientific policy

The automated workflow generates the following form for a run-local bundle;
paths inside the authority remain relative to `admission_bundle_root`:

```yaml
input_profile: ghana_firms_archive_sp_v1
admission_bundle_root: out/runs/archive_study/source_inputs
admission_manifest: data/raw/source_provenance/archive_sp_intake.json
file_glob: out/runs/archive_study/source_inputs/data/raw/viirs/Ghana_VIIRS_SNPP_SP_*.shp
```

The Archive profile preserves its 19 scientific fields and source values. The
workflow sets the matching MODIS glob automatically. Do not edit an old generated
configuration to substitute a new bundle.

The production `RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml` and the
Archive example select these settings for each sensor:

```yaml
input_profile: ghana_firms_archive_sp_v1
admission_manifest: data/raw/source_provenance/archive_sp_intake.json
```

These unchanged shared-input templates use the MODIS glob
`data/raw/modis/Ghana_MODIS_SP_*.shp` and VIIRS glob
`data/raw/viirs/Ghana_VIIRS_SNPP_SP_*.shp`. They are not populated in the fresh
checkout. The root workflow rebases those paths to the admitted run-local
bundle automatically; do not run the unmodified template directly on the
empty consumer tree. The adapter derives coordinates from
verified WGS84 points, converts `HH:MM` exactly, uses `conf_raw` for original
confidence, converts `fire_type` strictly and normalises Suomi-NPP to the
existing canonical satellite label. It supplies native-style fields to the
existing column map. `configs/example_project.yaml` remains the native-format
example with default `native_firms_v1` profile.

Retain TYPE=0, the RP1 national mask and spatial joins, count-stream deduplication,
and independently selected/deduplicated VIIRS nominal/high FRP. Primary counts
and persistence use nominal/high after count-stream deduplication. FRP is based
on unit-day maxima and monthly means over eligible UTC active days. FRP support
may occur where nominal/high count support is zero. Preserve missing support
and source FRP values, including valid zero and high finite values; investigate
their influence through QA rather than silently changing observations.

Raw coverage may exceed the study. The root workflow remains January
2001–December 2024, with native VIIRS source support from January 2012. Analysis
uses paired monthly support from February 2012 and complete paired years
2013–2024. The intake inventory does not change those windows or add NOAA data.

## Use changed inputs in a new run

Choose unused workflow and analysis run IDs after changing source bytes,
configuration or input profile. Update the source template, not an old generated
configuration snapshot. Preparation reuse validates current source families,
intake/configuration/geography identities and prepared outputs for both sensors;
paired VIIRS FRP evidence remains mandatory.

Rebuild annual active-fire preparation, monthly panels, AF exports, merged
panels and the analysis handoff under the new run. Existing c3 source bytes and
geography may remain unchanged, but the workflow needs genuine new-run local
preparation/admission receipts. Re-exporting burned area from Earth Engine is
not required solely for this active-fire update. Do not retag old receipts.

The workflow stages analysis inputs into its fixed
`RP1_Project/rp1_analysis/data/raw`. Archive the old populated bundle together
with its hash inventory and generated authorities before normal fresh staging.
Move the old `RP1_Project/rp1_analysis/data/input_sha256.json` out of the active
tree as part of that archival. Keeping a copy at its old location correctly
prevents the new handoff from replacing its recorded source origins. The normal
provenance generator creates a fresh inventory when the old one is absent;
Preserve the original hashes and source identities.
`--resume-analysis-inputs` only resumes the same verified interrupted handoff;
A different input bundle needs a new handoff. Follow the root README's workflow
commands with one unused run ID throughout.

Regenerate RQ3 input support/cohorts/models and VIIRS case inputs/scans. Verify
burned-area-only numerical invariants and use genuine external scan results
bound to exact new-run inputs. Regenerate publication and source/package
authorities even when a numerical result is unchanged. Preserve the existing baseline for comparison and validate the new input bundle,
workflow and scientific results.
## Existing geography handoff

For an unchanged verified handoff, prefer the explicit read-only `geo-reuse`
route above. It retains original generation provenance and QA status. Use the
replacement operation below only when generating and applying new geography.

The workflow refuses existing geography targets by default. When updating an
occupied checkout, preserve its complete baseline first, then use a fresh run ID
and an explicit, fresh absolute backup directory for the geography handoff:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id rp1_sp_run --geo-backup /absolute/path/to/fresh_geo_backup geo
```

In Windows PowerShell, use an absolute Windows path for `--geo-backup`, such as
`C:/RP1_backups/rp1_sp_geo`. The option invokes the existing verified-backup and
rollback procedure; it does not permit overwriting a backup or reusing a completed
workflow run. Retain the backup and its manifest with the original analysis
baseline. A failed run's diagnostic directories should be preserved; choose a
fresh run ID after resolving the failure.

