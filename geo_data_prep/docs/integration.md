# RP1 integration

Install and run this project independently before staging its outputs into RP1. Choose one successfully completed output run and use its boundaries, unit universe and crosswalk together. Do not mix files from different runs.

## Required handoffs

| Generated item | RP1 destination or consumer |
|---|---|
| `unit_universe.csv` | AF preparation metadata (`rp1_mv_firms_panels/data/metadata/unit_universe.csv`); the merger also reads the configured Stage 1 run |
| `analysis_boundaries/acz.*` | AF preparation (`rp1_mv_firms_panels/data/raw/boundaries/`) |
| `analysis_boundaries/districts_within_acz.*` | The same AF boundary directory |
| `analysis_boundaries/acz.*` | Analysis (`rp1_analysis/data/geo/acz.*`) when `crs.analysis` matches its contract |
| `analysis_boundaries/districts_within_acz.*` | Analysis (`rp1_analysis/data/geo/districts_within_acz.*`) when `crs.analysis` matches its contract |
| `crosswalks/district_to_acz_max_overlap.csv` | Analysis reference data (`rp1_analysis/data/reference/`) |
| Matching `.provenance.json` | The same analysis reference directory; update its configured reference if filenames differ |
| Split district and zone layers | Optional per-zone spatial exports |
| QA and manifests | Retain with the chosen run as its supporting evidence |

Use the [checked geography handoff](../../docs/GEO_HANDOFF.md) to stage complete shapefile bundles, including `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg`. The c3 upload uses the combined projected district and zone layers plus the configured national AOI. The workflow uses that same verified AOI derivative as its FIRMS land-mask input.

The supplied climatic profile retains `boundaries/` in the district source CRS (EPSG:4326) and writes `analysis_boundaries/` in EPSG:32630. The checked handoff supplies the EPSG:32630 bundles identically to FIRMS and analysis. Check the target configuration and run its geometry validator; file presence and CRS alone do not establish full analysis compatibility. Projected districts are serialized and read back before projected zones are dissolved from them. Do not relabel a `.prj` without transforming coordinates.

## Configuration and keys

The canonical universe has ten columns: `unit_type,level,unit_id,unit_code,unit_name,parent_level,parent_id,parent_code,parent_name,area_sqkm`. The unit key is `(level, unit_id)` and the parent key is `(parent_level, parent_id)`; identical IDs at different levels are permitted. Codes are metadata. District codes may be blank when no district-code field is configured. Zone rows have blank parent cells.

The Ghana AF configuration uses `dist_id` for district identity and `zone_id` for zone identity. Verify its actual ID, name and parent fields against the delivered data dictionary. Analysis crosswalk readers require reference-overlap values, not constructed coverage values of one.

The RP1 merger's default geography location is `geo_data_prep/out/example_acz/unit_universe.csv` relative to the RP1 repository. Generate that run explicitly before using that arrangement:

```bash
geo-prep run --config configs/example_acz.yaml --run-id example_acz
```

Alternatively, point the relevant consumer to your chosen completed run using its available configuration or CLI options (`--unit-universe` for the merger). The repository ships without output runs. This package does not modify the merger or activate a run automatically.

## Check before analysis

1. Confirm the geography run passed its structural checks; review every warning and its scientific relevance.
2. Verify the unit IDs, parent assignments and source hashes for the chosen geography.
3. Stage the complete boundary and metadata handoff into a working RP1 copy. Check the AF and analysis configurations against the staged paths.
4. Verify whether existing AF panels were spatially assigned using these exact intended boundaries. Regenerate affected panels if that relationship cannot be established.
5. Bind GEE BA exports to the corresponding uploaded boundary assets, country mask, pixel grid and QA policy. Matching district names alone does not establish compatible geometry.
6. Preserve missing values and observation-support rules in BA consolidation and merging. Geography success does not authorize recomputing withheld BA fractions.
7. Rebuild affected merged panels and analysis outputs with new provenance. An unchanged manifest must not be relabelled as evidence for different inputs.

This project supplies geography and metadata only. It does not run FIRMS preparation, GEE exports, AF/BA merging, SaTScan or statistical analysis.
