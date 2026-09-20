# Canonical notebook cell contract

`RP1_Analysis_v1.ipynb` is a thin orchestrator. Its sections are 00 scaffold/authority, 01 RQ1, 02 RQ2, 03 RQ3, 04 secondary SaTScan interface/integration, 90 publication outputs and 99 reproducibility closeout.

The notebook may load configuration/data, call package functions, display governed summaries, invoke publication builders and write run metadata. It must not implement scientific estimators, resampling/permutation algorithms, spatial statistics, PGEE/MBN equations, predictor transforms, SaTScan parser/provenance machinery or SaTScan parameter decisions. It must not auto-run SaTScan.

### 00-02 governed input admission

The notebook delegates input admission to package-owned `validate_governed_inputs()`. It requires `input_validation_status == PASS` and records `canonical_input_identity` as either `MATCH` or `DIFFERENT`; it does not calculate a second historical-SHA admission gate or require `MATCH`. Current hashes and population summaries may be displayed, but scientific validation logic remains package-owned.

### 04-01
Always generate the deterministic external-engine interfaces and result-location authority.

### 04-02
Call the package-owned optional-result integration API and display only a concise state summary. No result families yields `EXTERNAL_RESULTS_REQUIRED`; two complete valid families yields `RESULTS_VALIDATED`; partial or invalid material fails closed. Validated publication sources are run-local.

### Section 90
Always runs. Under `EXTERNAL_RESULTS_REQUIRED`, internally available publication outputs are generated and T3/F6/S6 remain explicitly deferred. Under `RESULTS_VALIDATED`, Section 90 consumes only the validated run-local sources and generates T3, recurrence-based F6 and S6.

### Section 99
Requires all scientific, publication and integration gates to pass, including `input_validation_status=PASS`. The canonical execution gate also records `canonical_input_identity=MATCH|DIFFERENT` without requiring either state for scientific success. It calls the package-owned interactive finalisation API. For direct Jupyter execution this writes a v3 machine-readable `M_NOTEBOOK_EXECUTION.json` without fabricating an executed-notebook snapshot. During controlled `nbclient` execution, notebook-owned finalisation is explicitly deferred to the wrapper so the wrapper can record its stronger notebook snapshot and code-cell evidence.
