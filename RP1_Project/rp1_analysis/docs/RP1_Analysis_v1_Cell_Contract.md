# Canonical notebook cell contract

`RP1_Analysis_v1.ipynb` is a thin orchestrator. Its sections are 00 scaffold/authority, 01 RQ1, 02 RQ2, 03 RQ3, 04 secondary SaTScan interface/integration, 90 publication outputs and 99 reproducibility closeout.

The notebook may load configuration/data, call package functions, display governed summaries, invoke publication builders and write run metadata. It must not implement scientific estimators, resampling/permutation algorithms, spatial statistics, PGEE/MBN equations, predictor transforms, SaTScan parser/provenance machinery or SaTScan parameter decisions. It must not auto-run SaTScan.

### 00-02 governed input admission

The notebook delegates input admission to package-owned `validate_governed_inputs()`. It requires `input_validation_status == PASS` and records `canonical_input_identity` as either `MATCH` or `DIFFERENT`; it does not treat byte identity as scientific validation. Current hashes and population summaries may be displayed, but scientific validation logic remains package-owned.

### 04-01
Always generate the deterministic external-engine interfaces and result-location authority.

### 04-02
Call the package-owned optional-result integration API and display only a concise state summary. No result families yields `EXTERNAL_RESULTS_REQUIRED`; two complete valid families yields `RESULTS_VALIDATED`; partial or invalid material fails closed. Validated publication sources are run-local.

### Section 90
Always runs. Under `EXTERNAL_RESULTS_REQUIRED`, internally available publication outputs are generated and T3/F6/S6 remain explicitly deferred. Under `RESULTS_VALIDATED`, Section 90 consumes only the validated run-local sources and generates T3, recurrence-based F6 and S6.

The package generates notebook artwork for F2–F6 and FS1–FS4. The figures show
panel identifiers, axes and keys. Figure titles and scientific panel context
belong in the manuscript captions.

### Section 99
Requires all scientific, publication and integration gates to pass, including `input_validation_status=PASS`. The canonical execution gate also records `canonical_input_identity=MATCH|DIFFERENT` without requiring either state for scientific success. It calls the package-owned interactive finalisation API. For direct Jupyter execution this writes a v3 machine-readable `M_NOTEBOOK_EXECUTION.json` without fabricating an executed-notebook snapshot. During controlled `nbclient` execution, notebook-owned finalisation is explicitly deferred to the wrapper so the wrapper can record its stronger notebook snapshot and code-cell evidence.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

