# Configuration guide

RP1 Analysis v1.2.3 uses five executable YAML contracts under `config/`. They are loaded as one configuration bundle and hashed individually and collectively.

1. `analysis_contract.yml` owns study populations, windows, field roles and scientific settings.
2. `data_schema_contract.yml` owns physical/semantic schemas, keys, support rules and geometry relationships.
3. `method_authorities.yml` owns qualified implementation identities and method status.
4. `output_contract.yml` owns table identities, schemas, roles and external-result-dependent availability.
5. `figure_contract.yml` owns generated F2–F6 and Figure S1 panel identities, semantic presentation sources, GridSpec placement and rendering policy. Manuscript Figure 1 is author supplied and is not a runtime asset. F6 consumes the semantic `cluster_recurrence_source` and displays distinct validated significant-cluster membership counts with the configured sequential scale and support-state styling. Generated principal composites use the governed 20 × 15 cm landscape physical-size role; `panel_count` counts scientific/data panels only and excludes configured auxiliary cells such as F4's shared graphical key.

## RQ2 execution ownership and provenance

`analysis_contract.yml` is the sole executable owner of the strict RQ2 admissibility rule. It requires distinct realised annual observations and specifies `fail_closed` on ties. `method_authorities.yml` documents method identity, reference scope and parameter provenance; it does not define a second executable tie policy. Generic Python reads and validates the configured rule.

For RQ2, the global Mann–Kendall rank statistic, studentisation principle, long-run variance construction and per-permutation re-studentisation are method-derived. The exact finite-sample bandwidth rule, variance floor, 9,999-permutation count, two-sided alternative, seed, plus-one Monte Carlo p-value and five-member BH family are governed study/computational choices. This distinction is validated by configuration and documentation-parity tests.

Scientific values should be changed only through the relevant contract and must pass configuration and method-authority tests. Runtime code may enforce structural compatibility but must not maintain competing Ghana-specific defaults.

All public workflows use repository-relative or contract-driven paths.

Optional external-result integration does not change scientific configuration. Deterministic SaTScan inputs remain configuration-owned in 04-01; 04-02 validates external material and writes any accepted publication sources only beneath the current run. Repository authority directories are immutable during notebook execution.

## Source-qualification configuration

`qualification_contract.yml` is the separate operational authority for constructing a clean, release-equivalent source tree. It does not contain scientific parameters and is not part of the five-contract scientific configuration aggregate. The contract enumerates governed repository roots, the three package/source mappings, generated-artifact exclusions, external projection/evidence rules and import-routing modes.

Configured paths are repository-relative. Absolute paths, parent traversal and governed symlinks are rejected. The clean projection is created outside the operational repository and is rebuilt from a pre-copy path/size/SHA-256 inventory. The projected tree must match that inventory exactly; missing, changed or unexpected files fail qualification. Configured installation/runtime residue such as `*.egg-info`, `__pycache__`, `*.pyc`, `.pytest_cache`, `build`, `dist` and `out` is recorded as excluded rather than deleted from the operational checkout.

Projected-source execution uses an explicit `PYTHONPATH` containing the projected source roots for `rp1_analysis_v1`, `mv_firms_panels` and `geo_data_prep`. An import-origin probe must confirm that all three modules resolve from those projected roots before projected qualification is accepted.
