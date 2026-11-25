# Source geography

The repository includes the exact national, district, agro-climatic and
agro-ecological study shapefiles. The full workflow also requires four FIRMS
archive reference files obtained separately from an authorised source. The two
sets of geography serve distinct roles in the pipeline.

| Repository-relative path | Contents |
| --- | --- |
| `geo_data_prep/data/raw/aoi/gha_admin0.*` | National reference boundary |
| `geo_data_prep/data/raw/districts/gha_admin2.*` | District boundaries |
| `geo_data_prep/data/raw/zones/Agro_climatic_zone.*` | Agro-climatic reference zones |
| `geo_data_prep/data/raw/zones/Agro_ecological_zone.*` | Agro-ecological reference zones for the optional ecological example |
| `RP1_Project/rp1_firms_archive/data/reference/geography/` | Separately obtained `acz.geojson`, `districts.geojson`, `ghana.geojson` and `units.json` |

Each shapefile bundle contains `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg`
components. The [study boundary inventory](../geo_data_prep/data/inputs_manifest.json)
and [FIRMS reference checksums](../RP1_Project/rp1_firms_archive/data/reference/geography/checksums.sha256)
record their respective SHA-256 values.

From the repository root, supply a source directory holding the four FIRMS
reference files at the relative path in the table. A complete authorised
copy of the original input tree also works.

```bash
python tools/admit_source_geography.py --source-root "/path/to/authorised/project"
```

In PowerShell, use a quoted Windows path such as `"C:/research/study-inputs"`.
The command verifies the study shapefiles in the checkout and stages the
missing reference files. It leaves matching files in place and fails on
missing or mismatched required files. Add `--verify-only` to validate without
copying, or `--include-ecological` to check the optional agro-ecological
components too.

For attribution, permissions and limits on the documented source lineage,
see [geography input sources](../geo_data_prep/docs/data_sources.md). A
different boundary source requires a matching configuration, Earth Engine
export and geography handoff.
