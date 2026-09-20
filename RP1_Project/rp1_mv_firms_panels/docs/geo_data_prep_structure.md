# `geo_data_prep` structure

`geo_data_prep/` is the repository-owned Stage 1 geography preparation
subproject. Its import package is also `geo_data_prep`.

## Canonical location

```text
ghana-fire-rp1-analysis-main/geo_data_prep/
```

## Shipped structure

```text
geo_data_prep/
├── configs/
│   ├── example.yaml
│   └── example_acz.yaml
├── data/raw/
│   ├── aoi/                  # gha_admin0 shapefile family
│   ├── districts/            # gha_admin2 shapefile family
│   └── zones/                # ACZ and AEZ source/reference families
├── docs/
│   ├── data_dictionary.md
│   ├── stage1_contract.md
│   └── user_guide.md
├── src/geo_data_prep/
├── tests/
├── GEO-DATA-PREP_README.md
├── LICENSE
└── pyproject.toml
```

`out/<run_id>/` is created by Stage 1 execution and is not part of the shipped
product. The repository source qualifier regenerates a deterministic
`out/example_acz/` fixture when required and removes it after qualification.

## Principal responsibilities

- validate Stage 1 configuration and input geometry;
- establish the Ghana AOI, district and agro-climatic-zone spatial authority;
- assign districts to parent zones using the governed overlap rule;
- write unit-universe, boundary, crosswalk, QA and manifest outputs;
- provide deterministic Stage 1 fixtures used by repository integration tests.

## Common commands

```bash
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
geo-prep validate --config geo_data_prep/configs/example_acz.yaml
geo-prep run --config geo_data_prep/configs/example_acz.yaml --run-id example_acz
pytest -q geo_data_prep/tests
```

Stage 1 is an upstream reconstruction facility. Normal RP1 scientific analysis
uses the governed geometries already shipped under
`RP1_Project/rp1_analysis/data/geo/` and does not require a Stage 1 run.
