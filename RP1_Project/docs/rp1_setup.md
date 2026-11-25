# Local setup

Use the shared Conda environment `rp_ghana_fire` with Python 3.13. The source-qualification environment also declares Node.js 24 for c3 builds and offline checks; ordinary CSV processing does not call Earth Engine. Follow the root README through geography, three combined boundary uploads, c3 export admission, Archive acquisition and active-fire panels, c3 merge and interactive notebook execution with external SaTScan results. All four editable Python projects must resolve to this checkout. The lightweight `rp1_ba_contracts` package is included in the analysis distribution, not installed as a separate fifth project.

Use the two applications in `RP1_Project/rp1_gee_ba_scripts/c3/scripts/`. Download annual per-zone district and ACZ extended CSVs to `RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/`. Run `consolidate-ba --profile c3` with the selected run/geography and boundary label. Full admission requires all 370 expected analytical files; an explicit 2024 pilot has 20 files and cannot certify full-window analysis. See [c3 preparation and handoff](ba_consolidation.md) for exact commands, schemas and recovery. Keep all original values, guarded nulls and 69 source fields together.

Commands beginning `python tools/` run from the repository root. From `RP1_Project/rp1_analysis`, use `python ../../tools/run_workflow.py` or `python ../../tools/consolidate_ba.py`. Workflow configuration paths and relative `--ba-input-dir` values resolve from the repository root; standalone input/output paths resolve from the shell directory. Use fresh run/output identities for changed sources or configuration.

For pinned c3 source checks, run `python tests/run_offline.py` from its `c3/` directory. `tools/qualify_source_checkout.py` runs these checks in a clean projection and verifies the shared contract's projected import origin. To qualify the source with no analytical inputs, run `python tools/qualify_environment.py --source-only --evidence-dir EXTERNAL_EVIDENCE_DIRECTORY` from the repository root. This records Node/version logs, treats c3 failures as hard source gates, builds all four wheels and checks a fresh non-editable installation, including the shared c3 contract origin. Keep evidence outside the checkout and preserve completed results. Source qualification does not establish full-period remote asset or physical-fire accuracy.

For the current 2001–2024 study use workflow and analysis ID
`ghana_fire_study`. Source availability, the selected observation window and
fixed BA eligibility unions are separate declarations. Follow
[study configuration](../../docs/STUDY_CONFIGURATION.md) for another complete-year
period and [analysis execution](../../docs/ANALYSIS_EXECUTION.md) for the
primary interactive route and controlled alternative.
