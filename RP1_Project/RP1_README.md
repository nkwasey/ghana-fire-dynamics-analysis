# RP1 Project

Package identity: `rp1-analysis-v1==1.2.3`.

The RP1 Project combines governed fire-panel preparation resources with the standalone `rp1-analysis-v1` v1.2.3 analysis package. The scientific entry point is `rp1_analysis/RP1_Analysis_v1.ipynb`; reusable logic is package-owned.

## Analysis questions

- RQ1: spatial support, heterogeneity, seasonality and spatial organisation of MCD64A1 burned area.
- RQ2: serial-dependence-aware monotonic change in ACZ burned-area rates.
- RQ3: cross-product observability among VIIRS-positive district-months.
- Secondary: MCD64A1 Poisson and VIIRS space-time-permutation SaTScan concentration.

Use `rp1_analysis/README.md` for installation, validation, notebook execution, publication outputs and scientific limitations.

For v1.2.3, runtime scientific admissibility and canonical release-byte identity are separate. `rp1_analysis/data/input_sha256.json` is the immutable exact-byte release inventory; `validate-inputs` admits current inputs only when the full governed data/scientific contract passes, while reporting `MATCH` or `DIFFERENT` against that inventory. Run provenance always records the hashes of the bytes actually analysed.

## Source and distribution qualification

Source qualification uses an **editable** install of the current checkout (`python -m pip install -e .` from the analysis subproject). Distribution qualification uses a **non-editable** install of the built `rp1_analysis_v1-1.2.3-*.whl` wheel. These modes test different contracts and should not be conflated.
