# FIRMS archive acquisition and RP1 handoff

The archive is a native, independently installable subproject at
`RP1_Project/rp1_firms_archive/`, alongside `rp1_mv_firms_panels` and
`rp1_analysis`. It retains the `ghana_fire_archive` import and
`ghana-fire-archive` command. Its source can be copied or packaged separately;
it does not import the RP1 workflow, panels package or analysis package.

## Responsibilities and locations

| Component | Responsibility | Working files |
| --- | --- | --- |
| `rp1_firms_archive` | NASA acquisition, scope evidence, source-preserving preparation, annual export, scientific validation and QA | `data/raw/`, pinned `data/reference/geography/`, `out/runs/<run-id>/` |
| Root workflow | Freeze the study/source request, validate the producer, verify geography compatibility and orchestrate admission | `out/workflows/<run-id>/archive*.json`, `archive_validation/` |
| `rp1_mv_firms_panels` | Verify admitted annual components, apply RP1 TYPE/confidence/deduplication, join RP1 polygons, prepare monthly panels and AF exports | `out/runs/<run-id>/source_inputs/`, normal preparation and export directories |
| c3 merger and analysis | Combine admitted AF and BA, preserve support evidence, and run the selected study | Existing stages and output contracts |

The producer supplies complete annual point shapefile ZIPs. Admission extracts
only the required MODIS and Suomi-NPP families, without changing component
bytes. It records checksums of the original annual ZIPs but retains no second
copy of them. Copied manifests, QA sidecars and geography evidence accompany
the staged components. The consumer's original shared `data/raw/` tree is not
activated, overwritten or deleted by this route.

The default workflow acquires annual fire detections with the Archive and
prepares the analytical boundaries and unit metadata with `geo_data_prep`.
The consumer's `data/raw/` and `data/metadata/` are populated by the
workflow. Use [source geography admission](SOURCE_GEOGRAPHY.md) to verify the
supplied study shapefiles and stage the separately obtained archive reference
files before starting. The producer's `data/raw/` is a local NASA download cache. Retain
the 370 Earth Engine exports included with the repository as inputs to the
burned-area preparation step.

## Install

Use Anaconda Prompt or a Conda-enabled PowerShell/WSL shell. From the RP1
repository root:

```text
conda env create -f environment.yml
conda activate rp_ghana_fire
python tools/qualify_source_checkout.py --origins-only
ghana-fire-archive --version
```

For an existing environment, follow the
[dependency update and editable installation commands](ENVIRONMENT_AND_RECOVERY.md#conda-environment-and-editable-packages).
The Archive requires `requests`, `PyYAML`, `pyshp` and `shapely`, as declared in
the environments and package metadata. All four imports must resolve to the
intended checkout. Use a separate environment for a different active checkout.

The standalone alternative is to enter `RP1_Project/rp1_firms_archive/`, create
its own `environment.yml`, and activate `ghana-fire-archive`. Consult that
subproject's README for its full acquisition, validation and packaging CLI.
No `.venv` paths are required in user commands.

## Set up the NASA FIRMS MAP_KEY

For build-mode acquisition, follow [NASA FIRMS key setup](FIRMS_KEY_SETUP.md).
That guide covers the required environment/origin checks, hidden prompts in
WSL and PowerShell, an external one-line key file and an effective local
status check that follows the selected producer configuration. Environment
values take precedence over `key_file`; neither the key nor a key file belongs
in the repository. Existing-archive and bundled-input validation require no
key and make no NASA requests. Local presence/format checks do not establish
NASA authorisation.

## Choose an input mode

| Mode | Configuration | Effect of `archive` |
| --- | --- | --- |
| `build` (default) | `configs/workflow.json` or `configs/workflow_archive_build.example.json` | Acquire NASA inputs, prepare annual ZIPs and verify the resulting Archive. The separate `archive-admit` step stages annuals for the consumer. |
| `existing` | `configs/workflow_archive_existing.example.json` | Read-only scientific, annual ZIP and QA validation of an existing producer archive. |
| `bundled` (optional) | `configs/workflow_bundled.example.json`, requiring separately available admitted inputs | Verify an already populated shared input bundle. This requires separately prepared shared inputs. |

The `firms_archive` block accepts `mode`, `manifest`, `producer_config`, and
`geography_policy`. Paths to existing producer manifests may be absolute or
relative to the RP1 root. Producer configuration paths must be inside RP1.
The supported geography policy is
`pinned_archive_population_rp1_rejoin_v1`; unknown policies reject.

`archive-plan` is a local preview. It freezes the request and reports selected
mode/study without downloading or querying NASA. In contrast, the standalone
`ghana-fire-archive plan` command queries provider availability.

### Stage 3: acquire, prepare and hand off active-fire inputs

Complete Stage 1 geography and Stage 2 burned-area admission using the root
README. From the repository root, with the Conda environment active and the
NASA key configured, run the Stage 3 commands sequentially:

```text
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-plan
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-admit
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study firms
```

`archive` owns NASA acquisition, canonical preparation, annual shapefile
exports, QA and full archive validation. Integrated acquisition derives years
from `study.start_yyyymm` and `study.end_yyyymm` in the root configuration.
It explicitly selects MODIS_SP and VIIRS_SNPP_SP; source availability must pass
provider and validation checks. The standalone preset's independent year range
does not redefine the integrated scientific study.

Stage 1 `geo` generates the analytical boundaries and unit metadata. Admission
stages the required annual components and their evidence under
`RP1_Project/rp1_mv_firms_panels/out/runs/ghana_fire_study/source_inputs/`.
`firms` generates its own configuration pointing at this accepted bundle and
Stage 1 geography. No manual detection copying is required. Do not run an
standalone panels command before its inputs are staged.

After Stage 1, shared consumer `data/raw/` contains generated boundaries;
fire detections remain under the run-local `source_inputs/` tree. Stage 4
merges these AF exports with the Stage 2 admitted BA bundle. Stage 5 stages
complete scientific inputs and executes the analysis. Use the same root
configuration and workflow ID throughout. See the
[root runbook](../README.md) and [study configuration](STUDY_CONFIGURATION.md).

### Optional existing archive

An existing prepared archive can be validated read-only instead of downloaded.
Choose a fresh ID and complete Stage 1 with the existing-mode configuration:

```text
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_existing_c3 geo
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_existing_c3 archive-plan --archive-manifest /absolute/path/to/archive-manifest.json
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_existing_c3 archive
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_existing_c3 archive-admit
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_existing_c3 firms
```

The manifest override is frozen in `archive_request.json` and reused. It need
not be repeated. Alternatively set `firms_archive.manifest` in a copied
configuration before starting. In PowerShell quote a Windows path such as
`"C:/path/to/archive-manifest.json"`; in WSL use a Linux path such as
`"/mnt/c/path/to/archive-manifest.json"`. Replace the example with the actual
local file. Only the `archive` mode changes; BA preparation, merge and analysis
still need the same selected study and verified geography.

For an occupied checkout, read-only `geo-reuse` is available only when the
original generation evidence, source boundaries, configuration and staged
geography are unchanged. Use it instead of `geo`, not in addition to it.
It retains original identity and QA and creates no new GEE assets. Changed
geography requires a fresh geography run and appropriate BA source/asset
review. See [geography handoff](GEO_HANDOFF.md).

### Standalone acquisition by year or year range

The producer remains independently installable. Its own configuration controls
sensor selection, acquisition years, cache, reference geography and output root.
The two-sensor `configs/rp1.yaml` preset and four-sensor `configs/archive.yaml`
are independent of the root workflow's study settings. The four-sensor preset
also supports NOAA-20 and NOAA-21; these do not augment the integrated study.

From the repository root, a bounded standalone test is:

```text
ghana-fire-archive plan --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --year 2024 --run-id archive_2024_test
ghana-fire-archive download --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --year 2024 --run-id archive_2024_test
ghana-fire-archive prepare --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --year 2024 --run-id archive_2024_test
ghana-fire-archive verify --manifest RP1_Project/rp1_firms_archive/out/runs/archive_2024_test/archive-manifest.json
```

Standalone `plan` queries NASA availability. `download` acquires or verifies
cached originals and receipts; `prepare` creates canonical data, annual ZIPs
and QA. `verify` checks the saved archive and day/night, scientific-value,
component and evidence contracts without changing it. Choose `build` instead
of separate download and prepare commands for a combined operation:

```text
ghana-fire-archive build --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --start-year 2001 --end-year 2024 --run-id archive_2001_2024
```

Use either `--year` or a complete `--start-year`/`--end-year` pair. Annual upload
ZIPs are under the producer run's `annual/MODIS/` and `annual/VIIRS/`; acquired
originals remain in its configured `data/raw/` cache. Consult the
[standalone README](../RP1_Project/rp1_firms_archive/README.md) for all commands,
QA fields, source handling and GEE-ready shapefile names.

A one-year archive is valid for that declared source interval. It cannot fill
missing years in a 2001–2024 admission. The one-year example workflow can test
bounded Archive admission and panel processing; its pilot BA selection cannot
satisfy the configured complete 2001–2024 scientific study. Use a fresh run and
matching source/geography configuration for a different declared study.

## Admission and scientific boundaries

For the configured 2001–2024 study, admission requires MODIS 2001–2024 and
Suomi-NPP 2012–2024: 37 source/year families. Another declared study derives
its obligations from its study period and actual source support. Extra years/sensors can remain
in the producer archive but are not staged for the study. Each required annual
must have provider-checked SP coverage encompassing its effective requested
interval. Suomi-NPP's structural start is 20 January 2012, so January remains
a partial-product month. This does not extend the study's paired RQ3 windows:
February 2012 onward and complete years 2013–2024 retain their existing roles.

A valid zero-row annual can be admitted only with explicit complete checked
coverage and file-backed lineage. `gee_upload_ready: false` for an empty table
does not make its checked coverage missing. Conversely, absent, unavailable,
unchecked or insufficiently covered required periods reject. Neither missing
provider coverage nor source gaps are converted to no-fire observations.

The validator checks canonical measurements and timestamps, raw/native
confidence, platform, instrument, SP version, TYPE, day/night, spatial support,
record identities, ZIP component parity and sparse QA semantics. QA flags
annotate observations without changing source-reported FRP/brightness or
removing detections. Missing measurements and finite zero measurements retain
their distinction. No physical-fire completeness or ground-truth accuracy is
claimed by an integrity pass.

Admission records the validator and producer identities separately. It checks
the exact validated research, annual-export and QA manifest hashes, preserves
the source authorities and binds each selected ZIP and its five flat
component hashes.

The fixed upstream archive population was filtered with its pinned Ghana
reference. Its national source `.shp`/`.prj` hashes and district ID/parent-zone
mapping must agree with RP1's source contract. Archive reporting polygons are
not asserted byte-identical to RP1's current dissolved analytical polygons.
The consumer always rejoins points to the RP1 polygons; archive district/zone
attributes remain provenance. A different upstream country population or
mapping requires separate scientific qualification, not a policy bypass.

The panels use vegetation TYPE selection and the configured count-stream
confidence and deduplication rules. The independent VIIRS FRP stream selects
nominal/high detections before FRP deduplication. Daily maximum FRP is averaged
over eligible UTC active days. Joins and eligibility retain FRP support when the
nominal/high count is zero. For covered months with a zero nominal/high detection
count, missing nominal/high active days and maximum streak are reported as zero.
Missing persistence alongside a positive count remains missing. Provided
values are preserved, and the coverage mask leaves unsupported periods
structurally missing. Confidence percentages require a detection denominator,
and FRP means require eligible active days.

## Receipts, reruns and failure recovery

`archive_request.json` binds study, selected producer/configuration, source
selection, validator code and workflow/intake code. `archive.json` binds the
producer source inventory and acceptance receipt. `archive_admission.json`
also binds the selected geography, staged bundle and intake identity. The
FIRMS completion receipt binds admission; merge rechecks it before proceeding.
Completed archive/admission steps verify existing identities on repetition.

Source mutation, changed configuration, altered code, mismatched geography,
stale validation reports or changed staged components reject. Choose a fresh
workflow ID after an intentional change. Exclusive locks serialize archive
writers; confirm the owner has stopped before removing an abandoned lock.
Failed validation never authorizes admission. Preserve a partial validation
directory for diagnostics and use a fresh run ID rather than retagging it.
If `firms` fails after writing its generated configuration or starting the
panels run, follow the [active-fire panel recovery procedure](ENVIRONMENT_AND_RECOVERY.md#interrupted-active-fire-panel-build).

Keep downloaded and prepared observations, QA, logs, local configuration and
credentials outside tracked source. Use [source geography admission](SOURCE_GEOGRAPHY.md)
for the producer's pinned reference inputs. The Earth Engine CSV inventory
is maintained with the repository. The archive subproject also provides a
standalone source packager at `tools/package_source.py`.

## Regression checks

Run from the RP1 root in the intended environment:

```text
python -m pytest -ra RP1_Project/rp1_firms_archive/tests
python -m pytest -ra tests/test_firms_archive_workflow.py tests/test_archive_workflow_integration_review.py tests/test_archive_sp_zip_direct.py tests/test_archive_empty_end_to_end.py tests/test_workflow_configuration.py
python -m pytest -ra RP1_Project/rp1_mv_firms_panels/tests
```

The checks cover source-preserving values, QA/day-night validation, missing
versus verified-empty coverage, malformed/foreign ZIPs, immutable authorities,
geography/source binding, independent FRP evidence, run-local routing, and
clean source packaging. Synthetic pass results establish implementation
behavior; a small real-data pilot establishes handoff compatibility. Full
scientific closeout still requires the chosen full-data run, model refits,
external SaTScan results, and existing GEE/source qualification as applicable.
