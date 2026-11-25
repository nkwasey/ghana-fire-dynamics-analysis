# Burned area CSV data dictionary

One row represents one unit and one month. The key is `(ba_domain, level, unit_id, yyyymm)`; require uniqueness across combined files. The selector contains 69 base and diagnostic fields in one CSV; retain the diagnostics. Blank numerical cells mean undefined or withheld. They are distinct from numeric zero.

Missing or multiple collection images block the requested action before row/task creation. A successful output row records one admitted image, not a guarantee that pixel-level QA or BurnDate is available. Source failures must be retained in the run log.

`ba_status` concerns primary-result admission; `ba_coverage_status` describes evidence **inside the known union** and does not override an unresolved-domain status. Full evidence with shortening does not mean the full month was reliably mapped.

| Field | Unit / type | Meaning |
|---|---|---|
| `run_id` | text | Client-generated UTC time-stamped identifier shared by one row-collection construction; not guaranteed unique across near-simultaneous calls and not a permanent source or file identifier. |
| `schema_version` | text | Literal `rp1_ba_c3_extended_v2`. |
| `level` | text | acz or district. |
| `unit_id` | text | Canonical zone_id or dist_id from the selected asset. |
| `unit_code` | text | zone_code for ACZ; dist_code for district if present, otherwise blank. |
| `unit_name` | text | zone_name or dist_name. |
| `parent_level` | text | acz for a district; blank for ACZ. |
| `parent_id` | text | District parent zone_id; blank for ACZ. |
| `parent_code` | text | District parent zone_code; blank for ACZ. |
| `parent_name` | text | District parent zone_name; blank for ACZ. |
| `yyyymm` | integer | Calendar month key YYYYMM. |
| `year` | integer | Calendar year. |
| `month` | integer | Calendar month 1–12. |
| `modis_ba_km2` | km² | Accepted positive BA inside the fixed period union; blank on reduction/accounting failure, no centres, unresolved union, or source-pixel anomaly. |
| `modis_burned_pixel_count` | count | Accepted pixel-centre count inside the known union; blank whenever the primary burned area is withheld. |
| `modis_ba_any` | 0/1 | One when accepted BA is positive, zero otherwise; blank whenever the primary burned area is withheld. |
| `modis_burnable_km2_union` | km² | Fixed period-union area, withheld for a source-pixel anomaly as well as unresolved membership or failed reduction/accounting. The underlying fixed union does not change with month. |
| `modis_burnable_km2_annual` | km² | Exact-year eligible area; blank if annual eligibility is unresolved anywhere in the unit, there are no centres, or reduction/accounting fails. Otherwise retained even when the primary result is withheld for a source-pixel anomaly or unresolved union. |
| `modis_burned_frac_union` | fraction | Union numerator / union denominator; blank when the primary result is withheld or the denominator is zero. |
| `modis_burned_frac_annual` | ratio | Union numerator / exact-year annual denominator; not annual-mask-matched; can exceed 1. Blank if the primary numerator or annual denominator is unavailable, or the annual denominator is zero. |
| `modis_aoi_area_land_km2` | km² | Vector area of the selected unit intersected with the configured Ghana boundary; not a raster pixel-area sum or an independently verified land-only area. |
| `modis_zero_union_den_flag` | 0/1 | Union denominator equals zero; blank if the domain is unresolved, there are no centres, or reduction/accounting fails. Retained when the domain is resolved even if an anomaly withholds the primary result. |
| `modis_zero_annual_den_flag` | 0/1 | Annual denominator equals zero; blank if annual eligibility is unresolved, there are no centres, or reduction/accounting fails. |
| `ba_domain` | text | BA2001 or BA2012. |
| `ba_domain_start_year` | integer | First year in the fixed land-cover union. |
| `ba_domain_end_year` | integer | Last year in the fixed land-cover union, inclusive. |
| `ba_status` | text | ADMITTED, SOURCE_PIXEL_ANOMALY, DOMAIN_UNRESOLVED, ZERO_UNION_DENOMINATOR, NO_PIXEL_CENTRES, EMPTY_REDUCTION_UNRESOLVED, REDUCTION_INCOMPLETE, or ACCOUNTING_INCONSISTENCY. Source/grid preflight may block the action before any row exists. |
| `ba_coverage_status` | text | EMPTY_REDUCTION_UNRESOLVED, ACCOUNTING_INCONSISTENCY, REDUCTION_INCOMPLETE, NO_PIXEL_CENTRES, NO_KNOWN_UNION_PIXELS, NO_SUPPORTED_EVIDENCE, PARTIAL_EVIDENCE, FULL_EVIDENCE_WITH_SHORTENING, or FULL_EVIDENCE_NO_SHORTENING; always conditional on the known union. |
| `ba_source_status` | text | ADMITTED for emitted rows; missing or ambiguous collections block the action without an ordinary output row. |
| `ba_source_count` | integer | Exactly 1 for emitted rows. |
| `ba_source_index` | text | Admitted MCD64A1 system:index for this month. |
| `ba_lc_source_indexes` | text | Pipe-separated MCD12Q1 system:index values in ascending reference-year order. |
| `ba_product` | text | Earth Engine BA collection ID. |
| `ba_lc_product` | text | Earth Engine annual land-cover collection ID. |
| `ba_boundary_asset` | text | Selected ACZ or district Earth Engine asset path; path alone does not establish geometry version. |
| `ba_ghana_asset` | text | Ghana boundary Earth Engine asset path; path alone does not establish geometry version. |
| `ba_grid_crs` | text | Configured BA CRS. |
| `ba_grid_transform` | text | Comma-separated six-element BA affine transform. |
| `ba_reducer` | text | sum_unweighted_centroid. |
| `ba_sampled_pixel_count` | count | Independent number of grid-pixel centres inside the clipped unit, irrespective of eligibility; blank when reduction reference, derived-band completeness or accounting guard fails. |
| `ba_known_union_area_km2` | km² | Diagnostic area of known-eligible union, including when other membership is unresolved or an anomaly withholds primary output; not a substitute for the primary denominator. |
| `ba_known_union_burned_km2` | km² | Diagnostic accepted positive BA in the known union; may be partial when union membership is unresolved and is not a substitute for a withheld primary numerator. |
| `ba_domain_unresolved_km2` | km² | Area with no known-eligible year and one or more unknown years. |
| `ba_domain_excluded_km2` | km² | Area definitely excluded across all reference years. |
| `ba_any_lc_missing_year_km2` | km² | Unit area where LC_Type1 is masked in at least one reference year; can overlap other flags. |
| `ba_any_lw_missing_year_km2` | km² | Unit area where LW is masked in at least one reference year; can overlap other flags. |
| `ba_any_lc_invalid_year_km2` | km² | Unit area with unmasked LC_Type1 outside 1–17 in at least one reference year. |
| `ba_any_lw_invalid_year_km2` | km² | Unit area with unmasked LW outside 1–2 in at least one reference year. |
| `ba_annual_unknown_km2` | km² | Unit area where either annual LC_Type1 or LW is unavailable or has an invalid code in the row year. |
| `ba_state_qa_missing_km2` | km² | Exclusive state: union area with missing monthly QA. |
| `ba_state_burndate_masked_km2` | km² | Exclusive state: union area with QA present and BurnDate masked. |
| `ba_state_unsupported_km2` | km² | Exclusive state: both bands available but the positive/explicit-zero criteria not met; includes anomalous positives. |
| `ba_state_explicit_zero_km2` | km² | Exclusive state: available BurnDate 0, QA land and valid, special code 0; may have shortened period. |
| `ba_state_accepted_km2` | km² | Exclusive state: available BurnDate in 1–366, available QA with land and valid-data bits set and special-condition code 0, within the known union; a shortened mapping period does not reject it. |
| `ba_reason_qa_missing_km2` | km² | Overlapping reason: QA mask absent inside known union. |
| `ba_reason_burndate_masked_km2` | km² | Overlapping reason: BurnDate mask absent inside known union, including where QA is also absent. |
| `ba_reason_qa_nonland_km2` | km² | Overlapping reason: available QA indicates non-land inside the known union. |
| `ba_reason_qa_invalid_km2` | km² | Overlapping reason: available QA indicates insufficient valid data inside the known union. |
| `ba_reason_shortened_km2` | km² | Overlapping reason: available QA indicates shortened mapping inside known union, regardless of other state. |
| `ba_reason_special_km2` | km² | Overlapping reason: available QA has nonzero special code inside known union. |
| `ba_reason_positive_special_km2` | km² | Overlapping contradiction flag: available positive BurnDate and QA with nonzero special code. |
| `ba_reason_unexpected_burndate_km2` | km² | Overlapping reason: available BurnDate < 0 or > 366, regardless of QA availability. A positive > 366 is an anomaly only when QA is also available; it is never an accepted positive. |
| `ba_anomaly_area_km2` | km² | Known-union area of anomalous positives: both bands available, positive BurnDate and either BurnDate > 366 or nonzero QA special code. Evaluated regardless of QA land/valid bits; overlapping anomaly reasons count the pixel once. |
| `ba_anomaly_pixel_count` | count | Number of anomalous pixel centres in the known union, counted once per pixel. |
| `ba_shortened_km2` | km² | Accepted BA in known union with shortened mapping. |
| `ba_full_period_only_km2` | km² | Sensitivity: accepted BA in known union with shortened flag clear. |
| `ba_supported_area_km2` | km² | Known-union area in accepted-positive or explicit-zero evidence states. |
| `ba_supported_fraction` | fraction | Known-union accepted BA / supported area; blank when supported area is zero or there are no centres. Diagnostic conditioned on BurnDate availability; not a coverage fraction or unbiased observation when source masks select burns. |
| `ba_state_closure_km2` | km² | Sum of five exclusive evidence-state areas minus known-union area; expect approximately zero, allowing floating-point summation. |

## State and reason accounting

For every row that passes the reduction and accounting guards and has sampled centres, the five `ba_state_*` areas are mutually exclusive and sum to `ba_known_union_area_km2` within numerical summation tolerance. `ba_domain_excluded_km2 + ba_domain_unresolved_km2 + ba_known_union_area_km2` covers the sampled polygon area under the same grid and reducer. The `ba_reason_*` fields may overlap, including both missing QA and masked BurnDate, and must **not** be added as a partition.

`ba_known_union_*` and evidence diagnostics remain labelled known-union-only when the complete primary fields are withheld. A positive anomaly is unsupported evidence, not an accepted burn. A unit–month anomaly occurs if at least one such pixel is in its known union; pixels outside it do not trigger that unit. Status precedence is source/grid blocking, reduction and accounting failures, unresolved union, `SOURCE_PIXEL_ANOMALY`, zero union, then `ADMITTED`. Concurrent diagnostic flags are retained when evaluable. For an anomaly, primary burned area, count, any-burn indicator, union denominator, and both fractions are blank; the annual area and denominator flags remain independently guarded. A masked BurnDate contributes zero under the analytical scenario but remains unresolved visible evidence; the mask alone does not identify whether the original product classified the pixel as unburned or another state. `modis_burned_frac_annual` is an intentionally retained mixed-domain ratio, not an annual-domain-matched fraction.

## Raster bands

The viewer BA GeoTIFF contains `c3_union_eligible`, `c3_union_unresolved`, `c3_state`, `c3_accepted_pixel_evidence`, `c3_source_pixel_anomaly`, `c3_full_period_only`, `c3_reason_shortened`, `c3_reason_qa_missing`, `c3_reason_burndate_masked`, `c3_reason_qa_nonland`, `c3_reason_qa_invalid`, `c3_reason_special`, `c3_reason_positive_special`, `c3_reason_unexpected_burndate`, and `raw_BurnDate`. State codes: 0 known outside union; 1 unresolved domain; 2 QA unavailable; 3 BurnDate masked with QA present; 4 unsupported; 5 explicit product zero; 6 accepted positive. Reason masks can overlap. Bands are exported as Float32, with NoData -9999 used for masked raw values and outside the export geometry. An indicator value of zero is not evidence of no physical fire. Pixel evidence is not a unit-level admission result: consult the corresponding CSV status, including for unresolved or anomalous units. Raster export tasks do not themselves certify that a unit–month is admissible.

Missing or masked derived values trigger `REDUCTION_INCOMPLETE`; a missing independent centre reference triggers `EMPTY_REDUCTION_UNRESOLVED`; and failed numeric accounting triggers `ACCOUNTING_INCONSISTENCY`. These failure rows withhold raster-derived metrics including the sampled count. `NO_PIXEL_CENTRES` requires a present zero independent reference with no conflicting evidence. The failure row does not identify a particular failing band. Identifiers are asset identities, not immutable content hashes. 


## Interpreting visible evidence and aggregation

The support fraction is accepted positive area divided by accepted positive plus qualifying visible explicit-zero area; it is not observation coverage. Masked BurnDate values do not identify the original source value. Under the adopted primary rule, eligible pixels without accepted mapped burned evidence contribute zero after successful source processing and technical admission; original evidence states remain distinct. Guarded technical nulls and absent inputs must not become ordinary zeros, and no-supported records remain governed by the admitted scenario. CSV marginals cannot reconstruct raw masked values or every pixel-level QA-by-mask intersection. Additional source-value investigations and sensitivity analyses require a declared sampling design, assumptions, population changes and run-specific evidence. See `SOURCE_REPRESENTATION_AND_SENSITIVITY.md`.

Keep the 69 columns and row-level statuses during consolidation. Build an expected domain-unit-month inventory; distinguish absent files, withheld values, valid zero-contribution results and observed product states. The fixed-union denominator repeats across months and must not be summed. A sum of monthly burned area is cumulative mapped monthly area, not automatically a unique annual footprint. The fixed unions for BA2001 and BA2012 differ and must not be treated as identical support. See `EXPORT_LAYOUT.md` and the project consolidation guide for the admitted handoff.


## Annual land-cover evidence outside a fixed union period

The configured delivery contains the 69 required fields described above.
`ba_annual_lc_source_index` is optional companion evidence for observations
whose year lies outside the selected fixed union-building interval. When such
an observation is admitted, this field must identify the separately checked
annual land-cover source. It does not alter `ba_lc_source_indexes`, which
continues to record the complete fixed-union source list. Preserve the optional
field when present; it is not a reason to rewrite the retained 2001–2024 CSVs.
An observation-year extension requires complete source preflight and validation,
not only a widened date control. See
[study configuration](../../../../docs/STUDY_CONFIGURATION.md).
