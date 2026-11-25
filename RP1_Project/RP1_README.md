# RP1 processing components

Follow the [repository-root README](../README.md) for the complete workflow:

1. Geography preparation and three GEE upload bundles.
2. Annual c3 burned-area exports and source admission.
3. Archive SP acquisition/admission and active-fire panels.
4. Merging of admitted burned-area and active-fire panels.
5. Analysis handoff and the interactive notebook, including genuine external SaTScan results.

The sole operational
burned-area profile is `c3`, containing both BA2001 and BA2012 fixed domains.

`rp1_gee_ba_scripts/c3/` contains two pinned applications and one shared source
and deterministic builder. Generate separate annual ACZ and full-zone district
extended CSVs for all five zones, retain original bytes under
`downloads/c3_release/`, and use `consolidate-ba --profile c3`. Full delivery is
370 analytical files with 69 fields each; no separate base file is required.
The workflow requires a documented boundary label, approved geography and actual
merger consumer admission before publishing a bundle and year-aware source lock.
See [c3 preparation](docs/ba_consolidation.md) and [merger contracts](docs/merge_profiles.md).

The three-layer GEE upload bundle maps Ghana AOI, combined ACZs and combined
districts to the `C3` asset settings. Its EPSG:32630 vectors do not replace the
native raster grid or establish remote asset content. A declared 2024 pilot
contains 20 analytical files and cannot certify full scientific handoff.

The merger retains 111 analytical columns with panel schema
`rp1_fire_panel_consolidated_v3` and writes a mandatory c3 evidence companion
preserving all source fields/nulls/provenance. Calendar availability is distinct
from primary admission and visible evidence. Retain admitted scenario zeros,
guarded nulls and qualifying shortened positives; do not interpret conditional
support fractions as coverage. BA-dependent analyses must be regenerated from
the selected admitted inputs; completed runs remain immutable.

Use editable source installs for development. Node.js 24 is declared for pinned
c3 source checks. Qualification runs the c3 offline suite in a clean projection,
builds four wheels and verifies isolated imports, including `rp1_ba_contracts`
inside the analysis wheel. Use the root qualification commands in a separate
environment for distribution checks. Keep editable and non-editable
installations in separate environments.

`rp1_firms_archive/` is the fourth native package. Its code is under `src/`,
pinned upstream geography staged under `data/reference/`, acquisition cache under
`data/raw/`, and generated Archive products under `out/runs/<run-id>/`.
The shared `environment.yml` installs all four projects editably and includes
`requests` and `pyshp`. Original source generation identity is retained separately
from the validator version used for a new RP1 admission.

The workflow stages the active-fire consumer inputs and generates unit metadata.
All 370 original Earth Engine CSVs are included. Obtain the exact geography
inputs using the [data access guide](../docs/data_access.md). Complete Stage 1 `geo`, then Stage 3 `archive-plan`, `archive`, `archive-admit`
and `firms` with one configuration/run ID. The default `build` mode acquires
and prepares upstream MODIS/Suomi-NPP inputs using the native producer;
`geo` computes and stages boundaries and unit metadata. `existing` optionally
validates a separately available whole Archive and QA read-only. Optional
`bundled` mode requires separately available admitted shared inputs and does
not claim a new producer validation for source data that it only verifies. Accepted ZIP components are copied unchanged into
`rp1_mv_firms_panels/out/runs/<run-id>/source_inputs/`, with local acceptance,
coverage, provenance and QA evidence. The consumer configuration is routed
automatically to these inputs. Use a separate checkout for pipeline testing.

The full 2001–2024 study selects 24 MODIS and 13 Suomi-NPP source years (37
families). Suomi-NPP begins on 20 January 2012; this checked partial first month
is accepted. NOAA-20/21 remain outside the RP1 input selection. Missing or
unchecked required intervals fail admission; verified empty years retain honest
empty observation lineage. The consumer applies the configured TYPE/confidence and independent FRP methods. Read the [Archive integration guide](../docs/FIRMS_ARCHIVE_INTEGRATION.md)
for commands. Its optional `geo-reuse` verifies the original unchanged geography
handoff without generating new GEE assets. Manual curated stage/activate remains
available as an optional curated-input operation.
