# c3 annual preparation and admitted handoff

`rp1_ba_consolidator` prepares original annual extended c3 exports.
`tools/consolidate_ba.py` and workflow `consolidate-ba` share this implementation.
The production source schema is `rp1_ba_c3_extended_v2`, method
`c3_methods_v1_schema_v2`, local policy `c3_preserve_admission_v1`. File names alone do not establish schema or method identity.

## Delivery and validation

Put original files under `RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/`.
Downloaded domain subfolders may remain. Match exactly:

```text
rp1_ba_<district|acz>_monthly_c3_<CZ|FZ|GS|SS|TZ>_<BA2001|BA2012>_<YYYY>_ext.csv
```

For the configured 2001–2024 study, the complete matrix is 240 BA2001 plus 130 BA2012 files, or 370 analytical CSVs.
Every ACZ file has 12 rows and every district file has 12 per approved district
in that zone. The 2001–2024 and 2012–2024 fixed unions stay unchanged when fewer
export years are selected. Preserve all 69 ordered fields and optional upstream
`system:index` / `.geo` columns. No paired base tables are expected.

Validation checks filename/row identity, exact unit/month matrix, duplicate
keys, products, source indexes, grid/reducer, status-specific nulls, independent
annual eligibility, five-state closure and arithmetic. The source key includes
domain: `(ba_domain, level, unit_id, yyyymm)`. Optional inventory receipts and
boundary logs are separate operational evidence. Combined ACZ tables, subsets,
inspection/viewer tables and incompatible schemas cannot fill the production
matrix. Technical reduction/accounting failures hold production admission.

Admitted no-supported rows retain their source scenario zero. Withheld or absent
primary values never become zero, and diagnostic known-union values cannot
replace them. `ba_supported_fraction` is not observation coverage. The annual
union-numerator/annual-denominator ratio can exceed one.

## Workflow admission

This is Stage 2 of the root workflow. Geography is Stage 1, Archive acquisition
and active-fire panels are Stage 3, merging is Stage 4 and analysis is Stage 5.
The example below shows their order; follow the root README for GEE uploads
and the actual export preparation before local admission.


Use the same configuration and run ID for geography, preparation, AF and merge:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study geo
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 --ba-input-dir RP1_Project/rp1_gee_ba_scripts/downloads/c3_release --boundary-label approved_boundary_release consolidate-ba
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-plan
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study archive-admit
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study firms
python tools/run_workflow.py --config configs/workflow.json --run-id ghana_fire_study --profile c3 merge
```

The geography step creates the local upload bundle and receipt; optional `gee-inputs`
verifies and reports that bundle without contacting Earth Engine. The retained
c3 delivery can be processed locally when its source and
geography evidence matches the selected run; this does not require uploading
assets or re-exporting the same CSVs. For a new burned-area delivery, upload the
three combined boundaries, run the pinned c3 exporter and retain the original
downloaded CSVs before `consolidate-ba`.

`configs/workflow.json` and `workflow_ba_preparation.example.json` use one
`ba_preparation.c3` block with `input_dir`, `boundary_label`, optional
`output_root`, and `scope`. For the unchanged retained delivery, use the example
label `approved_boundary_release`. For a different delivery, use its documented
label in the configuration or pass it with `--boundary-label`. Requests freeze the
source/output/geography/study/policy identity in `ba_c3_request.json` and record
completion in `ba_c3.json`. A changed request requires a new run.

Preparation invokes the merger's burned-area consumer before atomic
publication. Its new immutable bundle contains:

```text
out/workflows/ghana_fire_study/ba/c3/
  sources/                  original annual filenames and unchanged bytes
  auxiliary/                optional admitted operational records
  manifest.json
  validation_report.json
  source_lock.json
  handoff.json
```

The manifest/lock bind domain, level, zone, year, filename, hash and size for
every consumed source. The handoff binds implementation, canonical geography,
selected scope, actual consumer PASS and workflow request. Repeating a completed
step verifies these identities. Source or implementation changes require
readmission at a fresh output. A hash does not prove a remote asset revision.

WSL can publish to Windows drive paths using a non-replacing Windows directory
move if the Linux rename is unsupported. This requires enabled WSL
interoperability, `wslpath`, and `powershell.exe` on `PATH`. If publication is
unavailable on the destination filesystem, use a supported absolute
`--ba-output-root`, such as `$HOME/rp1_ba_outputs` on WSL. The workflow appends
`<run-id>/c3`, records the location and refuses overwrite. A published
bundle without its final workflow receipt can be recovered only after the same
request, source and geography verify; changed inputs cannot be rebound.

## Standalone checks and pilot scope

From the repository root:

```bash
python tools/consolidate_ba.py --help
python tools/consolidate_ba.py --input-dir RP1_Project/rp1_gee_ba_scripts/downloads/c3_release --output-dir out/ba_validation/c3 --unit-universe RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv --scope full --boundary-label approved_boundary_release --validate-only
```

Validate-only writes no output and does not run consumer admission. Omitting
`--validate-only` requires the canonical unit universe and publishes a bundle
only after actual consumer admission. The writing command never overwrites its
destination. Standalone paths resolve from the shell directory; workflow paths
resolve from the repository root. From the analysis directory, use
`python ../../tools/consolidate_ba.py` or `../../tools/run_workflow.py` with
appropriate standalone paths.

For a technical pilot, use `configs/workflow_c3_pilot_2024.example.json` with a
fresh run ID and documented boundary label. It selects 2024 while retaining both
full fixed-domain definitions: 20 analytical files across two levels/five zones.
Alternatively a standalone checked subset can declare `--scope pilot
--start-year 2024 --end-year 2024`. Use a separate pilot source root and new
destination. Pilot preparation/merge tests do not satisfy full `analysis-inputs`,
publication acceptance or complete RQ2 inference, and cannot rewrite the main
scientific configuration.

Review admitted/withheld/evidence distributions, local versus remote geography,
source-mask representation and task/script/asset provenance before scientific
interpretation. Offline arithmetic and bounded live samples do not establish
full-period source support or physical-fire accuracy.

## Configured observation periods

The root study selects the observation period independently from the fixed
BA2001 and BA2012 eligibility unions. Complete scope requires every declared
annual source, level, zone and unit/month for that selected study. A source
catalogue may retain additional years; their identities remain inventoried and
they are not silently included in the consumed source lock. Preserve all 370
original delivery files for the configured study.

For observations outside a fixed union-building period, require independent
annual land-cover evidence, including `ba_annual_lc_source_index` where
applicable. This evidence does not replace the original fixed-union source
list or change its denominator. Availability, source identity and technical
admission checks must still pass. See
[study configuration](../../docs/STUDY_CONFIGURATION.md) for future-period
requirements. No real future dataset is certified by a software test.
