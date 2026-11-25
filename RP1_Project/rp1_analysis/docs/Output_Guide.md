# Analysis outputs

The internal c3 input authorities are `QA_C3_EVIDENCE`,
`QA_C3_EXCLUSIONS`, `QA_C3_RECONCILIATION` and `QA_C3_DIAGNOSTICS`.
The last compares known-union/domain/evidence/sensitivity areas and sample/anomaly
counts even when primary results are withheld. Counts compare exactly. Areas
retain the configured reconciliation tolerances; missing district records and
withheld diagnostic values have separate counts. Overlapping reason areas are
not summed as an evidence partition.

## Main manuscript

- **T1** compact ACZ fire-regime summary. Primary trend statistics are in S4 and pointwise slope uncertainty is in S13.
- **T2** RQ3 marginal model: two focal predictors plus fixed burnable-area adjustment.
- **T3** significant SaTScan cluster summary; requires genuine validated external output.
- **Figure 1** study-area / analytical-geography figure supplied externally by the author. It is not generated, stored as a required runtime asset, or validated by image path/SHA.
- **F2** direct ACZ and district long-run mapped burned-area rates (1 × 2).
- **F3** district departure from the parent ACZ at left and Local Moran classification at right. Both maps use the same extent and scale. The departure map stipples below-ACZ rates and has a symmetric signed colourbar beneath its panel. The Local Moran panel uses colour and pattern with a separate class key. HH and LL denote high-high and low-low clusters, HL and LH denote high-low and low-high outliers, NS denotes a result without BH support, and ISLAND denotes a district without neighbours on the analytical Queen graph.
- **F4** five ACZ annual fixed-support rate trajectories and fitted Sen lines on a shared scale. The lower-right cell places the Sen slope, raw Romano-Tirlea permutation p-value and BH-adjusted q-value for each ACZ beneath the legend. S4 reports the primary inference and S13 gives pointwise model-conditional slope intervals.
- **F5** RQ3 mismatch geography, four-state correspondence and exactly two focal adjusted PGEE effects.
- **F6** recurrence of validated significant SaTScan membership. Identify the left panel as MCD64A1 discrete Poisson (January 2001 to December 2024) and the right panel as VIIRS space-time permutation (February 2012 to December 2024) in the manuscript caption. The shared scale gives the number of distinct significant clusters containing each eligible district. Each zero-count and unsupported district uses its governed map symbol. F6 is descriptive and requires `RESULTS_VALIDATED`.

## Supplement

- **S1** populations and eligibility.
- **S2** district RQ1 metrics.
- **S3** the single national Global Moran authority plus Local Moran statistics/classes.
- **S4** all 24 annual RQ2 rates for each ACZ with studentized-permutation quantities.
- **S5** RQ3 correspondence, diagnostics, full coefficients and standardised probabilities.
- **S6** complete primary SaTScan results, memberships, parameters and coordinate provenance. Requires validated external output.
- **S7-S9** district burnable support, the denominator distribution and conditional district mapped-rate variability, respectively.
- **S10-S12** fixed-area threshold sensitivities for national diagnostics, ACZ dispersion and district classifications, respectively. S11 reports within-ACZ minimum, 5th percentile, median, 95th percentile and maximum signed departures, plus counts and maximum absolute rank changes. S12 reports the full baseline rank, the baseline rank recalculated on each retained cohort and the scenario rank in the same cohort.
- **S13-S17** Sen slope intervals, simulation calibration, simulated detection frequencies, target attainment and simulation settings, respectively. The S13 `worst_held_out_coverage*` columns summarise independent repeats of the four calibration settings. S17 reports the distinct held-out noise mechanisms and the independent check of any preliminary S16 crossing.
- **S18-S20** VIIRS confidence-class counts, paired correspondence by confidence policy and annual source and processing receipts, respectively.
- **S21-S24** restricted BA Poisson scan comparison, significant clusters, district recurrence and keyed native-window matches, respectively. The two scans are compared on shared district membership and inclusive dates. These tables require a separately validated restricted scan.
- **S25** stable district identities and quantitative support for the D008 and D198 proof examples. A matched district inherits its fixed denominator and any eligible rates, departures and ranks from the governed baseline. Analytical fields are blank if the district is absent from the governed geography.
- **Figure S1 (`FS1`)** monthly mapped burned-area climatology for the five ACZs, with circular mean month and mean resultant length in the legend.
- **Figure S2 (`FS2`)** district seasonal diagnostics, with a district-month heatmap above circular timing and concentration summaries.
- **Figure S3 (`FS3`)** fixed burnable support, district rates and within-zone Gini sensitivity across thresholds.
- **Figure S4 (`FS4`)** model-conditional pointwise Sen slope intervals and scenario-based detectability. The default interval level is 95%. Dashed intervals mark limited coverage on independently simulated series under the specified settings. The left panel uses rotated ACZ labels with Guinea Savannah and Sudan Savannah on two lines. The right panel shows simulated Transition Zone BH detection under concurrent decline and the configured 80% target. Whiskers are the reference bank's conditional 95% Wilson intervals. Shading spans the smallest and largest estimates across the permutation banks. The complete effect grid covers four Gaussian scenarios in S15 and S16. S17 separately reports null rejection and interval coverage in the additional stress settings. S16 reports an attained crossing only after independent confirmation over the complete grid tail. The panel identifies when the complete five-zone simulation is unavailable.

Departure ranks are descending within each ACZ, with rank 1 for the largest
signed departure and average ranks for exact ties. S12 computes a shared-cohort
change as the scenario rank minus the baseline rank within the retained cohort.
It computes the screening shift as the retained-cohort baseline rank minus the
full-cohort baseline rank. Thresholding preserves the observed district rate
and its direct parent-ACZ reference, so each shared-cohort shift is zero by
construction. Screening shifts arise from removal of districts from the rank
roster. Only retained districts contribute to the S11 summaries. Empty cohorts
have zero rank-change counts and blank quantiles and rank-shift maxima.

Generated figures are accompanied by a source-data CSV and manifest. The
publication figure contract specifies the canvas and panel arrangement.
The notebook figures use manuscript captions for titles and scientific panel
context. The separate presentation exporter supplies artwork with titles.
Section 90 records whether outputs were generated or deferred. T3, F6 and S6
are deferred while the primary scans report `EXTERNAL_RESULTS_REQUIRED`, and
are generated from run-local sources at `RESULTS_VALIDATED`. S21-S24 require the
restricted scan. S7-S20, S25 and FS1-FS4 use the admitted analytical inputs and can
be generated before external scans. Partial or invalid external result families
fail validation. Reference fixtures are reserved for software tests.

T3 and S6 distinguish source-reported observed/expected (O/E) from Poisson
relative risk (RR). Space-time permutation expectations and O/E are
conditional model diagnostics, and Poisson RR is not applicable to that
model. Preserve the reported comparison qualifier on p-values. A successful
result-file check is not independent proof of external execution provenance
or the scientific acceptability of the chosen scan model.

`T_RESULT_REGISTRY.csv` records semantic result-to-presentation provenance. A `source_figure` is populated only when that figure actually consumes/displays the registered result. The national Global Moran result is sourced to S3 and has no manuscript `source_figure`, because no generated manuscript figure directly displays the Global Moran statistic.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

