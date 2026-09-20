# geo_data_prep

Stage 1 canonical geography preparation for the Ghana RP1 workflow.

This repository reads polygon shapefiles, optionally clips them to an AOI,
derives deterministic identifiers, assigns each district to one zone by maximum
overlap share, and writes the promoted Stage 1 contract consumed downstream.

## Clean-clone assumption

Treat Stage 1 source data as absent from a clean clone unless it is explicitly
documented as a maintained in-repo exception.

For Stage 1:

- the HDX Ghana administrative boundary inputs must be downloaded and staged
  locally by the user
- the ACZ source shapefile remains the documented in-repo exception
- the authoritative acquisition and regeneration policy lives in
  `RP1_Project/docs/external_data_contract.md`
- the canonical user-facing access guide is `docs/data_access.md`

## Required Stage 1 inputs

The promoted Stage 1 config expects these local files:

- `geo_data_prep/data/raw/zones/Agro_climatic_zone.shp`
- `geo_data_prep/data/raw/districts/gha_admin2.shp`
- `geo_data_prep/data/raw/aoi/gha_admin0.shp`

Dataset mapping:

- `Agro_climatic_zone.*`
  ACZ zone source layer used as the Stage 1 zone polygon input
- `gha_admin2.*`
  Ghana admin-2 districts used as the Stage 1 district boundary input
- `gha_admin0.*`
  Ghana admin-0 boundary used as the Stage 1 AOI / national boundary input

## How to obtain and stage the inputs

### Ghana administrative boundaries

Source:
- HDX COD-AB GHA

Access:
- `https://data.humdata.org/dataset/cod-ab-gha`

Stage locally as:

- download `gha_admin_boundaries.shp.zip`
- extract `gha_admin0.{shp,shx,dbf,prj,cpg}` into
  `geo_data_prep/data/raw/aoi/`
- extract `gha_admin2.{shp,shx,dbf,prj,cpg}` into
  `geo_data_prep/data/raw/districts/`

### ACZ source layer

The ACZ source layer is kept in this repository as the maintained source-data
exception:

- `geo_data_prep/data/raw/zones/Agro_climatic_zone.{shp,shx,dbf,prj,cpg,sbn,sbx,xml}`

Provenance:
- Yamba EI, Aryee JNA, Quansah E, Davies P, Wemegah CS, Osei MA, et al. (2023)
  Revisiting the agro-climatic zones of Ghana: A re-classification in
  conformity with climate change and variability. PLOS Clim 2(1): e0000023.
  `https://doi.org/10.1371/journal.pclm.0000023`

## Quick start

Validate the promoted ACZ config:

```bash
geo-prep validate --config configs/example_acz.yaml
```

Run the full Stage 1 pipeline:

```bash
geo-prep run --config configs/example_acz.yaml --run-id example_acz
```

## Main outputs from `geo-prep run`

Core outputs:

- `out/<run_id>/unit_universe.csv`
- `out/<run_id>/boundaries/acz.{shp,shx,dbf,prj,cpg}`
- `out/<run_id>/boundaries/districts_within_acz.{shp,shx,dbf,prj,cpg}`
- `out/<run_id>/crosswalks/district_zone_crosswalk.csv`
- `out/<run_id>/qa/district_zone_overlap.csv`
- `out/<run_id>/contract/stage1_contract_manifest.json`
- `out/<run_id>/inputs_fingerprint.json`
- `out/<run_id>/outputs_manifest.json`

Optional outputs controlled by config toggles:

- `splits/`
- `plots/`

## Downstream interface

Stage 1 is the canonical upstream geography contract.

The main downstream interfaces are:

- `out/example_acz/unit_universe.csv` ->
  `RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv`
- `out/example_acz/boundaries/acz.{...}` ->
  `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/acz.{...}`
- `out/example_acz/boundaries/districts_within_acz.{...}` ->
  `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/districts_within_acz.{...}`
- `out/example_acz/boundaries/acz.{...}` ->
  `RP1_Project/rp1_analysis/data/geo/acz.{...}`
- `out/example_acz/boundaries/districts_within_acz.{...}` ->
  `RP1_Project/rp1_analysis/data/geo/districts_within_acz.{...}`

`RP1_Project/merge_af_ba_panels.py` also reads:

- `geo_data_prep/out/example_acz/unit_universe.csv`

directly.

## Configuration model

The Stage 1 config sections are:

- `schema_version`
- `inputs`
- `levels`
- `crs`
- `outputs`
- `derivations`
- `area_policy`
- `qa`
- `contract`

All config paths are repo-relative. They point to local staging destinations,
not to guaranteed bundled data assets.

## Contract notes

- `unit_universe.csv` remains the canonical Stage 1 identity output.
- Canonical relational keys remain `unit_id` and `parent_id`.
- Shapefile schemas stay lean; richer diagnostics live in manifests and QA
  sidecars.
- Outputs can be written even when QA summaries later record a failed review
  state; inspect `qa/qa_summary.json` and related sidecars after each run.

## Validation and sanity checks

```bash
pytest -q
python -m geo_data_prep --help
geo-prep --help
geo-prep validate --config configs/example_acz.yaml
```

## Further documentation

- `docs/stage1_contract.md`
- `docs/data_dictionary.md`
- `docs/user_guide.md`
- `docs/decision_log.md`
- `docs/data_access.md`
