# Presentation Figure Exporter

RP1 Analysis v1.2.3 includes one public Python script for deriving standalone, presentation-ready figures from an **existing qualified analysis run**:

```bash
python scripts/export_presentation_figures.py --list
python scripts/export_presentation_figures.py \
  --run-dir out/runs/<run_id>_close \
  --output-dir presentation_figures \
  --figure rq2_coastal_trend
python scripts/export_presentation_figures.py \
  --run-dir out/runs/<run_id>_close \
  --output-dir presentation_figures \
  --group rq3
python scripts/export_presentation_figures.py \
  --run-dir out/runs/<run_id>_close \
  --output-dir presentation_figures \
  --all
```

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
python scripts/export_presentation_figures.py \
  --run-dir out/runs/<run_id>_close \
  --output-dir presentation_figures \
  --all --format png
```

Repeat `--format` to request more than one configured format. Unsupported formats fail closed. Format selection does not alter scientific rendering parameters.

## Output directory

The destination must be new and must be outside the governed source run. A complete export has the form:

```text
presentation_figures/
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

## Failure behaviour and scripting

The public script returns a non-zero exit status when a requested export fails. Typical failures include a missing or malformed run family, source/configuration incompatibility, missing scientific source, missing governed geometry, unsupported format, existing output destination, invalid export ID/group, and unresolved SaTScan result state.

For `--all`, a required figure failure is reported in the aggregate manifest/report and the command fails; failures are not silently ignored.
