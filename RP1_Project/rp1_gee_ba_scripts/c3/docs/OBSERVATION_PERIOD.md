# Observation periods and fixed analytical support

The current study observes January 2001 to December 2024. BA2001 uses the fixed
2001–2024 land-cover eligibility union. BA2012 uses a separate fixed 2012–2024
union and has observations from 2012. These support periods define the spatial
denominators. They are independent of the years selected for viewing or export.

The existing 370 annual CSV exports remain valid inputs for the current period.
Their source values, 69 required columns and fixed support definitions are
retained unchanged.

## Extending observations

The shared Earth Engine configuration contains `C3.observationStartYear` and
`C3.observationEndYear`. Change these observation settings for a different study
period, using complete annual observations. Rebuild the standalone programs
with `python build.py`, then use the viewer or exporter as described in the main
instructions. The fixed union definitions remain unchanged.

A requested period is accepted only after source preflight finds exactly one
monthly MCD64A1 image for each selected month, exactly one MCD12Q1 image for each
fixed union year and each additional observed year, and the required source
identities and projections. Missing, ambiguous or inaccessible sources block
the result or task. A calendar extension does not establish that these products
are already available. Complete the external Earth Engine checks for the new
delivery and retain its source evidence.

For an observed year outside the selected fixed union, the exporter appends
`ba_annual_lc_source_index` after the 69 required fields. This text identifies the
admitted MCD12Q1 image used for that year's annual eligibility denominator. The
fixed `ba_lc_source_indexes` field continues to identify only the unchanged
union-period sources. The additional field is required for out-of-union years;
for the declared MCD12Q1 Collection 6.1 product it must be `YYYY_01_01` for the
observed year, so a stale annual source cannot satisfy the new calendar.
If supplied for a union year, it must match that year's fixed-union source.

Annual eligibility in a later year can exceed the fixed union's area. It must
still lie within the sampled grid area. The burned-area numerator and primary
fixed-union denominator continue to use the same fixed support. Changing the
support itself requires a separately declared scientific method and new source
validation; it is not an automatic effect of changing observation dates.

## Local validation

From this directory, check a later annual file with the explicitly declared
observation period, for example:

```bash
python tools/check_extended_csv.py PATH_TO_2025_CSV --observation-start-year 2001 --observation-end-year 2025
```

These are structural and arithmetic checks. They do not verify remote geometry
identity or physical fire accuracy. The root workflow additionally verifies the
complete declared annual source matrix, geography, input hashes and actual
merger compatibility before publishing a handoff.

The standalone consolidator accepts `--observation-start-year` and
`--observation-end-year` to declare a complete production calendar independently
of fixed support. `--start-year` and `--end-year` select the annual files for the
delivery. Full production scope requires both domains, both reporting levels,
all five zones and every year in the declared observation calendar. A smaller
selection remains an explicit inspection scope.

Recognised annual files outside a selected delivery are inventoried as
`NOT_CONSUMED` and never enter the published source bundle. They do not satisfy
missing source requirements in the selected calendar.
