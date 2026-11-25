# Ghana Fire Dynamics Analysis — analytical workflow

This package analyses the workflow-generated district and agro-climatic-zone fire panels and matching geography. Use the repository-root README for environment setup, geography preparation, Archive SP validation/admission, active-fire processing, c3-only burned-area merging and analysis input handoff.

The shared Python 3.13 environment installs four editable packages:
`geo_data_prep`, `mv_firms_panels`, `rp1_analysis_v1` and `ghana_fire_archive`
from `RP1_Project/rp1_firms_archive`. It includes the producer's `requests` and
`pyshp` dependencies. From the repository root, run
`python tools/qualify_source_checkout.py --origins-only` to verify all four
origins and the shared c3 contract before using a matching notebook kernel.

To prepare active-fire inputs, the automated `geo`, then Stage 3 `archive-plan`, `archive`,
`archive-admit`, `firms` sequence prepares a run-local FIRMS bundle under
`RP1_Project/rp1_mv_firms_panels/out/runs/<run-id>/source_inputs/`. `existing`
mode validates a whole Archive and its QA evidence read-only through the current
producer API. The default `build` route acquires and prepares the fire inputs,
while `geo` stages boundaries and unit metadata. The consumer raw directory
is empty in the source ZIP. Optional `bundled` mode requires separately
available admitted shared inputs and preserves their original authority,
including its recorded source-generation semantics. Source generation identity and current
validator identity remain separate in the retained evidence. See the
[Archive integration guide](../../docs/FIRMS_ARCHIVE_INTEGRATION.md).

Full-study active-fire admission selects 24 MODIS and 13 Suomi-NPP source years
(37 families), with the first Suomi-NPP interval beginning on 20 January 2012.
This accepted partial first month does not alter the paired analysis windows.
Missing or unchecked required intervals fail; verified empty source years retain
empty observation lineage and do not imply physical fire absence. NOAA-20/21 are outside this study. TYPE/confidence selection and independent FRP definitions follow the configured method contracts.

The repository supplies the workflow and original Earth Engine CSV inputs.
If you already have a complete analysis-input companion, follow the
[data access guide](../../docs/data_access.md) to verify and admit it.
To generate the analysis inputs yourself, complete the upstream workflow and
its input handoff. Validate the selected inputs before notebook execution.
Each run records input identities, eligible populations and exclusions.

## Stage 5 execution

Follow the [root runbook](../../README.md) to prepare or admit the study inputs.
From this analysis directory, with `rp_ghana_fire` active:

```bash
python scripts/validate_inputs.py
python scripts/render_data_schema_contract.py --check
python scripts/render_data_contract_roles.py --check
python -m ipykernel install --user --name rp_ghana_fire --display-name "Python (rp_ghana_fire)"
```

The primary route is the interactive notebook with genuine SaTScan results.
Choose the shell-specific launch command in the
[analysis execution guide](../../docs/ANALYSIS_EXECUTION.md), using
`RP1_NOTEBOOK_RUN_ID=ghana_fire_study`. Run through 04-01, pause for both
external scans, integrate in 04-02 and require `RESULTS_VALIDATED`. Complete the
[restricted burned-area scan](../../docs/ANALYSIS_EXECUTION.md#restricted-burned-area-scan)
before Sections 90 and 99 to produce the sensitivity tables. Then run:

```bash
python scripts/validate_run.py --run-id ghana_fire_study
```

For controlled execution without an interactive pause, choose an unused
analysis family instead:

```bash
python scripts/execute_notebook.py --run-id ghana_fire_study_controlled --kernel rp_ghana_fire
```

The controlled route does not launch SaTScan and may retain
`EXTERNAL_RESULTS_REQUIRED`. Wrapper success is not complete RQ4 qualification.
Do not run both routes over the same result family. The notebook delegates
computation to the package; review input/configuration identities, diagnostics
and output manifests for the chosen run.

## Presentation figures

The notebook renders Figures 2–6 and Supplementary Figures S1–S4 without
embedded titles. Use the manuscript captions to identify these figures.
The presentation exporter adds a title to each of its 26 standalone outputs.
Both routes share colour scales and category styles for matching quantities.
In Figure 4, the zone statistics appear in a grey table below the legend.

From this directory, list the configured figures and export from a completed,
validated closeout run to a new destination outside the source run:

```bash
python scripts/export_presentation_figures.py --list
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_rq3 --group rq3
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_one --figure rq2_coastal_trend
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_all --all
```

Use the actual completed analysis run ID; use a different destination
for each invocation. The exporter supports `--all` and selected configured
formats. RQ4 requires validated external SaTScan results. See the
[presentation figure exporter guide](docs/Presentation_Figure_Exporter.md) for
the full commands, prerequisites and provenance.

RQ1 describes fixed-support patterns and spatial organisation; Local Moran uses the two-sided conditional rule in `docs/Local_Moran_Two_Sided.md`. RQ2 evaluates configured annual rate series under its dependence assumptions. RQ3 models the paired product relationship using nominal/high detections and the mean of eligible UTC daily FRP maxima. Model-specific secondary scan interfaces distinguish Poisson expectations/RR from conditional permutation expectations/OE. External SaTScan execution is required for actual cluster results.

A successful local calculation is not independent validation of data lineage, sensor observation support or scientific assumptions. Review burned-area grid, mask and export-lineage evidence for the selected delivery. Retain support diagnostics and distinguish assumption-derived zeroes from observed unburned evidence.

The data, method, figure/table, reproducibility and secondary-analysis contracts are under `docs/`; executable contracts are under `config/`. Focused tests are under `tests/`. Do not reuse outputs after changing inputs or configuration without regeneration and validation.

VIIRS active-fire days and MODIS active-fire co-detection are not model predictors. Eligibility fields and regression predictors have separate configured roles.

## Source and distribution installation

For source development, use an editable installation from the current checkout. With the declared environment dependencies installed, run from `RP1_Project/rp1_analysis`:

```bash
python -m pip install -e .
python -c "import rp1_analysis_v1; print(rp1_analysis_v1.__file__)"
```

For distribution qualification, use a separate clean environment and install a built wheel non-editably. From that subproject directory:

```bash
python -m build --wheel --outdir dist
python -m pip install --no-deps WHEEL_PATH
```

Replace `WHEEL_PATH` with the path to the analysis wheel just built in `dist/`.

Do not combine an editable source installation and non-editable distribution installation in the same validation environment. Confirm import origins and record the environment. Building a wheel does not generate or validate scientific inputs.

## Normal analysis use

Use the root README workflow to validate/build and admit Archive SP inputs,
prepare active-fire panels with `mv_firms_panels`, merge the selected BA source
and run `rp1_analysis`. Geography comes from `geo_data_prep` or explicit
read-only `geo-reuse` of an unchanged verified handoff; reuse preserves original
generation/QA identity and creates no new GEE assets. No completed results are
supplied. The manual curated stage/activate interface remains optional curated
input management, described in [Archive SP inputs](../../docs/FIRMS_SP_INPUTS.md).

## Complete source qualification

`tools/qualify_source_checkout.py` is the repository-level source qualification tool. It exercises the configured four-package source projection and test estate, including generated-input prerequisites and optional native plot checks. The embedded producer projection retains its reviewed source list and the reference-geography manifest while excluding runtime raw data, metadata, outputs and credentials. Read its CLI help and configure adequate temporary disk space before using it. Source qualification does not run or scientifically approve the national data analysis, GEE or SaTScan.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. Study windows are declared explicitly and bound to the admitted input evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

