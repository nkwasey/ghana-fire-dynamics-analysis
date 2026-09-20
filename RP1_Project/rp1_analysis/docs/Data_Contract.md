# Data Contract

## Runtime data authority

RP1 Analysis v1.2.3 separates **runtime scientific admissibility** from **canonical release identity**. `data/input_sha256.json` is the immutable inventory of the exact files supplied with the release. Each entry records:

- `origin_path`: provenance describing the upstream source location or source-relative identity;
- `staged_path`: the release-relative runtime location used by the analysis;
- canonical SHA-256;
- canonical byte size.

Runtime resolution uses only `staged_path`. `origin_path` is provenance and is never a required runtime dependency. Both paths must be relative, traversal-free and valid under their documented bases.

`validate_governed_inputs()` always calculates the current SHA-256 and size of every governed staged file and compares them with the immutable release inventory. It reports `canonical_input_identity=MATCH` only when every current byte identity matches; otherwise it reports `DIFFERENT`. A byte difference does **not** by itself reject ordinary analysis.

Runtime analysis requires `input_validation_status=PASS`. The current panels, metadata and geometries must load successfully and pass the complete governed contract: exact panel schema and column order, types/domains, key uniqueness, temporal support and monthly spines, structural-missingness rules, fixed denominators, geometry/CRS and panel relationships, district-to-ACZ reconciliation and the configured analytical populations. Missing or unreadable required inputs and malformed canonical-inventory structure still fail closed.

The canonical files shipped in this repository must satisfy both `input_validation_status=PASS` and `canonical_input_identity=MATCH`. Scientifically valid reconstructed/replacement files may satisfy `PASS + DIFFERENT`. The canonical inventory must not be rebased to regenerated candidates merely to turn `DIFFERENT` into `MATCH`.

The governed release inputs are the consolidated ACZ and district monthly panels, key/merge metadata, ACZ geometry and district geometry. Scientific execution does not download or regenerate them.

## Product semantics

- MCD64A1 burned area is mapped burned-surface evidence.
- S-NPP VIIRS active fire is thermal-detection evidence.
- MODIS active-fire fields remain governed source data but are not independent validation/corroboration authorities for MCD64A1 and do not enter the final RQ3 regression model.
- BA-2001 is the long-run burned-area authority.
- BA-2012 is the paired-overlap burned-area authority.
- None of these products is treated as ground truth for another product.

## Temporal support

The canonical panel spine is January 2001 through December 2024.

- Long-run MCD64A1 analysis: 2001-01 to 2024-12.
- Paired VIIRS/MCD64A1 analysis: 2012-02 to 2024-12.
- Complete-year overlap summaries: 2013-2024.

A numerical zero is valid only when the relevant product is supported for that unit-month. Unsupported periods remain structurally missing.

## Governed populations

| Population | Candidate units | Retained units | Rows | Eligibility |
|---|---:|---:|---:|---|
| ACZ monthly | 5 | 5 | 1,440 | complete balanced monthly spine |
| District monthly | 260 | 260 | 74,880 | complete balanced monthly spine |
| Long-run district | 260 | 250 | 72,000 | positive fixed BA-2001 burnable-union denominator for all 288 months |
| Paired overlap | 260 | 249 | 38,595 | positive fixed BA-2012 burnable-union denominator and complete paired support for 155 months |
| RQ3 PGEE | 249 paired districts | 249 | 22,939 | paired population restricted to VIIRS-positive district-months |

Eligibility is resolved from governed fields and configuration. Excluded districts remain documented in S1 with explicit reasons.

## Panel schema and keys

Both consolidated panels contain the 111 fields declared in `config/data_schema_contract.yml` and rendered in `docs/Data_Schema_Contract.md`.

Primary keys are configuration-owned. The loader validates:

- exact column set/order;
- data types and finite/range rules;
- categorical domains;
- key uniqueness;
- complete monthly spines;
- source-support and structural-missingness constraints;
- fixed-denominator invariance;
- geometry/panel relationships.

## Geometry

The release contains governed ACZ and district geometries. Spatial analysis uses EPSG:32630. District-to-ACZ relationships are validated against the panel authority before analysis.

## Additive reconciliation

Only fields declared additive in `config/data_schema_contract.yml` may be summed from districts to ACZs. The configured reconciliation includes MCD64A1 burned-area quantities, compatible burnable-area quantities and primary MODIS/VIIRS detection counts. Rates, percentages, shares, means, percentiles and flags are not additive.

The reconciliation fails closed when the configured absolute/relative tolerance is exceeded.

## RQ1 fields

Primary long-run fields are resolved from `field_roles.rq1`:

- burned area: `modis_ba_km2_ba2001`;
- fixed burnable area: `modis_burnable_km2_union_ba2001`.

RQ1 uses the 250-district long-run population.

## RQ2 fields

Final RQ2 uses only the fixed BA-2001 rate support:

- burned area: `modis_ba_km2_ba2001`;
- fixed denominator: `modis_burnable_km2_union_ba2001`.

`modis_burnable_km2_annual_ba2001` remains a governed dataset field for provenance and other non-production uses, but it is not used by final RQ2. RQ2 uses five complete ACZ annual series for 2001-2024.

## RQ3 fields

The paired population is established from governed product-support fields and then restricted to VIIRS-positive district-months for modelling. Population construction is not equivalent to regression-variable selection.

| Role class | Governed field(s) | Final analytical use |
|---|---|---|
| Population/support | `viirs_supported_flag`, `ba2012_supported_flag`, `viirs_det_primary_any` | establish paired support and VIIRS-positive model eligibility; these support/presence fields do not automatically enter the regression matrix |
| Outcome component | `modis_ba_any_ba2012` | defines MCD64A1 presence/absence among VIIRS-positive district-months |
| Focal production predictors | `viirs_det_primary`, `viirs_frp_mean_mw` | log2 focal predictors in the final model |
| Adjustment production predictors | `modis_burnable_km2_union_ba2012`, `month`, `year`, `parent_code` | burnable-area, calendar-month, calendar-year and ACZ adjustments |
| Governed source fields excluded from production RQ3 | `viirs_days_active_nh`, `modis_det_primary_any` | retained in the governed panel but excluded from the final regression design |

MODIS active-fire co-detection is not treated as an independent validation/corroboration authority for MCD64A1. No additional detection-derived variable is treated as satellite observation opportunity.

<!-- BEGIN CONFIG-DERIVED SCIENTIFIC ROLE PROJECTION -->
## Executable scientific-role projection

This section is generated from the executable configuration. It is a human-readable projection, not a second scientific authority.

### RQ2 executable authority

| Item | Configured value |
|---|---|
| Effect estimator | `sens_slope` |
| Inferential test | `studentized_global_mann_kendall_permutation` |
| Burned-area field | `modis_ba_km2_ba2001` |
| Fixed denominator | `modis_burnable_km2_union_ba2001` |
| Denominator support | `fixed_ba2001_burnable_union` |
| Requires distinct realised observations | `true` |
| On ties | `fail_closed` |
| Bandwidth rule | `floor_n_power_one_third` |
| Variance floor | `0.001` |
| Permutations | `9999` |
| p-value method | `monte_carlo_plus_one` |
| Multiple-testing method | `benjamini_hochberg` |
| Multiple-testing family size | `5` |
| Additional denominator analysis | `none` |

### RQ3 executable field roles

Population construction and regression design are distinct. A field used to establish support or VIIRS positivity does not automatically enter the regression matrix.

| Role class | Configured field(s) |
|---|---|
| Population/support | `viirs_supported_flag`, `ba2012_supported_flag`, `viirs_det_primary_any` |
| Outcome component | `modis_ba_any_ba2012` |
| Focal predictors | `viirs_det_primary`, `viirs_frp_mean_mw` |
| Continuous adjustment predictor | `modis_burnable_km2_union_ba2012` |
| Categorical adjustments | `month`, `year`, `parent_code` |

| Model property | Configured value |
|---|---|
| Estimator | `firth_penalized_gee` |
| Working correlation | `independence` |
| Covariance | `morel_bokossa_neerchal` |
| Coefficient reference | `standard_normal_wald` |
| Month reference | `January` (`1`) |
| Year reference | `2013` |
| ACZ reference | `Coastal Zone` (`CZ`) |
| Excluded predictor roles | `rq3.active_days`, `rq3.modis_af_presence` |
| Realised design | `31 columns` |

### Secondary SaTScan executable authority

| Item | Configured value |
|---|---|
| MCD model | `discrete_poisson` |
| MCD exposure role | `secondary.mcd64a1_exposure` |
| VIIRS model | `space_time_permutation` |
| VIIRS exposure | `null` |
| Maximum spatial size | `50%` |
| Maximum temporal length | `12 months` |
| Monte Carlo replications | `999` |
| Reporting method | `hierarchical_non_overlapping` |
| Geographical overlap | `false` |
| Gini-optimised reporting | `false` |

### Publication contract projection

- Main tables: **3** — `T1`, `T2`, `T3`.
- External manuscript Figure 1: author supplied; no runtime asset or generated-output requirement.
- Generated main figures: **5** — `F2`, `F3`, `F4`, `F5`, `F6`.
- Supplementary tables: **6** — `S1`, `S2`, `S3`, `S4`, `S5`, `S6`.
- Supplementary figures: **1** — `S1`.
<!-- END CONFIG-DERIVED SCIENTIFIC ROLE PROJECTION -->
## Secondary SaTScan fields

Exactly two current secondary field authorities are used:

- MCD64A1 cases: `modis_burned_pixel_count_ba2001`;
- MCD64A1 exposure: `modis_burnable_km2_union_ba2001`;
- VIIRS cases: `viirs_det_primary`.

The MCD64A1 model uses the 250-district long-run support. The VIIRS STP model uses the 249-district paired support over February 2012-December 2024 and has no population/exposure file.

Stable numeric SaTScan location IDs map one-to-one to governed district IDs. Coordinates are generated in EPSG:32630 by a generic geometry-safe rule: use the polygon centroid when the district geometry covers it; otherwise use a guaranteed interior point-on-surface. The emitted location authority records `polygon_centroid` or `point_on_surface` per district and verifies that every point is covered by its governed district geometry. Source-unsupported periods never enter the scan support.
