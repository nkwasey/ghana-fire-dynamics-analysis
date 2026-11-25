# Active-fire preparation

The active-fire component contains source code, configuration, tests and raw FIRMS annual detection bundles. Its generated boundary/unit metadata inputs come from Stage 1. Run outputs under `out/runs/<run_id>` include canonical detections, monthly sensor panels, combined panels, QA and `rp1_af_exports` for the merger.

Preparation applies configured TYPE filtering, sensor-specific confidence mapping, deduplication, temporal support and polygon assignment. Primary counts use nominal/high confidence from the count stream. VIIRS FRP independently selects nominal/high observations before deduplication; the streams can therefore retain different records. FRP applies finite-value and minimum-FRP eligibility, then a unit-day maximum and monthly active-day mean. See `rq3_frp_method.md`. Missing observations and processing failures are not valid fire zeroes.
