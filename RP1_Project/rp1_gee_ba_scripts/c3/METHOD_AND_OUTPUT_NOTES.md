# Method and output notes

## Domain, temporal support, and grid

The applications use MCD64A1 Collection 6.1 monthly BurnDate and QA, and MCD12Q1 Collection 6.1 annual `LC_Type1` and `LW`. They construct one fixed eligibility union for 2001–2024 and another for 2012–2024. A pixel is eligible in an annual image when both inputs are available and valid, `LW = 2`, and its IGBP class is in `{1,2,3,4,5,6,7,8,9,10,12,14}`. If at least one year is known eligible, the pixel belongs to the union. If no year is known eligible but at least one year is unknown, union membership is unresolved. Otherwise the pixel is excluded.

Both the primary burned-area numerator and union denominator use the relevant fixed union. Reducers use the configured native MCD64A1 grid and an unweighted centroid-in-polygon rule. BA source `BurnDate` and QA projection metadata are checked during source preflight; annual LC/LW projections are reported and categorical sampling uses Earth Engine's default nearest-neighbour behavior. A single monthly BA image and a single land-cover image for each required union year must be admitted. Metadata checks do not establish classification accuracy or full pixelwise support.

## Evidence and anomaly rule

A positive is accepted when BurnDate and QA are available, BurnDate is 1–366, QA indicates land and sufficient valid data, and the QA special-condition code is zero. A shortened mapping period does not itself reject an otherwise accepted positive; it is recorded separately. No extra month-of-year or leap-year rejection is applied.

An **anomalous positive** is a pixel for which both BurnDate and QA are available, BurnDate is greater than zero, and either BurnDate is greater than 366 or the QA special-condition code (bits 5–7) is nonzero. This check applies irrespective of the QA land and valid-data bits. An anomaly in the unit's known union triggers `SOURCE_PIXEL_ANOMALY`, subject to higher-priority guards, and the primary unit–month result is withheld. An anomaly outside the known union does not trigger this unit-level guard. The overlapping reason flags remain diagnostic and are not mutually exclusive; anomaly pixels belong to the unsupported evidence state rather than the accepted state.

An unresolved or unsupported observation does not prove that the land was physically unburned. The study's primary numerator assigns zero contribution to unaccepted evidence unless a higher-level guard withholds the result. Missing QA, masked BurnDate, available but unsupported evidence, explicit qualifying zero, and accepted positive form the five mutually exclusive evidence states within the known union. Their areas are checked for closure against that union. Additional reason fields overlap and must not be added as if they were exclusive states.

## Status and principal fields

The CSV selector contains 69 fields, including the two anomaly diagnostics.

Source/grid admission and reduction or accounting failures take precedence over unresolved union eligibility; unresolved union takes precedence over `SOURCE_PIXEL_ANOMALY`; an anomaly takes precedence over a resolved zero union. Review the specific status and all accompanying flags rather than relying on a zero numerator alone. Depending on the failure, an action may be blocked before a row or task is created.

| Output | Meaning and important qualification |
|---|---|
| `modis_ba_km2` | Accepted burned area in the fixed union, when the unit–month primary result is usable. |
| `modis_burnable_km2_union` | Fixed eligible union area, when the primary result is usable. It is withheld in an anomalous unit–month for an unambiguous primary output; the underlying union itself does not change. |
| `modis_burned_frac_union` | Primary burned area divided by the union area, only when the result is usable and the denominator is positive. |
| `modis_burnable_km2_annual` | Eligible area in the selected year, retained when its own availability/uncertainty checks allow it. |
| `modis_burned_frac_annual` | Union-based numerator divided by the annual eligible area, when usable and positive. This mixed-domain ratio can exceed 1 and is not a within-annual-domain burned proportion. |
| `ba_known_union_area_km2`, `ba_known_union_burned_km2` | Diagnostic values for the known portion. They are not substitutes for withheld primary values. |
| `ba_anomaly_area_km2`, `ba_anomaly_pixel_count` | Area and count of anomalous positives inside the known union; the union of anomaly reasons is counted once per pixel. |
| `ba_reason_*` | Potentially overlapping diagnostic areas. Special-condition and unexpected-date reasons are distinct from mutually exclusive evidence states. |
| `ba_state_*_km2`, `ba_state_closure_km2` | The five evidence-state areas and their closure diagnostic. |
| `ba_supported_fraction` | Accepted positive area divided by accepted positive plus qualifying explicit-zero area, when that restricted denominator is positive. It is not overall observation coverage or the fraction of the union burned. |

For an anomalous unit–month, the primary burned area, accepted count and any-burn indicator, union denominator, and both burned fractions are withheld. The annual denominator is retained when its own guard permits, as are separately labelled diagnostics. A resolved zero union has a zero denominator and a zero numerator over the empty union, with its fraction blank. This does not establish that no fire occurred across the geographic unit. A blank fraction is undefined or withheld; it must not be converted to zero without an explicitly justified downstream rule.

The annual ratio field preserves its mixed-domain meaning and should not be presented as the fraction burned within annually eligible land. Support and reason diagnostics describe product evidence, not independent verification of actual fires or land-cover accuracy.

The fixed union depends on the selected full reference period and can include a pixel in years when its annual class is ineligible. Consequently, the union-based monthly numerator is not restricted to that month's year-specific eligible land. The two unions use different year sets, so overlapping months from BA2001 and BA2012 need not have the same numerator or denominator. Analyses comparing domains must account for this difference. A fixed union is a retrospective study-domain choice; it is not evidence of contemporaneous burnability in every year.

Report the distribution of evidence states for each new run. A scenario zero does not establish physical absence of fire or full coverage. See `VERIFICATION.md` for checks.

## Source representation and analysis interpretation

A masked Earth Engine BurnDate does not, by itself, identify the original product value or prove that the source lacked valid observations. The adopted primary rule assigns native pixel area to accepted mapped burning and zero contribution to other pixels within the known eligible domain after successful source processing and technical admission. This zero contribution is a study-scenario value, not a claim that a masked raw source value was an explicit product zero or that physical absence of fire was established. Original masks/evidence remain recorded and technical guards continue to withhold failed or unresolved primary results.

The primary zero-contribution rule and the scope of additional source-representation and sensitivity checks are described in `docs/SOURCE_REPRESENTATION_AND_SENSITIVITY.md`. Preserve all 69 fields and provenance in downstream processing.

Summing monthly burned areas produces cumulative mapped monthly area and may count a pixel in multiple months; it is not necessarily unique annual footprint. Do not sum the fixed denominator across months or average zone fractions without appropriate weighting. Record missing and technically withheld rows separately from scenario zeros.
