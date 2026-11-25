# Ghana Fire Dynamics Analysis

This repository analyses satellite observations of fire in Ghana from January 2001 through December 2024. It estimates burned-area baselines and trends, examines correspondence with active-fire observations, and identifies recurring space–time concentrations across districts and agro-climatic zones.

## Inputs and configuration

| Input | Where to obtain it |
| --- | --- |
| Annual MODIS burned-area exports | The repository includes all 370 original Earth Engine CSVs in `RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/`. Preserve their filenames and bytes. |
| Study boundary shapefiles | The national, district and reference-zone inputs are supplied under `geo_data_prep/data/raw/`. See [source geography](docs/SOURCE_GEOGRAPHY.md) for file identities and reuse terms. |
| FIRMS archive reference geography | Obtain the four exact reference files through an authorised source and follow [source geography admission](docs/SOURCE_GEOGRAPHY.md). |
| Standard-processing active-fire observations | The workflow acquires MODIS and Suomi-NPP data from NASA FIRMS. See [key setup](docs/FIRMS_KEY_SETUP.md) or [use an existing verified archive](docs/FIRMS_ARCHIVE_INTEGRATION.md#choose-an-input-mode). |
| Published monthly panels | The [Ghana fire panel dataset](https://doi.org/10.6084/m9.figshare.31985559.v2) contains seven data and provenance files. The [data guide](docs/data_access.md) explains the additional files required for an analysis-only run. |

The full workflow needs space for downloaded observations, annual archives, admitted source files and analysis outputs. The FIRMS working files alone can occupy about 10 GiB. Use a short, writable checkout path with sufficient free space, especially on Windows.

The [study configuration](docs/STUDY_CONFIGURATION.md) defines the analysis calendar. The source availability and paired analysis windows are distinct. Complete paired years start in 2013.

```json
"study": {
  "start_yyyymm": 200101,
  "end_yyyymm": 202412,
  "viirs_support_start_yyyymm": 201201,
  "ba2012_support_start_yyyymm": 201201,
  "analysis_overlap_start_yyyymm": 201202
}
```

## Environment

From the repository root, use a Conda-enabled WSL/Linux terminal or Windows PowerShell. Use separate environments for Windows and WSL.

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
python tools/qualify_source_checkout.py --origins-only
```

The environment uses Python 3.13, Node.js 24 and editable local packages. The origin check must resolve all four local packages and the shared burned-area contract to the intended checkout. See [environment and recovery](docs/ENVIRONMENT_AND_RECOVERY.md) if you already have an environment or need shorter temporary paths.

Follow the five steps below in order and stop if any command fails. Run all workflow commands from the repository root. Use one configuration and the same unused ID throughout. The examples use `ghana_fire_study`. For reuse of an existing verified FIRMS archive, select the configuration and complete the local checks in the [archive integration guide](docs/FIRMS_ARCHIVE_INTEGRATION.md#choose-an-input-mode) before starting.

## Stage 1: Prepare geography

Use [source geography admission](docs/SOURCE_GEOGRAPHY.md) to verify the supplied shapefiles and stage the separately obtained FIRMS archive reference files before running the full workflow.

```bash
python -m geo_data_prep validate --config geo_data_prep/configs/example_acz.yaml
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study geo
```

The workflow assigns whole districts to their maximum-overlap agro-climatic zone and stages matching analysis boundaries in EPSG:32630. Review `geo_data_prep/out/ghana_fire_study/qa/reference_coverage.csv` and the [geography handoff guide](docs/GEO_HANDOFF.md). The workflow also creates three Earth Engine upload ZIPs. Upload and export steps are needed when generating a new Earth Engine delivery.

## Stage 2: Admit burned-area exports

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 --ba-input-dir RP1_Project/rp1_gee_ba_scripts/downloads/c3_release --boundary-label approved_boundary_release consolidate-ba
```

The command validates the retained CSVs, recorded boundary label, calendars, geography and source identities. BA2001 covers 2001–2024 and BA2012 covers 2012–2024. Each uses its corresponding fixed burnable-area union throughout its window. For a new Earth Engine delivery, see the [exporter](RP1_Project/rp1_gee_ba_scripts/c3/README.md) and [burned-area preparation guide](RP1_Project/docs/ba_consolidation.md) before changing the supplied inputs.

## Stage 3: Prepare active-fire panels

The `rp1_firms_archive` producer acquires and validates the annual observations. The `rp1_mv_firms_panels` workflow admits the annual files, applies the selected filters and joins observations to the analysis boundaries. In the default acquisition mode, follow [NASA FIRMS key setup](docs/FIRMS_KEY_SETUP.md) and run the status check below using the same terminal. If you selected an existing verified archive, use its configured path and proceed to `archive-plan`.

```bash
python -c "import json; from ghana_fire_archive.core import load_config, map_key; workflow=json.load(open('configs/workflow.json', encoding='utf-8')); key=map_key(load_config(workflow['firms_archive']['producer_config'])); print('FIRMS key is configured' if key else 'FIRMS key is missing'); raise SystemExit(0 if key else 1)"
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-plan
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-admit
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study firms
```

Review source calendar, observation type, confidence, deduplication and spatial-join checks. This configuration requires 24 MODIS and 13 Suomi-NPP annual input families. See [FIRMS input checks](docs/FIRMS_SP_INPUTS.md) and the [VIIRS fire radiative power method](RP1_Project/docs/rq3_frp_method.md).

## Stage 4: Assemble the monthly panels

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 merge
```

The merger writes district and agro-climatic-zone panels to `out/workflows/ghana_fire_study/merge/c3/`. Keep the audit, manifests and `ba_observation_support.csv` with the panels. The [panel dictionary](RP1_Project/docs/data_dictionary_fire_panels.md) describes variables and support indicators.

## Stage 5: Full analysis handoff and notebook

After Stages 1–4, stage the admitted panels and all their required support files:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 analysis-inputs
```

To start at Stage 5, obtain a complete verified analysis-input companion separately and follow the [analysis-only admission instructions](docs/data_access.md#analysis-only-inputs). The seven Figshare files supply the panels and selected provenance. A separate companion also supplies boundary derivatives, input inventories and the source evidence validated by the workflow.

From the repository root, validate the staged input and register the notebook kernel:

```bash
cd RP1_Project/rp1_analysis
python scripts/validate_inputs.py
python scripts/render_data_schema_contract.py --check
python scripts/render_data_contract_roles.py --check
python -m ipykernel install --user --name rp_ghana_fire --display-name "Python (rp_ghana_fire)"
```

Require `RP1_ANALYSIS_V1_INPUT_VALIDATION=PASS` and both contract checks to pass. Set `RP1_NOTEBOOK_RUN_ID` in the terminal that launches Jupyter. Choose an unused analysis ID.

```bash
export RP1_NOTEBOOK_RUN_ID=ghana_fire_study
jupyter lab --no-browser
```

```powershell
$env:RP1_NOTEBOOK_RUN_ID = 'ghana_fire_study'
jupyter lab
```

Open `RP1_Analysis_v1.ipynb` in the `Python (rp_ghana_fire)` kernel. Run through **04-01**, pause with the kernel running, and execute both primary parameter files using a local SaTScan 10.3.3 batch executable. The [analysis execution guide](docs/ANALYSIS_EXECUTION.md#interactive-notebook-complete-external-results-route) gives the Windows and Linux commands. Return to the same kernel and execute **04-02**. Require `RESULTS_VALIDATED`.

Before Section **90**, run and integrate the [restricted burned-area scan](docs/ANALYSIS_EXECUTION.md#restricted-burned-area-scan). It retains districts whose unrounded fixed BA2001 burnable area exceeds 50 km². Then complete Sections **90 and 99**, which assemble and check the results.

```bash
python scripts/validate_run.py --run-id ghana_fire_study
```

Require `RP1_ANALYSIS_V1_RUN_VALIDATION=PASS`, check the secondary result state and confirm that the restricted analysis produced S21–S24. The execution guide also documents [controlled notebook execution](docs/ANALYSIS_EXECUTION.md#controlled-notebook-execution) and [external execution evidence](docs/EXECUTION_EVIDENCE.md).

## Export presentation figures

Run from `RP1_Project/rp1_analysis` after validating the completed run. Use a fresh output directory for each export.

```bash
python scripts/export_presentation_figures.py --list
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_rq3 --group rq3
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_one --figure rq2_coastal_trend
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_all --all
```

The RQ4 export requires validated external SaTScan results. See the [figure exporter guide](RP1_Project/rp1_analysis/docs/Presentation_Figure_Exporter.md) for output formats.

## Testing and outputs

Run the [source checkout checks](docs/PORTABILITY_AND_TEST_PLAN.md) from the repository root:

```bash
python tools/qualify_source_checkout.py
```

Use the [output guide](RP1_Project/rp1_analysis/docs/Output_Guide.md) to locate scientific results and run evidence. Generated output goes into ignored working directories. See the [data guide](docs/data_access.md) for data provenance and licensing and [LICENSE](LICENSE) for the software terms.

