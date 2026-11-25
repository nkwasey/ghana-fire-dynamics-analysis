# Secondary SaTScan contract

The secondary analysis asks where and when MCD64A1 mapped burned-surface events and VIIRS active-fire detections form unusually concentrated district-level space-time patterns. It is descriptive and does not validate one sensor against another or identify causal mechanisms.

## MCD64A1
Retrospective space-time discrete Poisson; January 2001–December 2024; eligible long-run districts; cases `modis_burned_pixel_count_ba2001`; population/exposure `modis_burnable_km2_union_ba2001`; circular maximum 50% of exposure; temporal window 1–12 months; 999 Monte Carlo replications; high-rate clusters; hierarchical geographically non-overlapping reporting.

## VIIRS
The current configured profile specifies retrospective space-time permutation; February 2012–December 2024; eligible paired-supported districts; cases `viirs_det_primary`; no population/exposure; circular maximum 50% of cases; temporal window 1–12 months; 999 Monte Carlo replications; high-count clusters; hierarchical geographically non-overlapping reporting. Population membership is derived from admitted inputs under configured eligibility; scan settings are study choices rather than independent validation of the source.

The case-only conditional expectation uses observed spatial and temporal case margins. Neither the expectation nor O/E is an exposure-adjusted risk. The model does not automatically correct changes in detection opportunity across space and time. See [space_time_permutation.md](../../docs/space_time_permutation.md) for interpretation, assumptions and the qualification plan.

Coordinates use EPSG:32630 polygon centroids when covered by the district geometry and otherwise point-on-surface. The notebook does not execute SaTScan.

Preparation creates an `EXTERNAL_RESULTS_REQUIRED.txt` marker in each governed
model's result folder. Fresh integration removes these markers only after both
result families and their publication sources validate and the integrated
state has been written successfully. Absent, partial or invalid results leave
the markers intact. Cleanup is limited to those model folders, and a cleanup
failure restores any markers already removed. Read-only inspection and reuse
of an already validated run do not alter markers or other run files.

## Cluster statistics

The cluster parser reads named headers and distinguishes observed cases,
expected cases, source-reported observed/expected (`ODE`), and source
relative risk (`REL_RISK`). It never substitutes O/E for RR. For the
discrete Poisson model, expected cases and RR have their configured
exposure-based model interpretation. For space-time permutation, expected
cases and O/E are conditional to the permutation model; exposure-based
Poisson RR is not applicable and remains missing. The Poisson source `LLR`
is a log likelihood ratio and is distinct from the STP source test statistic. The
literal p-value report and any comparison qualifier are retained alongside
the numerical value. Unrecognised, missing, duplicate or inconsistent
required headers and ambiguous significance must fail validation.

The parsed cluster table distinguishes `expected_count` (Poisson) from
`conditional_expected` (space–time permutation), leaving the non-applicable
field missing. The T3/S6 sources distinguish `expected` (Poisson) from
`conditional_expected` (permutation), carry `observed_expected_ratio` for
both, and retain `relative_risk` and `log_likelihood_ratio` only for Poisson.
`test_statistic`, `test_statistic_type` and `p_value_report` retain
model-specific source information. The run-local publication-source manifest
uses its declared schema; incompatible sources must be regenerated from validated raw
results rather than treated as the corrected schema.

Parsing and model labels do not independently validate the chosen statistical
model, pixel-case interpretation, observational support or null assumptions.
See [SaTScan result contract](../../docs/satscan_results.md).

## 04-01 deterministic external interface

Section 04-01 always generates model-specific SaTScan inputs and parameter files beneath the current secondary run. MCD64A1 receives `.cas`, `.geo`, `.pop` and `.prm`; VIIRS receives `.cas`, `.geo` and `.prm` with no population file. The `.prm` `ResultsFile` entry is the naming authority for genuine external results.

### Monthly temporal-boundary representation

The scientific study windows are owned by `analysis_contract.yml` as monthly periods. The SaTScan interface layer converts only their representation: `StartDate` is the first calendar day of the configured starting month and `EndDate` is the final calendar day of the configured ending month. Month length is calendar-aware, so February resolves to 28 or 29 days as appropriate. For the current configuration the parameter bounds are `StartDate=2001/1/1`, `EndDate=2024/12/31` for MCD64A1 and `StartDate=2012/2/1`, `EndDate=2024/12/31` for VIIRS. No study month is selected in Python.

For a configured `ResultsFile=<prefix>`, the core result family is exactly:

- `<prefix>` — the extensionless human-readable main report written by SaTScan;
- `<prefix>.col.txt` — cluster output;
- `<prefix>.gis.txt` — cluster-membership output.

SaTScan may write auxiliary files such as `.rr.txt`, `.llr.txt` and `.sci.txt`. They are not part of the core completeness gate unless a future prospectively governed scientific contract explicitly adds them. The integration contract does **not** require a duplicate `<prefix>.txt` and does **not** require or generate an external `<prefix>.provenance.json` sidecar.

## 04-02 optional result validation and integration

The package-owned integration API applies the following fail-closed states:

- Neither governed result family has genuine material: `EXTERNAL_RESULTS_REQUIRED`. This is a normal external boundary. No SaTScan-dependent output is fabricated.
- Only one governed model has result material: error; fail closed.
- A governed model has only part of the core family (`ResultsFile`, `.col.txt`, `.gis.txt`): error; fail closed.
- Both result families are complete: validate both; return `RESULTS_VALIDATED` only if every check passes.
- Any malformed, stale, wrong-model, wrong-period, wrong-location, path-escaping or otherwise invalid family: error; fail closed. Invalid material is never silently downgraded to `EXTERNAL_RESULTS_REQUIRED`.

Validation checks the current 04-01 run's recorded inputs and result files. The package verifies run-relative path containment; the exact `.prm` hash; exact `.cas` and `.geo` hashes; the MCD `.pop` hash; absence of a VIIRS population/exposure authority; the `.prm` `ResultsFile` value; staleness relative to current parameter/input authorities; successful report completion; SaTScan version 10.3.3; the governed model and study period; parseable `.col` and `.gis` output; cluster/membership consistency; governed location and centroid IDs; temporal support and maximum cluster duration; and non-Poisson relative-risk semantics for the VIIRS space-time permutation model. These checks do not independently establish which executable and input bytes actually produced externally supplied result files.

Exact locally installed SaTScan executable path/version/SHA qualification remains a separate formal local-testing item. The package may record run-local validation metadata after successful result validation, including current input and result hashes and the version reported by the genuine result. Such metadata is Python-generated validation evidence, not an externally observed provenance sidecar and not a substitute for executable-SHA qualification.

Accepted live publication sources are written only below `out/runs/<run>_sec/04_secondary_concentration/publication_sources/`. Normal repository authority directories are never mutated by live integration.

## Section 90 continuation

After `RESULTS_VALIDATED`, Section 90 generates T3, recurrence-based F6 and S6 from the validated run-local publication sources. If the state remains `EXTERNAL_RESULTS_REQUIRED`, those SaTScan-dependent products remain deferred. The notebook remains thin orchestration and contains no parser, recovery or external-execution implementation.

## Recurrence presentation

F6 is a descriptive projection derived from validated significant cluster membership. For each product and eligible district, `significant_cluster_count` is the number of distinct significant cluster IDs containing that district. Eligible districts with no memberships are valid zeroes. Excluded/unsupported districts have no plotted recurrence value and retain the governed excluded style. The recurrence count is not a new p-value, relative risk, maximum likelihood-ratio statistic, permanent-hotspot label or simultaneous nationwide cluster state.

Monthly case dates use the first calendar day. The analysis end is the final calendar day of the configured ending month, using leap-year-aware calendar arithmetic. For the default study windows, endpoints are 2001/1/1 to 2024/12/31 for the long-run scan and 2012/2/1 to 2024/12/31 for the paired scan. Changing the configured window requires corresponding input support.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

