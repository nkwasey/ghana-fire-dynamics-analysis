# c3 merger contract

`RP1_Project/configs/merge_profiles.json` uses configuration version 2. Its
default and sole operational profile is `c3`, bound to
`rp1_ba_c3_extended_v2`, `c3_methods_v1_schema_v2` and
`c3_preserve_admission_v1`. Both BA2001 and BA2012 are retained within that
profile. The admitted c3 handoff is required; static BA-root discovery cannot bypass it.

From the repository root, use one unused run ID for geography,
c3 `consolidate-ba` and AF preparation before merging. Geography creates the
local upload bundle; `gee-inputs` can verify and report it without a remote upload:

```bash
python tools/run_workflow.py --config configs/workflow.json --run-id new_ba_run --profile c3 merge
```

The workflow binds the verified `handoff.json`, `manifest.json` and
`source_lock.json` into immutable merge runtime configuration and checks the
selected geography and actual unit counts. Repeating preparation verifies its
existing request and bundle. Review a failed merge before `--retry-merge`; retry
requires unchanged runtime configuration and an absent final destination.
An absolute `--merge-output-root` may select a filesystem supporting atomic
non-replacing publication. Its recorded `<root>/<run-id>/c3` location is reused
for retries and analysis handoff.

## Source binding and outputs

The admitted annual matrix contains one original `_ext.csv` per declared
domain/level/zone/year: 370 analytical files for the full study. The merger
checks year-aware identities, file hashes, 69-field schema, domain/month keys,
canonical units/parents, source/grid lineage and c3 admission arithmetic. It
validates original annual files separately; source run IDs may differ by batch
and are not file identities. Optional inventory receipts are not observation
support and cannot replace missing analytical files.

Each new output directory contains two compact 111-column panels, key audit,
manifest, merge summary and mandatory `ba_observation_support.csv`. The panel
semantic schema is `rp1_fire_panel_consolidated_v3`. The companion uses
`rp1-ba-c3-evidence-v1`, retains all 69 original source fields and explicit
file/hash/row provenance plus family identity, and is bound by the manifest.
Its derived key is `(level, unit_id, yyyymm, family)` with `ba2001` or `ba2012`;
original `ba_domain` remains available. No BA2012 source rows are invented before
2012. Keep this companion with the panels and staged input inventory.

c3 primary numerical values and nulls pass through unchanged. `ADMITTED` plus
`NO_SUPPORTED_EVIDENCE` can validly carry scenario BA zero, which is not physical
fire absence. Anomalies/unresolved domains withhold primary values; independently
guarded annual fields/flags can remain. Technical reduction/accounting failures
hold admission. A resolved empty union gives zero numerator/denominator and an
undefined fraction. The annual mixed-domain ratio can exceed one. Do not use
`ba_supported_fraction` as coverage or promote known-union diagnostics into
withheld primary fields. Calendar source flags do not assert complete evidence.

## Direct merger use

Standalone writing preparation also performs actual consumer admission. Point
`bundle_handoff` in a copied version-2 configuration at that handoff, or provide
the optional CLI override:

```bash
python RP1_Project/merge_af_ba_panels.py --config RP1_Project/configs/merge_profiles.json --profile c3 --ba-handoff out/ba_staging/c3/handoff.json --unit-universe RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv --af-root /path/to/rp1_af_exports --output-dir out/merge/new_c3 --run-id new_c3
```

The `--ba2001-root` and `--ba2012-root` options, when supplied, must agree with
the admitted bundle; they do not permit unadmitted sources. Configuration paths
resolve from the repository root; explicit CLI paths resolve from the shell
directory. The destination must be new. Publication is atomic and never replaces
a completed result.

The admitted bundle already contains a source lock. For an independent byte
inventory at a new path, `create_ba_source_lock.py --bundle <bundle> --output
<new-lock.json>` reconstructs the exact declared annual matrix and refuses
overwrite. This command does not create a handoff or grant source admission.

Only a full-scope c3 merge may enter workflow `analysis-inputs`. A pilot bundle
is valid solely for its declared technical scope. Source hashes, compatible
keys and successful software execution do not prove remote asset content,
full-period observation support or physical-fire accuracy.
