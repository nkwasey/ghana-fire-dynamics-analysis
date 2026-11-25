# Portability and test plan

Use the intended Python environment and verify import origins before testing:

```bash
python tools/qualify_source_checkout.py --origins-only
python tools/qualify_source_checkout.py
```

The checkout qualifier runs the source-tree tests against a fresh external
pytest directory. Supply `--pytest-base-temp SHORT_FRESH_EXTERNAL_PATH` to
choose its location. The selected path must be disjoint from the checkout and
qualification evidence. Inherited pytest options and generated-run selectors
are cleared for the projected test run.

For source and distribution checks, use the complete environment/distribution campaign
with its explicit source-only scope:

```bash
python tools/preflight_environment.py --json-out EXTERNAL_PREFLIGHT_JSON --work-dir EXTERNAL_SCRATCH_DIRECTORY
python tools/qualify_environment.py --source-only --evidence-dir EXTERNAL_QUALIFICATION_DIRECTORY
```

All evidence and scratch destinations must be outside the source checkout.
The source-only campaign still checks the four editable origins, dependency
consistency, clean projection, full configured tests, independent method
references, all four wheel builds and non-editable installed-wheel interfaces.
Only generated analytical-input validation is recorded as `NOT_APPLICABLE`;
neither a scientific execution nor a scientific result is qualified by this
mode. Use the default mode after the governed analytical handoff when that
input gate is required. A real notebook/SaTScan run needs its separate
[execution evidence](EXECUTION_EVIDENCE.md).

A dedicated Conda environment installed at a task-local prefix may use
`--validation-env-prefix ABSOLUTE_ENVIRONMENT_PREFIX`. The qualifier verifies
that this is its actual interpreter prefix and has Conda transaction history;
do not disguise it by assigning a different `CONDA_DEFAULT_ENV`. On Windows,
`--pytest-base-temp SHORT_FRESH_EXTERNAL_PATH` provides a short, unused path
for the full test suite without changing nested-test temporary directories.
The pytest base and evidence directory must be disjoint: neither may contain
the other, including fresh paths and resolved aliases. Use separate sibling
directories under the objective Workspace. The qualifier rejects overlap
before creating, clearing or writing evidence because pytest recreates its base
when a temporary-directory fixture first runs.
When the option is omitted, the qualifier selects and validates a fresh
`.rp1-pytest-...` base under the native per-user temporary folder on Windows,
or beside the evidence directory on POSIX. It records its logical path,
actual argument and automatic mode, and always passes `--basetemp`.
Windows DOS/UNC namespace aliases are normalized before containment and native
existence checks; unsupported device/raw NT/volume/global-root paths fail
before evidence cleanup. Explicit extended paths keep their native IO spelling.
Inherited `PYTEST_ADDOPTS`
and `PYTEST_DEBUG_TEMPROOT` are removed from the child environment, including
nested pytest calls; the parent environment is preserved. This prevents hidden
temporary-base and test-selection options from changing the recorded canonical
campaign. Use an explicit native Linux base for WSL kernel tests when evidence
is stored on a Windows mount. The selected automatic parent must permit
temporary-directory creation; use an explicit fresh writable path otherwise.
Report each platform separately, including failures, skips and any unavailable
gate. A preflight pass alone cannot establish the full software checks.

Run the commands from the repository root on the platform being qualified.
`environment.yml` installs four editable projects: geography, FIRMS panels,
analysis and `RP1_Project/rp1_firms_archive`. It includes the Archive dependencies
`requests` and `pyshp`. The origins-only check must resolve all four packages
and the shared c3 contract inside this checkout. A native Windows environment
and a WSL/Linux environment need separate installations and notebook kernels.

The Archive integration commands are single-line commands usable in PowerShell
and POSIX shells. Use absolute Windows paths in PowerShell and Linux paths in
WSL. For a fresh extraction, follow the default `build` workflow's
`geo`, then Stage 3 `archive-plan`, `archive`, `archive-admit`, `firms` sequence in the root
README. The following optional route instead uses a separately prepared
existing archive, from the repository root:

```bash
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study archive --archive-manifest '/absolute/path/archive-manifest.json'
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study archive-admit
python tools/run_workflow.py --config configs/workflow_archive_existing.example.json --run-id archive_study firms
```

Replace the manifest path with the actual local source, and complete `geo` or
verified read-only `geo-reuse` before admission. Existing-source validation is
local and preserves the archive; explicit `build` acquisition can use the
network. Planning performs no acquisition. Run-local input publication uses a
fresh `FIRMS/out/runs/<run-id>/source_inputs` bundle and retains no-overwrite
guarantees. See [Archive integration](FIRMS_ARCHIVE_INTEGRATION.md) for full
native paths and mode selection. Manual curated stage/activate remains an
optional curated-input interface.

Qualification exercises the clean source projection, offline c3 checks,
geography smoke test and configured test gates. Record commands, environment,
failures and skips; tests requiring generated analysis inputs may be skipped
in a clean projection. Synthetic fixtures check methods and contracts; real
scientific outcomes must be derived from the selected inputs.

The source archive includes the study shapefiles and all 370 original
Earth Engine CSVs. The archive producer's reference files are obtained and
verified separately using [source geography admission](SOURCE_GEOGRAPHY.md).
Archive and geography processing populate the consumer's local input
directories. Source qualification checks all four package builds and imports.
Report test passes and skips separately.

Exercise accepted ZIP parity, unsafe/extra members, required coverage gaps,
Suomi-NPP's 20 January 2012 effective start, validated empty source years,
tampered acceptance/QA evidence, and failure/no-overwrite behavior. Preparation,
reuse, combine and merger evidence must still bind the exact admitted source
bundle. The full-study requirement is 37 MODIS/Suomi-NPP source-year families;
the broader existing bundled v1 inventory does not receive a new producer
validation merely by being selected.

Check non-replacing publication and collision/failure behavior for the chosen
filesystem. For WSL Windows-mounted drives, follow the
[burned-area and merge publication guide](ENVIRONMENT_AND_RECOVERY.md#burned-area-and-merge-publication)
and use a suitable native output root when necessary.
If a PROJ import warning occurs, inspect the environment and consult the
geospatial setup guidance before interpreting spatial outputs.

Software tests do not establish source-data lineage, remote Earth Engine asset
identity, geographic equivalence, external SaTScan execution or scientific
validity. Review those authorities and the actual outputs for each research run.

## Explicit generated-publication references

Set `RP1_ANALYSIS_TEST_RUN` to a completed current-source analysis base ID before
running generated-publication integration checks. See [Test generated results](#test-generated-results) for WSL and PowerShell examples. The production validator checks the selected family before
its run-local primary sources are consumed; RQ4 also requires validated external
results. Missing selection yields skips for the affected dependencies.
A corrupt, incomplete or incompatible explicit selection fails. Configuration
and synthetic checks run without generated publication manifests. Use the
source snapshot recorded in the selected run and use disposable test copies.

The canonical qualifier always tests a clean source projection. It removes
`RP1_ANALYSIS_TEST_RUN`, `RP1_EXPORT_REGRESSION_ANALYSIS_ROOT` and
`RP1_EXPORT_REGRESSION_RUN_ID` from a copied environment used only for projected
test collection and the full projected suite. The caller's environment and normal
direct generated-run pytest invocations retain their selections. This prevents a
README-selected operational run from being mistaken for data shipped in a clean ZIP.

## Test generated results

Select a completed analysis family explicitly before running the analysis tests
that inspect generated results. In WSL/Linux Bash:

```bash
export RP1_ANALYSIS_TEST_RUN=ghana_fire_study
python -m pytest -ra RP1_Project/rp1_analysis/tests
```

In Windows PowerShell:

```powershell
$env:RP1_ANALYSIS_TEST_RUN = 'ghana_fire_study'
python -m pytest -ra RP1_Project/rp1_analysis/tests
```

The selected family needs its `_pub`, `_sec` and `_close` members.
Check skip reasons when running without generated results. RQ4 tests require
validated external scan results.

## Verify a source archive

Before installing or provisioning inputs into a fresh source ZIP extraction,
compare the ZIP's SHA-256 with its independent checksum. Then verify its
inventory from the extracted repository root:

```bash
python tools/package_clean_source.py audit --staged .
```

Require `"status": "PASS"`. A Git checkout can run the source tests above.
