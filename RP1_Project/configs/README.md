# Merger configuration

`merge_profiles.json` is version 2 and exposes only profile `c3`. It binds the
69-field `rp1_ba_c3_extended_v2` schema, `c3_methods_v1_schema_v2` method and
`c3_preserve_admission_v1` policy. BA2001 and BA2012 are distinct domain families
inside this profile. `bundle_handoff` is initially null; the root workflow fills
it from completed verified c3 preparation. Direct merger use may set it in a
copied configuration or pass `--ba-handoff`.

Use one fresh run/configuration for geography, annual c3 `consolidate-ba`, AF,
merge and full analysis handoff. All 370 selected annual files and current units
must be accounted for in full scope. There is no static-root fallback. A pilot
uses a separate configuration and cannot satisfy full scientific handoff.

Configuration paths resolve from the repository root; explicit CLI path
overrides resolve from the shell directory. Output destinations must be new.
See [merge contract](../docs/merge_profiles.md),
[c3 preparation](../docs/ba_consolidation.md), and the root README for exact
commands, immutable requests, evidence companions and source qualifications.
