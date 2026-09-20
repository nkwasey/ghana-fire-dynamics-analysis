# Analysis Methods Contract

## Authority chain

The controlling scientific design is the current governed scientific-method specification. `config/analysis_contract.yml` is its sole executable projection. Python implements generic algorithms and structural checks; tests must not recreate Ghana-specific scientific choices as an independent authority. Realised values belong in run metadata.

## RQ1 — spatial support, heterogeneity, seasonality and spatial organisation

RQ1 uses MCD64A1 from 2001–2024 at direct ACZ and district supports. Annual rates use the fixed BA-2001 burnable-union denominator and are expressed per 100 km². District long-run rates are summarised within parent ACZ by median, IQR and Gini. Parent ACZ is the governed maximum-original-polygon-overlap assignment and districts remain whole units. District departure is the raw district long-run rate minus the directly aggregated parent-ACZ long-run rate.

Seasonality retains the 12-month climatology and reports circular mean direction plus mean resultant length. The continuous publication coordinate is cyclic at the December/January boundary: 0 is equivalent to 12; the implementation is not restricted to a closed linear interval [1,12]. Spatial inference uses first-order Queen contiguity, row standardisation and no artificial island links. Islands are excluded from Moran inference. Exactly one national Global Moran result is reported for eligible district departures. Local Moran uses the frozen conditional-permutation convention recorded in `analysis_contract.yml`, with 9,999 permutations and BH-FDR over all eligible non-island Local Moran tests.

## RQ2 — monotonic ACZ burned-area-rate change

Each of the five ACZs contributes one complete fixed-support annual rate series for 2001–2024. Sen’s slope is the effect-size estimator. The sole production inferential authority is the Romano–Tirlea studentized global Mann–Kendall permutation test. Sen slope and the inferential null are distinct: the inferential null is not defined as a zero Sen slope. In the global reference framework, the null is strict stationarity. The theoretical validity result used as the reference scope assumes strict stationarity, absolute regularity, no ties (continuous marginal distribution), summable beta-mixing coefficients, positive long-run variance and an asymptotically admissible bandwidth sequence.

The executable RP1 contract requires distinct realised annual observations and `fail_closed` on ties for this strict reference-qualified route. The realised five Ghana ACZ annual series are tie-free. Generic MK pairwise code assigns zero contribution to equal pairs, but that mathematically correct kernel behaviour does not constitute inferential qualification for tied time series. The project makes no claim that the Romano–Tirlea reference theorem validates a tied-data extension without a separate prospective authority.

The reference-method-derived components are the global Mann–Kendall rank statistic, the studentisation principle, the long-run variance construction and re-studentisation of each permutation. The exact finite-sample bandwidth rule `floor(n^(1/3))`, variance floor 0.001, 9,999 permutation count, two-sided absolute extremeness, seed 20260822, plus-one Monte Carlo p-value and BH family of exactly five ACZ raw p-values are prospectively governed study/computational choices. The paper uses `floor(n^(1/3))` and a 0.001 truncation in its simulations, but its theorem permits a class of asymptotically admissible bandwidth sequences and does not uniquely mandate those finite-sample choices. The realised bandwidth is 2 at n=24.

All five realised Sen slopes are negative, but none has BH-FDR-supported evidence of monotonic decline at alpha 0.05. A non-significant p-value is treated as non-rejection under the configured inferential procedure; it is not evidence that no temporal change occurred. Trend estimates and inference are observational and are not interpreted causally.

## RQ3 — cross-product observability

All paired district-months first enter the four-state VIIRS/MCD64A1 descriptive correspondence. The primary regression then conditions on VIIRS-positive district-months. The outcome is MCD64A1 absence versus presence. The continuous model terms are configured, not hard-coded: VIIRS detection count and mean FRP are focal log2 predictors, and fixed BA-2012 burnable area is a log2 adjustment. Month, year and ACZ are configured categorical adjustments with configured reference levels. Active-fire days and MODIS active-fire co-detection are excluded from the final model.

The estimator is Firth-type penalised binomial-logit GEE with district clusters, fixed working independence and Morel–Bokossa–Neerchal corrected cluster covariance. Coefficient inference uses standard-normal Wald tests and intervals. VIF is a diagnostic on the final continuous predictor set and has no deletion authority. Standardised probabilities use observed-covariate predictive standardisation at configured focal-predictor quantiles.

## Secondary SaTScan analysis

MCD64A1 uses retrospective space-time discrete Poisson scanning with burned-pixel cases and fixed BA-2001 exposure. VIIRS uses retrospective space-time permutation scanning with no exposure. Shared scientific settings are supplied by configuration: circular spatial windows, high clusters only, 50% maximum spatial size, 12-month maximum temporal size, 999 Monte Carlo replications, alpha 0.05 and hierarchical geographically non-overlapping secondary clusters. Cluster reporting uses the configured hierarchical geographically non-overlapping rule. Coordinates use the governed point-on-surface/inside-polygon authority in the configured CRS.

SaTScan execution remains an external boundary. The project must bind exact executable/version and parameter/input hashes before cluster claims are accepted. No undocumented user-defined random-seed parameter is invented. The notebook does not execute SaTScan: 04-01 generates deterministic interfaces, while 04-02 optionally validates both external result families together. No supplied result families yields `EXTERNAL_RESULTS_REQUIRED`; two complete valid families yields `RESULTS_VALIDATED`; partial or invalid material fails closed. Validated T3/S6 sources and the F6 recurrence source are run-local only. F6 maps the number of distinct validated significant clusters containing each eligible district and adds no inferential rule.
