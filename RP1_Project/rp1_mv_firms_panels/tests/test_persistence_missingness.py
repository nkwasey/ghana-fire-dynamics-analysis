"""Absence of NH detections establishes zero persistence; absent metrics do not."""
import pandas as pd

from mv_firms_panels.stages.combine_panels import combine_panels
from test_af_exports import _load_cfg, _unit_universe


def test_combine_fills_missing_persistence_only_for_zero_nh_covered_months(tmp_path):
    cfg = _load_cfg(tmp_path)
    universe = _unit_universe()
    sources = {}
    for sensor in ("modis", "viirs"):
        cfg.processing.sensor_coverage[sensor].start_yyyymm = 202402
        cfg.processing.sensor_coverage[sensor].end_yyyymm = 202404
        rows = []
        for unit in universe.itertuples():
            for month, count, persistence in ((202401, 0, pd.NA), (202402, 2, pd.NA),
                                               (202403, 0, pd.NA), (202404, 3, 2)):
                rows.append({"level": unit.level, "unit_id": unit.unit_id, "yyyymm": month,
                    f"{sensor}_det_low": 0, f"{sensor}_det_nominal": count,
                    f"{sensor}_det_high": 0, f"{sensor}_det_nh": count,
                    f"{sensor}_days_active_nh": persistence, f"{sensor}_streak_max_nh": persistence})
        sources[sensor] = pd.DataFrame(rows)
    result = combine_panels(cfg=cfg, repo_root=tmp_path, run_id="missing_persistence",
        unit_universe_df=universe, viirs_monthly_df=sources["viirs"], modis_monthly_df=sources["modis"],
        start_yyyymm=202401, end_yyyymm=202404, write_outputs=True)
    extended = pd.read_csv(result.panel_ext_path)
    for sensor in ("modis", "viirs"):
        for metric in ("days_active_nh", "streak_max_nh"):
            column = f"{sensor}_{metric}"
            assert extended.loc[extended.yyyymm.eq(202401), column].isna().all()
            assert extended.loc[extended.yyyymm.eq(202402), column].isna().all()
            assert extended.loc[extended.yyyymm.eq(202403), column].eq(0).all()
            assert extended.loc[extended.yyyymm.eq(202404), column].eq(2).all()
        assert extended.loc[extended.yyyymm.eq(202402), f"{sensor}_det_nh"].eq(2).all()
        assert extended.loc[extended.yyyymm.eq(202403), f"{sensor}_det_nh"].eq(0).all()
        assert extended.loc[extended.yyyymm.eq(202404), f"{sensor}_det_nh"].eq(3).all()
