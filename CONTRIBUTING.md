# Contributing

Changes must preserve the governed RP1 Analysis v1 scientific contracts and fail-closed validation behaviour.

## Tests

From the repository root:

```bash
python -m pytest
```

The root test configuration includes the retained geography package, active-fire panel package and canonical v1 analysis package.

## Release qualification

Use the repository-owned qualifier with an evidence directory outside the checkout:

```bash
python tools/qualify_environment.py --evidence-dir /path/to/external/rp1_qualification_evidence
```

The qualifier verifies the operational editable checkout, reconstructs the governed clean source projection defined by `RP1_Project/rp1_analysis/config/qualification_contract.yml`, runs the hard-gate pytest/input/reference checks from that projection, builds clean wheels and verifies a fresh isolated installation. Do not weaken repository-hygiene tests to accommodate generated editable/build metadata in the operational checkout.

## Optional development quality checks

Black, Ruff and mypy are optional contributor aids, not release acceptance gates. When the configured development tools are installed:

```bash
ruff check geo_data_prep/src geo_data_prep/tests RP1_Project/rp1_mv_firms_panels/src RP1_Project/rp1_mv_firms_panels/tests RP1_Project/rp1_analysis/src RP1_Project/rp1_analysis/tests RP1_Project/rp1_analysis/scripts
black --check geo_data_prep/src geo_data_prep/tests RP1_Project/rp1_mv_firms_panels/src RP1_Project/rp1_mv_firms_panels/tests RP1_Project/rp1_analysis/src RP1_Project/rp1_analysis/tests RP1_Project/rp1_analysis/scripts
mypy RP1_Project/rp1_analysis/src/rp1_analysis_v1
```

Do not change scientific configuration or data values merely to obtain a passing test or preferred result.
