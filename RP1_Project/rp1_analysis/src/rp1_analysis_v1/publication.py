"""Configuration-driven publication output orchestration.

The publication layer consumes immutable, hash-verified source authorities
materialised from qualified RQ1/RQ2/RQ3 results.  It does not recompute study
statistics.  SaTScan-dependent outputs remain fail-closed when genuine
external-engine results are unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes

from .config import ConfigurationBundle, load_configuration_bundle
from .data_io import DataAuthorities, load_data_authorities
from .design import assert_execution_ready
from .figures import (
    RenderedFigure,
    district_seasonal_components,
    draw_circular_mean_timing,
    draw_coefficient_or_plot,
    draw_district_seasonal_heatmap,
    draw_resultant_length_by_group,
    draw_shared_trajectory_key,
    draw_seasonality_lines,
    draw_stacked_proportions,
    draw_trajectory_panel,
    export_figure,
)
from .mapping import (
    cluster_maps_grid,
    cluster_recurrence_maps_grid,
    draw_acz_choropleth_axis,
    draw_categorical_axis,
    draw_choropleth_axis,
    draw_support_acz_axis,
    prepare_geography,
)
from .outputs import OutputRecord, OutputWriter, require_exact_columns
from .paths import ProjectPaths
from .presentation import FigureSpecification, load_figure_specs
from .publication_sources import load_publication_authorities
from .registers import artefact_registry, figure_registry, result_registry, table_registry
from .secondary_clusters import EXTERNAL_RESULTS_REQUIRED, SecondaryInputRun, build_secondary_input_run
from .style import PublicationStyle
from .grid_rendering import (
    add_panel_labels,
    apply_axis_label_padding,
    apply_grid_spacing,
    build_horizontal_gutter_axes,
    build_grid_figure,
    build_vertical_band_axes,
    ensure_vertical_band_xlabel_clearance,
)
from .validation import DataContractSummary, validate_data_authorities


class PublicationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublicationRun:
    run_dir: Path
    table_registry: pd.DataFrame
    figure_registry: pd.DataFrame
    result_registry: pd.DataFrame
    artefact_registry: pd.DataFrame
    manifests: dict[str, dict]
    deferred_outputs: dict[str, str]
    secondary_execution_state: str


_SECTION_BY_RQ = {
    "GENERAL": "00_scaffold",
    "RQ1": "01_rq1_spatial_scale",
    "RQ2": "02_rq2_temporal_robustness",
    "RQ3": "03_rq3_observability",
    "INTEGRATED_RQ1_RQ2": "90_integrated",
    "SECONDARY": "04_secondary_concentration",
}


def _section(rq: str) -> str:
    try:
        return _SECTION_BY_RQ[rq]
    except KeyError as exc:
        raise PublicationError(f"No publication section for RQ family {rq!r}") from exc


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return [{str(k): v for k, v in row.items()} for row in clean.to_dict(orient="records")]


def _write_frame(
    writer: OutputWriter,
    relative: str,
    frame: pd.DataFrame,
    *,
    role: str,
    exact_columns: tuple[str, ...] | None = None,
) -> OutputRecord:
    actual = tuple(str(c) for c in frame.columns)
    columns = require_exact_columns(actual, exact_columns, context=relative) if exact_columns else actual
    return writer.write_csv(relative, _records(frame), columns=columns, role=role)


def _write_configured_tables(
    writer: OutputWriter,
    bundle: ConfigurationBundle,
    context: Mapping[str, pd.DataFrame],
    *,
    external_state: str,
) -> tuple[dict[str, OutputRecord], dict[str, str]]:
    records: dict[str, OutputRecord] = {}
    deferred: dict[str, str] = {}
    for spec in bundle.output.tables:
        if spec.builder != "dataframe_csv":
            raise PublicationError(f"Unsupported publication table builder {spec.builder!r}")
        frame = context.get(spec.source_attribute)
        if frame is None:
            if spec.requires_results_validated and external_state == EXTERNAL_RESULTS_REQUIRED:
                deferred[spec.output_id] = EXTERNAL_RESULTS_REQUIRED
                continue
            raise PublicationError(f"Publication source {spec.source_attribute!r} unavailable for {spec.output_id}")
        missing = [column for column in spec.required_columns if column not in frame.columns]
        if missing:
            raise PublicationError(f"{spec.output_id} source missing governed columns: {missing!r}")
        selected = frame.loc[:, list(spec.required_columns)].copy()
        records[spec.output_id] = _write_frame(
            writer,
            f"{_section(spec.rq)}/tables/{spec.output_id}.csv",
            selected,
            role=spec.role,
            exact_columns=spec.required_columns,
        )
    return records, deferred


def _mask(summary: DataContractSummary, name: str):
    if name == "long_run":
        return summary.long_run_mask
    if name == "paired":
        return summary.paired_mask
    raise PublicationError(f"Unknown analytical mask {name!r}")


def _cluster_membership_map(source: pd.DataFrame, summary: DataContractSummary, *, products: tuple[str, ...]) -> pd.DataFrame:
    """Project genuine parsed cluster membership onto the full governed map support."""
    rows: list[pd.DataFrame] = []
    for product in products:
        mask = _mask(summary, "long_run" if product == products[0] else "paired")
        m = mask.units[["unit_id", "eligible", "exclusion_reasons"]].copy()
        subset = source.loc[source["product"].astype(str).eq(product)].copy()
        grouped = (
            subset.groupby("unit_id", sort=True, observed=True)["cluster_id"]
            .agg(lambda values: "|".join(sorted({str(v) for v in values})))
            .rename("cluster_ids").reset_index()
        ) if not subset.empty else pd.DataFrame(columns=["unit_id", "cluster_ids"])
        out = m.merge(grouped, on="unit_id", how="left", validate="one_to_one")
        eligible = out["eligible"].astype(bool)
        member = eligible & out["cluster_ids"].fillna("").astype(str).ne("")
        out["product"] = product
        out["support_status"] = np.where(~eligible, "excluded", np.where(member, "valid_nonzero", "valid_zero"))
        out["value"] = np.where(member, 1.0, np.where(eligible, 0.0, np.nan))
        out["cluster_ids"] = out["cluster_ids"].fillna("")
        rows.append(out[["product","unit_id","support_status","value","cluster_ids","exclusion_reasons"]])
    return pd.concat(rows, ignore_index=True).sort_values(["product","unit_id"]).reset_index(drop=True)


def _figure_data(
    spec: FigureSpecification,
    *,
    context: Mapping[str, pd.DataFrame],
    summary: DataContractSummary,
) -> pd.DataFrame | None:
    source = context.get(spec.source_attribute)
    if spec.data_builder == "source_frame":
        return None if source is None else source.copy()
    if spec.data_builder == "cluster_membership_map":
        if source is None:
            return None
        # A local/live continuation may materialise either complete map-ready
        # rows or raw cluster membership.  Both are accepted explicitly.
        if set(spec.required_columns).issubset(source.columns):
            return source.loc[:, list(spec.required_columns)].copy()
        panel_order = tuple(str(x) for x in spec.renderer_options["panel_order"])
        return _cluster_membership_map(source, summary, products=panel_order)
    raise PublicationError(f"Unsupported publication figure-data builder {spec.data_builder!r}")


def validate_figure_data(spec: FigureSpecification, frame: pd.DataFrame, *, allow_empty: bool=False) -> None:
    require_exact_columns(tuple(frame.columns), spec.required_columns, context=spec.figure_id)
    if frame.empty and not allow_empty:
        raise PublicationError(f"{spec.figure_id} figure source is empty")
    if "support_status" in frame.columns and not frame.empty:
        allowed = {"valid_nonzero", "valid_zero", "excluded"}
        populated = frame["support_status"].dropna().astype(str)
        if not set(populated).issubset(allowed):
            raise PublicationError(f"{spec.figure_id} contains invalid support-status values")
        if "value" in frame.columns:
            excluded = frame["support_status"].astype(str).eq("excluded")
            if frame.loc[excluded, "value"].notna().any():
                raise PublicationError(f"{spec.figure_id} excluded units must not carry plotted values")


def _figure_title(spec: FigureSpecification, style: PublicationStyle) -> str:
    return spec.title if style.title_inside_figure else ""


def _composite_render(
    spec: FigureSpecification,
    frame: pd.DataFrame,
    *,
    authorities: DataAuthorities,
    style: PublicationStyle,
) -> RenderedFigure:
    """Render configured heterogeneous panels directly into one GridSpec Figure."""
    opts = spec.renderer_options
    panel_column = str(opts["panel_column"])
    order = [str(x) for x in opts["panel_order"]]
    renderers = [str(x) for x in opts["panel_renderers"]]
    labels = list(opts.get("panel_colorbar_labels", [""] * len(order)))
    cmaps = list(opts.get("panel_colormaps", ["viridis"] * len(order)))
    expected = list(opts.get("panel_expected_rows", []))
    if not (len(order) == len(renderers) == len(labels) == len(cmaps) == spec.panel_count):
        raise PublicationError(
            f"{spec.figure_id} composite panel configuration must match panel_count={spec.panel_count}"
        )
    layout = style.grid_for(spec.layout_role)
    if len(layout.data_cells) != spec.panel_count:
        raise PublicationError(f"{spec.figure_id} grid data-cell count does not match panel_count")
    map_authority = prepare_geography(authorities.district_geometry, authorities.acz_geometry)
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
        apply_grid_spacing(grid.figure, layout, style=style)
        label_axes: list[Axes] = []
        y_label_padding_overrides: list[tuple[Axes, float]] = []
        for idx, (panel_id, renderer_id) in enumerate(zip(order, renderers, strict=True)):
            panel = frame.loc[frame[panel_column].astype(str).eq(panel_id)].copy()
            if panel.empty:
                plt.close(grid.figure)
                raise PublicationError(f"{spec.figure_id} panel {panel_id!r} has no rows")
            if expected and int(expected[idx]) != len(panel):
                plt.close(grid.figure)
                raise PublicationError(
                    f"{spec.figure_id} panel {panel_id!r} expected {expected[idx]} rows; got {len(panel)}"
                )
            ax = grid.data_axes[idx]
            if renderer_id == "support_acz_map":
                realised = draw_support_acz_axis(
                    grid.figure, ax, map_authority, panel, style=style
                )
                label_axes.append(realised.map_ax)
            elif renderer_id == "acz_choropleth":
                realised = draw_acz_choropleth_axis(
                    grid.figure,
                    ax,
                    map_authority,
                    panel,
                    value="value",
                    colorbar_label=str(labels[idx]),
                    style=style,
                    cmap=str(cmaps[idx]),
                )
                label_axes.append(realised.map_ax)
            elif renderer_id == "choropleth":
                realised = draw_choropleth_axis(
                    grid.figure,
                    ax,
                    map_authority,
                    panel,
                    value="value",
                    colorbar_label=str(labels[idx]),
                    style=style,
                    cmap=str(cmaps[idx]),
                )
                label_axes.append(realised.map_ax)
            elif renderer_id == "categorical_map":
                realised = draw_categorical_axis(
                    grid.figure, ax, map_authority, panel, category="local_class", style=style
                )
                label_axes.append(realised.map_ax)
            elif renderer_id == "seasonality_lines":
                banded = build_vertical_band_axes(
                    grid.figure,
                    ax,
                    band_fraction=float(opts["seasonality_legend_band_fraction"]),
                    gap_fraction=float(opts["seasonality_legend_gap_fraction"]),
                    horizontal_inset_fraction=float(
                        opts["seasonality_horizontal_inset_fraction"]
                    ),
                    gid_prefix="f3-seasonality",
                )
                label_axes.append(banded.plot_ax)
                y_label_padding_overrides.append(
                    (banded.plot_ax, float(opts["seasonality_y_label_padding_pt"]))
                )
                draw_seasonality_lines(
                    banded.plot_ax,
                    panel,
                    xlabel=str(spec.panel_xlabels[idx] or ""),
                    ylabel=str(spec.panel_ylabels[idx] or ""),
                    style=style,
                    legend_ax=banded.band_ax,
                    legend_ncol=int(opts["seasonality_legend_ncol"]),
                )
            elif renderer_id == "stacked_proportion":
                banded = build_vertical_band_axes(
                    grid.figure,
                    ax,
                    band_fraction=float(opts["state_legend_band_fraction"]),
                    gap_fraction=float(opts["state_legend_gap_fraction"]),
                    gid_prefix="f5-four-state",
                )
                label_axes.append(banded.plot_ax)
                state_order = list(dict.fromkeys(panel["state"].astype(str).tolist()))
                draw_stacked_proportions(
                    banded.plot_ax,
                    panel,
                    category="parent_code",
                    state="state",
                    proportion="proportion",
                    state_order=state_order,
                    ylabel=str(spec.panel_ylabels[idx] or "Proportion"),
                    style=style,
                    legend_ax=banded.band_ax,
                    display_aliases={
                        str(k): str(v) for k, v in opts["state_display_aliases"].items()
                    },
                    legend_ncol=int(opts["state_legend_ncol"]),
                )
            elif renderer_id == "coefficient_or_plot":
                guttered = build_horizontal_gutter_axes(
                    grid.figure,
                    ax,
                    label_fraction=float(opts["effect_label_gutter_fraction"]),
                    gap_fraction=float(opts["effect_label_gap_fraction"]),
                    gid_prefix="f5-focal-effects",
                )
                label_axes.append(guttered.label_ax)
                draw_coefficient_or_plot(
                    guttered.plot_ax,
                    panel,
                    xlabel=str(spec.panel_xlabels[idx] or "Adjusted odds ratio"),
                    style=style,
                    label="term",
                    estimate="adjusted_or",
                    low="or_lower_95",
                    high="or_upper_95",
                    order=None,
                    label_ax=guttered.label_ax,
                    display_aliases={
                        str(k): str(v) for k, v in opts["effect_display_aliases"].items()
                    },
                    vertical_padding_rows=style.geometry.effect_vertical_padding_rows,
                )
            else:
                plt.close(grid.figure)
                raise PublicationError(f"Unsupported composite panel renderer {renderer_id!r}")
        add_panel_labels(tuple(label_axes), style=style)
        apply_axis_label_padding(tuple(label_axes), style=style)
        for axis, padding_pt in y_label_padding_overrides:
            axis.yaxis.labelpad = padding_pt
        return export_figure(grid.figure, style)


def _trajectory_grid_render(
    spec: FigureSpecification,
    frame: pd.DataFrame,
    *,
    style: PublicationStyle,
) -> RenderedFigure:
    opts = spec.renderer_options
    x = str(opts["x"])
    y = str(opts["y"])
    group = str(opts["group"])
    slope = str(opts["slope"])
    annotation_fields = tuple(str(value) for value in opts["annotation_fields"])
    required = [x, y, group, slope, *annotation_fields]
    missing = sorted(set(required).difference(frame.columns))
    if missing or frame.empty:
        raise PublicationError(f"{spec.figure_id} trajectory source is incomplete: {missing!r}")
    observed_groups = list(dict.fromkeys(frame[group].astype(str).tolist()))
    configured_order = opts.get("panel_order")
    groups = [str(value) for value in configured_order] if configured_order is not None else observed_groups
    if len(groups) != spec.panel_count:
        raise PublicationError(
            f"{spec.figure_id} requires {spec.panel_count} trajectory groups; got {len(groups)}"
        )
    if set(groups) != set(observed_groups):
        raise PublicationError(
            f"{spec.figure_id} configured trajectory groups do not match governed source groups"
        )
    layout = style.grid_for(spec.layout_role)
    trajectory_styles = opts.get("trajectory_styles", {})
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
        apply_grid_spacing(grid.figure, layout, style=style)
        for idx, (ax, key) in enumerate(zip(grid.data_axes, groups, strict=True)):
            panel = frame.loc[frame[group].astype(str).eq(key)].copy()
            draw_trajectory_panel(
                ax,
                panel,
                x=x,
                y=y,
                slope=slope,
                annotation_fields=annotation_fields,
                group_label=key,
                xlabel=str(spec.panel_xlabels[idx] or (spec.xlabel if idx == spec.panel_count - 1 else "")),
                ylabel=str(spec.panel_ylabels[idx] or ""),
                style=style,
                trajectory_styles=trajectory_styles,
            )
        auxiliary_key = opts.get("auxiliary_key")
        if auxiliary_key is not None:
            cell_id = str(auxiliary_key["cell_id"])
            try:
                aux_ax = grid.auxiliary_axes[cell_id]
            except KeyError as exc:
                raise PublicationError(f"{spec.figure_id} auxiliary key cell {cell_id!r} is not configured") from exc
            draw_shared_trajectory_key(
                aux_ax,
                entries=auxiliary_key["entries"],
                style=style,
                trajectory_styles=trajectory_styles,
            )
        if spec.ylabel:
            grid.figure.text(
                float(opts["shared_ylabel_x_fraction"]),
                0.5,
                str(spec.ylabel),
                rotation=90,
                ha="center",
                va="center",
                fontsize=style.axis_label_font,
                gid="f4-shared-ylabel",
            )
        if _figure_title(spec, style):
            grid.figure.suptitle(_figure_title(spec, style))
        add_panel_labels(grid.data_axes, style=style)
        apply_axis_label_padding(grid.data_axes, style=style)
        return export_figure(grid.figure, style)


def _district_seasonal_grid_render(
    spec: FigureSpecification,
    frame: pd.DataFrame,
    *,
    style: PublicationStyle,
) -> RenderedFigure:
    if spec.panel_count != 3:
        raise PublicationError("District seasonal diagnostics require three configured data panels")
    pivot, summary = district_seasonal_components(frame)
    layout = style.grid_for(spec.layout_role)
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
        apply_grid_spacing(grid.figure, layout, style=style)
        opts = spec.renderer_options
        banded = build_vertical_band_axes(
            grid.figure,
            grid.data_axes[0],
            band_fraction=style.geometry.heatmap_colorbar_band_fraction,
            gap_fraction=style.geometry.heatmap_colorbar_gap_fraction,
            gid_prefix="s1-heatmap",
        )
        image = draw_district_seasonal_heatmap(
            banded.plot_ax,
            pivot,
            xlabel=str(spec.panel_xlabels[0] or ""),
            ylabel=str(spec.panel_ylabels[0] or ""),
        )
        banded.band_ax.set_axis_on()
        banded.band_ax.set_yticks([])
        colorbar = grid.figure.colorbar(image, cax=banded.band_ax, orientation="horizontal")
        colorbar.set_label("Share of district long-run burned area")
        colorbar.ax.set_gid("nonmap-colorbar")
        draw_circular_mean_timing(
            grid.data_axes[1],
            summary,
            xlabel=str(spec.panel_xlabels[1] or ""),
            ylabel=str(spec.panel_ylabels[1] or ""),
            style=style,
        )
        draw_resultant_length_by_group(
            grid.data_axes[2],
            summary,
            xlabel=str(spec.panel_xlabels[2] or ""),
            ylabel=str(spec.panel_ylabels[2] or ""),
        )
        grid.data_axes[1].grid(alpha=style.grid_alpha)
        grid.data_axes[2].grid(axis="y", alpha=style.grid_alpha)
        panel_axes = (banded.plot_ax, grid.data_axes[1], grid.data_axes[2])
        add_panel_labels(panel_axes, style=style)
        apply_axis_label_padding(panel_axes, style=style)
        ensure_vertical_band_xlabel_clearance(grid.figure, banded)
        return export_figure(grid.figure, style)


def _render(spec: FigureSpecification, frame: pd.DataFrame, *, authorities: DataAuthorities, style: PublicationStyle) -> RenderedFigure:
    opts = spec.renderer_options
    if spec.renderer == "grid_composite":
        return _composite_render(spec, frame, authorities=authorities, style=style)
    if spec.renderer == "grid_trajectory_with_sen":
        return _trajectory_grid_render(spec, frame, style=style)
    if spec.renderer == "cluster_maps_grid":
        authority = prepare_geography(authorities.district_geometry, authorities.acz_geometry)
        return cluster_maps_grid(
            authority,
            frame,
            product_column=str(opts["panel_column"]),
            panel_order=[str(x) for x in opts["panel_order"]],
            style=style,
            layout=style.grid_for(spec.layout_role),
            figure_size=style.dimensions_for(spec.layout_role),
        )
    if spec.renderer == "cluster_recurrence_maps_grid":
        authority = prepare_geography(authorities.district_geometry, authorities.acz_geometry)
        return cluster_recurrence_maps_grid(
            authority,
            frame,
            product_column=str(opts["panel_column"]),
            panel_order=[str(x) for x in opts["panel_order"]],
            value_column=str(opts["value_column"]),
            panel_titles=[str(x) for x in opts["panel_titles"]],
            cmap=str(opts["cmap"]),
            colorbar_label=str(opts["colorbar_label"]),
            colorbar_labelpad_pt=float(opts["colorbar_labelpad_pt"]),
            style=style,
            layout=style.grid_for(spec.layout_role),
            figure_size=style.dimensions_for(spec.layout_role),
        )
    if spec.renderer == "grid_district_seasonal_diagnostics":
        return _district_seasonal_grid_render(spec, frame, style=style)
    raise PublicationError(f"Unsupported publication renderer {spec.renderer!r}")

def _source_tables(spec: FigureSpecification, bundle: ConfigurationBundle) -> list[str]:
    matches=[f"{item.output_id}.csv" for item in bundle.output.tables if item.source_attribute==spec.source_attribute]
    return matches


def _write_figure_bundle(
    writer: OutputWriter, *, spec: FigureSpecification, frame: pd.DataFrame,
    rendered: RenderedFigure | None, bundle: ConfigurationBundle, availability: str,
) -> dict:
    section=_section(spec.rq)
    fd=_write_frame(writer,f"{section}/figure_data/{spec.figure_data_identity}",frame,role=spec.role,exact_columns=spec.required_columns)
    images=[]
    if rendered is not None:
        png=writer.write_bytes(f"{section}/figures/{spec.figure_id}.png",rendered.png,role=spec.role)
        pdf=writer.write_bytes(f"{section}/figures/{spec.figure_id}.pdf",rendered.pdf,role=spec.role)
        images=[{"format":"png","path":png.path,"sha256":png.sha256,"size_bytes":png.size_bytes},{"format":"pdf","path":pdf.path,"sha256":pdf.sha256,"size_bytes":pdf.size_bytes}]
    manifest={
        "schema_version":bundle.analysis.schema_version,"figure_id":spec.figure_id,"role":spec.role,
        "availability":availability,"source_attribute":spec.source_attribute,"source_tables":_source_tables(spec,bundle),
        "presentation":{"layout_role":spec.layout_role,"renderer":spec.renderer,"data_builder":spec.data_builder,"xlabel":spec.xlabel,"ylabel":spec.ylabel,"colorbar_label":spec.colorbar_label,"panel_count":spec.panel_count,"panel_xlabels":list(spec.panel_xlabels),"panel_ylabels":list(spec.panel_ylabels),"embedded_notes":False,"title_inside_figure":False},
        "figure_data":{"path":fd.path,"sha256":fd.sha256,"size_bytes":fd.size_bytes,"rows":int(len(frame)),"columns":list(frame.columns)},
        "images":images,
        "render":None if rendered is None else {"dpi":rendered.dpi,"width_in":rendered.width_in,"height_in":rendered.height_in},
        "configuration_sha256":bundle.configuration_sha256,
    }
    rec=writer.write_json(f"{section}/manifests/{spec.figure_id}.manifest.json",manifest,role=spec.role)
    manifest["manifest_path"]=rec.path; manifest["manifest_sha256"]=rec.sha256
    return manifest


def _registry_authorities(context: Mapping[str,pd.DataFrame]) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    spatial=context["supplement_s3_spatial"]
    g=spatial.loc[spatial["record_type"].astype(str).eq("global_moran_national")].copy()
    if len(g)!=1: raise PublicationError("Publication source requires exactly one national Global Moran row")
    rq1=pd.DataFrame([{"specification_role":"primary","morans_i":float(g.iloc[0]["global_morans_i"]),"permutation_p":float(g.iloc[0]["global_permutation_p"]),"n_effective":int(g.iloc[0]["n_effective"])}])
    s4=context["supplement_s4_rq2"]
    rq2=s4.drop_duplicates("parent_code")[["parent_code","sen_slope","raw_p","bh_q"]].copy()
    realised_n = s4.groupby("parent_code", observed=True)["year"].nunique()
    rq2["n"] = rq2["parent_code"].map(realised_n).astype(int)
    t2=context["table2_rq3_model"]
    rq3=t2.loc[t2["predictor_role"].astype(str).eq("focal")].copy()
    return rq1,rq2,rq3


def build_publication_run(
    *, paths: ProjectPaths | None=None, run_id: str="publication_reference",
    bundle: ConfigurationBundle | None=None, authorities: DataAuthorities | None=None,
    data_contract: DataContractSummary | None=None, secondary_run: SecondaryInputRun | None=None,
    run_local_publication_sources: str | Path | None = None,
) -> PublicationRun:
    governed=paths or ProjectPaths.discover(); bundle=bundle or load_configuration_bundle(governed.root/"config")
    assert_execution_ready(bundle.analysis.to_dict(),bundle.methods,"rq2")
    authorities=authorities or load_data_authorities(governed,bundle.data_schema)
    data_contract=data_contract or validate_data_authorities(authorities,bundle.analysis,bundle.data_schema)
    context=load_publication_authorities(
        paths=governed, run_local_source_dir=run_local_publication_sources
    )
    secondary_run=secondary_run or build_secondary_input_run(paths=governed,bundle=bundle,authorities=authorities,run_id=f"{run_id}_secondary_interface")
    run_dir=governed.create_run(run_id); writer=OutputWriter(run_dir,bundle.output)
    table_records,deferred=_write_configured_tables(writer,bundle,context,external_state=secondary_run.execution_state)
    style=PublicationStyle.from_contract(bundle.figure)
    if not bundle.figure.source_data_policy["required_for_manuscript_figures"]: raise PublicationError("Publication figure source-data policy must remain enabled")
    if style.map.embedded_notes: raise PublicationError("Embedded explanatory notes are prohibited")
    manifests={}
    for spec in load_figure_specs(bundle.figure):
        frame=_figure_data(spec,context=context,summary=data_contract)
        if frame is None:
            if not (spec.requires_results_validated and secondary_run.execution_state==EXTERNAL_RESULTS_REQUIRED):
                raise PublicationError(f"Figure source unavailable for {spec.figure_id}")
            empty=pd.DataFrame(columns=list(spec.required_columns)); validate_figure_data(spec,empty,allow_empty=True)
            manifests[spec.figure_id]=_write_figure_bundle(writer,spec=spec,frame=empty,rendered=None,bundle=bundle,availability=EXTERNAL_RESULTS_REQUIRED)
            deferred[spec.figure_id]=EXTERNAL_RESULTS_REQUIRED; continue
        frame=frame.loc[:,list(spec.required_columns)].copy(); validate_figure_data(spec,frame)
        rendered=_render(spec,frame,authorities=authorities,style=style)
        manifests[spec.figure_id]=_write_figure_bundle(writer,spec=spec,frame=frame,rendered=rendered,bundle=bundle,availability="AVAILABLE")
    treg=table_registry(table_records,output_contract=bundle.output,deferred=deferred)
    freg=figure_registry(manifests,figure_contract=bundle.figure)
    rq1_reg,rq2_reg,rq3_reg=_registry_authorities(context)
    rreg=result_registry(rq1_reg,rq2_reg,rq3_reg,output_contract=bundle.output,figure_contract=bundle.figure)
    _write_frame(writer,"90_integrated/T_TABLE_REGISTRY.csv",treg,role="internal_authority")
    _write_frame(writer,"90_integrated/T_FIGURE_REGISTRY.csv",freg,role="internal_authority")
    _write_frame(writer,"90_integrated/T_RESULT_REGISTRY.csv",rreg,role="internal_authority")
    areg=artefact_registry(run_dir); _write_frame(writer,"90_integrated/T_ARTEFACT_REGISTRY.csv",areg,role="internal_authority")
    return PublicationRun(run_dir,treg,freg,rreg,areg,manifests,deferred,secondary_run.execution_state)
