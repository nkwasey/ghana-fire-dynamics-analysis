# Analysis Methods Contract

## Authority chain

The controlling scientific design is the current governed scientific-method specification. `config/analysis_contract.yml` is its sole executable projection. Python implements generic algorithms and structural checks; tests must not recreate Ghana-specific scientific choices as an independent authority. Realised values belong in run metadata.

## RQ1 — spatial support, heterogeneity, seasonality and spatial organisation

RQ1 uses MCD64A1 from 2001–2024 at direct ACZ and district supports. Annual rates use the fixed BA-2001 burnable-union denominator and are expressed per 100 km². District long-run rates are summarised within parent ACZ by median, IQR and Gini. Parent ACZ is the governed maximum-original-polygon-overlap assignment and districts remain whole units. District departure is the raw district long-run rate minus the directly aggregated parent-ACZ long-run rate.

Seasonality retains the 12-month climatology and reports circular mean direction plus mean resultant length. The continuous publication coordinate is cyclic at the December/January boundary: 0 is equivalent to 12; the implementation is not restricted to a closed linear interval [1,12]. Spatial inference uses first-order Queen contiguity, row standardisation and no artificial island links. Islands are excluded from Moran inference. Exactly one national Global Moran result is reported for eligible district departures. Local Moran uses the configured conditional-permutation convention recorded in `analysis_contract.yml`: inclusive tails, plus one per tail, twice the smaller corrected tail capped at one, and BH-FDR over all eligible non-island Local Moran tests. See `Local_Moran_Two_Sided.md`.

The Local Moran tail, tie and conditional-reference conventions are configured study-design choices. A direct-loop reference calculation and focused regression tests verify that the code follows the configured convention. Exchangeability of the Ghana data remains a scientific assumption.

## RQ2 — monotonic ACZ burned-area-rate change

Each of the five ACZs contributes one complete fixed-support annual rate series for 2001–2024. Sen’s slope is the effect-size estimator. The sole production inferential authority is the Romano–Tirlea studentized global Mann–Kendall permutation test. Sen slope and the inferential null are distinct: the inferential null is not defined as a zero Sen slope. In the global reference framework, the null is strict stationarity. The theoretical validity result used as the reference scope assumes strict stationarity, absolute regularity, no ties (continuous marginal distribution), summable beta-mixing coefficients, positive long-run variance and an asymptotically admissible bandwidth sequence.

The executable RP1 contract requires distinct realised annual observations and `fail_closed` on ties for this strict reference-qualified route. The realised five Ghana ACZ annual series are tie-free. Generic MK pairwise code assigns zero contribution to equal pairs, but that mathematically correct kernel behaviour does not constitute inferential qualification for tied time series. The project makes no claim that the Romano–Tirlea reference theorem validates a tied-data extension without a separate prospective authority.

The reference-method-derived components are the global Mann–Kendall rank statistic, the studentisation principle, the long-run variance construction and re-studentisation of each permutation. The exact finite-sample bandwidth rule `floor(n^(1/3))`, variance floor 0.001, 9,999 permutation count, two-sided absolute extremeness, seed 20260822, plus-one Monte Carlo p-value and BH family of exactly five ACZ raw p-values are prospectively governed study/computational choices. The paper uses `floor(n^(1/3))` and a 0.001 truncation in its simulations, but its theorem permits a class of asymptotically admissible bandwidth sequences and does not uniquely mandate those finite-sample choices. The run records the realised bandwidth from its configured annual series length.

Report the realised slopes and multiplicity-adjusted inference from the selected run. A non-significant p-value is treated as non-rejection under the configured inferential procedure; it is not evidence that no temporal change occurred. Trend estimates and inference are observational and are not interpreted causally.

## RQ3 — cross-product observability

All paired district-months first enter the four-state VIIRS/MCD64A1 descriptive correspondence. The primary regression then conditions on VIIRS-positive district-months. The outcome is MCD64A1 absence versus presence. The continuous model terms are configured, not hard-coded: VIIRS nominal/high-confidence detection count and the mean of eligible UTC daily maximum FRP values are focal log2 predictors, and fixed BA-2012 burnable area is a log2 adjustment. Month, year and ACZ are configured categorical adjustments with configured reference levels. Active-fire days and MODIS active-fire co-detection are excluded from the final model.

VIIRS FRP observations are selected and deduplicated independently of the count stream. FRP can be present in a district-month with zero count-stream nominal/high detections; that month is outside the positive-count conditional regression population. Required missing or nonpositive log predictors fail model validation.

The estimator is Firth-type penalised binomial-logit GEE with district clusters, fixed working independence and Morel–Bokossa–Neerchal corrected cluster covariance. Coefficient inference uses standard-normal Wald tests and intervals. VIF is a diagnostic on the final continuous predictor set and has no deletion authority. Standardised probabilities use observed-covariate predictive standardisation at configured focal-predictor quantiles. Read the month coefficients alongside the monthly counts of both outcomes. Sparse cells or complete separation can leave very large uncertainty and unstable effect sizes after penalisation. All effects describe conditional associations in the VIIRS-positive population for the mapped-absence endpoint.

## Secondary SaTScan analysis

MCD64A1 uses retrospective space-time discrete Poisson scanning with burned-pixel cases and fixed BA-2001 exposure. VIIRS uses retrospective space-time permutation scanning with no exposure. Shared scientific settings are supplied by configuration: circular spatial windows, high clusters only, 50% maximum spatial size, 12-month maximum temporal size, 999 Monte Carlo replications, alpha 0.05 and hierarchical geographically non-overlapping secondary clusters. Cluster reporting uses the configured hierarchical geographically non-overlapping rule. Coordinates use the governed point-on-surface/inside-polygon authority in the configured CRS.

For the case-only permutation model, expected counts and observed/expected
ratios are conditional diagnostics based on observed spatial and temporal
case margins. They are not exposure-based expected counts or Poisson relative
risks. Observation opportunity and source completeness require separate
qualification; a temporal coverage flag alone does not establish them.

SaTScan execution remains an external boundary. The project must bind exact executable/version and parameter/input hashes before cluster claims are accepted. No undocumented user-defined random-seed parameter is invented. The notebook does not execute SaTScan: 04-01 generates deterministic interfaces, while 04-02 optionally validates both external result families together. No supplied result families yields `EXTERNAL_RESULTS_REQUIRED`; two complete valid families yields `RESULTS_VALIDATED`; partial or invalid material fails closed. Validated T3/S6 sources and the F6 recurrence source are run-local only. F6 maps the number of distinct validated significant clusters containing each eligible district and adds no inferential rule.

Input admission and inferential prerequisites fail closed when required data, reference conditions or configured capabilities are unavailable.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

The adopted primary pixel rule assigns native area to accepted mapped burning and zero contribution to other pixels within the known eligible domain after successful source processing and technical admission. It does not redefine eligibility denominators or turn missing files, failed reductions and guarded technical conditions into ordinary zeros. QA/evidence fields and the companion remain available for traceability. This operational definition supports the study's measured-burned-area-or-zero endpoint; it does not identify every original masked value or establish physical fire absence.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

## Supplementary diagnostics

### District burnable-area support

The fixed BA-2001 union includes each pixel that meets the reported land and
land-cover rules in at least one reference year from 2001 to 2024. Annual
eligibility requires valid MCD12Q1 land and cover values, `LW=2`, and an IGBP
class in 1-10, 12 or 14. The BA-2012 union uses the same rule over 2012-2024.
The fixed unions represent product-defined eligibility during those windows.
See [burned-area methods](../../docs/burned_area_methods.md) for the grid,
source support and unresolved membership rules.

Summarise fixed BA-2001 support nationally and within each ACZ. For every
district, report support area, cumulative mapped burned area, mapped burned-pixel
cases, long-run rate, departure from the direct parent-ACZ rate and the support
state. Report the number of positive years, annual rate quantiles and the two
half-period means. Retain zero-area and ineligible districts in the diagnostic
inventory while limiting rate estimation to the eligible population.

Estimate pointwise uncertainty of each eligible district's mean annual rate
using circular blocks of calendar years sampled jointly across districts. The
95% percentile interval describes variation within the measured annual history
on fixed support. Interpret sparse, all-zero, constant and degenerate histories
alongside the status labels. Mapping uncertainty and uncertainty in burnable
area are separate from these intervals. Compare the primary block length with
the configured alternative lengths. S9 reports the spans of both endpoints
and flags material sensitivity when a resolved span reaches the configured
fraction of the primary interval width. The study uses one quarter of that
width as a descriptive review threshold. For a zero-width primary interval,
any span larger than the numerical tolerance is flagged. With fewer than two
available block lengths the flag is undefined. The observed half-period
means in S7 describe finite-record change and help assess whether a
stationary repeated-period interpretation is plausible.

Compare the full positive-support population with successively stricter
minimum fixed-area thresholds. The analysis contract governs the thresholds,
the named restricted scan cutoff, the S9 resample count and the primary and
sensitivity block lengths under `research_questions.rq1.support_sensitivity`.
Apply each cutoff as a strict lower bound on fixed burnable area. FS3 highlights
the named restricted scan cutoff. Report retained and excluded counts by ACZ,
Gini, district departures and Global and Local Moran results. Retain the
direct ACZ rates as the benchmarks. S11 reports departure distribution tails
and counts of rank changes. S12 distinguishes recomputed rank on the common
district population from the rank change caused by screening districts out.
S25 links the two proof names to their stable district identities and measured
support and departures. Rebuild the Queen graph within each
restricted district set. Recompute the Local Moran BH family on eligible
non-islands in that graph and report changes in graph size and island support.
An exclusion may therefore change the sampled population, weights and
multiplicity family together.

### Sen slope uncertainty and trend detectability

Use the complete consecutive RQ2 annual series and the settings in
`research_questions.rq2.trend_sensitivity` in the analysis contract. The Ghana study series cover
24 years. Fit Sen trends and resample median-centred log ratios to the fitted
positive lines. Draw synchronised stationary blocks, with a geometric block
length and circular continuation, across the eligible zones. Refit Sen slopes
for 9,999 observed resamples per expected block length. Use three years as
the primary length and two, four and six years as uncalibrated sensitivities.
Record why an interval is unavailable for a zone with nonpositive observations,
a nonpositive fitted path or degenerate residuals.

Calibrate the primary pointwise 95% intervals with 600 simulated series
families per mechanism and effect and an independent set of 600 simulated
families from each of the same settings. Use 299 bootstrap draws for each
simulated series as a computational proxy for the 9,999 draws in the reported
interval procedure. The calibration covers zero
change and a proportional decline of 0.20 of the central rate per decade across
four noise scenarios. Use a zone-specific width multiplier derived from the
largest 98th percentile of the required width across those scenarios, with a
lower bound of one. Claim nominal coverage in the simulated scenarios only
where the smallest 95% Wilson lower bound in the independent simulation reaches 0.95. These
intervals are pointwise and conditional on the simulated scenarios. The
five-zone primary permutation decisions remain the RQ2 inferential results.
S17 records the number of covered intervals, cases with truth below the lower
endpoint or above the upper endpoint, and invalid intervals. Coverage uses all
simulated families in its denominator. In S13, the columns
`worst_held_out_coverage` and `worst_held_out_coverage_lower_95` report the
minima over independently seeded repeats of the original calibration
settings. Assess the fixed multipliers separately
on 300 independent families per effect and held-out noise scenario. These
scenarios use independent zones, heavy-tailed marginal errors or right-skewed
marginal errors with the fitted zone-specific log-scale dispersion. Draw the
independent-zone innovations and stationary initial values directly by zone.
The heavy-tail
and skew scenarios stretch symmetric tails beyond one standard deviation or
stretch the positive half of the latent Gaussian error, respectively.
These transformations preserve a zero median and use unit variance before
applying the zone dispersion. Latent and realised Pearson correlations can
differ. Flag pointwise coverage estimates below 0.925
and report 95% Wilson bounds. The held-out assessment uses the same 299-draw
bootstrap proxy as the calibration.

Evaluate the S15 and S16 full detectability grid with 3,000 simulated
five-zone families per Gaussian scenario. Include independent years, fitted
weak AR(1), positive AR(1) and negative AR(1). Use cross-zone innovation correlation estimated
from the detrended series and regularised toward the identity matrix. Run
all-null, one-zone decline and concurrent-decline scenarios across the
declared grid and apply the same studentised rank statistic and five-zone BH
decision rule. Compute observed and reference statistics with the same
integer-rank arithmetic, and use the production adjusted-p calculation for
each BH family.
Count inclusive absolute-score exceedances.
Three independent permutation banks, each with 9,999 permutations, assess
Monte Carlo sensitivity. Report reference-bank raw and BH rejection
frequencies and their conditional 95% Wilson limits. For BH decisions, also
report the minimum and maximum rejection frequencies across banks. FS4
displays both quantities for the Transition Zone under concurrent decline.
Screen for 80% attainment at the first grid point from which the smallest
bank-wise 95% Wilson lower bound reaches 0.80 at every tested effect.
Report `NOT_ATTAINED_ON_GRID` when the screen finds no such point. Flag
all-null scenario estimates of any BH rejection above 0.075 for
interpretation. Independently simulate 4,000
all-null families per Gaussian or held-out noise scenario with fresh rank
permutation banks. Record Wilson uncertainty, bank variation and threshold
flags in S17. The additional independent-zone, heavy-tail and right-skew
settings qualify interval coverage and all-null rejection. Use another independent random stream to compare paired
positive and negative proportional slopes at the calibration effect size
under the independent-years scenario. For a screening crossing, use a fresh
4,000 families and separate permutation banks to test the candidate and every
greater grid effect. Also check the preceding point for context. In S16,
`ATTAINED_ON_GRID` requires a complete grid tail with the smallest 95%
Wilson lower bound at or above 0.80 in both runs. If confirmation supports
only a later tail, S16 reports its starting point. Use
`UNCONFIRMED_SCREENING_CROSSING` with blank sustained effect fields when
independent confirmation supports no complete tail. S17 retains the
screening candidates and independent results. Estimates apply to the
declared settings and series length. The detectability family requires all
five zones.

### Confidence-policy correspondence

Use one common set of supported district-months to compare all-confidence,
nominal-plus-high and high-only detection policies. Verify the annual
Suomi-NPP standard-processing receipts and the monthly count identities.
Report the fraction of detections excluded from the primary count and the
four correspondence states for each threshold. For conditional mapped
absence, report the number of positive months under that threshold as the
denominator. Results are descriptive. A change in detection policy selects
different district-months and the comparison does not reclassify the nominal
confidence population's fire history or refit the primary FRP model.

### Poisson scan support sensitivity

Prepare a separate MCD64A1 scan on districts whose fixed BA-2001 area exceeds
the cutoff in the selected baseline's governed support sensitivity settings.
The named BA-2001 GT50 scenario requires 50 km² and appears among the district
sensitivity thresholds. Restrict the count, coordinate and exposure
interfaces consistently.
Carry forward the baseline Poisson settings, require the original result
family to validate, and execute and validate the restricted scan with the
configured SaTScan binary. Report the numbers of districts and clusters,
exclusion composition by ACZ and recurrence comparisons on common districts.
Record distinct model and result identifiers for this supplementary scan.

Recurrence is the number of distinct significant scan clusters containing the
district. A scan window's duration measures months in the identified window.
Thermal events, the physical duration of individual fires and ecological
impact require separate observations. Expected counts, effect summaries and
log-likelihood ratios follow the model-specific null and are interpreted
within each scan. VIIRS space-time permutation expectations condition on
observed spatial and temporal case margins.

## Geography and source verification

Generate geography locally and upload the three configured Earth Engine table assets when preparing a new c3 export delivery. Record the geography run, local bundle hashes, asset identifiers, pinned scripts and available export or task identifiers. The Earth Engine applications check the native grid and source availability and apply the documented geometry buffer and intersection. The local workflow validates the retained files and their admission identities. Independent verification of remote asset geometry, source-mask behaviour and physical fire occurrence requires separate evidence.

