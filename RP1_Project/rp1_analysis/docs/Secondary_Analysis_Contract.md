# Secondary SaTScan contract

The secondary analysis asks where and when MCD64A1 mapped burned-surface events and VIIRS active-fire detections form unusually concentrated district-level space-time patterns. It is descriptive and does not validate one sensor against another or identify causal mechanisms.

## MCD64A1
Retrospective space-time discrete Poisson; January 2001–December 2024; 250 districts; cases `modis_burned_pixel_count_ba2001`; population/exposure `modis_burnable_km2_union_ba2001`; circular maximum 50% of exposure; temporal window 1–12 months; 999 Monte Carlo replications; high-rate clusters; hierarchical geographically non-overlapping reporting.

## VIIRS
Retrospective space-time permutation; February 2012–December 2024; 249 paired-supported districts; cases `viirs_det_primary`; no population/exposure; circular maximum 50% of cases; temporal window 1–12 months; 999 Monte Carlo replications; high-count clusters; hierarchical geographically non-overlapping reporting.

Coordinates use EPSG:32630 polygon centroids when covered by the district geometry and otherwise point-on-surface. The notebook does not execute SaTScan.

## 04-01 deterministic external interface

Section 04-01 always generates model-specific SaTScan inputs and parameter files beneath the current secondary run. MCD64A1 receives `.cas`, `.geo`, `.pop` and `.prm`; VIIRS receives `.cas`, `.geo` and `.prm` with no population file. The `.prm` `ResultsFile` entry is the naming authority for genuine external results.

### Monthly temporal-boundary representation

The scientific study windows are owned by `analysis_contract.yml` as monthly periods. The SaTScan interface layer converts only their representation: `StartDate` is the first calendar day of the configured starting month and `EndDate` is the final calendar day of the configured ending month. Month length is calendar-aware, so February resolves to 28 or 29 days as appropriate. For the current configuration the parameter bounds are `StartDate=2001/1/1`, `EndDate=2024/12/31` for MCD64A1 and `StartDate=2012/2/1`, `EndDate=2024/12/31` for VIIRS. No study month is selected in Python.

For a configured `ResultsFile=<prefix>`, the core result family is exactly:

- `<prefix>` — the extensionless human-readable main report written by SaTScan;
- `<prefix>.col.txt` — cluster output;
- `<prefix>.gis.txt` — cluster-membership output.

SaTScan may write auxiliary files such as `.rr.txt`, `.llr.txt` and `.sci.txt`. They are not part of the core completeness gate unless a future prospectively governed scientific contract explicitly adds them. The integration contract does **not** require a duplicate `<prefix>.txt` and does **not** require or generate an external `<prefix>.provenance.json` sidecar.

## 04-02 optional result validation and integration

The package-owned integration API applies the following fail-closed states:

- Neither governed result family has genuine material: `EXTERNAL_RESULTS_REQUIRED`. This is a normal external boundary. No SaTScan-dependent output is fabricated.
- Only one governed model has result material: error; fail closed.
- A governed model has only part of the core family (`ResultsFile`, `.col.txt`, `.gis.txt`): error; fail closed.
- Both result families are complete: validate both; return `RESULTS_VALIDATED` only if every check passes.
- Any malformed, stale, wrong-model, wrong-period, wrong-location, path-escaping or otherwise invalid family: error; fail closed. Invalid material is never silently downgraded to `EXTERNAL_RESULTS_REQUIRED`.

Validation is bound to the current 04-01 run. The package verifies run-relative path containment; the exact `.prm` hash; exact `.cas` and `.geo` hashes; the MCD `.pop` hash; absence of a VIIRS population/exposure authority; the `.prm` `ResultsFile` value; staleness relative to current parameter/input authorities; successful report completion; SaTScan version 10.3.3; the governed model and study period; parseable `.col` and `.gis` output; cluster/membership consistency; governed location and centroid IDs; temporal support and maximum cluster duration; and non-Poisson relative-risk semantics for the VIIRS space-time permutation model.

Exact locally installed SaTScan executable path/version/SHA qualification remains a separate formal local-testing item. The package may record run-local validation metadata after successful result validation, including current input and result hashes and the version reported by the genuine result. Such metadata is Python-generated validation evidence, not an externally observed provenance sidecar and not a substitute for executable-SHA qualification.

Accepted live publication sources are written only below `out/runs/<run>_sec/04_secondary_concentration/publication_sources/`. Normal repository authority directories are never mutated by live integration.

## Section 90 continuation

After `RESULTS_VALIDATED`, Section 90 generates T3, recurrence-based F6 and S6 from the validated run-local publication sources. If the state remains `EXTERNAL_RESULTS_REQUIRED`, those SaTScan-dependent products remain deferred. The notebook remains thin orchestration and contains no parser, recovery or external-execution implementation.

## Recurrence presentation

F6 is a descriptive projection derived from validated significant cluster membership. For each product and eligible district, `significant_cluster_count` is the number of distinct significant cluster IDs containing that district. Eligible districts with no memberships are valid zeroes. Excluded/unsupported districts have no plotted recurrence value and retain the governed excluded style. The recurrence count is not a new p-value, relative risk, maximum likelihood-ratio statistic, permanent-hotspot label or simultaneous nationwide cluster state.
