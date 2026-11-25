# Ghana Fire Archive


This package supplies NASA standard-processing (SP) active-fire observations
to the Ghana study. For the full workflow, use the
[project README](../../README.md). Integrated acquisition takes its years
from the root study configuration. The standalone commands below retain their
own configuration and explicit `--year` or `--start-year`/`--end-year` selection.

Import `ghana_fire_archive` in Python or run `ghana-fire-archive` in a shell.

It downloads the available Ghana SP observations, preserves source measurements,
prepares canonical annual CSVs and point shapefiles, checks their scientific and
spatial attributes, and publishes annual upload ZIPs and separate sparse QA
sidecars. It does not upload to Earth Engine or run downstream RP1 analysis.

The repository contains code, tests, configuration examples and checksums for
the required FIRMS archive reference files. Obtain those four files separately
and use the [source geography guide](../../docs/SOURCE_GEOGRAPHY.md) to verify
them before acquisition.

## Install and run

Use Anaconda Prompt on Windows or a Conda-enabled shell on Linux/macOS. From
this subproject directory, create the dedicated Python 3.12 environment:

```text
conda env create -f environment.yml
conda activate ghana-fire-archive
ghana-fire-archive --version
python -m pip check
```

The environment installs this package in editable mode. Alternatively install
`python -m pip install -e .` in a compatible existing environment (Python 3.11
or later). RP1's root environment includes the local subproject as well. Run
from this directory when creating/updating the dedicated environment. An
extracted standalone source ZIP provides the same `pyproject.toml`, source and
configuration layout. The CLI's default configuration lookup supports this
source/editable layout; use explicit `--config` paths when scripting elsewhere.

The source launcher `python archive.py ...` works from any working directory.
After installation, `python -m ghana_fire_archive ...` is equivalent. Windows
command launchers use the dedicated `ghana-fire-archive` Conda environment.

## Set up the NASA FIRMS MAP_KEY

Request a free key using your email address on the official
[NASA FIRMS MAP_KEY page](https://firms.modaps.eosdis.nasa.gov/api/map_key/).
Set it locally after activating the environment. For a hidden prompt in
WSL/Ubuntu (Bash):

```bash
read -r -s -p "NASA FIRMS MAP_KEY: " FIRMS_MAP_KEY
printf '\n'
export FIRMS_MAP_KEY
```

For Windows PowerShell:

```powershell
$firmsKeySecure = Read-Host "NASA FIRMS MAP_KEY" -AsSecureString
$firmsKeyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($firmsKeySecure)
try {
    $env:FIRMS_MAP_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($firmsKeyPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($firmsKeyPointer)
    $firmsKeySecure.Dispose()
    Remove-Variable firmsKeySecure, firmsKeyPointer
}
```

Paste the key at the prompt and press Enter. Its literal value is not recorded
in command history. Check the effective local key configuration without printing the key:

```text
python -c "from ghana_fire_archive.core import load_config, map_key; key=map_key(load_config('configs/archive.yaml')); print('FIRMS key is configured' if key else 'FIRMS key is missing'); raise SystemExit(0 if key else 1)"
```

Run this command from the standalone Archive directory and replace
`configs/archive.yaml` if another producer YAML is selected. The resolver checks
the environment first and then `key_file`. This is a local presence/format
check, not an API authentication test; malformed values fail without revealing
the key. The variable applies
to Python processes started from this terminal and does not persist into a new
terminal. Clear it with `unset FIRMS_MAP_KEY` in Bash or
`Remove-Item Env:FIRMS_MAP_KEY` in PowerShell.

Alternatively, create a text file outside the project containing only the key
on one line. Set `key_file` in the selected producer YAML. Examples:

```yaml
# For WSL Python; replace this placeholder with the actual external file path.
key_file: /absolute/path/to/external/firms_map_key.txt
```

For Windows Python, use a path such as
`key_file: X:/path/to/external/firms_map_key.txt` instead. These examples are
absolute-path placeholders, not supplied files or required locations.
WSL can read the same Windows file through `/mnt/c/...`. Relative `key_file`
paths resolve against the YAML directory; do not pass a Windows path directly
to WSL Python. `FIRMS_MAP_KEY` takes precedence over `key_file`, so clear an old
environment value when switching to the file option. Never put the actual key
in YAML, documentation, source control or a source ZIP.

NASA SP availability and Area API access require a configured key. Public
annual country files can be acquired without one, but products/recent dates
may be unavailable. Without a key, absence from that catalogue remains explicit
unavailability, never zero observations. Manifest-only verification needs no
key and does not query NASA; receipts redact key-bearing URLs.

## Native source layout

```text
configs/                         Main and single-year configuration examples
src/ghana_fire_archive/          Standalone package and reusable API
tests/                           Offline synthetic contract tests
tools/                           Annual and clean-source packaging utilities
data/raw/                        NASA originals, receipts and provider metadata cache
data/metadata/                   Local intake notes
data/reference/geography/       Reference manifest, checksums and locally staged files
out/runs/<run-id>/               Plans, accepted archive, annual exports and QA
```

Before an Archive build, stage the four reference files (`ghana.geojson`,
`acz.geojson`, `districts.geojson` and `units.json`) using the
[source geography guide](../../docs/SOURCE_GEOGRAPHY.md). In a standalone
copy, place the same files under `data/reference/geography/` and verify them
against that directory's `checksums.sha256`. Keep these input bytes intact.
Cached NASA acquisition metadata and batch evidence stay beside their
originals in `data/raw`. Acceptance and derived metadata belong to the run.

## Build one year

Internet access is required to create the environment and acquire NASA inputs.
Choose a fresh run identifier for a study selection you want to retain:

```powershell
ghana-fire-archive plan --config configs/single-year.example.yaml --run-id ghana-2024
ghana-fire-archive build --config configs/single-year.example.yaml --run-id ghana-2024
ghana-fire-archive verify --manifest out/runs/ghana-2024/archive-manifest.json
```

`plan` contacts NASA and writes a download plan. `build` downloads/verifies the
cache, prepares and verifies the canonical archive, publishes annual shapefile
exports, then derives QA. To split acquisition and preparation:

```powershell
ghana-fire-archive download --config configs/archive.yaml --year 2024 --run-id study-2024
ghana-fire-archive prepare --config configs/archive.yaml --year 2024 --run-id study-2024
```

Use the same selection and run identifier for both commands. A year override
changes requested scope and retains the configured output location. `--year`
and `--start-year`/`--end-year` are mutually exclusive. A range requires both ends.
The configured end year is explicit: update it when extending the archive.

## Run from the RP1 repository root

When this subproject is included in RP1, use the root `rp_ghana_fire` Conda
environment. From the RP1 root, the standalone command accepts the full
configuration path for a single-year raw-data processing test:

```text
ghana-fire-archive plan --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --year 2024 --run-id annual-2024
ghana-fire-archive build --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --year 2024 --run-id annual-2024
ghana-fire-archive verify --manifest RP1_Project/rp1_firms_archive/out/runs/annual-2024/archive-manifest.json
```

For a range, use both `--start-year` and `--end-year` instead of `--year`:

```text
ghana-fire-archive build --config RP1_Project/rp1_firms_archive/configs/rp1.yaml --start-year 2013 --end-year 2024 --run-id archive-2013-2024
```

The archive's `data/raw/` is a NASA download cache. Annual shapefiles retained
under the separate panels project's `data/raw/modis/` and `viirs/` are prepared
consumer inputs and do not populate this cache.

For the integrated full-study handoff, set up the key and configured year range,
choose a fresh run ID, and run from the RP1 root:

```text
python tools/run_workflow.py --config configs/workflow_archive_build.example.json --run-id archive_new geo
python tools/run_workflow.py --config configs/workflow_archive_build.example.json --run-id archive_new archive-plan
python tools/run_workflow.py --config configs/workflow_archive_build.example.json --run-id archive_new archive
python tools/run_workflow.py --config configs/workflow_archive_build.example.json --run-id archive_new archive-admit
python tools/run_workflow.py --config configs/workflow_archive_build.example.json --run-id archive_new firms
```

Here `archive-plan` is an offline workflow preview, whereas the standalone
`plan` command queries NASA. `archive` performs acquisition, preparation,
annual export, QA and validation. Use `geo` once the source boundaries are
staged. Use `geo-reuse` to reuse an existing, verified geography handoff.

`archive-admit` stages the required MODIS/Suomi-NPP shapefile components and
evidence under
`RP1_Project/rp1_mv_firms_panels/out/runs/archive_new/source_inputs/data/raw/`.
The subsequent `firms` command reads that bundle automatically. Keep the same
configuration/run throughout. The full RP1 study requires MODIS 2001–2024 and
Suomi-NPP 2012–2024; a single-year processing test cannot satisfy that handoff.
Use the RP1 root README and `docs/FIRMS_ARCHIVE_INTEGRATION.md` for the
existing-archive route, output locations and downstream stages.

## Configuration

Relative paths resolve against the YAML file directory. Example:

```yaml
schema_version: 1
years: {start: 2000, end: 2025}
sources: [MODIS_SP, VIIRS_SNPP_SP, VIIRS_NOAA20_SP, VIIRS_NOAA21_SP]
country: Ghana
geography: ../data/reference/geography
downloads: ../data/raw
output_root: ../out/runs
run_id: default
timeout_seconds: 120
retries: 3
api_batch_max_age_hours: 24
refresh_api_batches: false
```

The main example uses run `default`; the single-year example uses
`single-year-2024`. Override either with `--run-id`. Identifiers are one safe
directory name (letters, digits, periods, underscores and hyphens). Years must
be between 2000 and the current UTC year. Choose any nonempty, unique subset of
supported SP sources. `country` remains `Ghana` because the reference geometry
governs admission and spatial assignment.

`configs/rp1.yaml` selects `MODIS_SP` and `VIIRS_SNPP_SP`, the shared cache and
reference paths, and standalone run `rp1`. It requests 2000–2025 when invoked
directly. The integrated workflow supplies its study-specific acquisition
years from the root configuration.

Existing explicit `output: ../custom` configurations retain their original
path and accepted-manifest replacement behavior. They do not accept `--run-id`;
switch to `output_root` plus `run_id` to opt into scoped output. Separate runs
may share a download cache. Public API operations serialize writers to the run
and cache through exclusive lock files. An abandoned lock must only be removed
after confirming its owner has stopped.

## Accepted outputs and integrity

A successful run contains `archive-manifest.json`, `verification.json`,
`download-plan.json`, content-addressed `canonical/` CSVs and `artifacts/` annual
shapefiles, embedded `geography/`, `annual/`, `annual-current.csv`, and
`qa/qa-manifest.json` with sparse per-source/year flags. The manifest identifies
accepted paths, hashes, lineage, covered dates and scope completeness.

`complete_available_sp_scope` means the requested available SP combinations
were admitted. `complete_requested_scope` also requires full requested annual
coverage (except structural pre-product periods). A successful integrity check
can coexist with explicitly unavailable or partial periods. Neither flag proves
absence of physical fire in missing periods.

Archive observations preserve source-reported FRP, brightness, confidence,
day/night and fire type. Finite source zero measurements remain zero and receive
separate QA flags where applicable; missing values remain missing. Flags never
remove observations or explain anomaly causes. Deduplication retains distinct
measurement variants through source/platform/time/position/measurement identity.

Verification checks acquisition obligations, canonical scientific values and
identity, governed spatial assignments, all shapefile attributes and annual ZIP
structure/payload. The read-only public validator additionally verifies annual
exports and recomputes every sparse QA flag and count. The run records producer
module hashes and validator code hashes separately.

Failed preparation or annual publication preserves the previous accepted
manifest/report and annual view. New unaccepted content-addressed artifacts can
remain for inspection. QA runs after archive acceptance: if QA fails, scientific
outputs remain accepted and the `qa` command can retry. Downstream admission with
required QA rejects missing, corrupt or semantically inconsistent sidecars.

## Manifest-only operations

These commands do not load configuration or credentials when `--manifest` is
provided. The archive may live outside the checkout, including a prior accepted
standalone archive. Verification reads it without creating reports or repairing
files; `--output` optionally writes a report to a separate directory.

```powershell
ghana-fire-archive verify --manifest C:/research/archive/archive-manifest.json
ghana-fire-archive qa --manifest C:/research/archive/archive-manifest.json
ghana-fire-archive export --manifest C:/research/archive/archive-manifest.json --output C:/research/export-view
ghana-fire-archive package --manifest C:/research/archive/archive-manifest.json --output C:/research/annual-collection.zip
```

`qa` refreshes derived QA after verifying the accepted archive. `export`
refreshes a validated annual view. `package` produces a collection containing
individual annual sensor ZIPs. See [GEE_UPLOAD.md](GEE_UPLOAD.md) for local upload
format and manual ingestion instructions.

Verification checks every observation using bounded memory and temporary disk
files. Keep the system temporary directory writable and allow sufficient free
space for the largest annual partition and its verification index. Temporary
files are removed when the check finishes; accepted datasets remain unchanged.

## Reusable integration API

```python
from ghana_fire_archive import api

config = api.load_config('configs/single-year.example.yaml', run_id='study-2024')
plan = api.download(config)
manifest, exports = api.prepare_and_export(config, plan)
validated = api.validate_archive(config['output'] + '/archive-manifest.json')
```

`api.make_plan(config, refresh=True)` and `api.download(config, refresh=True)`
return existing plan dictionaries. `prepare_and_export(config, plan=None)` owns
preparation, annual export and QA orchestration and returns the accepted manifest
dictionary plus export summary. `validate_archive(manifest, verify_qa=True)` is
read-only; `verify_qa=False` explicitly omits QA while retaining archive/annual
checks. `load_config(path, year=None, start=None, end=None, run_id=None)` returns
the resolved configuration dictionary. Integrators reuse this API instead of
copying the standalone workflow. RP1 admits its own handoff separately; it does
not silently rebuild an existing archive selected for validation.

## Offline tests and clean source packaging

From the subproject directory with its environment activated, install the
test extra if the environment does not already provide pytest:

```bash
python -m pip install -e ".[dev]"
```

Then run:

```powershell
python -m pytest tests -q -p no:cacheprovider --basetemp C:/research/archive-test-temp
python tools/package_source.py --output C:/research/archives/Ghana_Fire_Archive_Source.zip
```

The packager checks the reference manifest, writes a SHA-256 inventory and
verifies the members and bytes of the source ZIP. It packages the checksums and
manifest for the separately staged reference files. The ZIP root is
`Ghana_Fire_Archive/`, which can be built and installed independently.
