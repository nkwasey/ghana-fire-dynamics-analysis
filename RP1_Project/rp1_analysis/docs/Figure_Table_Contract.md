# Figure and table contract

## Main manuscript

- **T1** compact ACZ fire-regime summary. S4 supplies the primary temporal series and inference, and S13 supplies the pointwise slope intervals.
- **T2** RQ3 marginal model: two focal predictors plus fixed burnable-area adjustment.
- **T3** significant SaTScan cluster summary; requires genuine validated external output.
- **Figure 1** study-area / analytical-geography figure supplied externally by the author. It is not generated, stored as a required runtime asset, or validated by image path/SHA.
- **F2** direct ACZ and district long-run mapped burned-area rates (1 × 2).
- **F3** district departure from the parent ACZ at left and Local Moran classification at right. Both maps use the same extent and scale. The departure map stipples below-ACZ rates and has a symmetric signed colourbar beneath its panel. The Local Moran panel uses colour and pattern with a separate class key.
- **F4** five ACZ annual fixed-support rate trajectories and fitted Sen lines on a shared scale. The lower-right cell places the Sen slope, raw Romano-Tirlea permutation p-value and BH-adjusted q-value for each ACZ beneath the legend. S4 reports the primary inference and S13 gives pointwise model-conditional slope intervals.
- **F5** RQ3 mismatch geography, four-state correspondence and exactly two focal adjusted PGEE effects.
- **F6** recurrence of validated significant SaTScan membership. Identify the left panel as MCD64A1 discrete Poisson (January 2001 to December 2024) and the right panel as VIIRS space-time permutation (February 2012 to December 2024) in the manuscript caption. The shared scale gives the number of distinct significant clusters containing each eligible district. Each zero-count and unsupported district uses its governed map symbol. F6 is descriptive and requires `RESULTS_VALIDATED`.

## Supplement

- **S1** populations and eligibility.
- **S2** district RQ1 metrics.
- **S3** the single national Global Moran authority plus Local Moran statistics/classes.
- **S4** all 24 annual RQ2 rates for each ACZ with studentized-permutation quantities.
- **S5** RQ3 correspondence, diagnostics, full coefficients and standardised probabilities.
- **S6** primary SaTScan cluster and membership records, parameters and coordinate provenance.
- **S7-S9** district burnable-area support, its distribution and conditional annual-rate variability.
- **S10-S12** sensitivity of national summaries, ACZ dispersion and district membership to minimum burnable support. S11 includes departure quantiles and within-ACZ rank-change summaries. S12 gives district-level ranks on the full eligible baseline and on each retained cohort.
- **S13-S17** pointwise Sen slope intervals, interval calibration, detectability, target attainment and simulation settings.
- **S18-S20** VIIRS confidence-class counts, correspondence by confidence policy and annual source receipts.
- **S21-S24** the restricted MCD64A1 scan comparison, cluster details, district recurrence and keyed scan-window matches on shared district membership and inclusive scan dates.
- **S25** crosswalk from the two district labels cited in the manuscript proof to stable district keys, fixed support, long-run rates, departures and within-ACZ baseline ranks.
- **Figure S1 (`FS1`)** monthly mapped burned-area climatology for the five ACZs, with circular mean month and mean resultant length in the legend.
- **Figure S2 (`FS2`)** district seasonal diagnostics, with a district-month heatmap above circular timing and concentration summaries.
- **Figure S3 (`FS3`)** fixed burnable support, district rates and within-zone Gini sensitivity across thresholds.
- **Figure S4 (`FS4`)** model-conditional pointwise Sen slope intervals and simulated Transition Zone detection under concurrent decline across all five zones. The left panel uses rotated ACZ labels with Guinea Savannah and Sudan Savannah on two lines. The right panel shows reference-bank BH decision frequencies, Wilson intervals conditional on that bank, the range of point estimates across banks and the configured detection target, when the complete five-zone family can be simulated.

Each generated figure has a source-data CSV and manifest. The notebook artwork
uses panel identifiers, axes and keys. Supply titles and scientific panel
context in the manuscript captions. The separate presentation exporter adds
titles from the catalogue and shares the notebook's colour mappings and limits
for equivalent quantities. See the [presentation exporter guide](Presentation_Figure_Exporter.md)
for the fixed scales and standalone layouts. The F3 departure colourbar
marks zero explicitly. The F6 scale uses whole cluster counts. A value
outside a configured fixed scale fails the affected figure export.
Principal composites use the configured 20 × 15 cm landscape canvas. Section 90
records which products were generated. S7-S20, S25 and Figures S1-S4 require
validated analytical inputs.
T3, F6 and S6 use the two primary external result families after they reach
`RESULTS_VALIDATED`. S21-S24 additionally require a validated restricted scan.
The run registry records unexecuted scans as pending and rejects incomplete or
invalid external materials. Reference fixtures are used for software tests.

T3 and S6 distinguish source-reported observed/expected (O/E) from Poisson
relative risk (RR). Space-time permutation expectations and O/E are
conditional model diagnostics, and Poisson RR is not applicable to that
model. Preserve the reported comparison qualifier on p-values. A successful
result-file check is not independent proof of external execution provenance
or the scientific acceptability of the chosen scan model.

In S22, the machine field `radius_max` preserves the SaTScan `SPAN` field,
the maximum distance between two member anchors in the cluster. Report it as
maximum member-to-member span. The native `RADIUS` field measures the
distance from the scan centre to its farthest member.

`T_RESULT_REGISTRY.csv` records semantic result-to-presentation provenance. A `source_figure` links a registered result to artwork showing its estimate. The national Global Moran result points to S3. S4 reports the primary trend estimates and tests, and F4 draws the fitted Sen lines.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

