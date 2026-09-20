# file: tests/test_aggregate_monthly_contract.py
"""Contract tests for aggregate_monthly + combine_panels.

What this test covers
--------------------------------------------
1) aggregate_monthly produces required *sensor* monthly metrics:
   - det_low, det_nominal, det_high, det_nh, pct_high_conf
   - FRP daily max → monthly sum / p95 / mean; mean NA when active_days=0
   - NH persistence: days_active_nh, streak_max_nh
2) combine_panels produces a *balanced* wide panel that:
   - matches unit×month spine (no missing unit-month rows)
   - validates against the current panel_monthly JSON schema
   - enforces exact fixed column order from config

Note
----
The current panel_monthly schema does not yet include pct_high_conf or NH
persistence metrics. Those are emitted by aggregate_monthly and by the optional
panel_monthly_ext artefact from combine_panels, while the base panel remains
schema-valid.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.schema import load_json_schema, validate_dataframe_against_schema
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg():
    repo_root = _repo_root()
    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    return loaded.config, repo_root


def _synthetic_fires(sensor: str) -> pd.DataFrame:
    # Two units, two months, a few days per month.
    rows = []
    if sensor == "viirs":
        # Unit U1: 3 detections in Jan (l,n,h) across 2 days; FRP > 0
        rows += [
            {
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-01",
                "conf_cat": "l",
                "frp_mw": 5.0,
            },
            {
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-01",
                "conf_cat": "h",
                "frp_mw": 10.0,
            },
            {
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-02",
                "conf_cat": "n",
                "frp_mw": 7.0,
            },
            # Unit U2: one high detection in Feb
            {
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U2",
                "yyyymm": 202402,
                "date_utc": "2024-02-03",
                "conf_cat": "h",
                "frp_mw": 3.0,
            },
        ]
    else:
        # MODIS: U1 has two nominal detections same day in Jan; daily max matters
        rows += [
            {
                "sensor": "modis",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-05",
                "conf_cat": "n",
                "frp_mw": 2.0,
            },
            {
                "sensor": "modis",
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 202401,
                "date_utc": "2024-01-05",
                "conf_cat": "n",
                "frp_mw": 9.0,
            },
        ]
    df = pd.DataFrame(rows)
    df.insert(0, "run_id", "test_run")
    return df


def test_aggregate_and_combine_contracts():
    cfg, repo_root = _load_cfg()

    viirs_fires = _synthetic_fires("viirs")
    modis_fires = _synthetic_fires("modis")

    viirs_res = aggregate_monthly(
        cfg=cfg,
        repo_root=repo_root,
        sensor="viirs",
        run_id="test_run",
        fires_canonical_df=viirs_fires,
        write_outputs=False,
    )
    modis_res = aggregate_monthly(
        cfg=cfg,
        repo_root=repo_root,
        sensor="modis",
        run_id="test_run",
        fires_canonical_df=modis_fires,
        write_outputs=False,
    )

    viirs = viirs_res.panel_sensor_monthly
    modis = modis_res.panel_sensor_monthly

    # Required sensor outputs
    for col in [
        "viirs_det_low",
        "viirs_det_nominal",
        "viirs_det_high",
        "viirs_det_nh",
        "viirs_pct_high_conf",
    ]:
        assert col in viirs.columns
    for col in ["viirs_days_active_nh", "viirs_streak_max_nh"]:
        assert col in viirs.columns
    for col in [
        "viirs_frp_active_days",
        "viirs_frp_sum_daily_max_mw",
        "viirs_frp_p95_daily_max_mw",
        "viirs_frp_mean_mw",
    ]:
        assert col in viirs.columns

    for col in [
        "modis_det_low",
        "modis_det_nominal",
        "modis_det_high",
        "modis_det_nh",
        "modis_pct_high_conf",
    ]:
        assert col in modis.columns
    for col in ["modis_days_active_nh", "modis_streak_max_nh"]:
        assert col in modis.columns
    for col in [
        "modis_frp_active_days",
        "modis_frp_sum_daily_max_mw",
        "modis_frp_p95_daily_max_mw",
        "modis_frp_mean_mw",
    ]:
        assert col in modis.columns

    # Unit universe for balancing
    unit_universe = pd.DataFrame(
        [
            {"level": "district", "unit_id": "U1", "unit_name": "Unit 1"},
            {"level": "district", "unit_id": "U2", "unit_name": "Unit 2"},
        ]
    )

    comb = combine_panels(
        cfg=cfg,
        repo_root=repo_root,
        run_id="test_run",
        unit_universe_df=unit_universe,
        viirs_monthly_df=viirs,
        modis_monthly_df=modis,
        start_yyyymm=202401,
        end_yyyymm=202402,
        write_outputs=False,
        validate_schema=True,
        write_extended_metrics=True,
    )
    panel = comb.panel_monthly

    # Balanced: 2 units × 2 months = 4 rows
    assert len(panel) == 4

    # Fixed column order + schema validation (current contract)
    schema_rel = cfg.outputs.schemas["panel_monthly"]
    schema = load_json_schema((repo_root / schema_rel).resolve())
    expected_cols = cfg.determinism.column_order["panel_monthly"]
    panel2 = validate_dataframe_against_schema(
        panel, schema=schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(panel2.columns) == list(expected_cols)

    # Missingness semantics: month with no detections for a sensor has frp_mean_mw == NA
    # Example: for U2 in 202401 there are no VIIRS detections.
    u2_jan = panel.loc[(panel["unit_id"] == "U2") & (panel["yyyymm"] == 202401)].iloc[0]
    assert int(u2_jan["viirs_frp_active_days"]) == 0
    assert pd.isna(u2_jan["viirs_frp_mean_mw"])
