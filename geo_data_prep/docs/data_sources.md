# Inputs and permissions

The four study boundary bundles are supplied in `geo_data_prep/data/raw/`.
The [source geography guide](../../docs/SOURCE_GEOGRAPHY.md) explains how to
verify the shapefiles and provision the separate FIRMS reference files.

| Role | Dataset | CRS | Source fields used |
|---|---|---|---|
| Administrative districts | `districts/gha_admin2.shp` | EPSG:4326 | `adm2_name`; `adm2_pcode` is available if explicitly selected |
| National reference | `aoi/gha_admin0.shp` | EPSG:4326 | Geometry |
| Agro-climatic reference | `zones/Agro_climatic_zone.shp` | EPSG:32630 | `acz_name`; codes configured explicitly |
| Agro-ecological reference | `zones/Agro_ecological_zone.shp` | EPSG:32630 | `CAPTION` |

Each bundle includes `.shp`, `.shx`, `.dbf`, `.prj` and `.cpg`. Optional spatial-index and descriptive XML files are not required by this workflow. The input inventory records hashes of the exact delivered components. Existing ancillary attributes are not used to substitute for recomputed geometry areas or maximum-overlap assignments.

The input inventory identifies the supplied files. Their ground accuracy,
vintage and public redistribution permissions remain unverified. Retain the
original provider's attribution and permissions when publishing data or derived
results. The BSD licence applies to project code.

Keep input components immutable during processing. For a different source or geographic vintage, use a separate configuration and output run and retain its input hashes. Do not overwrite input files to reproduce a different result under an unchanged identity.
