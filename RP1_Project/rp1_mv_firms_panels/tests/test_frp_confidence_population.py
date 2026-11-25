from pathlib import Path

import pandas as pd
import pytest

from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly


@pytest.mark.parametrize('sensor', ['viirs', 'modis'])
@pytest.mark.parametrize('streaming', [False, True])
def test_frp_uses_nominal_high_before_daily_max(tmp_path, sensor, streaming):
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / 'configs/example_project.yaml', validate_paths=False, repo_root=root).config
    rows = pd.DataFrame([
        # Low-confidence high FRP must not win the daily maximum or add a day.
        ('A', '2024-01-01', 'l', 1000.0), ('A', '2024-01-01', 'n', 4.0),
        ('A', '2024-01-01', 'h', 9.0), ('A', '2024-01-02', 'h', 3.0),
        ('A', '2024-01-03', 'l', 500.0), ('B', '2024-01-01', 'l', 999.0),
    ], columns=['unit_id', 'date_utc', 'conf_cat', 'frp_mw'])
    rows['level'] = 'district'
    rows['yyyymm'] = 202401
    kwargs = {}
    if sensor == 'viirs' and streaming:
        # Annual VIIRS streaming requires preparation receipts, exercised by
        # test_dual_stream_integration; an ungoverned CSV must be rejected.
        from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError
        p = tmp_path / 'fires_canonical_viirs_2024.csv'
        rows.to_csv(p, index=False)
        with pytest.raises(AggregateMonthlyError):
            aggregate_monthly(cfg=cfg, repo_root=root, sensor=sensor, run_id='test_nh',
                fires_canonical_paths=[p], start_yyyymm=202401, end_yyyymm=202401, write_outputs=False)
        return
    if streaming:
        p = tmp_path / f'fires_canonical_{sensor}_2024.csv'
        rows.to_csv(p, index=False)
        kwargs['fires_canonical_paths'] = [p]
    else:
        kwargs['fires_canonical_df'] = rows
        if sensor == 'viirs':
            kwargs['fires_frp_canonical_df'] = rows.loc[rows.conf_cat.isin(['n', 'h'])]
    result = aggregate_monthly(cfg=cfg, repo_root=root, sensor=sensor, run_id='test_nh', write_outputs=False, **kwargs)
    result_rows = result.panel_sensor_monthly.set_index('unit_id')
    a, b = result_rows.loc['A'], result_rows.loc['B']
    assert a[f'{sensor}_det_nh'] == 3
    assert a[f'{sensor}_det_low'] == 2
    assert a[f'{sensor}_frp_active_days'] == 2
    assert a[f'{sensor}_frp_sum_daily_max_mw'] == 12
    assert a[f'{sensor}_frp_mean_mw'] == 6
    assert b[f'{sensor}_det_nh'] == 0
    assert b[f'{sensor}_frp_active_days'] == 0
    assert pd.isna(b[f'{sensor}_frp_mean_mw'])
    assert result.qa_summary['steps']['frp']['confidence_categories'] == ['n','h']


def test_min_frp_gate_is_separate_from_detection_count():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / 'configs/example_project.yaml', validate_paths=False, repo_root=root).config
    cfg.processing.frp_policy.min_frp_mw = 5.0
    rows = pd.DataFrame([
        {'level': 'district', 'unit_id': 'A', 'yyyymm': 202401, 'date_utc': '2024-01-01', 'conf_cat': 'n', 'frp_mw': 4},
        {'level': 'district', 'unit_id': 'A', 'yyyymm': 202401, 'date_utc': '2024-01-02', 'conf_cat': 'h', 'frp_mw': 8},
    ])
    result = aggregate_monthly(cfg=cfg, repo_root=root, sensor='viirs', run_id='test_gate', fires_canonical_df=rows, fires_frp_canonical_df=rows, write_outputs=False)
    row = result.panel_sensor_monthly.iloc[0]
    assert row['viirs_det_nh'] == 2
    assert row['viirs_frp_active_days'] == 1
    assert row['viirs_frp_mean_mw'] == 8


def test_frp_excludes_nonfinite_values():
    from mv_firms_panels.metrics.frp import compute_daily_max_frp
    rows = pd.DataFrame({'unit_id':['A']*4,'yyyymm':[202401]*4,'date_utc':['2024-01-01']*4,'frp_mw':[float('inf'),float('-inf'),float('nan'),3.0]})
    result = compute_daily_max_frp(rows, id_cols=['unit_id'])
    assert result['daily_max_frp_mw'].tolist() == [3.0]
    with pytest.raises(ValueError, match='finite nonnegative'):
        compute_daily_max_frp(rows, id_cols=['unit_id'], min_frp_mw=float('inf'))
