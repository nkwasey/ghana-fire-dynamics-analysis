# geo_data_prep

This subproject assigns whole administrative districts to reference zones by maximum overlap and constructs district-based reporting-zone boundaries. It supplies the geography, identities, crosswalk and metadata needed by downstream processing.

A run creates its own directory under `out/`.

## Required inputs

The climatic configuration uses the following shapefile bundles:

| Input | Path relative to `geo_data_prep/` | Role |
|---|---|---|
| Districts | `data/raw/districts/gha_admin2.shp` | Whole administrative units |
| Reference zones | `data/raw/zones/Agro_climatic_zone.shp` | Maximum-overlap assignment |
| National reference | `data/raw/aoi/gha_admin0.shp` | Validation reference, not a clipping mask |

The repository supplies these three bundles and the agro-ecological
reference used by the optional ecological example. Each bundle has `.shp`,
`.shx`, `.dbf`, `.prj` and `.cpg` components. The
[input inventory](data/inputs_manifest.json) records exact file identities.
See the [source geography guide](../docs/SOURCE_GEOGRAPHY.md) for verification
and the separate FIRMS archive reference requirement.

HDX COD-AB GHA (https://data.humdata.org/dataset/cod-ab-gha) may be consulted for administrative-boundary data. The provider, vintage, ground accuracy and redistribution rights of the exact supplied components have not been independently established. Preserve the source provider's attribution and permissions. The code licence does not grant rights over the input datasets. See [data_sources.md](docs/data_sources.md).

Background on Ghana's five agro-climatic zones: Yamba, E. I., Aryee, J. N. A., Quansah, E., Davies, P., Wemegah, C. S., Osei, M. A., Ahiataku, M. A., & Amekudzi, L. K. (2023). Revisiting the agro-climatic zones of Ghana: A re-classification in conformity with climate change and variability. *PLOS Climate, 2*(1), e0000023. https://doi.org/10.1371/journal.pclm.0000023. This publication is contextual literature; it does not by itself verify the lineage or accuracy of the supplied digitised shapefile.

## Environment and installation

Use the shared `rp_ghana_fire` Conda environment for the RP1 project. From the RP1 repository root:

```bash
conda activate rp_ghana_fire
python --version
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python -c "import geo_data_prep; print(geo_data_prep.__file__)"
```

The package supports Python 3.12 and 3.13. The shared environment must already provide its declared dependencies, `pytest`, and the build tools required for an editable install. Install or reconcile missing dependencies using the parent project's environment policy; `--no-deps` does not install them. If your shell is already inside `geo_data_prep/`, use the command below; the path `./geo_data_prep` in the repository-root example would otherwise refer to a nonexistent nested directory.

```bash
python -m pip install --no-build-isolation --no-deps -e .
```

`requirements-tested.txt` records a tested dependency set; it is not a complete cross-platform lockfile and should not be applied to a shared environment without reviewing the impact on other RP1 packages.

## Quick start

From the `geo_data_prep` directory, with `rp_ghana_fire` active:

```bash
python -m pytest
geo-prep validate --config configs/example_acz.yaml
geo-prep run --config configs/example_acz.yaml --run-id example_acz
```

Validation reads the inputs and calculates assignments without creating an analytical output run. The run command writes `out/example_acz/`. Choose a new portable run ID for another run; completed runs are not overwritten. `WARN` can accompany successful structural processing: inspect `qa/qa_summary.json` and the coverage evidence before adopting results.

## Method

For each district, calculate the area intersecting each reference zone divided by the whole district area, in the configured working CRS. Select the largest positive overlap subject to the configured tie rule, write the pairing CSV, and use that serialized pairing to group whole districts. Dissolve the exported whole districts to create the final reporting zones.

Districts are not clipped, snapped, simplified, buffered or silently repaired. A reference overlap below one can occur when a district crosses a zone boundary; it is distinct from full containment of the district within its constructed reporting zone. Reporting zones approximate the reference zones at district scale and are not independent proof of climatic boundary accuracy.

## Main outputs

All paths below are relative to `out/<run_id>/`.

| Path | Contents |
|---|---|
| `unit_universe.csv` | Canonical district and zone identities, parent relationships and projected areas |
| `boundaries/` | Whole-district and reporting-zone bundles in the source district CRS |
| `analysis_boundaries/` | Configured projected district and reporting-zone bundles for analysis |
| `crosswalks/` | Serialized district-zone assignments, reference-overlap crosswalk and provenance |
| `qa/` | Reference overlaps and coverage, constructed hierarchy and QA summary |
| `contract/` | Machine-readable geography contract |
| `inputs_fingerprint.json`, `environment.json`, `outputs_manifest.json` | Input identities, runtime and output hashes |
| `splits/`, `district_lists/`, `plots/` | Optional per-zone layers, lists and numbered district maps |

The supplied climatic configuration requests an EPSG:32630 analysis handoff. Projected districts are serialized and the projected zones are dissolved from those districts; the source-CRS boundaries are retained separately. GeoJSON and maps use EPSG:4326. The analysis handoff is optional for configurations that do not specify `crs.analysis`.

## Downstream interface

Use files from one completed run together; do not mix boundaries, crosswalks, unit metadata or provenance from different runs.

| Item within `out/example_acz/` | RP1 destination or consumer |
|---|---|
| `unit_universe.csv` | `RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv`; also read by the merger's configured geography input |
| `analysis_boundaries/acz.*` and `analysis_boundaries/districts_within_acz.*` | Identical EPSG:32630 bundles in `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/` and `RP1_Project/rp1_analysis/data/geo/` |
| `crosswalks/district_to_acz_max_overlap.csv` and its matching `.provenance.json` | `RP1_Project/rp1_analysis/data/reference/` |
| QA and manifests | Retain with the selected run as supporting evidence |

Copy complete shapefile bundles, including `.cpg`, through the checked geography handoff. The workflow also packages the configured national source as a projected GEE upload bundle and uses that same national AOI derivative for FIRMS after verifying the source selection. The merger's panel outputs and their provenance must be staged into the analysis project's configured input location. A geometry handoff does not establish that independently supplied FIRMS or burned-area exports used compatible boundaries, grid or QA rules. See [integration.md](docs/integration.md).

## Configuration and contract

The configuration sections are `project_root`, `inputs`, `crs`, `assignment`, `qa`, `outputs` and `expected`. Paths are resolved against `project_root`, which is resolved relative to the configuration file. Unknown or duplicate settings and invalid value types are rejected. Multilayer inputs require an explicit layer selection when ambiguous.

The canonical unit key is `(level, unit_id)`; district parents use `(parent_level, parent_id)`. Zone and district IDs, names and codes must match the consuming configuration. Reference overlap and constructed coverage are separate concepts. Structural success and `handoff_eligible` do not approve a source for every scientific use. Invalid inputs or failed construction checks prevent publication of a completed run.

## Validation and documentation

```bash
python -m geo_data_prep --help
geo-prep --help
python -m pytest
geo-prep validate --config configs/example_acz.yaml
```

See [configuration.md](docs/configuration.md), [method.md](docs/method.md), [data_dictionary.md](docs/data_dictionary.md), [plots.md](docs/plots.md), [testing.md](docs/testing.md) and [integration.md](docs/integration.md). Input positional accuracy, source permissions, raster-grid reconciliation and downstream analysis require separate review.
