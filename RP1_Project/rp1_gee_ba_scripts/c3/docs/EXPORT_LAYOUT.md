# Extended CSV export layout

The exporter writes one 69-field extended analytical CSV per selected year and reporting scope. It does not create a separate 23-field base table. Each row describes one ACZ or district and one month. The `ba_domain` field and filename distinguish the BA2001 and BA2012 fixed unions; selecting fewer export years never shortens the union.

## Annual ACZ exports

```text
rp1_ba_acz_monthly_c3_CZ_BA2001_2024_ext.csv
rp1_ba_acz_monthly_c3_ALL_ACZ_BA2012_2024_ext.csv
```

`ALL_ACZ` means rows for the five zones in one annual table; it is not a national polygon. For a complete year, a selected zone has 12 rows and all five zones have 60, provided the intended units exist and all months are returned. ACZ `_ext` follows the year.

## Annual district exports

```text
rp1_ba_district_monthly_c3_TZ_BA2012_2024_ext.csv
rp1_ba_district_monthly_c3_TZ_BA2001_2024_ext.csv
rp1_ba_district_monthly_c3_TZ_BA2012_D_Asutifi_Nort_5b76ed12_2024_ext.csv
```

For both ACZ and district annual analytical files, `_ext` follows the export year. All-zone district exports create a separate annual table for each ACZ. A selected district filter adds `_D_`, a sanitized prefix of up to 12 characters and an eight-hex-digit hash of the full ID before the year to distinguish the subset from all districts in a zone. The filtered example assumes the exact `Asutifi_North` ID. A valid full-year table has 12 rows per included district; actual unit counts depend on the selected asset. During the existing boundary inventory, a selected-district action checks whether another district ID in the same ACZ generates the same compact tag and blocks the action if so. This check adds no separate Earth Engine metadata request and does not apply to unfiltered district or ACZ actions. The hash is not globally unique; the check cannot cover other asset versions or prior sessions. The full ID remains in the CSV.

The selected-month exporter CSV uses `rp1_ba_inspection_c3_<level>_<zonecode>_<domain>_<YYYYMM>[_D_<sanitized ID>_<hash>]_ext`. It uses the preview ACZ, even when the annual plan is configured for all ACZs. In district mode, a blank filter includes all districts of that preview ACZ; a filter uses the same bounded ID tag. The viewer uses `rp1_ba_viewer_inspection_c3_<domain>_<level>_<scope>_<YYYYMM>_ext` and requires ACZ or district scope.

The exporter applies a conservative project-local limit of 80 characters before the `.csv` extension and permits only ASCII letters, digits, underscore and hyphen in task descriptions and file prefixes. The same stem is supplied as the task description and filename prefix. The 80-character bound is an internal safeguard, not a published Earth Engine maximum. Session duplicate checks cannot discover names from prior sessions or Drive files.

## Counts and optional receipts

| Annual analytical scope | BA2001 | BA2012 |
|---|---:|---:|
| One ACZ | 24 | 13 |
| All ACZs combined | 24 | 13 |
| Districts in one ACZ | 24 | 13 |
| Districts in all five ACZs | 120 | 65 |

Five separately selected ACZs produce 120 ACZ files for BA2001 and 65 for BA2012. Together with one district file per ACZ-year, the intended complete set comprises 370 analytical CSVs: 240 BA2001 and 130 BA2012. This count excludes optional receipts and assumes districts within each zone share a file; it does not mean one file per individual district. The `All ACZs` ACZ option remains available and produces one combined file per year.

An optional unit-inventory QA receipt adds one task per selected district zone when enabled. Its filename contains the inclusive selected year range before `_qa_by_acz`, including repeated years for a one-year plan; for example, `rp1_ba_district_monthly_c3_TZ_BA2012_2022-2024_qa_by_acz.csv`. A filtered receipt adds the district tag before the range. It records identity and source preflight and a nonzero Ghana-clipped vector-area check; it does not establish geometry validity or local/GEE equivalence. Every separate district plan produces its own receipts when enabled.

Invalid/missing IDs or parent assignments and zero clipped vector area block data tasks; units are not silently dropped. After a detected zero-area block, an optional boundary exception log can record that condition as `BLOCKED_NOT_DROPPED`. It is not a complete record of all other causes or a general dropped-unit log. Review the plan, Console and Tasks, including any partially created tasks, before retrying.

A district boundary-exception filename includes the inclusive selected range and ends in `_boundary`, for example `rp1_ba_district_monthly_c3_TZ_BA2012_2022-2024_boundary.csv`; filtered names add the district tag before the range. ACZ exception names retain `_boundary_issue_log` and add `_start_to_end` for a bounded range. These records describe blocked units; the script does not drop units. Confirm full IDs and inspect previous Tasks and Drive files before retrying. Session duplicate checking cannot discover prior sessions.

### District inventory receipt schema

The optional receipt is a separate one-row CSV per selected district-zone scope, with these 14 fields in order:

| Header | Meaning |
|---|---|
| `schema_version` | Literal `c3_unit_inventory_v1`. |
| `domain` | Selected `BA2001` or `BA2012` fixed union. |
| `zone_id`, `zone_code` | Canonical parent-zone identity and short code. |
| `district_filter` | Exact selected district ID, or blank for all districts in the zone. |
| `selected_unit_count` | Number of selected district features. |
| `raw_asset_zone_count` | Number of district features assigned to the zone in the unfiltered asset inventory. |
| `identity_preflight` | `PASSED` when the receipt is created after the inventory checks. |
| `geometry_preflight` | `CLIPPED_NONZERO_AREA_ONLY`; not geometry equivalence or general validity. |
| `source_preflight` | `PASSED` for the selected source metadata checks; not pixel-level completeness. |
| `start_year`, `end_year` | Inclusive selected export-year range, not the fixed-union endpoints. |
| `boundary_asset`, `ghana_asset` | Asset paths used; paths do not freeze asset content. |

The 14-field count treats paired names in the table as separate fields. An uncreated or failed preflight need not produce a receipt.

### Boundary exception schema

Each per-zone exception CSV has nine fields in this order: `domain`, `level`, `unit_id`, `zone_id`, `reason`, `clipped_area_m2`, `disposition`, `boundary_asset`, `ghana_asset`. A recorded zero Ghana-clipped vector area has reason `ZERO_GHANA_CLIPPED_VECTOR_AREA` and disposition `BLOCKED_NOT_DROPPED`. Other failures may block task creation without an exception record; the log is not a general geometry audit.

For an assembled multi-year table, concatenate checked extended files without changing row values, converting blanks to zero, summing the repeated fixed-union denominator across months, or mixing domains. Build the expected unit-month scaffold so missing files, withheld results, and zero-contribution results are distinguished. Monthly burned areas may be summed as cumulative mapped monthly area, but a location may be counted in more than one month, so this is not automatically a unique annual footprint. Preserve source files, per-batch `run_id` values and task receipts; validate unique `(ba_domain, level, unit_id, yyyymm)` keys and expected month/unit coverage. The project consolidator admits this schema and the merger carries its evidence and guarded nulls into the analysis handoff; admission still depends on the selected delivery and geography.

Admit the c3 files through the project's configured consolidator and merger. The mixed-domain annual ratio can exceed one; preserve its documented interpretation and null semantics.
