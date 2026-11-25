# Analysis execution and external SaTScan results

Stage 5 analyses the complete, admitted monthly study panels. Follow the
[root README](../README.md) for the
five-stage route and input handoff. All commands below start in
`RP1_Project/rp1_analysis` unless another working directory is specified.
Use the intended checkout's `rp_ghana_fire` environment and kernel.

## Input validation

```bash
python scripts/validate_inputs.py
python scripts/render_data_schema_contract.py --check
python scripts/render_data_contract_roles.py --check
python -m ipykernel install --user --name rp_ghana_fire --display-name "Python (rp_ghana_fire)"
```

Require `RP1_ANALYSIS_V1_INPUT_VALIDATION=PASS` and both contract checks to pass.
Keep the declared study period, prepared source identities and input inventory
unchanged throughout execution. A genuine external scan run must retain its
executable identity and execution evidence; successful parsing alone cannot
establish which executable produced the files.

## Interactive notebook: complete external-results route

Start this route with a fresh analysis run ID. It pauses after 04-01 while both
SaTScan models are run externally, then integrates their results in 04-02 before
Sections 90 and 99. The controlled `execute_notebook.py` command runs cells
without such a pause and can finish with `EXTERNAL_RESULTS_REQUIRED`.

Complete either input route in the [root README](../README.md#stage-5-full-analysis-handoff-and-notebook).
Use the same checkout and its Python 3.13 environment, run `validate_inputs.py` and
both contract `--check` commands successfully; and install a qualified local
SaTScan **10.3.3** executable. The package does not install or run SaTScan in
the notebook. Obtain the appropriate executable and user guide from the
[official SaTScan download page](https://www.satscan.org/download_satscan_for_linux.html)
or its Windows download link. The instructions below describe the interface;
local SaTScan execution and executable qualification must be verified on the
machine being used.

1. From `RP1_Project/rp1_analysis`, choose a **fresh** base run ID whose
   `_sec`, `_pub` and `_close` directories do not already exist. Set it before
   launching JupyterLab. For example, in WSL/Linux Bash:

   ```bash
   conda activate rp_ghana_fire
   export RP1_NOTEBOOK_RUN_ID=ghana_fire_study
   python -m ipykernel install --user --name rp_ghana_fire --display-name "Python (rp_ghana_fire)"
   jupyter lab --no-browser
   ```

   Open the localhost URL printed by Jupyter in a Windows browser. The
   `--no-browser` option avoids WSL attempting to launch a Linux browser.
   Jupyter may mark a notebook as untrusted until its outputs have been
   reviewed and trusted; this does not stop the kernel from starting.

   Or, in a native Windows PowerShell session, from the same analysis
   directory in the intended checkout and a separately configured Windows
   environment:

   ```powershell
   conda activate rp_ghana_fire
   $env:RP1_NOTEBOOK_RUN_ID = 'ghana_fire_study'
   python -m ipykernel install --user --name rp_ghana_fire --display-name "Python (rp_ghana_fire)"
   jupyter lab
   ```

   Open `RP1_Analysis_v1.ipynb` and select `Python (rp_ghana_fire)`. Confirm
   the displayed `run_tag` is the chosen ID and the package/input identities
   belong to this checkout. Do not change the shared editable installation
   while the notebook is active.

2. Execute the notebook cells **in order through the code cell under 04-01**.
   Stop before the code cell under 04-02. Leave the kernel and its variables
   running. The 04-01 output displays `secondary.secondary_run_registry` with
   each model's parameter and input paths and `results_prefix`. The run root
   is `out/runs/ghana_fire_study_sec/` relative to the analysis directory;
   the registry paths and the paths inside the `.prm` files are relative to
   that secondary run root.

3. In a separate terminal, run the two **unchanged** generated parameter files
   with the qualified SaTScan batch executable, with the secondary run root as
   the process working directory. The following are command templates: replace
   the executable path and use the paths shown by this run's registry. For
   WSL/Linux with a Linux SaTScan executable:

   ```bash
   cd out/runs/ghana_fire_study_sec
   /absolute/path/to/SaTScanBatch 04_secondary_concentration/satscan/MCD64A1_POISSON_PRIMARY/MCD64A1_POISSON_PRIMARY.prm && \
   /absolute/path/to/SaTScanBatch 04_secondary_concentration/satscan/VIIRS_STP_PRIMARY/VIIRS_STP_PRIMARY.prm
   ```

   For Windows PowerShell with a Windows executable and a secondary run on a
   Windows-accessible filesystem, use the Windows path to the **same** checkout.
   This can also be used with a WSL notebook whose checkout is on `/mnt/c`:

   ```powershell
   Set-Location out/runs/ghana_fire_study_sec
   & 'C:\path\to\SaTScanBatch64.exe' '04_secondary_concentration/satscan/MCD64A1_POISSON_PRIMARY/MCD64A1_POISSON_PRIMARY.prm'
   if ($LASTEXITCODE -ne 0) { throw 'MCD64A1_POISSON_PRIMARY failed' }
   & 'C:\path\to\SaTScanBatch64.exe' '04_secondary_concentration/satscan/VIIRS_STP_PRIMARY/VIIRS_STP_PRIMARY.prm'
   if ($LASTEXITCODE -ne 0) { throw 'VIIRS_STP_PRIMARY failed' }
   ```

   Start each example from the analysis directory in a separate terminal;
   stop and investigate if either execution fails. The MCD64A1 Poisson model
   uses the generated population file; the VIIRS space-time permutation model
   has no population file. Keep the generated parameters and input files
   unchanged. Retain the executable path, version and SHA-256, input and
   output hashes, execution logs and timestamps as external execution
   evidence. Do not assume a Windows executable can use Linux-only paths or
   that a GUI resolves relative paths as the batch working directory does.
   Cross-platform execution against a WSL-mounted Windows drive requires local
   verification of executable access, resulting paths and timestamps.
   To capture an observed receipt for each primary run, use the
   [recording wrapper commands](EXECUTION_EVIDENCE.md#record-an-external-satscan-execution)
   in place of the two direct batch commands.

4. For **each** model, check that the exact `ResultsFile` prefix in its `.prm`
   has the extensionless main report, `<prefix>.col.txt` and `<prefix>.gis.txt`
   at the run-relative locations. Preserve any auxiliary files and the raw
   outputs. A partial family or a single completed model is not enough. Do not
   replace the parameter or input files, or copy results from a different run.

5. Return to the same Jupyter kernel and run 04-02. Proceed only if the
   displayed integration state is `RESULTS_VALIDATED`; errors, partial families
   or `EXTERNAL_RESULTS_REQUIRED` do not satisfy the full-results route.
   To produce the restricted-scan supplement, pause here and follow the
   [restricted burned-area scan](#restricted-burned-area-scan) instructions.
   Then execute the remaining cells in order through Sections 90 and 99.
   Section 90 generates T3, F6 and S6 from the validated primary results and
   S21-S24 from the validated restricted result family when available. Review
   the recorded result states in the closed run.

   Successful integration clears the pending-result
   `EXTERNAL_RESULTS_REQUIRED.txt` markers from both governed result folders.
   Pending or invalid results keep their markers. Inspection and reuse of an
   already validated run remain read-only. A validated state beside pending
   markers or an incomplete transition is rejected as a conflict; inspection
   leaves the sealed run read-only. Follow the explicit
   [provenance recovery procedure](../RP1_Project/rp1_analysis/docs/PROVENANCE_RECOVERY.md).

6. From a terminal in `RP1_Project/rp1_analysis` with the same checkout and
   environment, validate the completed interactive run:

   ```bash
   python scripts/validate_run.py --run-id ghana_fire_study
   ```

   Require `RP1_ANALYSIS_V1_RUN_VALIDATION=PASS` and check that the reported
   secondary state is `RESULTS_VALIDATED`. Direct Jupyter finalisation records
   interactive execution; it does not create the controlled wrapper's executed
   notebook snapshot. Reconcile T3/S6 and recurrence outputs with the validated
   raw results and review the executable and execution evidence. Raw files alone
   do not establish the exact binary; the prospective receipt route below
   records the operator-invoked executable and checks it during ingestion. See
   the [secondary analysis contract](../RP1_Project/rp1_analysis/docs/Secondary_Analysis_Contract.md)
   and [SaTScan result qualification](../RP1_Project/docs/satscan_results.md).

If the notebook has already completed with deferred results, do not rerun its
publication or closeout cells over existing run directories. Preserve that run
and use a fresh run ID for the interactive route above. If the kernel is lost at the pause, preserve the secondary run and its inputs.
When the publication and closeout destinations and publication-source directory
are absent, `python scripts/execute_notebook.py --run-id ghana_fire_study --kernel rp_ghana_fire`
can resume the same validated secondary run in a fresh kernel. Keep inputs and
configuration unchanged; the wrapper revalidates the result family. If any
publication or closeout destination is partial, preserve it and prepare a fresh
run family instead of overwriting it.


## Restricted burned-area scan

After 04-02 validates both primary scans, run the restricted MCD64A1 scan
before Section 90. From the analysis directory, use the prepared secondary
run and an unoccupied `support_sensitivity` directory within it. This example
uses the run ID from the root runbook and a Windows SaTScan installation path:

```powershell
python scripts/execute_scan_sensitivity.py --baseline-secondary-dir out/runs/ghana_fire_study_sec --run-dir out/runs/ghana_fire_study_sec/support_sensitivity --executable "C:/Program Files/SaTScan/SaTScanBatch64.exe"
```

For the desktop app, prepare the sensitivity files from the analysis directory:

```bash
python scripts/execute_scan_sensitivity.py --baseline-secondary-dir out/runs/ghana_fire_study_sec --run-dir out/runs/ghana_fire_study_sec/support_sensitivity --prepare-only
```

Open `support_sensitivity/modis_gt50.prm` from the secondary run in SaTScan.
Set the case, coordinate and population paths to the generated input files
and the output prefix to `support_sensitivity/results/modis_gt50`. Use
absolute paths in the app. If saving desktop settings, save a separate
copy and preserve the generated parameter file and inputs as the comparison
authority. After SaTScan finishes, run this from the analysis directory:

```bash
python scripts/execute_scan_sensitivity.py --baseline-secondary-dir out/runs/ghana_fire_study_sec --run-dir out/runs/ghana_fire_study_sec/support_sensitivity --integrate-results
```

The desktop route records validated result files. The batch route also records
an observed subprocess receipt.

On Linux or WSL pass the compatible native batch executable. The interface
uses the validated baseline and retains districts whose unrounded, admitted
fixed BA-2001 burnable area exceeds 50 km². The engine population file provides
the exposure at its exchange precision. The separate sensitivity directory
holds the support authority, input hashes, parameters, raw results and any
observed execution receipt. The derived comparison is published as a unit.
After a successful execution, return to the notebook and continue Sections 90
and 99. Inspect S21-S24 and the restricted-scan evidence status. A deferred
restricted scan leaves S21-S24 unavailable.

## Independent trend sensitivity

The trend supplement can be reproduced separately from a governed S4 annual
rate table. Obtain the table SHA-256 from the verified publication or
execution evidence inventory. From `RP1_Project/rp1_analysis` run:

```text
python scripts/evaluate_trend_sensitivity.py --s4 PATH_TO_S4 --expected-s4-sha256 TRUSTED_S4_SHA256 --output-dir FRESH_DESTINATION
```

The command writes the interval, calibration and detectability outputs and
the resolved simulation settings. `MANIFEST.json` records the S4 and
configuration digests and the output inventory. The presence of this terminal
manifest identifies a completed sensitivity export. Use a fresh directory for
a retry after an interrupted write.

## Controlled notebook execution

Choose this route for a fresh analysis ID when no live pause is required.
For a strict export, use the [prospective execution sequence below](#prospective-execution-evidence)
and resume the same prepared ID before publication and closeout exist.

```bash
python scripts/execute_notebook.py --run-id ghana_fire_study_controlled --kernel rp_ghana_fire
python scripts/validate_run.py --run-id ghana_fire_study_controlled
```

The command executes cells in order in a fresh kernel and does not launch
SaTScan. It can finish with `EXTERNAL_RESULTS_REQUIRED`. Report that state as
pending external integration; wrapper execution success is not a complete RQ4
or scientific qualification result. Do not replace the publication/closeout
files from a completed pending run. To integrate results before publication,
use the interactive route with an unused ID, or follow the narrowly defined
recovery conditions above when its publication and closeout destinations have
not been created.

## Interpreting and exporting outputs

Inspect input-support, exclusion, denominator and reconciliation diagnostics.
The monthly mapped-area sum is cumulative mapped monthly area; it need not be
a unique annual footprint. Poisson expectations and relative risk differ from
space-time permutation conditional expectations and observed/expected ratios.
Do not report a conditional permutation ratio as a Poisson relative risk.

After completed run validation, derive presentation PNG/PDF files from the
actual closeout directory, for example `out/runs/ghana_fire_study_close`.
RQ4 exports and `--all` require validated external scan results. See the
[presentation exporter guide](../RP1_Project/rp1_analysis/docs/Presentation_Figure_Exporter.md).
Software checks do not qualify remote GEE asset equivalence, full-period
satellite observation support, spatial exchangeability or physical fire truth.

## Prospective execution evidence

For a newly prepared secondary run, the optional operator-invoked
`scripts/execute_satscan_with_evidence.py` runs one selected external model and
records the actual batch executable, unchanged input identities, command,
working directory, console logs, timing, exit status and raw output hashes.
Run it separately for both governed models before 04-02; the notebook itself
continues not to launch SaTScan. Existing output/evidence paths are refused.

For a strict export, check the host before preparing a run. From the repository
root in the dedicated project environment, pass the native Batch executable
for the operating system. This Windows example checks sockets, starts an
isolated disposable kernel, and probes the governed SaTScan version:

```powershell
python tools/preflight_environment.py --strict-execution "C:/Program Files/SaTScan/SaTScanBatch64.exe" --timeout-seconds 25
```

A failure identifies the unavailable prerequisite. Repair the runtime or use
a compatible machine before retrying. A preflight pass confirms readiness to
attempt strict execution. The three scans and controlled notebook still have
to run and produce their own evidence.

Use a fresh base ID and follow this sequence from `RP1_Project/rp1_analysis`.

1. In Jupyter, execute through 04-01 to prepare the secondary inputs.
2. Run both [recorded primary model commands](EXECUTION_EVIDENCE.md#record-an-external-satscan-execution)
   with the prepared `<base-id>_sec` and the actual batch executable. Run
   04-02 and require `RESULTS_VALIDATED`.
3. Run `scripts/execute_scan_sensitivity.py` with `--executable` for the
   restricted scan, then check its integration and observed receipt.
4. Leave Sections 90 and 99 for the controlled wrapper. Run the following
   commands in order, using the same prepared base ID and a fresh evidence
   directory outside the analysis tree.

```text
python scripts/execute_notebook.py --run-id new_run --kernel rp_ghana_fire
python scripts/validate_run.py --run-id new_run
python scripts/export_execution_evidence.py --run-id new_run --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY
python scripts/export_execution_evidence.py --output-dir ABSOLUTE_NEW_WORKSPACE_DIRECTORY --validate-only --expected-manifest-sha256 TRUSTED_MANIFEST_SHA256
```

Strict export requires an error-free controlled snapshot and an observed
execution receipt for each of the two primary scans and the restricted scan.
The exporter can record missing attestations in a declared-limited bundle.
Use the manifest SHA-256 conveyed by the provider for independent transfer
verification. [Execution evidence](EXECUTION_EVIDENCE.md)
