# Reproducibility contract

Reproducibility rests on five scientific configuration hashes, the operational execution-contract hash, exact **current-run** input SHA-256 identities, package/environment identity, method qualification, the repository-owned current human-readable methods DOCX/PDF under `docs/` and their exact identity recorded in `data/authorities/methods_document_authority.json`, run-scoped output manifests and deterministic source generation where applicable. `data/input_sha256.json` has a narrower role: it is the immutable exact-byte inventory of the canonical release inputs. Runtime scientific validity is established independently by the complete governed data/scientific validators. Historical scientific run metadata remain immutable snapshots and are not rewritten when the current documentation authority is rematerialised without a scientific-method change.

Source qualification requires imports to resolve inside the current checkout. Tests must be self-contained and use only repository-shipped fixtures and governed inputs; they must not require external development artefacts or stale generated outputs. Synthetic/reference SaTScan fixtures are test-only assets and do not represent Ghana scientific results. Public workflows use relative/configuration-driven paths.

The canonical notebook records realised configuration, input identities, method-reference state, the optional external-result validation state, output inventory and execution gate. SaTScan executable identity and genuine result provenance are required before cluster-dependent scientific outputs are accepted. Section 04-01 is deterministic and does not execute SaTScan; Section 04-02 accepts either no result families (`EXTERNAL_RESULTS_REQUIRED`) or two complete valid families (`RESULTS_VALIDATED`) and fails closed on partial/invalid material. Accepted live publication sources are run-local only.

Section 99 finalises direct interactive Jupyter execution through a package-owned closeout API. Interactive completion writes `99_closeout/M_NOTEBOOK_EXECUTION.json` with `execution_mode: interactive_jupyter`, run/configuration/schema identities, final gate state, secondary state and explicit provenance limitations. It deliberately does not claim that the kernel can prove the Jupyter front-end has saved the current notebook document, so an executed-notebook snapshot is not required for interactive completion. Controlled `nbclient` execution is identified separately and defers notebook-owned execution finalisation to `scripts/execute_notebook.py`, which retains the stronger executed-notebook snapshot and code-cell execution evidence.

A release build is accepted only after manifest verification in a fresh extraction followed by import/configuration/notebook/documentation/integration smoke checks. Cache, bytecode, temporary test and build artefacts are excluded from the governed product.

## Runtime input identity and execution record v3

Ordinary analysis requires `input_validation_status=PASS`; it does not require canonical historical byte equality. `canonical_input_identity` is reported separately as `MATCH` or `DIFFERENT`. The canonical shipped inputs must remain `PASS + MATCH`; a reconstructed input may be `PASS + DIFFERENT` only when all governed scientific/data checks pass. Reconstruction does not require reproducing a historical `run_id` or timestamp, and users must not rewrite `data/input_sha256.json` merely to analyse a valid reconstruction.

Each run inventories the files it actually consumed. `M_REPRODUCIBILITY_MANIFEST.json` therefore preserves current file paths, SHA-256 values and sizes, while `canonical_input_identity` answers the separate historical-release comparison question. Active v1.2.3 execution records use schema `rp1-notebook-execution-v3`; both controlled and interactive modes require `input_validation_status=PASS` and allow either canonical-identity value. The canonical gate, reproducibility manifest and execution record must agree.

## Canonical environment

The intended environment is declared at the repository root as `environment.yml` and is named `rp_ghana_fire`. It requires Python `>=3.13,<3.14` and binds the three local packages to the same checkout.

```bash
conda env create -f environment.yml
conda activate rp_ghana_fire
```

Black, Ruff and mypy may be used for development but are not release acceptance gates. Pytest, governed-input validation, reference-method qualification, operational command checks and notebook/run validation remain the regression authorities.

## Source qualification

For normal analysis source use from this subproject, install the current checkout in **editable** mode:

```bash
python -m pip install -e .
python -c "import rp1_analysis_v1; print(rp1_analysis_v1.__file__)"
```

Complete source qualification requires the three local source projects from one checkout because the reference and integration test estate crosses those boundaries. From the repository root:

```bash
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_analysis
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python tools/qualify_source_checkout.py
```

The qualifier checks that `rp1_analysis_v1`, `mv_firms_panels` and `geo_data_prep` import from the current checkout before running the three local test estates. It regenerates the governed `example_acz` Stage-1 fixture and enables native rendering smoke tests without resolving dependencies from the network.

## Distribution qualification

Build the wheel and install it **non-editably** in a clean Python 3.13 environment:

```bash
python -m build --wheel --outdir dist .
python -m pip install --no-deps dist/rp1_analysis_v1-1.2.3-*.whl
```

## Clean qualification projection

Editable installation may create normal metadata in an operational checkout, so release-equivalent source qualification uses a separate clean projection rather than deleting or ignoring files in place. `config/qualification_contract.yml` defines the governed source set and generated-artifact exclusions. `rp1_analysis_v1.source_projection` inventories governed files by relative path, byte size and SHA-256, recreates an external projection, verifies an exact post-copy inventory and provides explicit projected-source import routing. Projection evidence is written outside the clean tree.

The five scientific contracts and their aggregate identity remain independent of this operational qualification policy. A clean projection cannot omit configured governed files, accept path traversal or absolute developer paths, follow governed symlinks, or silently import an editable operational source in place of the projected source.

## Canonical environment qualification lifecycle

`tools/qualify_environment.py --evidence-dir <external-directory>` is the canonical end-to-end qualifier. It first verifies the active Python/Conda identity and that all three editable packages resolve from the intended operational checkout. It then creates a fresh clean projection under the external evidence root, verifies its inventory and import origins, and runs collection, the complete pytest estate, input validation and reference-method qualification from that projected tree. Release-qualification wheels are built from projected project roots, installed into a freshly recreated external target, and re-imported from that target with version/origin checks.

Qualifier runtime, wheel, projection and isolated-install roots are deleted and recreated on every run with the same evidence directory, so stale executable artefacts cannot satisfy a later run. Generated caches or build/output residue created inside the disposable projection are removed only from that projection and an exact governed inventory is rechecked before build authority is accepted. `pytest` remains the operational hard gate; Black, Ruff and mypy are development tools rather than qualification gates.
