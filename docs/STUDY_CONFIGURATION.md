# Study period, source support and fixed domains

The root workflow configuration declares the scientific observation period.
For this study, use `configs/workflow.json` with January 2001–December 2024.
Complete all five stages using the same configuration and an unused identifier,
such as `ghana_fire_study`. Configuration snapshots and source hashes bind
each run; a changed request needs a fresh run.

## Temporal declarations

| Setting under `study` | Meaning | Current value |
| --- | --- | --- |
| `start_yyyymm` | First study month, January of a complete year | `200101` |
| `end_yyyymm` | Last study month, December of a complete year | `202412` |
| `viirs_support_start_yyyymm` | Configured Suomi-NPP calendar support | `201201` |
| `ba2012_support_start_yyyymm` | BA2012 observation support start | `201201` |
| `analysis_overlap_start_yyyymm` | First paired monthly analysis month | `201202` |

Suomi-NPP source coverage starts on 20 January 2012. Its partial initial month
is recorded in source evidence. The monthly paired analysis begins in February
2012; complete-year paired analysis begins in 2013. Sensor support does not
guarantee a usable observation for every unit/month. Technical withholding,
missing source support and valid scenario zeros remain distinct.

The workflow propagates the declared study and sensor windows into Archive
acquisition and admission, active-fire processing, merger and analysis contracts.
Integrated acquisition derives its requested years from the root study settings;
the standalone Archive preset retains its independent year-selection settings.
Selected sensors and provider availability must cover the requested interval.
Expected annual counts, monthly spines, paired complete years and
time-dependent output names derive from the declared selection and admitted
source evidence. They must not be inferred solely from whichever rows happen
to be present.

## Fixed eligibility unions

BA2001 uses the 2001–2024 land-cover eligibility union and BA2012 uses the
2012–2024 union. Their domain fields and source-index lists describe these
fixed reference periods. The observation period and the years used to build a
fixed union are different declarations. Selecting fewer observations or
requesting later observations does not silently rebuild either union.

For the configured study, the retained delivery contains 240 BA2001 and 130
BA2012 annual CSVs: two levels, five zones and every supported year. Preserve
all 370 original files and their source identities. The consumed delivery is
validated against its explicit selected matrix, geography and source lock.
An incomplete pilot does not qualify a complete scientific handoff.

## Selecting another complete-year period

1. Copy the workflow configuration to a clearly named file and select an unused
   run identifier. Set the study bounds to January and December. Declare the
   paired analysis start consistently with actual sensor and burned-area support.
2. Review selected Archive sensors, source availability and SP processing
   status. Integrated acquisition uses the root study years; unavailable or
   unchecked intervals are errors, not empty fire years.
3. Prepare the matching original GEE observations and source evidence. Maintain
   the fixed-domain definitions unless a separate scientific decision explicitly
   changes them. Observation years outside a union-building period require
   independent annual land-cover evidence as well as the fixed union evidence.
   Set `C3.observationStartYear` and `C3.observationEndYear` in the GEE
   applications to match the root study. These remote export settings are
   manual; the Python workflow does not operate the Earth Engine interface.
4. Run geography and source admission using the new configuration. Require all
   declared years, months, units and source families, plus source indexes,
   geographic identities, QA, arithmetic and provenance, to pass.
5. Generate active-fire panels, merge and stage analysis inputs. Verify that
   panel ranges, eligible complete years, RQ2 series length and analysis support
   agree with the bound declaration. Run the chosen notebook route and validate
   genuine external scan results before complete-result closeout.

Use the selected configuration in every root command, for example
`--config configs/my_complete_year_study.json`. Do not amend an existing run's
snapshot, source lock or result receipts to accept changed inputs.

Local burned-area preparation derives its `observation_windows` from the
root study declaration; no additional operator setting is needed for that
generated contract. Match the GEE selection to it and retain a complete
downloaded delivery. See the
[GEE observation-period guide](../RP1_Project/rp1_gee_ba_scripts/c3/docs/OBSERVATION_PERIOD.md)
for the export controls and source-evidence requirements.

## Source evidence for observations outside a fixed union

The c3 extended record retains its fixed-domain source-index list. The optional
`ba_annual_lc_source_index` evidence identifies the annual land-cover source
used for an observation year outside that list. Such a year requires admitted
annual evidence; a filename or a widened year setting is insufficient. Preserve
the optional field with the original CSV and evidence companion.

Future study periods are a supported configuration pathway, not a declaration
that future NASA/GEE inputs have been downloaded or scientifically qualified.
Remote source availability, asset equivalence, annual land-cover support and
external SaTScan execution must be verified for the actual requested run.

The supplementary trend module derives the consecutive calendar from the
configured study. Proportional-noise intervals require positive annual rates,
a positive fitted path and usable residual variation for the relevant zone.
The module reports an unavailable interval with its reason when a zone fails
those conditions. The full five-zone detectability analysis requires all five
zones, and records unavailable status when that family is incomplete.

See [burned-area preparation](../RP1_Project/docs/ba_consolidation.md),
[Archive integration](FIRMS_ARCHIVE_INTEGRATION.md),
[analysis execution](ANALYSIS_EXECUTION.md) and the
[root runbook](../README.md).
