from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

gpd = pytest.importorskip("geopandas")

import mv_firms_panels.stages.prepare_year as py_stage  # noqa: E402
from mv_firms_panels.core.config import load_config  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402

RUN_NATIVE_PLOT_SMOKE = os.environ.get("RP_RUN_NATIVE_PLOT_SMOKE") == "1"
NATIVE_PLOT_SKIP_REASON = (
    "Set RP_RUN_NATIVE_PLOT_SMOKE=1 to run native GeoPandas/Matplotlib rendering smoke tests."
)


def _stub_join_points_to_units(**kwargs):
    """Deterministic stub for join_points_to_units.

    - Assigns unit_id="A1" for all points.
    - Writes level into the points frame.

    This avoids GeoPandas/Shapely spatial join variability in test environments.
    """
    points = kwargs["points"].copy()
    points["level"] = kwargs["level"]
    points["unit_id"] = "A1"
    points["unit_name"] = "Alpha"
    return points


def _polys_by_level(cfg, pts):
    out = {}
    for lvl in cfg.io.inputs.polygons:
        cols = {lvl.unit_id_field: ["A1"], lvl.unit_name_field: ["Alpha"]}
        out[lvl.level] = gpd.GeoDataFrame(cols, geometry=pts.geometry[:1], crs="EPSG:4326")
    return out


def _stub_maybe_plot_outside_land(**kwargs):
    """Write deterministic dummy artefacts without entering native GeoPandas plotting."""
    out_png = kwargs.get("out_png")
    out_pdf = kwargs.get("out_pdf")
    outside_points = kwargs.get("outside_points")
    all_points = kwargs.get("all_points")

    status = {
        "status": "WRITTEN",
        "n_points_total": int(len(all_points)) if all_points is not None else 0,
        "n_outside_total": int(len(outside_points)) if outside_points is not None else 0,
        "n_plotted_total": int(len(all_points)) if all_points is not None else 0,
        "n_plotted_blue": int(len(outside_points)) if outside_points is not None else 0,
    }
    if out_png is not None:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        out_png.write_bytes(b"stub-plot-png")
        status["png"] = out_png
    if out_pdf is not None:
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(b"stub-plot-pdf")
        status["pdf"] = out_pdf
    return status


def _run_prepare_year_qa_exports_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    native_plotting: bool,
):
    """Execute one synthetic prepare_year QA-export run under controlled plotting mode."""
    repo_src = Path(__file__).resolve().parents[1]
    repo_root = tmp_path / "repo"
    (repo_root / "configs" / "schemas").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        repo_src / "configs" / "example_project.yaml",
        repo_root / "configs" / "example_project.yaml",
    )
    shutil.copy(
        repo_src / "configs" / "schemas" / "fires_canonical.schema.json",
        repo_root / "configs" / "schemas" / "fires_canonical.schema.json",
    )
    shutil.copy(
        repo_src / "configs" / "schemas" / "panel_monthly.schema.json",
        repo_root / "configs" / "schemas" / "panel_monthly.schema.json",
    )

    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    cfg = loaded.config.model_copy(deep=True)

    cfg.outputs.base_dir = "out/runs"
    cfg.outputs.prepare_year_qa_exports.enabled = True
    cfg.outputs.prepare_year_qa_exports.write_geopackage = True
    cfg.outputs.prepare_year_qa_exports.also_write_shapefile = False
    cfg.outputs.prepare_year_qa_exports.export_outside_land_points = True
    cfg.outputs.prepare_year_qa_exports.plot_outside_land_points_png = True
    cfg.outputs.prepare_year_qa_exports.plot_outside_land_points_pdf = False
    cfg.outputs.prepare_year_qa_exports.plot_max_points = 1000

    monkeypatch.setattr(py_stage, "join_points_to_units", _stub_join_points_to_units)
    if not native_plotting:
        monkeypatch.setattr(py_stage, "_maybe_plot_outside_land", _stub_maybe_plot_outside_land)

    cm = cfg.io.inputs.firms_points["viirs"].column_map

    x = [-1.0, -1.01, 10.0, -1.02]
    y = [5.0, 5.01, 0.0, 5.02]

    pts = gpd.GeoDataFrame(
        {
            cm["latitude"]: y,
            cm["longitude"]: x,
            cm["acq_date"]: ["2020-03-15", "2020-03-15", "2020-03-15", "2020-03-15"],
            cm["acq_time"]: ["0130", "0130", "0130", "0130"],
            cm["confidence"]: ["nominal", "high", "high", "high"],
            cm["frp"]: [10.0, 20.0, 5.0, 99.0],
            cm.get("daynight", "DAYNIGHT"): ["D", "D", "D", "D"],
            cm.get("satellite", "SATELLITE"): ["N", "N", "N", "N"],
            cm["type"]: [0, 0, 0, 1],
        },
        geometry=gpd.points_from_xy(x, y),
        crs="EPSG:4326",
    )

    poly = Polygon([(-3.0, 4.0), (2.0, 4.0), (2.0, 12.0), (-3.0, 12.0), (-3.0, 4.0)])
    land_mask = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")

    res = py_stage.prepare_year(
        cfg=cfg,
        repo_root=repo_root,
        sensor="viirs",
        year=2020,
        run_id="testrun",
        points_gdf=pts,
        polygons_by_level=_polys_by_level(cfg, pts),
        land_mask_gdf=land_mask,
        write_outputs=True,
        validate_schema=True,
    )

    qa = json.loads(res.qa_summary_path.read_text(encoding="utf-8"))
    return repo_root, res, qa


def _assert_prepare_year_qa_exports_contract(repo_root: Path, res, qa: dict[str, object]) -> None:
    assert res.fires_canonical_path is not None
    assert res.fires_canonical_path.exists()

    assert res.qa_summary_path is not None
    assert res.qa_summary_path.exists()

    assert "qa_exports" in qa
    qa_exports = qa["qa_exports"]
    assert qa_exports.get("enabled") is True
    assert qa["steps"]["type_filter"]["n_in"] == 4
    assert qa["steps"]["type_filter"]["n_kept"] == 3
    assert qa["steps"]["type_filter"]["n_dropped_nonzero"] == 1
    assert qa_exports.get("type_filter", {}).get("applied_before_dedup") is True

    cleaned_files = qa_exports.get("cleaned_points", {}).get("files", [])
    for item in cleaned_files:
        if isinstance(item, dict) and item.get("path"):
            assert (repo_root / str(item["path"])).exists()

    outside_plot = qa_exports.get("outside_land", {}).get("plot")
    if isinstance(outside_plot, dict) and outside_plot.get("status") == "WRITTEN":
        png_rel = outside_plot.get("png")
        if png_rel:
            assert (repo_root / str(png_rel)).exists()


def test_prepare_year_qa_exports_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root, res, qa = _run_prepare_year_qa_exports_smoke(
        tmp_path,
        monkeypatch,
        native_plotting=False,
    )

    _assert_prepare_year_qa_exports_contract(repo_root, res, qa)


@pytest.mark.native_plot_smoke
@pytest.mark.skipif(not RUN_NATIVE_PLOT_SMOKE, reason=NATIVE_PLOT_SKIP_REASON)
def test_prepare_year_qa_exports_best_effort_native_plot_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root, res, qa = _run_prepare_year_qa_exports_smoke(
        tmp_path,
        monkeypatch,
        native_plotting=True,
    )

    _assert_prepare_year_qa_exports_contract(repo_root, res, qa)
