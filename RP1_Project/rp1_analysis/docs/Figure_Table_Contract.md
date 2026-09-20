# Figure and table contract

## Main manuscript

- **T1** ACZ fire-regime summary.
- **T2** RQ3 marginal model: two focal predictors plus fixed burnable-area adjustment.
- **T3** significant SaTScan cluster summary; requires genuine validated external output.
- **Figure 1** study-area / analytical-geography figure supplied externally by the author. It is not generated, stored as a required runtime asset, or validated by image path/SHA.
- **F2** direct ACZ and district long-run mapped burned-area rates (1 × 2).
- **F3** RQ1 seasonality and spatial organisation: wide ACZ seasonality above district departure and FDR-supported Local Moran.
- **F4** five ACZ annual fixed-support rate trajectories with Sen slope, raw Romano–Tirlea permutation p and BH q, plus one auxiliary shared graphical-key cell.
- **F5** RQ3 mismatch geography, four-state correspondence and exactly two focal adjusted PGEE effects.
- **F6** recurrence of validated significant SaTScan membership for MCD64A1 and VIIRS. Each eligible district is coloured by the number of distinct validated significant clusters containing it for that product. Eligible zero-count districts are valid zeroes; excluded/unsupported districts remain excluded. F6 is descriptive and requires `RESULTS_VALIDATED`.

## Supplement

- **S1** populations and eligibility.
- **S2** district RQ1 metrics.
- **S3** the single national Global Moran authority plus Local Moran statistics/classes.
- **S4** all 24 annual RQ2 rates for each ACZ with studentized-permutation quantities.
- **S5** RQ3 correspondence, diagnostics, full coefficients and standardised probabilities.
- **S6** complete SaTScan results, memberships, parameters and coordinate provenance; requires genuine validated external output.
- **Figure S1** full district seasonal diagnostics: wide district × month heatmap above circular-mean timing and resultant-length diagnostics.

Every generated figure has a governed source-data CSV and manifest and uses the configured 20 × 15 cm landscape canvas. Section 90 always runs. With no external result families, T3/F6/S6 remain explicitly unavailable under `EXTERNAL_RESULTS_REQUIRED`; with both complete valid result families they are generated from run-local sources under `RESULTS_VALIDATED`; partial or invalid external material fails closed. Reference fixtures are test artefacts only and never scientific Ghana results.

`T_RESULT_REGISTRY.csv` records semantic result-to-presentation provenance. A `source_figure` is populated only when that figure actually consumes/displays the registered result. The national Global Moran result is sourced to S3 and has no manuscript `source_figure`, because no generated manuscript figure directly displays the Global Moran statistic.
