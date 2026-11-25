# Geographic preparation

`geo_data_prep/` is the Stage 1 subproject. It assigns whole districts to reference zones by maximum projected-area overlap and dissolves the original districts by the selected zone. It does not clip districts. The pairing CSV and reference-overlap share describe the assignment; the constructed reporting zones preserve complete district geometries.

```text
geo_data_prep/
  configs/          climatic and ecological example configurations
  data/raw/         supplied source shapefile bundles
  data/inputs_manifest.json
  docs/             configuration, method, dictionary, integration and testing
  src/geo_data_prep/
  tests/
  README.md
  pyproject.toml
```

The distributed subproject contains no completed output run. The climatic profile creates `out/<run_id>/` with source-CRS boundaries, an EPSG:32630 analysis derivative, the unit universe, crosswalk, QA, manifest, plots and split layers. Review the source-coverage warnings and assignment diagnostics; successful geometry construction is not a finding of independent ground accuracy or satellite-panel compatibility.

From the repository root with `rp_ghana_fire` active:

```bash
python -m pip install --no-build-isolation --no-deps -e ./geo_data_prep
python -m pytest geo_data_prep/tests
geo-prep validate --config geo_data_prep/configs/example_acz.yaml
geo-prep run --config geo_data_prep/configs/example_acz.yaml --run-id example_acz
```

Use `tools/stage_geo_handoff.py` and [GEO_HANDOFF.md](../../docs/GEO_HANDOFF.md) for the checked downstream handoff. Preserve the separate FIRMS land mask and inspect existing target files before replacing them. Read `geo_data_prep/README.md` and `geo_data_prep/docs/` for the complete method and configuration.

For c3 Earth Engine exports, `tools/stage_gee_handoff.py` packages only the three
combined projected layers: Ghana AOI, ACZs, and districts within ACZs. The
versioned mapping identifies `C3.ghanaAsset`, `C3.zoneAsset`, and
`C3.districtAsset`. Geography construction and whole-district assignments remain
the Stage 1 authority; matching local identities alone does not certify the
remote asset geometry or native MODIS pixel-centre membership.
