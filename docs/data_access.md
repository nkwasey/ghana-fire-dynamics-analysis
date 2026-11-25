# Input data

## Included and external inputs

The repository contains 370 original Earth Engine burned-area CSVs, the
study's national, district and reference-zone shapefiles and their SHA-256
inventories. Keep these files unchanged. Obtain the four FIRMS archive
reference files separately and use [source geography admission](SOURCE_GEOGRAPHY.md)
to check the inputs. The software licence in [LICENSE](../LICENSE) applies to
the code. Follow the applicable permissions and attribution for each dataset.

The workflow generates FIRMS consumer boundaries and unit metadata from
the admitted source geography. It acquires MODIS and Suomi-NPP standard-processing
observations and prepares annual shapefile families, each with
`.shp`, `.shx`, `.dbf`, `.prj` and `.cpg` sidecars.

## Published panels

The [Ghana fire panel dataset](https://doi.org/10.6084/m9.figshare.31985559.v2)
is archived on Figshare under CC BY 4.0. It contains the monthly district
and agro-climatic-zone panels, the burned-area observation-support CSV,
the key audit, the analysis and original merge manifests, and the merge
summary. Cite the DOI for these exact deposited files.

## Analysis-only inputs

Analysis-only execution requires a complete verified analysis-input
companion obtained separately. In addition to the deposited panel files,
it carries the derived geography, the input inventory and the manifest-bound
active-fire evidence. Use the [full workflow](../README.md) if you do not
have a verified companion. The companion needs about 8 GiB of disk space
when unpacked and approximately another 8 GiB for admitted files.

Obtain and verify the companion's SHA-256 through the same trusted source
that provided the data. Extract it outside the checkout and pass the
extracted directory containing `RP1_Project/`. From the repository root:

```bash
python tools/admit_analysis_inputs.py --source-root "/path/to/verified-inputs"
```

On Windows use the applicable local path, for example
`'C:/RP1_Input_Companion'`. Admission verifies all required inputs and
evidence before copying and rejects conflicting destination files.
Continue with [analysis input validation](ANALYSIS_EXECUTION.md#input-validation).

## FIRMS and burned-area sources

The `ghana_firms_archive_sp_v1` production input profile is bound to an intake
authority containing component hashes and local Archive provenance/field
dictionaries. Archive country filtering, validation and measurement
deduplication precede RP1 processing; RP1 still applies its own TYPE, mask,
confidence, deduplication and spatial-join policies. Archive district/zone
attributes do not replace analytical geography. NOAA-20 and NOAA-21 are excluded.

The fourth local package, `RP1_Project/rp1_firms_archive`, is the native Archive
producer. The shared environment installs `ghana_fire_archive` editably along
with geography, FIRMS panels and analysis; it declares `requests` and `pyshp`.
Admit the pinned source geography under the producer's `data/reference/`.
Keep acquired observation files and generated metadata in local working directories. Keep credentials outside distributed source trees.

Use the automated `geo`, then Stage 3 `archive-plan`, `archive`, `archive-admit` and `firms`
stages from the RP1 root. The default `configs/workflow.json` selects `build`
and acquires/prepares the upstream fire inputs before admission. `existing` mode reads
a whole Archive without changing it and requires current API validation of its
source/export/coverage/QA evidence. `build` uses the embedded producer and may
contact NASA during acquisition. New admissions extract accepted ZIP bytes into
`RP1_Project/rp1_mv_firms_panels/out/runs/<run-id>/source_inputs/`, with local
acceptance and QA evidence. Geography is staged under the consumer's
`data/raw/boundaries/` by `geo`; the initial empty directory is not populated
manually. Optional `bundled` mode requires separately available admitted
shared inputs. The default mode builds the archive.
Original generation identity remains separate from current validator identity.

For January 2001–December 2024, required coverage is 24 MODIS plus 13 Suomi-NPP
source years (37 families). Suomi-NPP's checked first interval begins on
20 January 2012. Missing or unchecked required coverage fails admission; a
verified zero-record year is not an unavailable year. See the
[Archive integration guide](FIRMS_ARCHIVE_INTEGRATION.md) for the commands and
[Archive SP input policy](FIRMS_SP_INPUTS.md) for detailed evidence and optional
curated plan/stage/activate operations.

Generate burned-area exports with the pinned c3 scripts under `RP1_Project/rp1_gee_ba_scripts/c3/`. Place the original annual CSVs under `RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/`; the repository carries the study delivery as source input. The selected production names are `rp1_ba_<district|acz>_monthly_c3_<CZ|FZ|GS|SS|TZ>_<BA2001|BA2012>_<YYYY>_ext.csv`. Both levels and all five zones are required for each selected year. BA2001 covers 2001–2024 and BA2012 covers 2012–2024: the full delivery contains 370 analytical CSVs, while a declared 2024 pilot contains 20. Every file retains the complete 69-field `rp1_ba_c3_extended_v2` record; no separate base CSV is required. Preserve original bytes and submit the delivery to the c3 `consolidate-ba` admission route before merging. Keep other downloads and workflow outputs in local working directories.

Geography, unit metadata, crosswalks, active-fire panels, merged panels, analysis authorities, figures, tables and run manifests are generated by the workflow. They are not supplied as analysis results. Use one configured geography and one identified merged profile together; do not select inputs from a directory merely because its filename is convenient or recent. An explicit `geo-reuse` stage can verify the unchanged current geography handoff and original generation evidence without rewriting it or creating new GEE assets. The root README provides the local execution sequence.

FIRMS source portal: https://firms.modaps.eosdis.nasa.gov/download/. Product collection and confidence mapping are configured by sensor. Verify source coverage rather than inferring valid zero observations from an empty source month.

BA2001 and BA2012 have distinct fixed unions and may differ in numerator as well as denominator during overlapping months. Retain all c3 admission/evidence diagnostics and nulls. Admitted scenario zeros do not establish physical fire absence; absent or withheld cells cannot become zeros. Bind the approved geography, source/script identities, source indexes and available asset-version evidence to the admitted delivery. BA grid, mask representation and export-lineage qualification remain separate from software acceptance; bounded sample checks do not qualify the full study.
