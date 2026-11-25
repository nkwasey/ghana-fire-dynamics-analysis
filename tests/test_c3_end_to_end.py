"""Execute source-only c3 preparation, real AF/BA merger and analysis handoff."""
from pathlib import Path
import csv
import importlib.util
import json
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from c3_fixture import write_delivery, write_csv
from c3_analysis_handoff import complete_runtime_handoff
from RP1_Project import merge_af_ba_panels as merger
from RP1_Project.rp1_ba_consolidator import core
from rp1_ba_contracts import c3
from rp1_analysis_v1.ba_support import load_observation_support, validate_observation_support


def af_sources(root, universe, full, end_year=2024):
    firms = root / 'RP1_Project/rp1_mv_firms_panels'
    exports = firms / 'out/runs/fixture/rp1_af_exports'
    with universe.open(newline='') as handle:
        units = list(csv.DictReader(handle))
    records = []
    for sensor in ('modis', 'viirs'):
        years = range(2001 if sensor == 'modis' else 2012, end_year + 1) if full else [2024]
        fields = merger.MODIS_AF_REQUIRED_COLUMNS if sensor == 'modis' else merger.VIIRS_AF_REQUIRED_COLUMNS
        for unit in units:
            rows = []
            for year in years:
                for month in range(1, 13):
                    row = {name: unit.get(name, '') for name in merger.COMMON_PREFIX_COLUMNS}
                    row.update(run_id='independent_af_fixture', schema_version='rp1_af_monthly_stage1_generic_v1',
                               year=str(year), month=str(month), yyyymm=str(year * 100 + month))
                    values = {'det_low': 1, 'det_nominal': 1, 'det_high': 1, 'det_all': 3,
                              'det_nh': 2, 'pct_high_conf': 100 / 3, 'days_active_nh': 1,
                              'streak_max_nh': 1, 'frp_active_days': 1, 'frp_sum_daily_max_mw': 5,
                              'frp_mean_mw': 5, 'frp_p95_daily_max_mw': 5}
                    row.update({sensor + '_' + name: str(value) for name, value in values.items()})
                    rows.append(row)
            zone = unit['unit_code'] if unit['level'] == 'acz' else unit['parent_code']
            path = exports / unit['level'] / sensor / f'rp1_af_{unit["level"]}_{sensor}_{zone}.csv'
            write_csv(path, rows, fields)
            records.append({'path': str(path.relative_to(firms)), 'sha256': merger.sha256_file(path)})
    evidence = []
    for index in range(6):
        path = firms / f'evidence_{index}.json'
        path.write_text('{"synthetic":true}')
        evidence.append({'path': path.name, 'sha256': merger.sha256_file(path)})
    receipt = exports.parent / 'qa/combine_panels_manifest.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({'active_fire_method': {
        'status': 'VERIFIED_AGGREGATION_INPUTS', 'frp_confidence_categories': ['n', 'h'],
        'frp_aggregation': 'mean_of_daily_maxima_over_eligible_utc_days', 'evidence_files': evidence,
        'method_version': 'viirs_frp_dual_stream_v1',
        'frp_selection_stage': 'before_independent_deduplication',
        'frp_population_viirs': 'nominal_high_independently_deduplicated',
        'frp_deduplication_independent': True, 'frp_finite_values_rank_first': True,
        'config_sha256': 'a' * 64, 'frp_min_mw': 0.0,
        'deduplication': {'latlon_round_decimals': 6, 'include_satellite_in_key': True,
                          'tie_break': ['max_frp_mw', 'max_conf_cat_rank', 'stable_first']},
        'viirs_preparation_evidence': evidence[:5]},
        'rp1_af_exports': records}))
    return exports


@pytest.mark.parametrize('full,end_year', [(False, 2024), (True, 2024), (True, 2025)])
def test_actual_preparation_merge_and_governed_evidence_handoff(tmp_path, full, end_year):
    states = {(domain, level, zone, month): state
              for domain, month, state in [('BA2001', 1, 'none'), ('BA2012', 3, 'anomaly')]
              for level in c3.LEVELS for zone in c3.ZONES}
    source, universe = write_delivery(tmp_path / 'input', full=full, states=states, end_year=end_year)
    transport_source = next(source.glob('*.csv'))
    with transport_source.open(newline='') as handle:
        original_rows = list(csv.DictReader(handle))
    for index, row in enumerate(original_rows):
        row.update({'system:index': str(index), '.geo': '{}'})
    write_csv(transport_source, original_rows, fields=[*c3.FIELDS, 'system:index', '.geo'])
    bundle = tmp_path / 'bundle'
    report = core.consolidate(core.ConsolidationOptions(source, bundle,
        start_year=None if full else 2024, end_year=end_year,
        observation_windows=c3.observation_windows(2001, end_year) if full else None,
        unit_universe=universe, boundary_label='independent_fixture'))
    assert report['input_files'] == (10*((end_year-2001+1)+(end_year-2012+1)) if full else 20)
    assert (bundle / 'sources' / transport_source.name).read_bytes() == transport_source.read_bytes()
    exports = af_sources(tmp_path, universe, full, end_year=end_year)
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'version': 2, 'default_profile': 'c3',
        'profiles': {'c3': dict(c3.PROFILE, bundle_handoff=str(bundle / 'handoff.json'))},
        'paths': {'unit_universe': str(universe), 'af_root': str(exports), 'output_root': str(tmp_path / 'merged')},
        'study': {'start_yyyymm': 200101 if full else 202401, 'end_yyyymm': end_year*100+12,
                  'viirs_support_start_yyyymm': 201201, 'ba2012_support_start_yyyymm': 201201}}))
    args = merger.build_arg_parser().parse_args(['--repo-root', str(tmp_path), '--config', str(config)])
    try:
        paths = merger.build_paths_config(args)
        result = merger.run(paths, 'independent_c3_full' if full else 'independent_c3_pilot')
        panel = pd.read_csv(result['fire_panel_district'])
        january = panel.yyyymm.eq(202401)
        march = panel.yyyymm.eq(202403)
        assert panel.loc[january, 'modis_ba_km2_ba2001'].eq(0).all()
        assert panel.loc[march, 'modis_ba_any_ba2012'].isna().all()
        assert panel.loc[march, 'modis_zero_union_den_flag_ba2012'].eq(0).all()
        assert panel.loc[march, 'modis_burnable_km2_annual_ba2012'].eq(2).all()
        assert panel.modis_det_primary.eq(2).all()
        assert panel.modis_frp_sum_daily_max_mw.eq(5).all()
        assert panel.loc[march, 'viirs_primary_without_ba_any_ba2012_flag'].isna().all()
        spec = importlib.util.spec_from_file_location('c3_stage_fixture', ROOT / 'RP1_Project/rp1_analysis/scripts/prepare_profile_handoff.py')
        staging = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(staging)
        analysis_root = tmp_path / 'RP1_Project/rp1_analysis'
        destination = analysis_root / 'data/raw'
        if not full:
            with pytest.raises(ValueError, match='Pilot'):
                staging.prepare(paths.output_dir, destination)
            assert not destination.exists()
        else:
            staging.prepare(paths.output_dir, destination)
            manifest = json.loads((destination / 'fire_panel_manifest.json').read_text())
            evidence = load_observation_support(analysis_root, manifest)
            acz = pd.read_csv(destination / result['fire_panel_acz'].name)
            district = pd.read_csv(destination / result['fire_panel_district'].name)
            validate_observation_support(evidence, manifest, acz, district)
            assert len(evidence) == report['input_files'] * 12
            assert set(c3.FIELDS).issubset(evidence.columns)
            assert len(evidence.columns) == (74 if end_year > 2024 else 73)
            assert evidence.source_path.nunique() == report['input_files']
            assert not evidence.duplicated(['source_path', 'source_row']).any()
            complete_runtime_handoff(analysis_root, universe, end_year=end_year)
    finally:
        merger.configure_study({})
