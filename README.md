# Ghana Fire RP1 Analysis

## 1. Introduction

Ghana Fire RP1 Analysis is the governed software and data workflow used to analyse landscape-fire observations across Ghana at agro-climatic-zone (ACZ) and district scales. The finished analysis product is **RP1 Analysis v1.2.3**, software version `1.2.3`.

Product identities are fixed as follows:

- distribution: `rp1-analysis-v1`
- Python package: `rp1_analysis_v1`
- software version: `1.2.3`
- analysis schema: `rp1-analysis-v1.1`
- data schema: `rp1-data-schema-v1.1`
- canonical environment: `rp_ghana_fire`
- supported Python: `>=3.13,<3.14`
- canonical analysis subproject: `RP1_Project/rp1_analysis/`
- canonical notebook: `RP1_Project/rp1_analysis/RP1_Analysis_v1.ipynb`
- external cluster engine for genuine secondary analysis: SaTScan `10.3.3`

### Public GitHub projection and qualified-release relationship

This repository is the publication-facing GitHub projection of the qualified **RP1 Analysis v1.2.3** codebase. It preserves the scientific source code, executable contracts, canonical notebook, governed geometries/reference authorities and the five canonical consolidated analysis-input files required for normal analysis.

The GitHub projection is intentionally leaner than the full qualified archival package. It does **not** track the bulky upstream FIRMS raw-source tree, Stage 1 raw boundary inputs, Earth Engine export bundles, generated run/output trees, or the external `local_qualification/` evidence estate. Those omissions do not change the normal scientific analysis because the canonical consolidated analysis inputs are tracked directly under `RP1_Project/rp1_analysis/data/raw/`. Path-specific rules in `.gitattributes` disable line-ending normalisation for those five files so their qualified bytes and SHA-256 identities are preserved by Git.

The exact archival authority from which this projection was prepared is `RP1_V123_FINAL.zip`, SHA-256 `e40e36529d7458e055d910cc8924e15f15b202398bab3e19962deda3ad0b13a6`. The public GitHub projection is therefore **not byte-identical to the full qualified archive** and should not be cited as replacement evidence for the archived local-qualification campaign. Internal product, package, schema and notebook identities remain unchanged.

For manuscript reproducibility, use the repository release/tag **`v1.2.3`**.

The repository contains four connected operational components:

- `geo_data_prep/` — Stage 1 geography preparation and spatial authorities;
- `RP1_Project/rp1_mv_firms_panels/` — Stage 2 MODIS/VIIRS active-fire panel construction;
- `RP1_Project/rp1_gee_ba_scripts/` — governed MCD64A1 burned-area preparation;
- `RP1_Project/rp1_analysis/` — governed consolidated inputs, scientific analysis, notebook execution, SaTScan interface, run validation and publication/presentation outputs.

### Observation-system distinction

The fire products are deliberately kept separate because they observe different manifestations of fire:

- **MCD64A1** provides **mapped burned-surface evidence**.
- **VIIRS active fire** provides **satellite thermal-detection evidence at overpass times**.

They are complementary observation systems. They are not interchangeable measurements, and disagreement between them is not automatically an error in either product.

### Normal analysis versus upstream reconstruction

**Normal analysis** uses the governed consolidated panels and geometries tracked under `RP1_Project/rp1_analysis/`. You do **not** need to rebuild geography, reacquire or reprocess the upstream FIRMS source files, or rerun the burned-area workflow before running the scientific analysis.

**Upstream reconstruction** is optional. Use it when you need to rebuild the geography authority, active-fire panels or final consolidated analytical inputs from their governed upstream sources. The main reconstruction flow is:

```text
geo_data_prep
    -> geography authorities

rp1_mv_firms_panels
    -> MODIS/VIIRS active-fire authorities ---------\
                                                   \
MCD64A1 BA-2001 + BA-2012 governed exports ---------> merge_af_ba_panels.py
                                                   /
                                                  /
                                governed consolidated RP1 panels
                                                   |
                                                   v
                                        rp1_analysis
```

The shipped consolidated analytical panels retain the governed support of **1,440 ACZ-months** and **74,880 district-months**. These are properties of the qualified analysis inputs; the figures should not be interpreted as evidence that a new reconstruction has been run unless you actually perform one.

## 2. Environment and installation

Run commands in this guide from the repository root unless a section states otherwise.

### 2.1 Create the canonical environment

The repository-level `environment.yml` defines the `rp_ghana_fire` environment and Python `>=3.13,<3.14`.

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
```

The environment definition installs the three local source projects. If an existing environment needs to be rebound explicitly to this checkout, use the repository's supported source-qualification order:

```bash
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_analysis
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
```

Confirm the installed command surfaces and the active package origins:

```bash
geo-prep --help
mv-firms-panels --help
rp1-analysis version
rp1-analysis doctor
```

`rp1-analysis doctor` checks the active Python runtime, import origins, configuration readability, governed-input visibility, runtime dependencies, notebook availability and SaTScan discovery. SaTScan is not required for ordinary RQ1-RQ3 analysis.

### 2.2 Source qualification and the public projection

Source qualification is broader than normal scientific analysis. The qualification utilities remain in this repository and can be used to qualify a checkout or environment:

```bash
python tools/qualify_source_checkout.py
```

For the environment/source/build/install lifecycle, keep qualification evidence outside the repository:

```bash
python tools/qualify_environment.py \
  --evidence-dir /path/to/external/rp1_qualification_evidence
```

The public GitHub projection intentionally omits bulky upstream raw-source families and the accepted `local_qualification/` evidence estate from the full archival package. A qualification run performed from this GitHub projection therefore qualifies the files present in this projection; it does **not** recreate the byte-identical terminal qualification campaign recorded in the full `RP1_V123_FINAL.zip` archive.

For ordinary manuscript reproducibility from a clean clone, the primary checks are the governed analysis checks in Section 5 (`rp1-analysis validate-inputs`, `rp1-analysis reference-check`, notebook execution and `rp1-analysis validate-run`). The exact accepted terminal qualification evidence remains an archival-release authority.

### 2.3 Source checkout versus distribution installation

The commands above use **editable source-checkout mode** so that qualification imports the three local projects from this repository. For a release-style **distribution mode**, build the analysis wheel from `RP1_Project/rp1_analysis` and install that wheel **non-editably** in a clean Python 3.13 environment:

```bash
cd RP1_Project/rp1_analysis
python -m build --wheel --outdir dist .
python -m pip install --no-deps dist/rp1_analysis_v1-1.2.3-*.whl
cd ../../
```

Do not mix the editable source-checkout qualification mode with a non-editable distribution installation when establishing package origin. After either mode, `rp1-analysis doctor` and `python -c "import rp1_analysis_v1; print(rp1_analysis_v1.__file__)"` should identify the intended installation source.

## 3. Geography preparation — `geo_data_prep`

Stage 1 constructs the governed spatial framework used by downstream reconstruction. Its responsibilities include:

- ACZ geometry preparation;
- district geometry preparation;
- geometry and overlap validation;
- deterministic district-to-ACZ assignment;
- unit-universe, crosswalk, QA and provenance outputs.

Validate the canonical example configuration without writing outputs:

```bash
geo-prep validate \
  --config geo_data_prep/configs/example_acz.yaml
```

Run the full Stage 1 example:

```bash
geo-prep run \
  --config geo_data_prep/configs/example_acz.yaml \
  --run-id example_acz
```

The run is written under `geo_data_prep/out/example_acz/`. Principal outputs include:

- `unit_universe.csv`;
- `boundaries/acz.*`;
- `boundaries/districts_within_acz.*`;
- `crosswalks/district_zone_crosswalk.csv`;
- `contract/stage1_contract_manifest.json`;
- input/output manifests and QA reports;
- optional split boundaries and plots configured by `example_acz.yaml`.

Stage 1 is an upstream reconstruction facility. Normal RP1 analysis uses the governed geometries already shipped in `RP1_Project/rp1_analysis/data/geo/` and does not require this stage to be rerun.

## 4. Active-fire panel construction — `rp1_mv_firms_panels`

Stage 2 converts annual NASA FIRMS active-fire shapefiles into governed monthly MODIS/VIIRS panels and merger-ready active-fire exports.

### 4.1 Upstream FIRMS source hierarchy

Upstream reconstruction expects the following source hierarchy:

```text
RP1_Project/rp1_mv_firms_panels/data/raw/
├── boundaries/
├── modis/
└── viirs/
```

The bulky upstream FIRMS files are **not tracked in the public GitHub projection**. They belong to the optional reconstruction path and must be reacquired from the original provider under the applicable access/licensing conditions, or recovered from an authorised archival distribution when available.

The qualified archival release contained source availability spanning:

- MODIS: **2000-2025**;
- VIIRS: **2012-2025**.

The frozen RP1 reconstruction periods remain narrower:

- MODIS: **2001-2024**;
- VIIRS: **2012-2024**.

Use explicit RP1 year arguments for reconstruction. This pins reconstruction to the study design rather than to whichever additional yearly files happen to be present locally. Normal RP1 analysis does not require this upstream tree because the five canonical consolidated analysis-input files are tracked under `RP1_Project/rp1_analysis/data/raw/`.

### 4.2 Canonical RP1 Stage 2 run

From the repository root:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  pipeline \
  --years-modis 2001-2024 \
  --years-viirs 2012-2024
```

To inspect the resolved plan without processing the full archive:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  pipeline \
  --years-modis 2001-2024 \
  --years-viirs 2012-2024 \
  --dry-run
```

To run the pipeline without plot generation:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  pipeline \
  --years-modis 2001-2024 \
  --years-viirs 2012-2024 \
  --no-plots
```

### 4.3 Manual Stage 2 commands

The same pipeline can be run stage by stage. `--config` and the common operational options may be placed before or after the subcommand.

Prepare one annual source file:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  prepare-year \
  --sensor viirs \
  --year 2024
```

Aggregate a sensor into monthly panels:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  aggregate \
  --sensor viirs \
  --start-yyyymm 201201 \
  --end-yyyymm 202412
```

Combine the sensor panels across the governed reconstruction span:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  combine \
  --start-yyyymm 200101 \
  --end-yyyymm 202412
```

Generate summaries and plots from the combined panel:

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  visualise
```

Use `--no-plots` with `visualise` or `pipeline` when plots are not required.

### 4.4 Safe resume and forced reruns

`--skip-existing` is a governed resume mechanism, not a simple file-exists shortcut. A stage is skipped only when its sentinel/manifests and expected outputs satisfy the current checks.

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  --skip-existing \
  pipeline \
  --years-modis 2001-2024 \
  --years-viirs 2012-2024
```

`--force` reruns a stage even when resume gating would otherwise permit reuse. Use it only when an intentional rebuild is required.

```bash
mv-firms-panels \
  --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml \
  --run-id ghana_full \
  --force \
  prepare-year \
  --sensor viirs \
  --year 2024
```

Stage 2 outputs are written under `RP1_Project/rp1_mv_firms_panels/out/runs/<run_id>/`. The merger-ready active-fire family is `rp1_af_exports/`.

### 4.8 Active-fire/burned-area consolidation

`rp1_mv_firms_panels` supplies the governed **active-fire** authorities. MCD64A1 BA-2001 and BA-2012 come from the separate governed burned-area workflow. The two families are joined only at the consolidation step:

```text
active-fire panels ---------\
                            \
                             -> RP1_Project/merge_af_ba_panels.py
                            /
BA-2001 + BA-2012 ---------/

            -> governed consolidated RP1 panels
```

The current merger exposes these arguments:

```bash
python RP1_Project/merge_af_ba_panels.py --help
```

Its repository-relative defaults resolve to:

- unit universe: `geo_data_prep/out/example_acz/unit_universe.csv`;
- active-fire root: `RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/rp1_af_exports`;
- BA-2001 root: `RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001`;
- BA-2012 root: `RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012`;
- consolidated output directory: `RP1_Project/rp1_analysis/data/raw`.

An explicit reconstruction therefore has the current concrete form:

```bash
python RP1_Project/merge_af_ba_panels.py \
  --repo-root . \
  --unit-universe geo_data_prep/out/example_acz/unit_universe.csv \
  --af-root RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/rp1_af_exports \
  --ba2001-root RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001 \
  --ba2012-root RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012 \
  --output-dir RP1_Project/rp1_analysis/data/raw \
  --run-id rp1_merge
```

That command targets the canonical governed input directory, which is already populated in this GitHub projection with the five canonical consolidated files from the qualified v1.2.3 release. Do not overwrite those analysis inputs casually. Rebuild them only as an intentional upstream reconstruction and requalify the resulting authorities before using them as scientific inputs.

## 5. Analysis and notebook workflow

The scientific analysis is governed by the configuration and source authorities in `RP1_Project/rp1_analysis/`. RQ1-RQ3 are internal Python analyses; the secondary SaTScan calculation is an explicit external-engine boundary.

### 5.1 Preflight

From the repository root:

```bash
rp1-analysis validate-inputs
rp1-analysis reference-check
```

`validate-inputs` runs the complete governed scientific/data contract and reports byte identity separately. A successful canonical release reports `RP1_ANALYSIS_V1_INPUT_VALIDATION=PASS` and `CANONICAL_INPUT_IDENTITY=MATCH`. A scientifically valid reconstruction may report `PASS` and `DIFFERENT`; byte inequality with the historical release is not, by itself, a scientific-validation failure. `reference-check` qualifies the active numerical reference-method families.

`RP1_Project/rp1_analysis/data/input_sha256.json` remains the immutable exact-byte inventory for the files supplied with this release. Every run independently records the SHA-256 and size of the files actually analysed, so provenance answers both which bytes were used and whether those bytes matched the canonical release. Do not rewrite `input_sha256.json` merely to admit a reconstruction.

You can also inspect the operational environment at any time:

```bash
rp1-analysis doctor
```

### 5.2 Option A — primary analysis without SaTScan results

This is a valid complete workflow for RQ1-RQ3. The logical sequence is:

```text
RQ1
 -> RQ2
 -> RQ3
 -> deterministic SaTScan input preparation
 -> no genuine external result families available
 -> EXTERNAL_RESULTS_REQUIRED
 -> normal publication/closeout for all available authorities
```

`EXTERNAL_RESULTS_REQUIRED` is **not** a failure and does **not** mean that SaTScan found zero clusters. It means the genuine external SaTScan result families have not been validated and bound to the run.

#### Automated execution

Run the canonical notebook through the package-owned wrapper:

```bash
rp1-analysis run --run-id my_run
```

Then validate the complete run family:

```bash
rp1-analysis validate-run \
  --run-id my_run \
  --write-report
```

A canonical base run ID produces the governed members under `RP1_Project/rp1_analysis/out/runs/`:

- `my_run_pub` — publication tables, figures and machine-readable sources;
- `my_run_sec` — SaTScan interface and secondary state;
- `my_run_close` — realised configuration, execution/closeout evidence and validation material.

#### Direct Jupyter execution

The notebook can also be run interactively from `RP1_Project/rp1_analysis/`:

```bash
cd RP1_Project/rp1_analysis
export RP1_NOTEBOOK_RUN_ID=my_run
jupyter lab RP1_Analysis_v1.ipynb
```

If you use **Run All** when no genuine SaTScan outputs are already present, the notebook does not pause at Section 04. It prepares the deterministic SaTScan interface, records `EXTERNAL_RESULTS_REQUIRED`, continues through publication and closeout, and finishes the valid primary-analysis run.

### 5.3 Option B — complete staged SaTScan workflow

Use this path when you want genuine secondary cluster results in the same interactive notebook run.

The notebook does **not** contain an automatic pause. The operator must control execution deliberately:

1. Start the notebook with a stable run ID and execute in order through **Section 04-01 — SaTScan interface and external-result boundary**.
2. Stop further notebook execution before Section 04-02.
3. Run the two generated SaTScan parameter files with the separately qualified **SaTScan 10.3.3** application.
4. Return to the same notebook run.
5. Continue from **Section 04-02 — Validate and integrate optional genuine SaTScan results**.
6. Complete Sections 90 and 99.
7. Validate the finished run with `rp1-analysis validate-run --run-id my_run --write-report`.

The governed secondary scenario identities are:

- `MCD64A1_POISSON_PRIMARY` — retrospective space-time discrete Poisson scan with fixed BA-2001 burnable-area exposure;
- `VIIRS_STP_PRIMARY` — retrospective space-time permutation scan with no exposure file.

Python owns deterministic case, population where applicable, coordinate and parameter generation, plus provenance and parser validation. SaTScan performs the external cluster computation. Python does not launch the SaTScan engine and does not fabricate missing cluster results.

### 5.4 SaTScan command surface

Inspect the available interface:

```bash
rp1-analysis satscan --help
```

The current subcommands are:

```bash
rp1-analysis satscan prepare --run-id my_secondary_run
rp1-analysis satscan status --run-id my_secondary_run
rp1-analysis satscan integrate --run-id my_secondary_run
```

`prepare` writes the governed external-engine inputs. `status` inspects the external-result state without modifying the run. `integrate` validates and binds complete genuine result families. There is intentionally no Python command that runs SaTScan itself.

### 5.5 Already validated secondary results

If the run already contains genuine governed secondary authorities recognised as `RESULTS_VALIDATED`, reuse them. The execution workflow recognises and reuses a valid secondary authority rather than rerunning SaTScan unnecessarily. Partial, stale, wrong-model, wrong-period, wrong-input or path-invalid result families fail closed.

`RESULTS_VALIDATED` is not a separate scientific design; it is the state reached when the configured secondary design has genuine validated external output.

### 5.6 Execution mode versus secondary scientific state

Keep these concepts separate:

- **execution mode** — how the notebook was executed:
  - interactive Jupyter;
  - controlled automated notebook execution;
- **secondary scientific state** — whether genuine SaTScan results are available and valid:
  - `EXTERNAL_RESULTS_REQUIRED`;
  - `RESULTS_VALIDATED`.

An interactive or automated run can legitimately finish with `EXTERNAL_RESULTS_REQUIRED` when RQ1-RQ3 are complete but external cluster results have not been supplied.

## 6. Presentation-figure exports

Presentation figures are exported from an existing qualified **closeout** run. The exporter reads the source run and writes a separate output tree; it does not mutate the source run and does not execute SaTScan.

List the configured export catalogue:

```bash
python RP1_Project/rp1_analysis/scripts/export_presentation_figures.py \
  --list
```

The configured estate contains **24 exports** in five groups:

- `study`
- `rq1`
- `rq2`
- `rq3`
- `rq4`

Supported presentation formats are **PNG** and **PDF**. SVG is not part of the current presentation-export contract.

Export one figure:

```bash
python RP1_Project/rp1_analysis/scripts/export_presentation_figures.py \
  --run-dir RP1_Project/rp1_analysis/out/runs/my_run_close \
  --output-dir presentation_figures \
  --figure rq2_coastal_trend
```

Export one group:

```bash
python RP1_Project/rp1_analysis/scripts/export_presentation_figures.py \
  --run-dir RP1_Project/rp1_analysis/out/runs/my_run_close \
  --output-dir presentation_figures \
  --group rq3
```

Export the complete available estate:

```bash
python RP1_Project/rp1_analysis/scripts/export_presentation_figures.py \
  --run-dir RP1_Project/rp1_analysis/out/runs/my_run_close \
  --output-dir presentation_figures \
  --all
```

Restrict the export format when required:

```bash
python RP1_Project/rp1_analysis/scripts/export_presentation_figures.py \
  --run-dir RP1_Project/rp1_analysis/out/runs/my_run_close \
  --output-dir presentation_figures_png \
  --all \
  --format png
```

`--format` may be repeated to request more than one configured format.

RQ4 presentation exports depend on genuine validated SaTScan authorities. If the source run is still `EXTERNAL_RESULTS_REQUIRED`, the exporter fails closed for RQ4 rather than fabricating zero clusters or executing SaTScan.

See `RP1_Project/rp1_analysis/docs/Presentation_Figure_Exporter.md` for the export contract and provenance fields.

## 7. Workflow states and troubleshooting

### `EXTERNAL_RESULTS_REQUIRED`

This is the normal external-results boundary when the deterministic SaTScan interface exists but genuine returned result families have not been validated. RQ1-RQ3 can still be complete. Do not interpret the state as zero significant clusters.

### `RESULTS_VALIDATED`

This means complete genuine governed SaTScan result families have passed the package's current identity, provenance, parser and model checks and have been integrated into the secondary authority.

### Common operational problems

**Wrong working directory.** The commands in this guide assume the repository root unless stated otherwise. Relative configuration and script paths may fail when run from another directory. Return to the repository root and retry.

**Package-origin problems.** Run:

```bash
rp1-analysis doctor
python -c "import rp1_analysis_v1, mv_firms_panels, geo_data_prep; print(rp1_analysis_v1.__file__); print(mv_firms_panels.__file__); print(geo_data_prep.__file__)"
```

All three imports should resolve from the checkout you intend to operate. If they do not, reinstall the three editable projects in the order shown in Section 2.

**Missing Stage 2 raw source.** Upstream reconstruction expects `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/`, `modis/` and `viirs/`. Those bulky upstream files are intentionally absent from the public GitHub projection. Normal RP1 analysis does not depend on those folders because the governed consolidated inputs are tracked under `RP1_Project/rp1_analysis/data/raw/`.

**Stale run IDs.** Run families are identity-bound. Reusing a run ID with inconsistent files can trigger collision or stale-authority checks. Use a new run ID unless you are deliberately resuming a governed compatible run.

**Stage 2 resume.** Prefer `--skip-existing` for a controlled resume. It checks sentinels/manifests and output contracts before reuse. Use `--force` only for an intentional rerun. Unknown or incomplete provenance should not be silently reused.

**External-result boundary versus code failure.** `EXTERNAL_RESULTS_REQUIRED` is a valid scientific state. A Python exception, failed validation gate, malformed/stale SaTScan family, missing dependency or invalid path is an operational failure and should be diagnosed separately.

**Dependency/environment failure.** Run `rp1-analysis doctor`. Confirm Python `>=3.13,<3.14`, package origins, runtime dependencies and notebook support before changing project files.

**Validate before presentation export.** Before exporting from a run family, execute:

```bash
rp1-analysis validate-run \
  --run-id my_run \
  --write-report
```

The presentation exporter also performs its own preflight and requires the configured closeout member.

## 8. Licence and further documentation

The repository software is licensed under the **BSD 3-Clause License**. See `LICENSE` for the exact terms.

The five canonical consolidated analysis-input files under `RP1_Project/rp1_analysis/data/raw/` are tracked in this GitHub projection to support standalone normal analysis. Third-party source data and the omitted upstream raw-source families retain their own provider provenance and access/licensing conditions. See `RP1_Project/docs/external_data_contract.md` for the repository's data-source contract.

For deeper technical and scientific detail, use the existing documentation rather than treating this operator guide as the full methods specification:

- `RP1_Project/docs/rp1_setup.md` — installation and repository-level setup;
- `RP1_Project/docs/geo_data_prep_structure.md` — Stage 1 structure;
- `RP1_Project/docs/mv_firms_panels_structure.md` — Stage 2 structure;
- `RP1_Project/docs/data_dictionary_fire_panels.md` — consolidated panel fields;
- `RP1_Project/rp1_analysis/README.md` — analysis-subproject guide;
- `RP1_Project/rp1_analysis/docs/Analysis_Methods_Contract.md` — scientific analysis contract;
- `RP1_Project/rp1_analysis/docs/Data_Contract.md` and `RP1_Project/rp1_analysis/docs/Data_Schema_Contract.md` — governed data semantics and schema;
- `RP1_Project/rp1_analysis/docs/Secondary_Analysis_Contract.md` — SaTScan secondary-analysis boundary;
- `RP1_Project/rp1_analysis/docs/Presentation_Figure_Exporter.md` — presentation-export contract;
- `RP1_Project/rp1_analysis/docs/Reproducibility_Contract.md` — reproducibility and qualification rules.
