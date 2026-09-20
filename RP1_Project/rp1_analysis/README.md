# Ghana Fire RP1 Analysis v1.2.3

`rp1-analysis-v1` is the standalone reproducible analysis package for the Ghana landscape-fire study. Reusable statistical, spatial, modelling, SaTScan-interface and publication logic is implemented in `src/rp1_analysis_v1/`; `RP1_Analysis_v1.ipynb` is the canonical thin orchestration notebook.

## Product identity

- Distribution: `rp1-analysis-v1`
- Package: `rp1_analysis_v1`
- Version: `1.2.3`
- Analysis schema: `rp1-analysis-v1.1`
- Data schema: `rp1-data-schema-v1.1`
- Canonical notebook: `RP1_Analysis_v1.ipynb`
- Python: `>=3.13,<3.14`

## Scientific questions and design

The study is observational. MCD64A1 mapped burned area and active-fire thermal detections are complementary observation systems, not interchangeable measurements or ground truth.

1. **RQ1 — spatial-scale dependence:** long-run MCD64A1 burned-area burden, district heterogeneity, circular seasonality and spatial organisation during 2001–2024.
2. **RQ2 — temporal robustness:** monotonic ACZ change in annual fixed-support burned-area rate using Sen slopes and the studentized global Mann–Kendall permutation test, with Benjamini–Hochberg adjustment across five ACZ tests.
3. **RQ3 — cross-product observability:** among VIIRS-positive district-months, associations with absence of corresponding MCD64A1 mapped burned area using Firth-type penalised marginal GEE.
4. **Secondary analysis:** district-level space-time concentration using MCD64A1 discrete-Poisson SaTScan and VIIRS space-time-permutation SaTScan.

The analysis does not estimate causal effects of climate, land use, ignition sources, management or other drivers.

## Governed datasets

- ACZ panel: 1,440 rows, 5 ACZs, January 2001–December 2024.
- District panel: 74,880 rows, 260 districts, January 2001–December 2024.
- Long-run district population: 72,000 rows, 250 districts.
- Paired overlap population: 38,595 rows, 249 districts, February 2012–December 2024.
- RQ3 model population: 22,939 VIIRS-positive district-months, 249 districts.

`data/input_sha256.json` records the exact byte identities shipped with the canonical release. Runtime admission is separate: current files must satisfy the complete governed schema, support, geometry, reconciliation and analytical-population contract. A scientifically valid reconstruction can therefore be analysed with `canonical_input_identity=DIFFERENT`; structural missingness is still never recoded as an observed zero. Every run records the SHA-256 and size of the current files actually analysed.

## Configuration hierarchy

Five machine-readable contracts jointly define the executable study:

- `config/analysis_contract.yml` — study design, populations, field roles and scientific parameters;
- `config/data_schema_contract.yml` — panel, geometry and relationship schema;
- `config/method_authorities.yml` — qualified method identities;
- `config/output_contract.yml` — table and supplementary-output identities;
- `config/figure_contract.yml` — figure identities, panel sources and presentation policy.

See `docs/Configuration_Guide.md`.

## Installation

### Canonical Conda environment

From the repository root, create and activate the declared environment:

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
```

The environment uses Python `>=3.13,<3.14` and installs `geo_data_prep`, `rp1_mv_firms_panels` and `rp1_analysis` from the same checkout.

### Normal analysis use

Normal RP1 analysis needs the `rp1_analysis` product itself. Source mode uses the editable current subproject; distribution mode uses a non-editable wheel.

```bash
python -m pip install -e .
# Offline/source-controlled installation may use:
python -m pip install --no-build-isolation --no-deps -e .
python -c "import rp1_analysis_v1; print(rp1_analysis_v1.__version__); print(rp1_analysis_v1.__file__)"
```

### Complete source qualification

The complete reference/integration test estate additionally imports sibling source projects shipped in the same repository. From the repository root, install all three editable checkouts and run the repository-owned qualifier:

```bash
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_analysis
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python tools/qualify_source_checkout.py
```

The source qualifier verifies all three operational import origins, constructs the governed clean projection defined by `config/qualification_contract.yml`, proves projected import origins, regenerates the Stage-1 example, and runs the complete repository pytest estate from the clean tree. Normal editable-install metadata in the operational checkout is recorded and excluded by the projection policy rather than accepted by the release-hygiene tests.

For the complete environment/source/build/install lifecycle, use an evidence directory outside the repository:

```bash
python tools/qualify_environment.py --evidence-dir /path/to/external/rp1_qualification_evidence
```

The canonical qualifier keeps operational checkout checks, clean-source pytest, clean wheel builds and isolated wheel-import checks as separate authorities. The evidence directory is recreated internally for projection/build/install runtime state on each run; `pytest` is a hard gate.

Build/install distribution mode in a clean Python 3.13 environment:

```bash
python -m build --wheel --outdir dist .
python -m pip install --no-deps dist/rp1_analysis_v1-1.2.3-*.whl
```

## Operational CLI

The installed package exposes a thin package-owned command surface. It delegates to the same validation, reference-method, notebook, run-validation and SaTScan-interface implementations used by the source scripts. SaTScan execution remains external.

```bash
rp1-analysis version
rp1-analysis doctor
rp1-analysis validate-inputs
rp1-analysis reference-check
rp1-analysis run --run-id example_run
rp1-analysis validate-run --run-id example_run --write-report
rp1-analysis satscan prepare --run-id example_secondary
rp1-analysis satscan status --run-id example_secondary
rp1-analysis satscan integrate --run-id example_secondary
```

There is intentionally no `rp1-analysis satscan run` command. The `prepare` command writes the governed SaTScan interfaces; `status` performs read-only external-result inspection; `integrate` validates and binds complete genuine result families.

## Run families and execution modes

A canonical analysis run uses one base run ID and three governed members under `out/runs/`:

- `<run_id>_pub` — publication tables, figures and machine-readable source authorities;
- `<run_id>_sec` — deterministic SaTScan interfaces, external-result state and any validated run-local secondary publication sources;
- `<run_id>_close` — realised configuration, provenance, canonical gates, execution evidence and run-validation outputs.

The package recognises two legitimate completion modes. The mode is recorded explicitly in `99_closeout/M_NOTEBOOK_EXECUTION.json`; validation never infers interactive execution merely because an automated artefact is missing.

### Direct Jupyter execution

Activate the canonical environment, start Jupyter from this subproject (or otherwise ensure this checkout is the active package source), optionally choose a stable run ID, then execute every cell in `RP1_Analysis_v1.ipynb` in order:

```bash
export RP1_NOTEBOOK_RUN_ID=my_run       # optional; otherwise a timestamped ID is generated
jupyter lab RP1_Analysis_v1.ipynb
```

The notebook's final section calls the package-owned interactive closeout API. A successful direct run records `execution_mode: interactive_jupyter`, the run/configuration/schema identities, all required section gates, the finalisation state and the secondary state. Interactive closeout does **not** claim that the Jupyter front-end saved the notebook document and therefore does not fabricate an executed-notebook snapshot or wrapper-observed code-cell evidence. Repeating identical interactive finalisation is idempotent; conflicting completion evidence fails closed.

### Controlled automated notebook execution

Use either the CLI or compatibility script:

```bash
rp1-analysis run --run-id my_run
# equivalent source-script form
python scripts/execute_notebook.py --run-id my_run
```

Controlled execution uses a fresh `nbclient` kernel in an isolated working directory and records `execution_mode: controlled_nbclient`. It requires the stronger automated evidence: a complete executed-notebook snapshot, its SHA-256, kernel/execution metadata and evidence that every canonical code cell executed. The notebook detects the controlled context and defers final execution-record ownership to the wrapper.

### Secondary-state reuse and resume

A canonical run may complete with `EXTERNAL_RESULTS_REQUIRED`. This is a valid completed state for RQ1–RQ3 and means that genuine external SaTScan result families have not yet been validated; it does **not** mean that zero significant clusters were found. After the separately qualified SaTScan application has produced both governed result families at the parameter-file `ResultsFile` locations, `rp1-analysis satscan status` and `rp1-analysis satscan integrate` validate provenance and bind the results. A complete current secondary authority then records `RESULTS_VALIDATED`.

A controlled notebook run may resume a pre-existing secondary member only when that member satisfies the shared package-owned secondary contract. Valid `RESULTS_VALIDATED`/integrated authorities are reused read-only. Partial, stale, wrong-model, wrong-period, wrong-input, path-invalid or otherwise inconsistent result families are rejected rather than downgraded or silently replaced.

### Run validation

Validate a completed family by its base run ID:

```bash
rp1-analysis validate-run --run-id my_run --write-report
# equivalent source-script form
python scripts/validate_run.py --run-id my_run --write-report
```

Validation resolves all three run members and applies the same execution/closeout contract used by notebook finalisation, the controlled wrapper and presentation-export preflight. It checks package, schema and configuration identities; required section and publication gates; mode-specific execution evidence; secondary-state concordance; output schemas; inventories; and provenance. Repeated validation is supported. Unknown execution modes, malformed closeout, invalid configuration identity and unsupported or stale secondary state fail closed.

## Presentation figure export

Standalone presentation figures are derived from an existing qualified run through the single public script:

```bash
python scripts/export_presentation_figures.py --list
python scripts/export_presentation_figures.py --run-dir out/runs/<run_id>_close --output-dir presentation_figures --figure rq2_coastal_trend
python scripts/export_presentation_figures.py --run-dir out/runs/<run_id>_close --output-dir presentation_figures --group rq3
python scripts/export_presentation_figures.py --run-dir out/runs/<run_id>_close --output-dir presentation_figures --all
```

The exporter treats the source run as read-only and writes only to the new external destination. RQ4 exports require genuine `RESULTS_VALIDATED` SaTScan results and fail closed on `EXTERNAL_RESULTS_REQUIRED`. See `docs/Presentation_Figure_Exporter.md` for output layout, formats, manifest fields, collision behaviour and scripting exit semantics.

## Source-script forms

The existing source-script commands remain available and call the same package-owned operational functions:

```bash
python scripts/validate_inputs.py
python scripts/qualify_reference_methods.py
python scripts/execute_notebook.py --run-id example_run
python scripts/validate_run.py --run-id example_run --write-report
python -m pytest
```

The notebook loads governed configuration and inputs, invokes package-owned RQ builders, prepares the external SaTScan interface, constructs publication outputs and records run metadata. It contains no implementations of Sen slope, permutation inference, circular statistics, Moran statistics, PGEE/MBN equations or SaTScan scientific parameter decisions.

## RQ1 method

RQ1 uses the fixed BA-2001 burnable-area denominator, direct ACZ rates, district median/IQR/Gini summaries, district-minus-parent-ACZ departures, circular mean/resultant length, first-order Queen row-standardised weights, one national Global Moran statistic with 9,999 permutations, and Local Moran statistics with 9,999 conditional permutations and BH-FDR across eligible non-island districts.

## RQ2 method

Each of the five ACZs contributes 24 annual fixed-support rates. Sen's slope reports direction and magnitude; it is not the null hypothesis of the inferential test. Inference uses the Romano–Tirlea studentized global Mann–Kendall permutation procedure. The reference global framework formulates the null as strict stationarity under its stated weak-dependence conditions. The strict production route is reference-qualified only for tie-free realised annual series: all five Ghana ACZ series are tie-free, and configured tied input fails closed rather than invoking an unqualified extension. Generic pairwise MK code still assigns zero contribution to equal pairs, but that kernel behaviour is not inferential qualification for tied time series. The governed finite-sample choices are `floor(n^(1/3))` (realised bandwidth 2 at n=24), variance floor 0.001, 9,999 permutations, seed 20260822, two-sided absolute extremeness, plus-one Monte Carlo p-values and BH adjustment across exactly five ACZs. These finite-sample choices are study/computational authorities rather than uniquely theorem-mandated parameters. All five realised Sen slopes are negative, but none has BH-FDR-supported evidence of monotonic decline at alpha 0.05; non-rejection does not establish no temporal change and the analysis is not causal.

## RQ3 method

RQ3 conditions on VIIRS-positive district-months. The fixed 31-column design contains an intercept; log2 VIIRS detection count; log2 mean FRP; log2 fixed BA-2012 burnable area; categorical month; categorical year; and ACZ. VIIRS active days and MODIS active-fire co-detection are not model predictors. Estimation uses Firth-type penalised GEE with binomial-logit mean, district clustering, working independence and Morel–Bokossa–Neerchal covariance. Inference uses standard-normal Wald statistics. Predictive standardisation reports Q25/Q75 probabilities for the two focal VIIRS predictors over the observed covariate distribution.

## Secondary SaTScan method

- **MCD64A1:** retrospective space-time discrete Poisson; burned-pixel cases; fixed BA-2001 burnable-area exposure; 250 districts.
- **VIIRS:** retrospective space-time permutation; `viirs_det_primary` cases; 249 paired-supported districts; no population/exposure file.

Both use a circular 50% spatial ceiling, 1–12 month temporal window, 999 Monte Carlo replications, high clusters only and hierarchical non-overlapping reporting. District coordinates use the polygon centroid when covered by the polygon and otherwise a point-on-surface.

Configured SaTScan study windows are expressed as calendar months in `analysis_contract.yml`. The interface serialiser represents the start month with its first calendar day and the end month with its final calendar day, using the actual month length and leap-year calendar. The current MCD64A1 interface therefore spans `2001/1/1` to `2024/12/31`, and the VIIRS interface spans `2012/2/1` to `2024/12/31`. These day values are interface representation semantics; they do not redefine the configured study months.

SaTScan is an external engine and the notebook does not execute it. Section 04-01 always generates the deterministic `.cas`, `.geo`, model-appropriate `.pop` and `.prm` interfaces. Section 04-02 validates optional external output at the `ResultsFile` locations governed by those parameter files. If neither result family is present, the run records `EXTERNAL_RESULTS_REQUIRED` and continues automatically. If both MCD64A1 and VIIRS result families are complete, current-run, provenance-bound and parse-valid, the run records `RESULTS_VALIDATED`. Any partial, stale, path-escaping, identity-mismatched or otherwise invalid material fails closed. Validated live publication sources are written only below the current run and never to repository authority directories.

## Publication structure

Manuscript Figure 1 (study area / analytical geography) is supplied externally by the author and is outside the generated runtime figure estate. The project generates exactly **5 main figures, F2–F6, and 3 main tables**. The supplement is exactly **Tables S1–S6 and Figure S1**. T3, F6 and S6 depend on genuine validated SaTScan output. F6 is a descriptive recurrence projection: district colour is the number of distinct validated significant SaTScan clusters containing that eligible district for the relevant product. It is not a new inferential test, district relative risk or permanent-hotspot classification. All other generated publication products are derived from qualified machine-readable authorities. See `docs/Output_Guide.md` and `docs/Figure_Table_Contract.md`.

## Reproducibility and provenance

Runs record configuration hashes, exact current input hashes and sizes, `input_validation_status`, `canonical_input_identity`, software metadata, method-qualification state, output inventories and file hashes. `M_CANONICAL_EXECUTION_GATE.json`, `M_REPRODUCIBILITY_MANIFEST.json` and the v3 `M_NOTEBOOK_EXECUTION.json` must agree on the runtime-validation and canonical-identity states. The current human-readable methods DOCX/PDF identity is recorded separately in `data/authorities/methods_document_authority.json`; immutable scientific run snapshots retain the methods-document SHA used when they were materialised. All paths used by public workflows are repository-relative or configuration-driven. See `docs/Reproducibility_Contract.md`.

## Scientific limitations

Satellite omission/commission, overpass timing, atmospheric obscuration, viewing geometry, product resolution and monthly aggregation affect observation. District boundaries are reporting units rather than causal fire-process units. Cross-product mismatch is not product error without independent validation. Trend estimates and PGEE associations are observational and do not identify drivers.

## Troubleshooting

- **Command not found:** activate `rp_ghana_fire` and reinstall the analysis package from the current checkout.
- **Unexpected import origin:** from the repository root reinstall all three editable packages and run `python tools/qualify_source_checkout.py --origins-only`.
- **Input-validation failure:** correct the reported schema/support/geometry/reconciliation/population defect. `PASS + DIFFERENT` is a valid runtime state and means only that the scientifically admissible current bytes do not equal the release bytes; do not rewrite `data/input_sha256.json` to suppress that distinction.
- **`EXTERNAL_RESULTS_REQUIRED`:** this is the expected state when genuine external SaTScan result families are absent. RQ1–RQ3 and all non-SaTScan-dependent publication outputs remain valid.
- **Partial/stale SaTScan family:** the integration route fails closed by design. Use result files produced from the current prepared `.prm`/input family.
- **Run validation failure:** inspect the run-local validation report and manifest before rerunning; do not copy outputs from another run into the current run directory.

## Documentation

- `docs/Analysis_Methods_Contract.md`
- `docs/Configuration_Guide.md`
- `docs/Data_Contract.md`
- `docs/Data_Schema_Contract.md`
- `docs/Figure_Table_Contract.md`
- `docs/Ghana_Fire_Scientific_Analysis_Methods_Specification_2026-08-28.docx`
- `docs/Ghana_Fire_Scientific_Analysis_Methods_Specification_2026-08-28.pdf`
- `docs/Method_Authority_Register.md`
- `docs/Output_Guide.md`
- `docs/Presentation_Figure_Exporter.md`
- `docs/Reference_Method_Validation.md`
- `docs/Reproducibility_Contract.md`
- `docs/RP1_Analysis_v1_Cell_Contract.md`
- `docs/Secondary_Analysis_Contract.md`
- `docs/Variable_Map.md`

## Licence

BSD-3-Clause. See `LICENSE`.
