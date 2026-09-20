"""Standalone RQ3 presentation renderers.

These renderers consume already-governed RQ3 presentation sources and
supporting semantic authorities. They do not refit the penalised GEE, reverse
the conditional outcome, convert odds ratios into probabilities, or derive any
scientific values from raster pixels.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from .contracts import FigureSpecificationContract, PresentationExportSpecificationContract
from .figures import FigureRenderError, RenderedFigure, draw_coefficient_or_plot, draw_stacked_proportions, export_figure
from .grid_rendering import build_horizontal_gutter_axes, build_vertical_band_axes
from .mapping import GhanaMapAuthority, MappingError, choropleth, prepare_geography
from .style import PublicationStyle


class _GeometryAuthorityLike(Protocol):
    members: Mapping[str, tuple[Path, ...]]


class _RegistryLike(Protocol):
    semantic_styles: Mapping[str, Any]


class _BundleLike(Protocol):
    figure: Any


class _RunLike(Protocol):
    publication_run: Path


class RenderContextLike(Protocol):
    geometry: _GeometryAuthorityLike
    registry: _RegistryLike
    bundle: _BundleLike
    run: _RunLike
    style: PublicationStyle


_FOUR_STATE_COLUMNS = ("parent_code", "unit_name", "state", "proportion")
_DISTRICT_MISMATCH_COLUMNS = ("unit_id", "unit_name", "parent_code", "support_status", "value")
_FOCAL_EFFECT_COLUMNS = ("term", "adjusted_or", "or_lower_95", "or_upper_95", "p")
_STANDARDISED_PROBABILITY_COLUMNS = (
    "predictor_id",
    "quantile",
    "raw_quantile_value",
    "standardised_probability",
    "n",
    "districts",
)
_EXPECTED_ACZ_CODES = ("CZ", "FZ", "GS", "SS", "TZ")
_EXPECTED_STATES = (
    "both_zero",
    "mcd64a1_positive_viirs_zero",
    "viirs_positive_mcd64a1_zero",
    "both_positive",
)


def _require_columns(frame: pd.DataFrame, required: Sequence[str], *, context: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise FigureRenderError(f"{context} source missing columns: {missing!r}")
    if frame.empty:
        raise FigureRenderError(f"{context} source is empty")


def _shapefile(context: RenderContextLike, geometry_id: str) -> Path:
    try:
        members = context.geometry.members[geometry_id]
    except KeyError as exc:
        raise FigureRenderError(
            f"Renderer requires governed geometry {geometry_id!r}, but it is not configured"
        ) from exc
    shp = tuple(path for path in members if path.suffix.casefold() == ".shp")
    if len(shp) != 1:
        raise FigureRenderError(
            f"Governed geometry {geometry_id!r} must resolve exactly one shapefile; observed {len(shp)}"
        )
    return shp[0]


def _load_geometry(context: RenderContextLike, geometry_id: str) -> gpd.GeoDataFrame:
    path = _shapefile(context, geometry_id)
    try:
        frame = gpd.read_file(path)
    except Exception as exc:  # pragma: no cover
        raise FigureRenderError(f"Unable to read governed geometry {path}") from exc
    if frame.crs is None:
        raise FigureRenderError(f"Governed geometry has no CRS: {path}")
    return frame


def _map_authority(context: RenderContextLike) -> GhanaMapAuthority:
    districts = _load_geometry(context, "district")
    acz = _load_geometry(context, "acz")
    try:
        return prepare_geography(districts, acz)
    except MappingError as exc:
        raise FigureRenderError(f"Governed map authority is invalid: {exc}") from exc


def _configured_colourbar_label(spec: PresentationExportSpecificationContract) -> str:
    prefix = "horizontal colourbar:"
    for annotation in spec.annotation_policy:
        text = str(annotation).strip()
        if text.casefold().startswith(prefix):
            label = text[len(prefix):].strip()
            if label:
                return label
    raise FigureRenderError(f"{spec.export_id} lacks its configured scientific colourbar label")


def _f5_spec(context: RenderContextLike) -> FigureSpecificationContract:
    matches = tuple(item for item in context.bundle.figure.figures if item.figure_id == "F5")
    if len(matches) != 1:
        raise FigureRenderError("RQ3 presentation rendering requires exactly one governed F5 contract")
    spec = matches[0]
    if spec.source_attribute != "cross_product_observability_presentation_source":
        raise FigureRenderError("Governed F5 contract is incompatible with the RQ3 presentation renderer")
    return spec


def _four_state_palette(context: RenderContextLike) -> dict[str, str]:
    raw = context.registry.semantic_styles.get("four_state_categories")
    if not isinstance(raw, Mapping) or not raw:
        raise FigureRenderError("Presentation registry lacks governed four-state colour semantics")
    return {str(key): str(value) for key, value in raw.items()}


def _f5_state_aliases(context: RenderContextLike) -> dict[str, str]:
    opts = _f5_spec(context).renderer_options
    raw = opts.get("state_display_aliases", {})
    if not isinstance(raw, Mapping) or not raw:
        raise FigureRenderError("Governed F5 state display aliases are unavailable")
    return {str(key): str(value) for key, value in raw.items()}


def _f5_effect_aliases(context: RenderContextLike) -> dict[str, str]:
    opts = _f5_spec(context).renderer_options
    raw = opts.get("effect_display_aliases", {})
    if not isinstance(raw, Mapping) or not raw:
        raise FigureRenderError("Governed F5 effect display aliases are unavailable")
    return {str(key): str(value) for key, value in raw.items()}


def _s5_path(context: RenderContextLike) -> Path:
    return context.run.publication_run / "03_rq3_observability" / "tables" / "S5.csv"


def _load_s5(context: RenderContextLike) -> pd.DataFrame:
    path = _s5_path(context)
    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # pragma: no cover
        raise FigureRenderError(f"Unable to read governed RQ3 supplement source {path}") from exc
    if frame.empty:
        raise FigureRenderError("Governed RQ3 supplement source is empty")
    return frame


def _overall_four_state_counts(context: RenderContextLike) -> dict[str, int]:
    s5 = _load_s5(context)
    required = ("record_type", "scope", "state", "count", "denominator_n")
    _require_columns(s5, required, context="RQ3 supplement S5")
    overall = s5.loc[
        s5["record_type"].astype(str).eq("four_state")
        & s5["scope"].astype(str).eq("overall")
    ].copy()
    if len(overall) != 4:
        raise FigureRenderError("Governed overall four-state summary must contain exactly four rows")
    observed_states = tuple(overall["state"].astype(str).tolist())
    if observed_states != _EXPECTED_STATES:
        raise FigureRenderError("Governed overall four-state summary has unexpected state order")
    denominators = pd.to_numeric(overall["denominator_n"], errors="raise").astype(int)
    if not denominators.eq(38595).all():
        raise FigureRenderError("Governed four-state overall denominator must be 38,595")
    counts = pd.to_numeric(overall["count"], errors="raise").astype(int)
    return dict(zip(observed_states, counts, strict=True))


def _overall_model_diagnostics(context: RenderContextLike) -> tuple[int, int, int, int, int]:
    s5 = _load_s5(context)
    required = ("record_type", "diagnostic_name", "diagnostic_value")
    _require_columns(s5, required, context="RQ3 supplement S5")
    diag = s5.loc[s5["record_type"].astype(str).eq("diagnostic")].copy()
    if diag.empty:
        raise FigureRenderError("Governed diagnostic summary is missing")
    lookup = {
        str(row["diagnostic_name"]): row["diagnostic_value"]
        for _, row in diag.iterrows()
    }
    try:
        observations = int(float(lookup["observations"]))
        districts = int(float(lookup["districts"]))
        outcome_y1 = int(float(lookup["outcome_y1"]))
        outcome_y0 = int(float(lookup["outcome_y0"]))
        model_columns = int(float(lookup["model_columns"]))
    except KeyError as exc:
        raise FigureRenderError(f"Governed diagnostic summary is missing {exc.args[0]!r}") from exc
    return observations, districts, outcome_y1, outcome_y0, model_columns


def _normalise_four_state(
    frame: pd.DataFrame,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> pd.DataFrame:
    _require_columns(frame, _FOUR_STATE_COLUMNS, context=spec.export_id)
    work = frame.loc[:, _FOUR_STATE_COLUMNS].copy()
    if len(work) != 20:
        raise FigureRenderError(f"{spec.export_id} requires exactly 20 governed rows; got {len(work)}")
    acz_codes = tuple(str(code) for code in work["parent_code"].drop_duplicates().tolist())
    if acz_codes != _EXPECTED_ACZ_CODES:
        raise FigureRenderError("RQ3 four-state source must preserve governed ACZ order CZ/FZ/GS/SS/TZ")
    state_order = tuple(str(value) for value in spec.category_order.get("values", ()))
    if state_order != _EXPECTED_STATES:
        raise FigureRenderError("RQ3 four-state export must preserve the configured state order")
    palette = _four_state_palette(context)
    if set(state_order) != set(palette):
        raise FigureRenderError("Configured four-state palette is not concordant with the export order")
    work["proportion"] = pd.to_numeric(work["proportion"], errors="raise").astype(float)
    if not work["proportion"].between(0.0, 1.0, inclusive="both").all():
        raise FigureRenderError("RQ3 four-state proportions must lie within 0-1")
    for code, group in work.groupby("parent_code", sort=False, observed=True):
        states = tuple(group["state"].astype(str).tolist())
        if states != state_order:
            raise FigureRenderError(f"RQ3 four-state rows for {code!r} do not preserve the configured state order")
        if len(group) != 4:
            raise FigureRenderError(f"RQ3 four-state rows for {code!r} do not contain all four states")
        total = float(group["proportion"].sum())
        if not np.isclose(total, 1.0, rtol=0.0, atol=1e-9):
            raise FigureRenderError(f"RQ3 four-state proportions for {code!r} must sum to 1")
    return work


def render_rq3_four_state_correspondence(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ3 four-state correspondence renderer requires the governed presentation source")
    work = _normalise_four_state(frame, spec=spec, context=context)
    aliases = _f5_state_aliases(context)
    palette = _four_state_palette(context)
    counts = _overall_four_state_counts(context)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.single_panel)
        banded = build_vertical_band_axes(
            fig,
            ax,
            band_fraction=0.22,
            gap_fraction=0.06,
            gid_prefix="rq3-four-state",
        )
        draw_stacked_proportions(
            banded.plot_ax,
            work,
            category="parent_code",
            state="state",
            proportion="proportion",
            state_order=_EXPECTED_STATES,
            ylabel="Proportion of paired district-months",
            style=context.style,
            legend_ax=banded.band_ax,
            display_aliases=aliases,
            legend_ncol=2,
        )
        for container, state in zip(banded.plot_ax.containers, _EXPECTED_STATES, strict=True):
            colour = palette[state]
            for patch in container.patches:
                patch.set_facecolor(colour)
                patch.set_edgecolor("white")
                patch.set_linewidth(0.4)
        banded.plot_ax.set_xlabel("Agro-climatic zone")
        banded.plot_ax.set_title(spec.label)
        count_text = (
            "Overall paired population n=38,595\n"
            f"Both zero: {counts['both_zero']:,}; "
            f"MCD64A1 only: {counts['mcd64a1_positive_viirs_zero']:,}; "
            f"VIIRS only: {counts['viirs_positive_mcd64a1_zero']:,}; "
            f"Both positive: {counts['both_positive']:,}"
        )
        banded.plot_ax.text(
            0.01,
            0.99,
            count_text,
            transform=banded.plot_ax.transAxes,
            ha="left",
            va="top",
            fontsize=context.style.tick_font,
            color="#333333",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "0.8", "alpha": 0.9},
            gid="rq3-four-state-counts",
        )
        return export_figure(fig, context.style)


def render_rq3_district_mismatch(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ3 district mismatch renderer requires the governed presentation source")
    _require_columns(frame, _DISTRICT_MISMATCH_COLUMNS, context=spec.export_id)
    work = frame.loc[:, _DISTRICT_MISMATCH_COLUMNS].copy()
    if work["unit_id"].astype(str).duplicated().any():
        raise FigureRenderError("RQ3 district mismatch source has duplicate district identifiers")
    if len(work) != 260:
        raise FigureRenderError(f"{spec.export_id} requires the full governed 260-district map universe; got {len(work)}")
    valid = work.loc[~work["support_status"].astype(str).eq("excluded")].copy()
    if len(valid) != 249 or valid["unit_id"].astype(str).nunique() != 249:
        raise FigureRenderError("RQ3 district mismatch source must contain 249 non-excluded districts")
    valid["value"] = pd.to_numeric(valid["value"], errors="raise").astype(float)
    if not valid["value"].between(0.0, 1.0, inclusive="both").all():
        raise FigureRenderError("RQ3 district mismatch values must lie within 0-1 for all supported districts")
    authority = _map_authority(context)
    return choropleth(
        authority,
        work,
        value="value",
        title=spec.label,
        colorbar_label=_configured_colourbar_label(spec),
        style=context.style,
        cmap="viridis",
    )


def _normalise_focal_effects(
    frame: pd.DataFrame,
    *,
    spec: PresentationExportSpecificationContract,
) -> pd.DataFrame:
    _require_columns(frame, _FOCAL_EFFECT_COLUMNS, context=spec.export_id)
    work = frame.loc[:, _FOCAL_EFFECT_COLUMNS].copy()
    if len(work) != 2:
        raise FigureRenderError(f"{spec.export_id} requires exactly two focal association rows; got {len(work)}")
    expected_order = tuple(str(value) for value in spec.category_order.get("values", ()))
    observed_order = tuple(str(value) for value in work["term"].tolist())
    if observed_order != expected_order:
        raise FigureRenderError("RQ3 focal association source does not preserve the configured focal predictor order")
    for column in ("adjusted_or", "or_lower_95", "or_upper_95", "p"):
        work[column] = pd.to_numeric(work[column], errors="raise").astype(float)
    if np.any(work[["adjusted_or", "or_lower_95", "or_upper_95"]].to_numpy(float) <= 0.0):
        raise FigureRenderError("RQ3 focal adjusted odds ratios and confidence intervals must be strictly positive")
    if not work["p"].between(0.0, 1.0, inclusive="both").all():
        raise FigureRenderError("RQ3 focal p-values must lie within 0-1")
    return work


def render_rq3_focal_effects(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ3 focal-effects renderer requires the governed presentation source")
    work = _normalise_focal_effects(frame, spec=spec)
    observations, districts, outcome_y1, outcome_y0, model_columns = _overall_model_diagnostics(context)
    effect_aliases = _f5_effect_aliases(context)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.wide_single_panel)
        gutter = build_horizontal_gutter_axes(
            fig,
            ax,
            label_fraction=0.46,
            gap_fraction=0.02,
            gid_prefix="rq3-focal-effects",
        )
        draw_coefficient_or_plot(
            gutter.plot_ax,
            work,
            xlabel="Adjusted odds ratio per doubling",
            style=context.style,
            label="term",
            estimate="adjusted_or",
            low="or_lower_95",
            high="or_upper_95",
            label_ax=gutter.label_ax,
            display_aliases=effect_aliases,
            vertical_padding_rows=context.style.geometry.effect_vertical_padding_rows,
        )
        gutter.plot_ax.set_title(spec.label)
        gutter.plot_ax.text(
            0.01,
            0.02,
            f"Conditional model population: n={observations:,} VIIRS-positive district-months; {districts} districts\nOutcome Y=1 mapped burned-area absence; Y=0 mapped burned-area presence; design columns={model_columns}",
            transform=gutter.plot_ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=context.style.tick_font,
            color="#333333",
            gid="rq3-focal-footnote",
        )
        for idx, row in enumerate(work.itertuples(index=False)):
            gutter.plot_ax.text(
                0.99,
                float(idx),
                f"OR {row.adjusted_or:.3f} [{row.or_lower_95:.3f}, {row.or_upper_95:.3f}]\np={row.p:.2e}",
                transform=gutter.plot_ax.get_yaxis_transform(),
                ha="right",
                va="center",
                fontsize=context.style.tick_font,
                color="#333333",
                gid=f"rq3-focal-stat-{idx}",
            )
        return export_figure(fig, context.style)


def _normalise_standardised_probabilities(
    frame: pd.DataFrame,
    *,
    spec: PresentationExportSpecificationContract,
) -> dict[str, dict[float, dict[str, float]]]:
    _require_columns(frame, _STANDARDISED_PROBABILITY_COLUMNS, context=spec.export_id)
    work = frame.loc[:, _STANDARDISED_PROBABILITY_COLUMNS].copy()
    if len(work) != 4:
        raise FigureRenderError(f"{spec.export_id} requires exactly four governed standardised-probability rows; got {len(work)}")
    for column in ("quantile", "raw_quantile_value", "standardised_probability", "n", "districts"):
        work[column] = pd.to_numeric(work[column], errors="raise").astype(float)
    if not work["standardised_probability"].between(0.0, 1.0, inclusive="both").all():
        raise FigureRenderError("RQ3 standardised probabilities must lie within 0-1")
    if not work["quantile"].isin([0.25, 0.75]).all():
        raise FigureRenderError("RQ3 standardised-probability rows must be governed Q25/Q75 values")
    if work["n"].nunique() != 1 or int(work["n"].iloc[0]) != 22939:
        raise FigureRenderError("RQ3 standardised-probability source must report n=22,939")
    if work["districts"].nunique() != 1 or int(work["districts"].iloc[0]) != 249:
        raise FigureRenderError("RQ3 standardised-probability source must report 249 districts")
    grouped: dict[str, dict[float, dict[str, float]]] = {}
    for predictor_id, group in work.groupby("predictor_id", sort=False, observed=True):
        if len(group) != 2:
            raise FigureRenderError(f"Predictor {predictor_id!r} must have exactly two governed quantile rows")
        quantiles = tuple(group["quantile"].tolist())
        if quantiles != (0.25, 0.75):
            raise FigureRenderError(f"Predictor {predictor_id!r} does not preserve governed Q25/Q75 order")
        grouped[str(predictor_id)] = {
            float(row.quantile): {
                "raw_quantile_value": float(row.raw_quantile_value),
                "standardised_probability": float(row.standardised_probability),
            }
            for row in group.itertuples(index=False)
        }
    if tuple(grouped) != ("viirs_detection_count", "viirs_mean_frp"):
        raise FigureRenderError("RQ3 standardised-probability source must preserve the governed focal predictor order")
    return grouped


def _predictor_display_name(predictor_id: str) -> str:
    mapping = {
        "viirs_detection_count": "VIIRS detection count",
        "viirs_mean_frp": "Mean VIIRS FRP (MW)",
    }
    try:
        return mapping[predictor_id]
    except KeyError as exc:
        raise FigureRenderError(f"Unsupported governed predictor identity {predictor_id!r}") from exc


def _draw_probability_pair(
    ax: Axes,
    *,
    y: float,
    predictor_id: str,
    pair: Mapping[float, Mapping[str, float]],
    style: PublicationStyle,
) -> None:
    q25 = pair[0.25]
    q75 = pair[0.75]
    p25 = float(q25["standardised_probability"])
    p75 = float(q75["standardised_probability"])
    ax.annotate(
        "",
        xy=(p75, y),
        xytext=(p25, y),
        arrowprops={"arrowstyle": "->", "linewidth": 1.1, "color": "0.25"},
    )
    ax.plot([p25, p75], [y, y], linewidth=1.1, color="0.45", gid=f"rq3-std-line-{predictor_id}")
    ax.plot([p25], [y], marker="o", markersize=4.5, color="black", gid=f"rq3-std-q25-{predictor_id}")
    ax.plot([p75], [y], marker="s", markersize=4.2, color="black", gid=f"rq3-std-q75-{predictor_id}")
    delta_pp = (p75 - p25) * 100.0
    name = _predictor_display_name(predictor_id)
    ax.text(
        -0.02,
        y,
        name,
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="center",
        fontsize=style.tick_font,
        color="#111111",
        clip_on=False,
        gid=f"rq3-std-label-{predictor_id}",
    )
    ax.text(
        p25,
        y + 0.16,
        f"Q25={q25['raw_quantile_value']:.6g}\nP={p25:.3f}",
        ha="center",
        va="bottom",
        fontsize=style.tick_font,
        color="#333333",
        gid=f"rq3-std-q25-text-{predictor_id}",
    )
    ax.text(
        p75,
        y - 0.16,
        f"Q75={q75['raw_quantile_value']:.6g}\nP={p75:.3f}",
        ha="center",
        va="top",
        fontsize=style.tick_font,
        color="#333333",
        gid=f"rq3-std-q75-text-{predictor_id}",
    )
    ax.text(
        0.99,
        y,
        f"Δ={delta_pp:+.1f} pp",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="center",
        fontsize=style.tick_font,
        color="#111111",
        gid=f"rq3-std-delta-{predictor_id}",
    )


def render_rq3_standardised_probabilities(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ3 standardised-probability renderer requires the governed supplement source")
    grouped = _normalise_standardised_probabilities(frame, spec=spec)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.wide_single_panel)
        y_positions = np.array([1.0, 0.0])
        for y, predictor_id in zip(y_positions, grouped, strict=True):
            _draw_probability_pair(ax, y=y, predictor_id=predictor_id, pair=grouped[predictor_id], style=context.style)
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(-0.5, 1.5)
        ax.set_yticks([])
        ax.set_xlabel("Standardised probability of mapped burned-area absence")
        ax.set_title(spec.label)
        ax.grid(axis="x", alpha=context.style.grid_alpha)
        ax.text(
            0.01,
            0.02,
            "Q25/Q75 vary one focal predictor at a time across observed covariates\nConditional model population: n=22,939 VIIRS-positive district-months; 249 districts",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=context.style.tick_font,
            color="#333333",
            gid="rq3-std-footnote",
        )
        fig.tight_layout()
        return export_figure(fig, context.style)


RQ3_PRESENTATION_RENDERERS = {
    "stacked_proportions": render_rq3_four_state_correspondence,
    "coefficient_or_plot": render_rq3_focal_effects,
    "standardised_probability_pairs": render_rq3_standardised_probabilities,
}
