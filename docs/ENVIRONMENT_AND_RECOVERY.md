# Environment, output locations and recovery

Use the [root README](../README.md) for the main five-stage route. These
instructions cover installation choices and recovery after a reviewed failure.
Run root workflow commands from the repository root. Never remove scientific
inputs or completed outputs merely to bypass a collision or provenance check.

## Conda environment and editable packages

Use Python 3.13 in a checkout-specific `rp_ghana_fire` environment. Node.js 24 is declared
for c3 source qualification; local CSV processing does not call Earth Engine.

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
python --version
node --version
python tools/qualify_source_checkout.py --origins-only
python -c "import rp1_analysis_v1; print(rp1_analysis_v1.__file__)"
```

If the environment already exists, update its dependencies and bind all four
editable installations to this checkout. Run from this repository root:

```bash
conda env update -n rp_ghana_fire -f environment.yml
conda activate rp_ghana_fire
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_analysis
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_firms_archive
python tools/qualify_source_checkout.py --origins-only
```

All four project imports and the lightweight `rp1_ba_contracts.c3` import
must resolve to this checkout. The contract is part of the analysis wheel.
`--no-deps` assumes declared dependencies/build tools are already installed.

An editable installation belongs to one checkout at a time. Two WSL terminals
using the same Conda environment share that installation, even when one
checkout is on `/mnt/c` and the other is under the Linux home directory.
Installing from either checkout switches the environment for both terminals;
do not switch while a run using the other checkout is active. Before starting
or resuming a run, activate its environment, change to its repository root,
repeat the four editable installs above, and rerun the origin check. For the
analysis package also inspect the distribution metadata:

```bash
python -c "import importlib.metadata as m, rp1_analysis_v1; print(rp1_analysis_v1.__file__); print(m.distribution('rp1-analysis-v1').read_text('direct_url.json'))"
```

Both paths must identify the intended checkout. The origin check is a snapshot;
another installation in the same environment can change it afterward. For
concurrent work, use separately configured environments and kernels, and verify
each against the analysis environment and kernel requirements.

## Bounded environment preflight

On Windows, a deeply nested default temporary directory can exceed a build
backend's path limit during an editable install. In that case, select a short
task-local directory for the current PowerShell process before the four
installs. Replace the example with a fresh directory in the objective
Workspace; this does not change the machine's environment settings:

```powershell
$env:TEMP = 'ABSOLUTE_WORKSPACE_TEMP_DIRECTORY'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
```

Activate the intended environment so its `Scripts` directory and native
libraries are on that process's command search path. Installing the four
projects alone does not supply all dependencies declared in `environment.yml`.
Keep environment setup failures with the qualification record and rerun from
a fresh evidence directory after correcting the environment.

Before the longer qualification campaign, run the local preflight with the
intended Python 3.13 interpreter. Replace `EXTERNAL_EVIDENCE_FILE` with a fresh
absolute JSON filename and `EXTERNAL_SCRATCH_DIRECTORY` with an absolute
directory outside the source checkout. In the objective layout, use the
corresponding `Workspace/evidence` and `Workspace/working` task directories.
In WSL, Jupyter connection files require a native Linux temporary filesystem
that enforces mode `0600`. If a Windows-mounted Workspace cannot enforce that
mode, pass a fresh native `/tmp` directory through `--work-dir` and keep
`--json-out` in the Workspace. Kernel-based tests similarly need a native
`--pytest-base-temp`. Retain the commands and the filesystem limitation with
the qualification evidence; do not disable Jupyter's secure-file check.
The pytest base must be disjoint from the qualification evidence directory:
neither may contain the other. This also applies to fresh paths and resolved
aliases. Use a separate temporary sibling directory, since pytest owns and
recreates its base; qualification rejects overlap before changing evidence.
If `--pytest-base-temp` is omitted, the qualifier selects a fresh
`.rp1-pytest-...` base under Windows' native per-user temporary folder, or an
evidence sibling on POSIX. It validates the base before evidence cleanup and
passes it explicitly. The report records the logical path, actual command
argument and automatic or explicit mode. Windows' default parent is obtained
from the native known-folder API, independently of `TEMP`, `TMP` or
`LOCALAPPDATA` overrides. A long user/application profile can still need an
explicit short base for native-library path limits. In WSL, select a native Linux explicit
base when the evidence sibling would be on a Windows-mounted filesystem.
Inherited `PYTEST_ADDOPTS` and `PYTEST_DEBUG_TEMPROOT` are ignored in the child
environment for collection, qualification and nested test processes. They cannot
supply an unvalidated base or silently filter the canonical test selection.
The qualifier does not modify the calling shell's environment. Temporary test
files are retained at the recorded base for investigation; use a new base for
the next qualification.
Ordinary and extended DOS/UNC spellings of the same Windows filesystem path
have one ownership identity. An explicitly requested extended path retains its
native IO form; ordinary paths retain their ordinary form for native-client
compatibility. Device, raw NT, volume and global-root namespaces are refused
before evidence changes; use a drive or UNC filesystem path.

```bash
python tools/preflight_environment.py --json-out EXTERNAL_EVIDENCE_FILE --work-dir EXTERNAL_SCRATCH_DIRECTORY
```

The tool runs fresh bounded child probes for Python 3.13, imported dependency
versions versus distribution metadata, all four project import origins and
the shared c3 contract, Node.js 24, local geospatial transformation, native
linear algebra/off-screen rendering, an independent standard-library socket
pair and selector event loop, and an ephemeral same-interpreter Jupyter kernel.
The version/import probe includes the scientific and geospatial dependencies,
Pydantic, Requests, PyShp, and the nbformat, nbclient, ipykernel and jupyter_client
execution stack, so missing core configuration, request, shapefile or notebook
dependencies are reported before the longer qualification campaign.
It neither installs packages nor rebinds an editable package or named kernel.
It performs no Earth Engine or SaTScan request and runs no scientific notebook.

Native DLL and PROJ/GDAL search paths are selected from that interpreter's
actual `sys.base_prefix` for the probe process and recorded in the evidence.
This does not repair or modify a shared environment. A runtime/metadata
disagreement, including conflicting NumPy metadata, is a preflight failure;
create or repair the dedicated validation environment from the declared
specification rather than deleting shared metadata speculatively.

The defaults are 20 seconds per ordinary probe and 30 seconds for kernel
readiness/execution, with a short outer cleanup allowance. Use
`--timeout-seconds` and `--kernel-timeout-seconds` for a documented cold-start
allowance. A hung worker and its owned process tree are terminated. Probe
scratch products are removed after the check; optional JSON evidence remains
outside the checkout and is never overwritten. If Node.js 24 is supplied
separately, pass its explicit path using `--node NODE24_EXECUTABLE`.

Every probe reports `PASS`, `FAIL` or `UNAVAILABLE`. The command exits zero only
when all probes pass. A missing dependency/kernel is not counted as a pass.
Timeouts or native-runtime errors describe the observed environment condition;
they do not by themselves identify a project-calculation defect. Preflight
success is a prerequisite check, not full source, platform or scientific
qualification. Continue with the declared qualification campaign and retain
its builds, test results, skips and platform limitations separately. Editable
source qualification and non-editable wheel qualification use separate
environments. Existing completed run evidence must remain bound to its original
source/configuration identities.

## Geography already present

A fresh extraction starts with no prepared consumer geography. Run `geo` once.
An occupied checkout requires a verified backup before replacing handoff files,
or read-only `geo-reuse` when existing geography and original evidence are
unchanged. Neither option permits substituting different geometry under the
same source identity. See [geography handoff](GEO_HANDOFF.md).

## Interrupted active-fire panel build

If `firms` stops after creating
`RP1_Project/rp1_mv_firms_panels/configs/generated/<run-id>.yaml`, it
refuses to rerun over that configuration and any partial panel outputs.
Keep the failed run for diagnostics and correct the cause. Use a fresh run
ID for the retry. For an unchanged and verified geography handoff, start the
new workflow with `geo-reuse`. Complete burned-area admission, Archive
validation and active-fire admission for the new ID before running `firms`.
To reuse a valid whole Archive instead of acquiring it again, follow the
[existing-archive procedure](FIRMS_ARCHIVE_INTEGRATION.md#optional-existing-archive).

## Burned-area and merge publication

On WSL, publication to a Windows drive can use Windows interoperability when
the Linux filesystem does not support a non-replacing rename. This requires
`wslpath`, Windows PowerShell (`powershell.exe` on `PATH`) and enabled WSL
interoperability. Preparation and merge refuse publication when existing
output cannot be protected.

Use an absolute `--ba-output-root` on a supported filesystem when required.
For example, add `--ba-output-root "$HOME/rp1_ba_outputs"` to `consolidate-ba`
in WSL. The published location becomes `<root>/<run-id>/c3` and is recorded.
Use an absolute Windows path in PowerShell. See
[c3 preparation](../RP1_Project/docs/ba_consolidation.md).

If a reviewed merge failure left no final output, retry with unchanged
inputs/configuration. This WSL example selects a native output root:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 --retry-merge --merge-output-root "$HOME/rp1_merge_outputs" merge
```

For a new merge, omit `--retry-merge`. Existing published destinations are not
overwritten. Keep one operating environment so recorded paths remain valid.
Preserve failed state and logs until the cause is understood.

## Interrupted analysis handoff

`analysis-inputs` requires an empty analysis raw-input destination. A verified,
interrupted handoff can resume using the same run and configuration:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 --resume-analysis-inputs analysis-inputs
```

Resume verifies the exact bound bundle; it cannot replace another study.
Use a separate clean checkout for a different handoff. For lost kernels or
pending external results, follow [analysis execution](ANALYSIS_EXECUTION.md).
