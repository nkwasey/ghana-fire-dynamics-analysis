# Method register

Methods are declared in the executable configuration and implemented by the analysis package. Numerical tests verify specified calculations; source admission, scientific interpretation and external-engine execution require additional evidence.

- RQ1: fixed-support burned-area summaries, circular seasonality, Queen-contiguity spatial inference and conditional Local Moran inference. The Local Moran two-sided rule is documented in `Local_Moran_Two_Sided.md`.
- RQ2: Sen slope and Romano–Tirlea studentized global Mann–Kendall permutation inference. The configured bandwidth, variance floor, simulation count, seed and multiplicity family are study choices; inspect realised data and assumptions.
- RQ3: Firth-type penalised GEE, Morel–Bokossa–Neerchal covariance adjustment, standard-normal Wald inference and covariate standardisation. FRP is the mean of eligible UTC daily maxima using nominal/high confidence, not a mean across detections or calendar days.
- Secondary analysis: model-specific discrete Poisson and case-only space–time permutation scans with hierarchical non-overlapping reporting, specifically hierarchical geographically non-overlapping cluster selection. Genuine external SaTScan execution and input/output reconciliation are required.

Methods documentation describes current behavior. It does not certify source lineage or replace run-specific manifests, statistical diagnostics or scientific review.

The c3 source measurement and admission authority is `c3_methods_v1_schema_v2`
with CSV schema `rp1_ba_c3_extended_v2` and local policy
`c3_preserve_admission_v1`. This revises the source/scenario contract while
retaining the statistical estimators listed above. Original c3 evidence,
scenario zeros and guarded nulls remain bound to the selected input manifest;
an editorial document hash cannot certify that source change.
