# Scientific integration test references

The selected generated handoff is the input authority for integration tests.
Research populations, fitted coefficients, cluster counts and figure hashes are
derived from those inputs. They are not prescribed results or input identities.

The generated-input checks use the following independently computed references:

- Excluded district identities are checked against the selected panel's
  nonpositive primary denominators in the configured population windows.
- Reconciliation uses the declared field-specific absolute and relative bounds.
- Queen islands are checked with pairwise polygon-boundary intersections on the
  retained population, independently of the indexed production neighbour graph.
- Crosswalk lineage is checked against the SHA-256 of the selected staged CSV.
- RQ3 outcomes and all-one/all-zero clusters are recomputed from the selected raw
  district panel; monthly zero/positive counts are checked for all twelve months.
- Predictor VIFs are checked against the inverse correlation matrix of raw
  log-transformed input predictors as well as the realized design matrix.

These are executable consistency and method tests. They do not accept a source
profile scientifically or prove the identity of live exports. Mathematical examples
under `reference_methods` retain their exact expected values and tolerances.

Generated-run integration checks require an explicit `RP1_ANALYSIS_TEST_RUN` base
identifier. A single available family is never selected implicitly. Its `_pub`,
`_sec` and `_close` members must pass the production current-source run validator;
RQ4 references additionally require `RESULTS_VALIDATED` external results. Primary
sources are loaded through `primary_run_id=<ID>_pub` from the run-local publication
manifest.

An unselected clean distribution deliberately skips only generated-result checks;
configuration, CLI, synthetic and independently data-bound checks retain their
own prerequisites. A selected missing/corrupt/incompatible run is an error, not a
skip. Validate the selected run under its recorded source identity. These tests
check implementation consistency.
Run invasive regression fixtures on disposable copies, preserving operational runs.
