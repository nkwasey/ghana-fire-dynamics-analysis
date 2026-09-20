# External data contract

This contract distinguishes the self-contained RP1 Analysis v1.2.3 product
from optional upstream data reconstruction.

## Product rule

Normal scientific analysis and the shipped test estate use repository-owned,
governed data. They do not require network access, an external development
archive, a user-specific staging directory, or locally retained historical
pipeline outputs.

The analysis authority is the validated data under
`RP1_Project/rp1_analysis/data/`, including consolidated fire panels,
analysis geometries, the district-to-ACZ crosswalk, exact input hashes and
qualified reference authorities.

Runtime `out/` directories are generated artefacts and are excluded from the
shipped product.

## Data classes

### Governed analysis inputs

Repository-owned files consumed directly by the canonical analysis:

```text
RP1_Project/rp1_analysis/data/raw/
RP1_Project/rp1_analysis/data/geo/
RP1_Project/rp1_analysis/data/reference/
RP1_Project/rp1_analysis/data/authorities/
RP1_Project/rp1_analysis/data/input_sha256.json
```

These files are validated before use. Their presence makes normal RP1 analysis
standalone with respect to scientific input acquisition.

### Repository-owned upstream resources

Files distributed to support source reconstruction and qualification:

- extracted Ghana admin-0 and admin-2 shapefile families under
  `geo_data_prep/data/raw/`;
- agro-climatic-zone and agro-ecological-zone source/reference geometries;
- `RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv`;
- Earth Engine JavaScript under `RP1_Project/rp1_gee_ba_scripts/`;
- BA-2001 and BA-2012 Earth Engine CSV export bundles under the two
  `RP1_Project_MODIS_BA_c1_*` directories.

These resources are not silently substituted for governed Stage 4 inputs.
They are used only through the relevant regeneration and validation workflow.

### External regeneration inputs

Raw yearly MODIS and VIIRS FIRMS active-fire files are not distributed.
Reconstructing Stage 2 requires source acquisition from NASA FIRMS and local
staging under the configuration-owned `data/raw/modis/` and `data/raw/viirs/`
locations. Earth Engine is also an external service if the burned-area exports
are regenerated rather than using the shipped export bundles.

### Generated working data

The following are run-local or regeneration-time products, not persistent
product authorities:

```text
geo_data_prep/out/<run_id>/
RP1_Project/rp1_mv_firms_panels/out/runs/<run_id>/
RP1_Project/rp1_analysis/out/runs/<run_id>/
```

Stage 2 boundary mirrors under `RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/`
are likewise regeneration-time working data and are not shipped.

## Source registry

| Source family | Provider/authority | Role |
| --- | --- | --- |
| Ghana administrative boundaries | HDX COD-AB GHA, `https://data.humdata.org/dataset/cod-ab-gha` | Stage 1 source geometry |
| Agro-climatic zones | maintained project source based on Yamba et al. (2023), `https://doi.org/10.1371/journal.pclm.0000023` | Stage 1 ACZ source/reference |
| MODIS and VIIRS active fire | NASA FIRMS, `https://firms.modaps.eosdis.nasa.gov/download/` | Stage 2 source detections when rebuilding |
| MODIS burned area | project Earth Engine workflow under `RP1_Project/rp1_gee_ba_scripts/` | burned-area export generation/reconstruction |

## Authority and provenance rules

- Governed analysis inputs must pass `scripts/validate_inputs.py` before
  scientific execution.
- Structural missingness, unsupported observations and observed zeroes are
  different states and must remain different through regeneration.
- Mirrored or regenerated data do not become authoritative merely because they
  occupy a familiar path.
- Tests use repository-owned deterministic fixtures or governed inputs; they do
  not consume live FIRMS folders, local SaTScan outputs or user directories.
- Genuine SaTScan scientific results are external-engine outputs and are
  governed by the separate SaTScan interface/provenance contract, not by this
  data-acquisition contract.

The user-facing acquisition and reconstruction instructions are in
`docs/data_access.md`.

## RP1 v1.2.3 reconstruction identity

A reconstructed analysis input is not required to reproduce historical provenance-only bytes, `run_id` values or timestamps. It must instead pass the complete RP1 governed data/scientific validation. The analysis release inventory at `rp1_analysis/data/input_sha256.json` remains immutable and is used only to report whether current bytes `MATCH` or are `DIFFERENT` from the release; it must not be rebased to a reconstruction candidate.
