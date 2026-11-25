# Data contract

The analysis consumes the selected workflow handoff: merged district and zone panels, merger manifest and QA/support companion, matching projected geography and district-to-zone crosswalk. The workflow creates those inputs from the selected run. The validator checks the actual files, schemas, keys, temporal support, denominators, geometry, reconciliation and realised analytical populations. A hash identifies bytes; it is not scientific acceptance or independent lineage evidence. Missing dependencies fail closed.

## Product semantics

- MCD64A1 burned area is mapped burned-surface evidence.
- S-NPP VIIRS active fire is thermal-detection evidence.
- MODIS active-fire fields remain governed source data but are not independent validation/corroboration authorities for MCD64A1 and do not enter the final RQ3 regression model.
- BA-2001 is the long-run burned-area authority.
- BA-2012 is the paired-overlap burned-area authority.
- None of these products is treated as ground truth for another product.

The c3 source already applies its documented zero-contribution evidence scenario. Analytical values and guarded nulls are preserved exactly; the pipeline does not apply an additional zero-fill policy. The mandatory lossless companion retains source status, coverage/evidence, domain, source/grid and file/row provenance. Missing sources and withheld results cannot become numerical zeros.

The annual-denominator burned-area field is a ratio of a union-masked numerator
to year-specific burnable area; it is not an annual-mask fraction and can
exceed one. The union-denominator fraction remains bounded between zero and one.

## Temporal support

The canonical panel spine is January 2001 through December 2024.

- Long-run MCD64A1 analysis: 2001-01 to 2024-12.
- Paired VIIRS/MCD64A1 analysis: 2012-02 to 2024-12.
- Complete-year overlap summaries: 2013-2024.

A numerical zero is present only when the relevant product family is within
its governed temporal support. A zero may still be assumption-derived when
observation support is absent or partial; consult the sidecar before treating
it as observed. Periods outside product support remain structurally missing.

## Analytical populations

Population eligibility is calculated from input support and configured rules. Report realised unit and row counts for the balanced panel, positive long-run union support, paired product support and VIIRS-positive modelling population. Do not require a precomputed result table to determine eligibility. Excluded units remain documented with explicit reasons.

## Panel schema and keys

Both consolidated panels contain the fields declared in `config/data_schema_contract.yml` and rendered in `docs/Data_Schema_Contract.md`.

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

The geography handoff supplies ACZ and district geometries. Spatial analysis uses EPSG:32630. District-to-ACZ relationships are validated against the panel authority before analysis.

## Additive reconciliation

Only fields declared additive in `config/data_schema_contract.yml` may be summed from districts to ACZs. The configured reconciliation includes MCD64A1 burned-area quantities, compatible burnable-area quantities and primary MODIS/VIIRS detection counts. Rates, percentages, shares, means, percentiles and flags are not additive.

The reconciliation fails closed when the configured absolute/relative tolerance is exceeded.

## RQ1 fields

Primary long-run fields are resolved from `field_roles.rq1`:

- burned area: `modis_ba_km2_ba2001`;
- fixed burnable area: `modis_burnable_km2_union_ba2001`.

RQ1 uses the eligible long-run district population.

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
| Realised design | `derived from the admitted model population during execution` |

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
- Supplementary tables: **25** — `S1`, `S2`, `S3`, `S4`, `S5`, `S6`, `S7`, `S8`, `S9`, `S10`, `S11`, `S12`, `S13`, `S14`, `S15`, `S16`, `S17`, `S18`, `S19`, `S20`, `S21`, `S22`, `S23`, `S24`, `S25`.
- Supplementary figures: **4** — `FS1`, `FS2`, `FS3`, `FS4`.
<!-- END CONFIG-DERIVED SCIENTIFIC ROLE PROJECTION -->
## Secondary SaTScan fields

Exactly two current secondary field authorities are used:

- MCD64A1 cases: `modis_burned_pixel_count_ba2001`;
- MCD64A1 exposure: `modis_burnable_km2_union_ba2001`;
- VIIRS cases: `viirs_det_primary`.

The MCD64A1 model uses eligible long-run support. The VIIRS STP model uses eligible paired support within its configured interval and has no population/exposure file.

Stable numeric SaTScan location IDs map one-to-one to governed district IDs. Coordinates are generated in EPSG:32630 by a generic geometry-safe rule: use the polygon centroid when the district geometry covers it; otherwise use a guaranteed interior point-on-surface. The emitted location authority records `polygon_centroid` or `point_on_surface` per district and verifies that every point is covered by its governed district geometry. Source-unsupported periods never enter the scan support.

The RQ3 monthly support audit distinguishes temporal product availability from
observation quality. It reports complete, partial, no-valid, no-union and
QA-unavailable counts, including counts of analytical zeroes in each state and
zeroes for which the unknown-area assumption was applied. A zero with partial
or no valid support is not an observed zero over the entire union; an empty
union has no area over which a burned fraction can be estimated. Inputs without observation-quality evidence are reported as QA unavailable.
The audit does not exclude or recode rows: models use the analytical BA
presence flag, including zeroes that incorporate the unknown-area assumption.
Sensitivity to this assumption requires separate analysis.

Within-unit fixed and within-unit-year annual burnable areas are checked with
an absolute tolerance of 1e-9 km² (0.001 m²) to accommodate decimal and
floating-point round trips. Differences above this tolerance still fail.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

