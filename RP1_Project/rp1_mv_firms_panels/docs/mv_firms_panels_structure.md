# `rp1_mv_firms_panels` structure

`RP1_Project/rp1_mv_firms_panels/` is the Stage 2 active-fire panel subproject.
The project directory is named `rp1_mv_firms_panels`; the Python import package
is `mv_firms_panels`.

## Canonical location

```text
ghana-fire-rp1-analysis-main/RP1_Project/rp1_mv_firms_panels/
```

## Shipped structure

```text
rp1_mv_firms_panels/
├── configs/
│   ├── schemas/
│   ├── example_project.yaml
│   ├── ghana_full.yaml
│   └── my_project.yaml
├── data/metadata/
│   └── unit_universe.csv
├── docs/
├── scripts/
├── src/mv_firms_panels/
├── tests/
├── MV-FIRMS_README.md
├── LICENSE
└── pyproject.toml
```

Raw yearly FIRMS inputs, boundary staging files and `out/runs/<run_id>/` are
regeneration-time material and are not shipped. The configuration defines the
expected local `data/raw/` locations when an upstream Stage 2 rebuild is
requested.

## Principal outputs when executed

A Stage 2 run can generate:

- the contracted combined monthly panel;
- additive extended and QC panels;
- sensor-specific, merger-ready `rp1_af_exports` for MODIS and VIIRS;
- manifests and run-scoped provenance below `out/runs/<run_id>/`.

## Common commands

```bash
python -m pip install --no-build-isolation --no-deps -e ./RP1_Project/rp1_mv_firms_panels
python -m mv_firms_panels.cli.main --config RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml pipeline --dry-run
pytest -q RP1_Project/rp1_mv_firms_panels/tests
```

Stage 2 is an upstream reconstruction facility. Normal RP1 scientific analysis
uses the governed consolidated panels shipped in
`RP1_Project/rp1_analysis/data/raw/` and does not require live FIRMS source
folders.
