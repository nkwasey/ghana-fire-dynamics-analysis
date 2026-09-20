"""Typer application for the geo-prep CLI.

Stage 1 focus
-------------
- Config-driven, reproducible geodata prep (NO ArcPy)
- configuration surfaces for area policy, QA thresholds and contract
  metadata while preserving existing runtime behaviour
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from geo_data_prep.core.config import ConfigError, load_config, resolve_paths
from geo_data_prep.core.runtime import RunError, run_from_config

console = Console()

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="geo-prep: Stage 1 geodata & metadata prep (NO ArcPy).",
)


def _print_validation_summary(cfg_path: Path) -> None:
    cfg = load_config(cfg_path)
    resolved = resolve_paths(cfg, config_path=cfg_path)

    # Binding: validate must confirm inputs exist and are readable, but must not write outputs.
    if not resolved.zones_path.exists():
        raise ConfigError(f"Input zones layer not found: {resolved.zones_path}")
    if not resolved.districts_path.exists():
        raise ConfigError(f"Input districts layer not found: {resolved.districts_path}")
    if cfg.inputs.aoi is not None and cfg.inputs.aoi.enabled:
        if resolved.aoi_path is None or not resolved.aoi_path.exists():
            raise ConfigError(f"Input AOI layer not found: {resolved.aoi_path}")

    console.print("[green]OK[/green] Config validated.")
    console.print(f"schema_version={cfg.schema_version}")
    console.print(f"contract_version={cfg.contract_version}")

    t = Table(title="Resolved paths (computed; config values remain relative)")
    t.add_column("Item", style="bold")
    t.add_column("Value")
    t.add_row("repo_root", str(resolved.repo_root))
    t.add_row("config", str(resolved.config_path))
    t.add_row("inputs.zones.path", str(resolved.zones_path))
    t.add_row("inputs.districts.path", str(resolved.districts_path))
    if cfg.inputs.aoi is None:
        t.add_row("inputs.aoi", "<not set>")
    else:
        t.add_row("inputs.aoi.enabled", str(cfg.inputs.aoi.enabled))
        t.add_row("inputs.aoi.path", str(resolved.aoi_path) if resolved.aoi_path else "<not set>")
    t.add_row("outputs.out_dir", str(resolved.out_dir))
    console.print(t)

    s = Table(title="Key settings")
    s.add_column("Setting", style="bold")
    s.add_column("Value")
    s.add_row("levels.zone.level", cfg.levels.zone.level)
    s.add_row("levels.district.level", cfg.levels.district.level)
    s.add_row("crs.working_crs", cfg.crs.working_crs)
    s.add_row("crs.overlay_crs", cfg.crs.overlay_crs)
    s.add_row("crs.plot_crs", cfg.crs.plot_crs)
    s.add_row("area_policy.method", cfg.area_policy.method)
    s.add_row(
        "area_policy.projected_crs",
        (
            cfg.effective_area_projected_crs
            if cfg.effective_area_projected_crs is not None
            else "<not set>"
        ),
    )
    s.add_row("area_policy.geodesic_ellipsoid", cfg.area_policy.geodesic_ellipsoid)
    s.add_row("area_policy.units", cfg.area_policy.units)
    s.add_row("outputs.toggles.splits", str(cfg.outputs.toggles.splits))
    s.add_row("outputs.toggles.plots", str(cfg.outputs.toggles.plots))
    s.add_row("outputs.basenames.zones", cfg.outputs.basenames.zones)
    s.add_row("outputs.basenames.districts", cfg.outputs.basenames.districts)
    s.add_row("derivations.zone_code.mapping_size", str(len(cfg.derivations.zone_code.mapping)))
    s.add_row("derivations.zone_code.fallback.method", cfg.derivations.zone_code.fallback.method)
    s.add_row(
        "derivations.zone_code.fallback.collision", cfg.derivations.zone_code.fallback.collision
    )
    console.print(s)

    c = Table(title="Stage 1 contract")
    c.add_column("Setting", style="bold")
    c.add_column("Value")
    c.add_row("contract.stage", cfg.contract.stage)
    c.add_row("contract.name", cfg.contract.name)
    c.add_row("contract.version", cfg.contract_version)
    c.add_row("contract.canonical_upstream", str(cfg.contract.canonical_upstream))
    c.add_row("contract.downstreams_adapt_later", str(cfg.contract.downstreams_adapt_later))
    console.print(c)

    q = Table(title="QA thresholds")
    q.add_column("Metric", style="bold")
    q.add_column("Warn")
    q.add_column("Fail")
    q.add_row(
        "overlap_share",
        f"<{cfg.qa.thresholds.overlap_share.warn_below}",
        f"<{cfg.qa.thresholds.overlap_share.fail_below}",
    )
    q.add_row(
        "area_relative_difference",
        f">{cfg.qa.thresholds.area_relative_difference.warn_above}",
        f">{cfg.qa.thresholds.area_relative_difference.fail_above}",
    )
    q.add_row(
        "unassigned_units",
        f">{cfg.qa.thresholds.unassigned_units.warn_above}",
        f">{cfg.qa.thresholds.unassigned_units.fail_above}",
    )
    q.add_row(
        "invalid_geometries",
        f">{cfg.qa.thresholds.invalid_geometries.warn_above}",
        f">{cfg.qa.thresholds.invalid_geometries.fail_above}",
    )
    console.print(q)

    d = Table(title="QA diagnostics")
    d.add_column("Diagnostic", style="bold")
    d.add_column("Enabled")
    d.add_column("Details")
    d.add_row(
        "sliver_diagnostics",
        str(cfg.qa.sliver_diagnostics.enabled),
        (
            f"share_cutoffs={list(cfg.qa.sliver_diagnostics.share_cutoffs)}; "
            f"area_sqkm_cutoffs={list(cfg.qa.sliver_diagnostics.area_sqkm_cutoffs)}; "
            f"examples={cfg.qa.sliver_diagnostics.example_limit}"
        ),
    )
    d.add_row(
        "crs_sensitivity",
        str(cfg.qa.crs_sensitivity.enabled),
        (
            "alternative=auto equal-area sensitivity projection; "
            f"examples={cfg.qa.crs_sensitivity.example_limit}"
        ),
    )
    console.print(d)


@app.command("validate")
def validate(
    config: Path = typer.Option(..., "--config", "-c", exists=True, readable=True)  # noqa: B008
) -> None:
    """Validate a YAML config against the strict Stage 1 schema.

    This command performs validation and prints resolved paths plus key policy
    settings. It does NOT process data and does NOT write outputs.
    """

    try:
        _print_validation_summary(config)
    except ConfigError as e:
        console.print("[red]ERROR[/red] " + str(e))
        raise typer.Exit(code=2)  # noqa: B904



@app.command("version")
def version() -> None:
    """Print the installed package version."""
    from geo_data_prep import __version__

    console.print(__version__)


@app.command("run")
def run(
    config: Path = typer.Option(..., "--config", "-c", exists=True, readable=True),  # noqa: B008
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Optional run identifier. If omitted, a UTC timestamp is used.",
    ),
) -> None:
    """Run the full Stage 1 pipeline (read -> derive -> assign -> exports -> plots -> QA).

    Note: we intentionally use ASCII in CLI help strings to avoid Windows console
    encoding failures when Python stdout/stderr are not in UTF-8 mode.
    """

    try:
        outs = run_from_config(config_path=config, run_id=run_id)
    except (ConfigError, RunError) as e:
        console.print("[red]ERROR[/red] " + str(e))
        raise typer.Exit(code=2)  # noqa: B904

    console.print("[green]OK[/green] Run complete.")
    console.print(f"run_id={outs.run_id}")
    console.print(f"run_dir={outs.run_dir}")
    console.print(f"inputs_fingerprint={outs.inputs_fingerprint_path}")
    console.print(f"outputs_manifest={outs.outputs_manifest_path}")
