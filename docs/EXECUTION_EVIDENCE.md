# Execution evidence

The source archive, software qualification and an executed scientific run are
separate deliverables. The source ZIP intentionally excludes generated results
and executed notebooks. This guide explains how to record analysis and external-engine evidence.

## Record an external SaTScan execution

After 04-01 has prepared a fresh secondary run, choose either the usual manual
external execution route or the explicit recording helper below. The notebook
does not launch SaTScan. The recording helper is an operator-invoked external
execution step; it runs only the selected model and does not integrate results.

From `RP1_Project/rp1_analysis`, after the documented environment and source-origin
checks, substitute a new prepared secondary run ID and the actual batch binary:

```powershell
python scripts/execute_satscan_with_evidence.py --secondary-run-id new_run_sec --model-id MCD64A1_POISSON_PRIMARY --executable "C:/Program Files/SaTScan/SaTScanBatch64.exe"
python scripts/execute_satscan_with_evidence.py --secondary-run-id new_run_sec --model-id VIIRS_STP_PRIMARY --executable "C:/Program Files/SaTScan/SaTScanBatch64.exe"
```

For the restricted burned-area Poisson scan, use the explicit recorded run
command in [Analysis execution](ANALYSIS_EXECUTION.md). Integrate its sensitivity
comparison before exporting execution evidence.

On Linux/WSL, pass the native batch executable path for that platform. These
commands use the two-model registry and the unchanged parameter/input files
created by 04-01. They probe the actual executable version and require the
configured authority. They refuse existing result, receipt or log files rather
than executing over an earlier result family. They do not invent a random-seed
parameter unsupported by the engine.

Each successful invocation writes next to the parameter-governed ResultsFile:

- `ResultsFile.execution.json`: observed command, working directory, platform,
  binary path/version/hash, start/end times, exit status, input hashes before and
  after execution, raw result hashes and console-log hashes. The receipt pins
  each native output individually, including `ResultsFile.llr.txt` if the
  engine writes its optional Monte Carlo maxima. The wrapper refuses a maxima
  file already present at the destination.
- `ResultsFile.stdout.log` and `ResultsFile.stderr.log`: captured console streams.

The parameter file must reference exactly the registry's case, coordinate,
population and result paths. The binary and governed inputs must remain unchanged during execution. Exit code
zero alone is insufficient: fatal diagnostics and an incomplete or invalid
ResultsFile family fail. A failure retains `ResultsFile.execution.failed.json`,
console logs and any raw output; preserve the failed attempt and prepare a fresh
run. An interrupted wrapper may leave its `.execution.lock` reservation; preserve
it as incomplete evidence rather than deleting it to manufacture success.
Normal ingestion rejects this interrupted/in-progress reservation.

Manual ingestion accepts a complete raw result family without an execution
receipt and records the missing binary attestation. When a receipt is present,
validation checks the model, inputs, raw results, logs and observed success.
The receipt schema defines the scope of the executable attestation. Only
outputs listed and verified in the receipt carry that attestation.
A malformed, changed or failed receipt is rejected. Keep both model receipts
with their raw outputs before running 04-02.

## Retain an executed notebook

The controlled wrapper executes the canonical notebook in a fresh
kernel and saves its executed artifact, hash, code-cell completion record and
run gates. Use a new run ID and the documented controlled/resume route in
[Analysis execution](ANALYSIS_EXECUTION.md). A prepared secondary run with both
genuine result families can be reused only under that guide's collision and
identity checks. A fresh controlled run with no external results may legitimately
finish with `EXTERNAL_RESULTS_REQUIRED`; that is incomplete external evidence.

Interactive Jupyter closeout records the evidence available at closeout.
Use the controlled wrapper to capture the executed notebook and observed
code-cell completion required by strict export.

## Export a separate run evidence bundle

After run validation, export to a new directory outside the operational analysis
tree, normally the objective's Workspace:

```text
python scripts/export_execution_evidence.py --run-id new_run --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY
python scripts/export_execution_evidence.py --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY --validate-only
python scripts/export_execution_evidence.py --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY --validate-only --expected-manifest-sha256 TRUSTED_MANIFEST_DIGEST
```

Strict export requires the controlled executed notebook with matching canonical
source and complete error-free code-cell evidence, validated/integrated external
results and three prospective engine receipts. These receipts cover the primary
MCD64A1 discrete Poisson scan, the primary VIIRS space-time permutation scan
and the restricted MCD64A1 discrete Poisson scan. The exporter copies the
publication, secondary and closeout families and includes the canonical source
notebook with a controlled execution snapshot. It writes
`EXECUTION_EVIDENCE_MANIFEST.json` last. All copied files have size and SHA-256
entries. Before semantic run
validation, the exporter pins all three complete run-family inventories, selected
configuration files, canonical notebook and package-version authority. The same
bytes and file membership must remain stable through validation, copying and the
last pre-seal check; source file freshness timestamps are also pinned. Each copied
file is checked against that initial inventory, and staged/published members must
match it before the terminal manifest is written. A changed source is refused,
rather than becoming a new post-validation baseline. The exporter refuses to
replace a bundle. It does not prevent an external writer from changing the
original tree after the last read. The bundle identifies the validated snapshot.

Validate a transferred bundle from an RP1 source checkout on the receiving
machine. The original run tree, checkout and SaTScan installation are unnecessary
for transfer validation. The validator checks file membership and hashes, cross-checks
the notebook and closeout gates, and binds each receipt to its governed scenario,
inputs, outputs and logs. For validated primary scans it checks the four
run-local SaTScan source identities and reconstructs their contents using the
transferred native results and input authorities. It reconciles the published
T3 and S6 tables and the F6 figure-data CSV with those sources. The coordinate
rosters establish which districts were eligible for each scan. The recorded
reasons for excluded districts depend on the original source panels. The
validator also checks the embedded publication registries and verifies the
restricted-scan comparison and its published tables against the recorded
baseline when the derivation evidence is available.

The verified checks determine the evidence status and required limitations.
Obtain the manifest SHA-256 from a trusted source to verify the expected
evidence bundle. A check without the independent
digest establishes internal consistency within the scope above. On Windows,
extract the results archive or evidence bundle to a short path before validation.

The bundle records scientific configuration and notebook identities. The run's
reproducibility records retain original input identities. Derived SaTScan input
files accompany their raw results; the original source panels and engine binary
are not embedded. Keep the engine binary outside the run family. Link the bundle to the separately audited source
source package and software-qualification records for the run.

Use a limited export for a valid run with missing execution attestations:

```text
python scripts/export_execution_evidence.py --run-id interactive_run --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY --allow-declared-limitations
```

The manifest labels missing notebook or engine attestations
`DECLARED_LIMITATIONS`. The run must pass validation under its recorded source
and configuration. The bundle verifies artifact identity. Field-fire accuracy
and scientific assumptions require independent evidence.

If publication is interrupted, the bundle has no terminal manifest or contains
`BUNDLE_INCOMPLETE.txt`; validation rejects it. Preserve it and export to a fresh
directory. Raw external results and existing run authorities are never rewritten
by the exporter. See the [provenance recovery procedure](../RP1_Project/rp1_analysis/docs/PROVENANCE_RECOVERY.md)
for an integration transition conflict.

## Optional genuine-run export regression

The clean source suite exercises snapshot interleavings with self-contained
fixtures. A separate integration regression can use an existing generated run,
without rerunning the scientific notebook or external engine. Select the original
analysis root and base run identifier explicitly, then run:

```powershell
$env:RP1_EXPORT_REGRESSION_ANALYSIS_ROOT = 'ABSOLUTE_ORIGINAL_ANALYSIS_ROOT'
$env:RP1_EXPORT_REGRESSION_RUN_ID = 'ORIGINAL_BASE_RUN_ID'
python -m pytest RP1_Project/rp1_analysis/tests/test_execution_export_real_run.py --basetemp ABSOLUTE_FRESH_WORKSPACE_TEST_DIRECTORY
```

The test first requires actual run validation to pass, preserves source file
timestamps while copying the generated family/data to its test temporary area,
then injects a newline-only table edit after a second actual validation. Export
must refuse it before a qualified manifest is published. The original run and
its input/lineage authorities remain read-only. Without the two explicit
selections the test reports a generated-input prerequisite skip, not a pass.
