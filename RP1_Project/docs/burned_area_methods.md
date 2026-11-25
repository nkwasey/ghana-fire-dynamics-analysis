# Burned-area methods and interpretation

## c3 source measurement

Monthly burned area uses MODIS MCD64A1 Collection 6.1 BurnDate and QA on the
declared native grid, with unweighted centroid-in-polygon reduction. Two fixed
eligibility unions use MCD12Q1 Collection 6.1 reference years 2001–2024 (BA2001)
and 2012–2024 (BA2012). Annual eligibility requires available valid LC/LW,
`LW=2`, and IGBP classes 1–10, 12 or 14. A pixel eligible in any reference year
belongs to that union; with no known-eligible year and at least one unknown year,
membership is unresolved. Export-year subsets do not shorten these unions.

A positive is accepted inside the selected union when BurnDate and QA are
available, BurnDate is 1–366, and QA indicates land, valid data and special code
zero. Qualifying shortened-mapping positives remain accepted; their area is
reported in `ba_shortened_km2`, with `ba_full_period_only_km2` as a separate
diagnostic. No extra month-of-year or leap-year date rejection is imposed.
An available positive above 366 or with nonzero special code is an anomaly,
regardless of land/valid bits; an anomaly in the known union can withhold the
whole primary unit-month under the documented precedence rules.

The primary numerator assigns zero contribution to unaccepted evidence only
where higher result guards admit the unit-month. This adopted scenario does
not establish physically unburned land. `ADMITTED` means the result guards
passed, not complete observation. Source/grid preflight can block an export
before any row exists. Reduction/accounting failure, no centres, unresolved
membership and source anomalies retain their specific statuses and nulls.
Independently guarded annual fields and denominator flags may remain defined.

## Interpretation and aggregation

The five exclusive evidence-state areas partition the known union. Overlapping
reason areas must not be summed as a partition. `ba_supported_fraction` is
accepted-positive area divided by accepted-positive plus qualifying explicit-zero
area; it is conditional visible evidence, not observation coverage. Source masks
alone cannot reconstruct raw unburned, unmapped or water states. Keep all 69
source fields and provenance in the mandatory companion and report admitted,
withheld and evidence-class distributions by zone, season and year.

Primary `modis_burned_frac_union` pairs the selected union numerator and fixed
denominator. BA2001 and BA2012 can differ in both numerator and denominator in
overlapping months and are not independent samples. The secondary
`modis_burned_frac_annual` divides the union numerator by exact-year eligible
area, can exceed one, and is not the fraction burned within the annual mask.
`modis_aoi_area_land_km2` is Ghana-clipped vector area, not independently verified
land-only area or raster-area sum.

A resolved zero union gives zero numerator/denominator and an undefined fraction;
it says nothing about fires elsewhere in the geographic unit. A blank withheld
primary value or absent file/key cannot become zero. Do not replace a withheld
primary value with a known-union diagnostic. Summing monthly BA gives cumulative
mapped monthly area and may count a location repeatedly; it is not necessarily
unique annual burned footprint. Do not sum repeated fixed denominators.

Retain the primary scenario. Evidence-restricted or alternative-source
sensitivities need explicit rules, lost-population accounting and separate
interpretation; dropping low-evidence rows may select positive outcomes. Report
the analyses actually performed. Local software/fixture acceptance does not
establish full-period source support, remote geometry equivalence, product
accuracy or physical-fire absence. See the pinned c3 source-representation
protocol and verification record for bounded evidence and remaining work.

## Dataset citations

Friedl, M., & Sulla-Menashe, D. (2022). *MODIS/Terra+Aqua land cover type yearly L3 global 500m SIN grid V061* [Data set]. NASA Land Processes Distributed Active Archive Center. https://doi.org/10.5067/MODIS/MCD12Q1.061

Giglio, L., Justice, C., Boschetti, L., & Roy, D. (2021). *MODIS/Terra+Aqua burned area monthly L3 global 500m SIN grid V061* [Data set]. NASA Land Processes Distributed Active Archive Center. https://doi.org/10.5067/MODIS/MCD64A1.061

Giglio, L., Boschetti, L., Roy, D., Hoffmann, A. A., Humber, M., & Hall, J. V. (2021). *Collection 6.1 MODIS burned area product user's guide* (Version 1.0). NASA MODIS Land. https://modis-land.gsfc.nasa.gov/pdf/MODIS_C61_BA_User_Guide_1.0.pdf
