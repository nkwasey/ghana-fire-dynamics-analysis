from __future__ import annotations

from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.mapping import build_cluster_recurrence_map_figure, cluster_recurrence_maps_grid, prepare_geography
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.publication_sources import PublicationSourceError, build_cluster_recurrence_source
from rp1_analysis_v1.style import PublicationStyle
from rp1_analysis_v1.validation import validate_data_authorities

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def governed():
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    style = PublicationStyle.from_contract(bundle.figure)
    geography = prepare_geography(authorities.district_geometry, authorities.acz_geometry)
    return bundle, authorities, summary, style, geography


def _eligible_ids(summary, product: str) -> list[str]:
    mask = summary.long_run_mask if product == "mcd64a1" else summary.paired_mask
    return mask.units.loc[mask.units["eligible"].astype(bool), "unit_id"].astype(str).tolist()


def test_recurrence_is_distinct_cluster_nunique_and_duplicates_cannot_inflate(governed) -> None:
    _, _, summary, _, _ = governed
    mcd = _eligible_ids(summary, "mcd64a1")
    viirs = _eligible_ids(summary, "viirs")
    source = pd.DataFrame(
        [
            {"product": "mcd64a1", "unit_id": mcd[0], "cluster_id": 1},
            {"product": "mcd64a1", "unit_id": mcd[0], "cluster_id": 1},
            {"product": "mcd64a1", "unit_id": mcd[0], "cluster_id": 2},
            {"product": "mcd64a1", "unit_id": mcd[1], "cluster_id": 2},
            {"product": "viirs", "unit_id": viirs[0], "cluster_id": 5},
            {"product": "viirs", "unit_id": viirs[0], "cluster_id": 5},
        ]
    )
    out = build_cluster_recurrence_source(source, summary)
    mcd0 = out.loc[(out["product"].eq("mcd64a1")) & (out["unit_id"].eq(mcd[0]))].iloc[0]
    mcd1 = out.loc[(out["product"].eq("mcd64a1")) & (out["unit_id"].eq(mcd[1]))].iloc[0]
    viirs0 = out.loc[(out["product"].eq("viirs")) & (out["unit_id"].eq(viirs[0]))].iloc[0]
    assert int(mcd0["significant_cluster_count"]) == 2
    assert int(mcd1["significant_cluster_count"]) == 1
    assert int(mcd0["total_significant_clusters"]) == 2
    assert float(mcd0["significant_cluster_fraction"]) == pytest.approx(1.0)
    assert float(mcd1["significant_cluster_fraction"]) == pytest.approx(0.5)
    assert int(viirs0["significant_cluster_count"]) == 1
    assert int(viirs0["total_significant_clusters"]) == 1


def test_recurrence_zero_and_excluded_semantics_are_distinct(governed) -> None:
    _, _, summary, _, _ = governed
    mcd = _eligible_ids(summary, "mcd64a1")
    viirs = _eligible_ids(summary, "viirs")
    source = pd.DataFrame([
        {"product": "mcd64a1", "unit_id": mcd[0], "cluster_id": 1},
        {"product": "viirs", "unit_id": viirs[0], "cluster_id": 1},
    ])
    out = build_cluster_recurrence_source(source, summary)
    zero = out.loc[(out["product"].eq("mcd64a1")) & (out["unit_id"].eq(mcd[1]))].iloc[0]
    excluded_id = summary.long_run_mask.units.loc[~summary.long_run_mask.units["eligible"], "unit_id"].astype(str).iloc[0]
    excluded = out.loc[(out["product"].eq("mcd64a1")) & (out["unit_id"].eq(excluded_id))].iloc[0]
    assert zero["support_status"] == "valid_zero"
    assert int(zero["significant_cluster_count"]) == 0
    assert float(zero["significant_cluster_fraction"]) == pytest.approx(0.0)
    assert excluded["support_status"] == "excluded"
    assert pd.isna(excluded["significant_cluster_count"])
    assert pd.isna(excluded["significant_cluster_fraction"])
    assert str(excluded["exclusion_reasons"])


def test_recurrence_fails_closed_for_non_significant_wrong_product_and_excluded_membership(governed) -> None:
    _, _, summary, _, _ = governed
    mcd = _eligible_ids(summary, "mcd64a1")[0]
    with pytest.raises(PublicationSourceError, match="Non-significant"):
        build_cluster_recurrence_source(
            pd.DataFrame([{"product": "mcd64a1", "unit_id": mcd, "cluster_id": 1, "p_value": 0.2}]),
            summary,
        )
    with pytest.raises(PublicationSourceError, match="outside the recurrence projection"):
        build_cluster_recurrence_source(
            pd.DataFrame([{"product": "other", "unit_id": mcd, "cluster_id": 1}]),
            summary,
        )
    excluded_id = summary.long_run_mask.units.loc[~summary.long_run_mask.units["eligible"], "unit_id"].astype(str).iloc[0]
    with pytest.raises(PublicationSourceError, match="excluded mcd64a1"):
        build_cluster_recurrence_source(
            pd.DataFrame([{"product": "mcd64a1", "unit_id": excluded_id, "cluster_id": 1}]),
            summary,
        )


def test_recurrence_renderer_has_equal_map_viewports_one_shared_scale_and_exact_canvas(governed) -> None:
    bundle, _, summary, style, geography = governed
    mcd = _eligible_ids(summary, "mcd64a1")
    viirs = _eligible_ids(summary, "viirs")
    source_rows = []
    for cid in range(1, 5):
        for uid in mcd[:cid + 1]:
            source_rows.append({"product": "mcd64a1", "unit_id": uid, "cluster_id": cid})
    for cid in range(1, 8):
        for uid in viirs[:cid + 1]:
            source_rows.append({"product": "viirs", "unit_id": uid, "cluster_id": cid})
    recurrence = build_cluster_recurrence_source(pd.DataFrame(source_rows), summary)
    spec = next(x for x in bundle.figure.figures if x.figure_id == "F6")
    fig, panels, shared = build_cluster_recurrence_map_figure(
        geography,
        recurrence,
        product_column="product",
        panel_order=("mcd64a1", "viirs"),
        value_column="significant_cluster_count",
        panel_titles=("MCD64A1", "VIIRS"),
        cmap="cividis",
        colorbar_label="Distinct significant clusters containing district",
        colorbar_labelpad_pt=2.0,
        style=style,
        layout=bundle.figure.grid_layouts[spec.layout_role],
        figure_size=style.dimensions_for(spec.layout_role),
    )
    try:
        fig.canvas.draw()
        a, b = (panel.map_ax for panel in panels)
        ba, bb = a.get_position().bounds, b.get_position().bounds
        assert ba[2] == pytest.approx(bb[2], abs=1e-12)
        assert ba[3] == pytest.approx(bb[3], abs=1e-12)
        assert ba[1] == pytest.approx(bb[1], abs=1e-12)
        assert a.get_xlim() == pytest.approx(b.get_xlim(), abs=1e-9)
        assert a.get_ylim() == pytest.approx(b.get_ylim(), abs=1e-9)
        assert shared.get_gid() == "map-shared-cluster-recurrence-colorbar"
        assert len([ax for ax in fig.axes if ax.get_gid() == "map-shared-cluster-recurrence-colorbar"]) == 1
        assert fig.get_size_inches()[0] == pytest.approx(20 / 2.54, abs=1e-12)
        assert fig.get_size_inches()[1] == pytest.approx(15 / 2.54, abs=1e-12)
    finally:
        plt.close(fig)
    rendered = cluster_recurrence_maps_grid(
        geography,
        recurrence,
        product_column="product",
        panel_order=("mcd64a1", "viirs"),
        value_column="significant_cluster_count",
        panel_titles=("MCD64A1", "VIIRS"),
        cmap="cividis",
        colorbar_label="Distinct significant clusters containing district",
        colorbar_labelpad_pt=2.0,
        style=style,
        layout=bundle.figure.grid_layouts[spec.layout_role],
        figure_size=style.dimensions_for(spec.layout_role),
    )
    image = Image.open(BytesIO(rendered.png)).convert("RGB")
    assert image.size == (2362, 1772)
    width, height = image.size
    edge_pixels = []
    for x in range(width):
        edge_pixels.extend(image.getpixel((x, y)) for y in (0, 1, height - 2, height - 1))
    for y in range(height):
        edge_pixels.extend(image.getpixel((x, y)) for x in (0, 1, width - 2, width - 1))
    assert all(pixel == (255, 255, 255) for pixel in edge_pixels)
    assert len(rendered.pdf) > 10_000
