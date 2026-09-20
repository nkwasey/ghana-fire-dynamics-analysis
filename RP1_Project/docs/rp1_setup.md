# RP1 Analysis v1.2.3 setup

This guide covers normal analysis use, complete source qualification and
optional upstream data reconstruction from the canonical repository:

```text
ghana-fire-rp1-analysis-main/
```

The normal analysis is standalone: governed scientific inputs are shipped under
`RP1_Project/rp1_analysis/data/`. Upstream source acquisition is not a
prerequisite for validation, RQ1-RQ3 execution or the no-results SaTScan state.

## 1. Create the canonical environment

From the repository root:

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
```

For an existing environment:

```bash
conda env update -f environment.yml --prune
conda activate rp_ghana_fire
```

`environment.yml` defines the three repository source projects. Do not inject a
different checkout through `PYTHONPATH` or `sys.path`.

## 2. Verify source imports

For complete repository source qualification, install the three local projects
from this checkout and verify their origins:

```bash
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_analysis
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python tools/qualify_source_checkout.py --origins-only
```

The full repository qualifier is:

```bash
python tools/qualify_source_checkout.py
```

It regenerates its deterministic Stage 1 fixture, checks import origins, runs
the analysis, geography and active-fire test estates, and cleans generated
qualification outputs.

## 3. Validate and run the scientific analysis

```bash
python RP1_Project/rp1_analysis/scripts/validate_inputs.py
python RP1_Project/rp1_analysis/scripts/qualify_reference_methods.py
python RP1_Project/rp1_analysis/scripts/execute_notebook.py --run-id example_run
python RP1_Project/rp1_analysis/scripts/validate_run.py --run-id example_run --write-report
```

Input validation in v1.2.3 separates two questions. `input_validation_status=PASS` means the current inputs satisfy the complete governed scientific/data contract. `canonical_input_identity=MATCH|DIFFERENT` states whether those current bytes equal the historical files in `rp1_analysis/data/input_sha256.json`. Valid reconstruction does not require reproducing the old `run_id` or timestamp and must not rewrite that canonical inventory merely to obtain `MATCH`. Every completed run records the hashes of the bytes actually analysed.

`RP1_Analysis_v1.ipynb` is a thin package-driven notebook. It writes one
isolated run below `RP1_Project/rp1_analysis/out/runs/<run_id>/` and does not
regenerate the governed source panels.

Section 04-01 generates deterministic external SaTScan interfaces. SaTScan is
executed outside the notebook. Section 04-02 accepts no external results
(`EXTERNAL_RESULTS_REQUIRED`) or two complete validated result families
(`RESULTS_VALIDATED`) and fails closed on partial or invalid material.
Section 90 generates all publication products authorised by the current run
state.

## 4. Build and qualify the Python distribution

Distribution qualification uses a non-editable wheel in a clean Python 3.13
environment:

```bash
python -m build --wheel --outdir dist RP1_Project/rp1_analysis
python -m pip install --no-deps dist/rp1_analysis_v1-1.2.3-*.whl
```

The installed `rp1_analysis_v1` import must resolve from that environment, not
from the repository source tree.

## 5. Optional upstream reconstruction

Upstream reconstruction is needed only when rebuilding the governed analysis
inputs from source observations. The sequence is:

1. run `geo_data_prep` to regenerate Stage 1 geography products;
2. acquire raw yearly MODIS/VIIRS FIRMS files and run
   `rp1_mv_firms_panels`;
3. use the shipped burned-area export bundles, or regenerate them through the
   Earth Engine scripts under `RP1_Project/rp1_gee_ba_scripts/`;
4. run `RP1_Project/merge_af_ba_panels.py` to construct consolidated panels;
5. validate every regenerated input against the scientific/data contract and record its current provenance identity before scientific use. A valid reconstruction may report canonical identity `DIFFERENT`; this is expected when provenance-only fields or serialisation bytes differ.

Acquisition paths and source authorities are described in `docs/data_access.md`
and `RP1_Project/docs/external_data_contract.md`.

## 6. Jupyter kernel (optional)

```bash
python -m ipykernel install --user --name rp_ghana_fire --display-name "RP1 Analysis (rp_ghana_fire)"
```

## 7. Targeted test commands

```bash
pytest -q RP1_Project/rp1_analysis/tests
pytest -q geo_data_prep/tests
pytest -q RP1_Project/rp1_mv_firms_panels/tests
```

The mirrored copy of this guide under
`RP1_Project/rp1_mv_firms_panels/docs/rp1_setup.md` is maintained
text-identically.
