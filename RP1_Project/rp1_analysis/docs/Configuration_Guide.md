# Configuration guide

The analysis uses five executable YAML contracts under `config/`. They are loaded as one configuration bundle and hashed individually and collectively.

1. `analysis_contract.yml` owns study populations, windows, field roles and scientific settings.
2. `data_schema_contract.yml` owns physical/semantic schemas, keys, support rules and geometry relationships.
3. `method_authorities.yml` owns qualified implementation identities and method status.
4. `output_contract.yml` owns the three main tables, 25 supplementary tables, four QA tables and their required sources. T3 and S6 require both validated primary SaTScan scans. S21-S24 require the validated restricted MCD64A1 scan. S25 records the two district identities linked to the manuscript proof and their admitted burned-area results.
5. `figure_contract.yml` owns F2–F6 and `FS1`–`FS4` (Supplementary Figures S1–S4). It defines semantic sources, panel placement and rendering policy. The author supplies manuscript Figure 1 separately. F6 uses `cluster_recurrence_source` to display the number of distinct validated significant clusters containing each district, with separate styles for zero recurrence and excluded support. Principal composites use the 20 × 15 cm landscape physical-size role. `panel_count` counts data panels. F4's auxiliary cell holds the shared legend and ACZ statistics table. The notebook figures rely on manuscript captions for titles. Standalone presentation figures use the titles from the presentation export catalogue.

## RQ2 execution ownership and provenance

`analysis_contract.yml` is the sole executable owner of the strict RQ2 admissibility rule. It requires distinct realised annual observations and specifies `fail_closed` on ties. `method_authorities.yml` documents method identity, reference scope and parameter provenance; it does not define a second executable tie policy. Generic Python reads and validates the configured rule.

For RQ2, the global Mann–Kendall rank statistic, studentisation principle, long-run variance construction and per-permutation re-studentisation are method-derived. The exact finite-sample bandwidth rule, variance floor, 9,999-permutation count, two-sided alternative, seed, plus-one Monte Carlo p-value and five-member BH family are governed study/computational choices. This distinction is validated by configuration and documentation-parity tests.

Scientific values should be changed only through the relevant contract and must pass configuration and method-authority tests. Runtime code may enforce structural compatibility but must not maintain competing Ghana-specific defaults.

All public workflows use repository-relative or contract-driven paths.

Optional external-result integration does not change scientific configuration. Deterministic SaTScan inputs remain configuration-owned in 04-01; 04-02 validates external material and writes any accepted publication sources only beneath the current run. Repository authority directories are immutable during notebook execution.

## Source-qualification configuration

`qualification_contract.yml` is the separate operational authority for constructing a clean source tree. It does not contain scientific parameters and is not part of the five-contract scientific configuration aggregate. The contract enumerates governed repository roots, the four package/source mappings, generated-artifact exclusions, external projection/evidence rules and import-routing modes.

Configured paths are repository-relative. Absolute paths, parent traversal and governed symlinks are rejected. The clean projection is created outside the operational repository and is rebuilt from a pre-copy path/size/SHA-256 inventory. The projected tree must match that inventory exactly; missing, changed or unexpected files fail qualification. Configured installation/runtime residue such as `*.egg-info`, `__pycache__`, `*.pyc`, `.pytest_cache`, `build`, `dist` and `out` is recorded as excluded rather than deleted from the operational checkout.

Projected-source execution uses an explicit `PYTHONPATH` containing the projected source roots for `rp1_analysis_v1`, `mv_firms_panels`, `geo_data_prep` and `ghana_fire_archive`. An import-origin probe must confirm that all four modules resolve from those projected roots before projected qualification is accepted.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.



## Study period and source support

The root `study` declaration controls the selected observation period and
`analysis_overlap_start_yyyymm` controls the first paired analysis month.
The configured study is 2001–2024; its paired monthly window starts in
February 2012 and its complete-year paired window in 2013. Generated
contracts bind those declared periods to validated input coverage. RQ2 series
length derives from complete study years; eligible/model populations remain
input-derived. Selecting dates does not redefine BA2001/BA2012 fixed unions.
See [study configuration](../../../docs/STUDY_CONFIGURATION.md) for future
periods and the additional source-evidence requirements.
