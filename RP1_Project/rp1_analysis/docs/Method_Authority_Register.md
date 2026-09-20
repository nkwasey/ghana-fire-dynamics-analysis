# Method authority register

The executable method identities are governed by `config/method_authorities.yml` together with `analysis_contract.yml`.

- RQ1: circular mean/resultant length; Gini; first-order Queen row-standardised weights; Global Moran permutation; Local Moran conditional permutation; BH-FDR.
- RQ2: Sen slope for effect magnitude plus Romano–Tirlea studentized global Mann–Kendall permutation inference. The global reference null is strict stationarity under the stated weak-dependence conditions. The strict route requires tie-free realised annual series and fails closed on ties. Method-derived components are the global rank statistic, studentisation, long-run-variance construction and re-studentisation of every permutation. Study/computational authorities are the exact `floor(n^(1/3))` finite-sample bandwidth rule, variance floor 0.001, 9,999 permutations, two-sided absolute tail, seed 20260822, plus-one Monte Carlo p-value and the five-ACZ BH family. The reference paper provides practical simulation context for `floor(n^(1/3))` and 0.001 but does not uniquely mandate them by theorem.
- RQ3: Firth-type penalised GEE, binomial-logit mean, district clusters, working independence, MBN covariance and standard-normal Wald inference. VIF is diagnostic only. Q25/Q75 standardised probabilities use predictive standardisation over the observed covariate distribution.
- Secondary: MCD64A1 discrete-Poisson SaTScan with fixed BA-2001 exposure and VIIRS space-time-permutation SaTScan without exposure; both use hierarchical non-overlapping cluster reporting.

The Local Moran conditional-permutation convention holds the focal standardised value fixed and samples other non-island standardised values without replacement according to the configured scheme.

Both space-time analyses use the registered hierarchical geographically non-overlapping cluster-reporting authority.

The current human-readable methods documents are stored under `docs/` and their exact DOCX/PDF byte identities are recorded in `data/authorities/methods_document_authority.json`. Updating that current documentation authority does not rewrite historical RQ run metadata: those run records remain immutable snapshots of the methods-document identity bound when the scientific authorities were materialised.
