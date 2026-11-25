# Presentation Figure Exporter

From `RP1_Project/rp1_analysis`, use the public Python script to derive standalone, presentation-ready figures from an **existing qualified analysis run**. These commands use the `ghana_fire_study` interactive analysis identity in the root README, after that run has completed and passed validation. For the controlled alternative use its actual closeout, such as `ghana_fire_study_controlled_close`. These single-line commands work in WSL and PowerShell, and each export uses a fresh destination:

```bash
python scripts/export_presentation_figures.py --list
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_one --figure rq2_coastal_trend
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_rq3 --group rq3
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_all --all
```

The `--all` selection covers 26 presentation figures, including RQ4, which
requires validated external SaTScan results. The ACZ seasonality, fixed-support
sensitivity and trend uncertainty exports use the data in FS1, FS3 and FS4,
respectively. Select each from the completed publication and closeout family.

```bash
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_seasonality --figure rq1_acz_seasonality
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_support --figure rq1_burnable_support_sensitivity
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_trends --figure rq2_trend_uncertainty
```

These selections use the registered seasonality, district support and trend
sensitivity sources. Their calculation does not require SaTScan results.

The script is intentionally thin. Scientific source selection, renderer identities, dimensions, category ordering, palettes, output names, configured formats, and SaTScan result-state requirements are owned by the package configuration and renderer modules.

## Existing-run requirement

`--run-dir` must identify the closeout member of an existing run family under `out/runs/`. The exporter resolves the associated publication and secondary run members and validates their compatibility with the current scientific contracts. It does not run the analysis and it does not execute SaTScan.

The source run is treated as read-only. Before and after every export operation, the exporter inventories the run family and fails if a source-run file is added, removed, or modified.

## Listing configured exports

```bash
python scripts/export_presentation_figures.py --list
```

The catalogue reports the configured groups, available formats, export IDs, renderer identities, and implementation status. The configured groups are `study`, `rq1`, `rq2`, `rq3`, and `rq4`.

## Selecting figures

Exactly one selection mode is used per export invocation:

```bash
--figure <export_id>
--group study
--group rq1
--group rq2
--group rq3
--group rq4
--all
```

`--figure` exports one configured figure. `--group` exports every configured figure in that group. `--all` exports the complete configured estate. Unknown export IDs and groups fail with a non-zero exit status.

## Output formats

Omitting `--format` uses the configured formats. The current presentation contract provides PNG and PDF. A configured format may be selected explicitly, for example:

```bash
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_png --all --format png
```

Repeat `--format` to request more than one configured format. Unsupported formats fail closed. Format selection does not alter scientific rendering parameters.

## Figure layout

Presentation figures include a title within the configured 20 × 15 cm canvas.
Standalone maps display a north arrow and scale bar. Categorical and support
symbols use a boxed key beside the map when needed. Numeric values use a
horizontal colourbar beneath the map. The district departure map, for example,
uses both the support key and the signed colourbar. PNG and PDF use the same
layout. The district conditional-absence map displays percentage ticks on
the colourbar and reads probabilities on the 0–1 scale from the source.

The matching notebook and standalone views share reversed Cividis for
long-run burned-area rates (0–70 km² per 100 km² per year) and recurrence
counts (0–45). District departures use a blue–white–red scale centred at
zero (−60 to +60), with stippling below zero. Conditional-absence proportions
and the district monthly-share heatmap use reversed Viridis across their
full proportion scales. The maps distinguish valid zero, non-significance
and excluded support with keys where those states apply.

The titled `rq2_five_acz_comparison` export places the ACZ statistics table
beneath the shared legend. The titled `rq3_focal_effects` export puts the model
notes in a grey box below the x-axis and keeps the estimate labels clear
of the odds-ratio reference line.

For `rq3_four_state_correspondence`, the overall paired-population/count summary
appears in a dedicated bottom-right footer area, outside the bar axes. The
category legend occupies a separate area on the left. Neither the summary nor
the category legend covers the stacked observations. The summary is an
annotation rather than a fifth observation category. Layout changes do not
change the plotted source values, category order or source-run provenance.

## Output directory

The destination must be new and must be outside the governed source run. A complete export has the form:

```text
out/presentation_figures/
    study/
    rq1/
    rq2/
    rq3/
    rq4/
    RP1_PRESENTATION_FIGURE_MANIFEST.json
    RP1_PRESENTATION_FIGURE_EXPORT_REPORT.md
    RP1_PRESENTATION_FIGURE_OUTPUT_INVENTORY.csv
```

Only groups requested by the invocation need contain figure files. Output collisions are errors; the exporter does not silently overwrite an existing destination.

## Manifest and provenance

The aggregate manifest identifies the source run and records each requested output with its export ID, group, renderer, analysis schema, data schema, semantic source identity, source path and SHA-256, geometry authority paths and hashes when applicable, configuration SHA-256, required and observed external-result state, output path, output SHA-256, format, physical dimensions, raster DPI, status, and any error.

The output inventory provides a compact machine-readable file/hash list. The Markdown export report provides the human-readable success/failure summary.

## SaTScan-dependent exports

RQ4 presentation figures are available only when the associated secondary run records genuine `RESULTS_VALIDATED` SaTScan results. If the run remains `EXTERNAL_RESULTS_REQUIRED`, the RQ4 export fails explicitly. That state does **not** mean that zero clusters were found, and no synthetic or stale result family is substituted.

MCD64A1 and VIIRS retain their product-specific SaTScan models. The exporter never executes SaTScan and never invents STP expected counts or relative risks.

Recurrence totals come from the selected run's validated cluster memberships.
Each district count must be an integer between zero and that product's total;
fractions must agree with those counts, and excluded districts retain missing
values. The export rechecks linkage to the raw SaTScan results. Keep those
authorities unchanged when addressing a presentation error.

## Failure behaviour and scripting

The public script returns a non-zero exit status when a requested export fails. Typical failures include a missing or malformed run family, source/configuration incompatibility, missing scientific source, missing governed geometry, unsupported format, existing output destination, invalid export ID/group, and unresolved SaTScan result state.

For `--all`, a required figure failure is reported in the aggregate manifest/report and the command fails; failures are not silently ignored.

An aggregate failure can accompany successful figure files. Read the report's
`Export results` table to identify the failed export and its error. Preserve that
report, correct the cause and choose a fresh destination for the retry. For
example, to retry the VIIRS recurrence figure alone:

```bash
python scripts/export_presentation_figures.py --run-dir out/runs/ghana_fire_study_close --output-dir out/presentation_viirs_retry --figure rq4_viirs_recurrence
```

Use the actual closeout run path for your analysis. A retry into an existing
destination is rejected, including a directory from an earlier failed attempt.

## c3 input and evidence contract

Only the admitted c3 workflow handoff enters this analysis. The 111 analytical roles retain separate BA2001 and BA2012 suffixes; panel schema is rp1_fire_panel_consolidated_v3 and data schema is rp1-data-schema-v1.2. Both retrospective unions keep their full reference windows. Annual CSV selection does not redefine a union.

The mandatory ba_observation_support.csv preserves all 69 source fields plus family, source_path, source_sha256 and source_row (1-based data-record index). Its schema is rp1-ba-c3-evidence-v1, policy c3_preserve_admission_v1, method c3_methods_v1_schema_v2. Original source run IDs stay separate from workflow/merge run identity. Its bytes belong to the exact 18-file staged input inventory.

Calendar availability, primary-result usability and visible evidence are distinct. An admitted no-supported-evidence scenario zero remains zero; it does not prove physical absence. An anomaly, unresolved domain or other guard can withhold primary values. Withheld values stay null, independently guarded annual fields stay as exported, and diagnostics never replace withheld primary fields. Five exclusive evidence states partition the known union; reason areas overlap. ba_supported_fraction is a restricted evidence ratio, not union coverage.

Full-window primary products require complete usable inputs and positive fixed union support. An incomplete pilot cannot configure complete scientific inputs. The declared study and source support remain bound to the admitted evidence. Complete-constituent reconciliation reports withheld comparisons rather than silently summing the remaining districts. Generate research and publication outputs from the selected inputs, and validate external results before integrating them.

