"""Declared observation calendars preserve independently fixed BA support."""
import copy
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_fixture import make_row, write_csv, write_delivery
from rp1_ba_contracts import c3
from RP1_Project.rp1_ba_consolidator import core, handoff


def future_row(**kwargs):
    return dict(make_row(year=2025, **kwargs), ba_annual_lc_source_index='2025_01_01')


def test_future_observations_require_explicit_calendar_and_annual_source():
    row = future_row()
    before = copy.deepcopy(row)
    windows = c3.observation_windows(2001, 2025)
    name = 'rp1_ba_district_monthly_c3_CZ_BA2001_2025_ext.csv'
    with pytest.raises(ValueError, match='observation coverage'):
        c3.parse_filename(name)
    with pytest.raises(ValueError, match='year/domain'):
        c3.validate_row(row)
    identity = c3.parse_filename(name, observation_windows=windows)
    c3.validate_header([*c3.FIELDS, 'ba_annual_lc_source_index'])
    c3.validate_row(row, identity=identity, observation_windows=windows)
    assert row == before
    assert c3.DOMAIN_WINDOWS == {'BA2001': (2001, 2024), 'BA2012': (2012, 2024)}
    for value in ('', 'unsafe/source', '2024_01_01', '2025_07_01'):
        with pytest.raises(ValueError, match='annual LC source index'):
            c3.validate_row(dict(row, ba_annual_lc_source_index=value), observation_windows=windows)
    with pytest.raises(ValueError, match='year/domain'):
        c3.validate_row(dict(row, ba_domain_end_year='2025'), observation_windows=windows)


def test_annual_eligibility_beyond_fixed_union_is_checked_against_grid():
    windows = c3.observation_windows(2001, 2025)
    row = future_row()
    row.update(ba_domain_excluded_km2='4', modis_burnable_km2_annual='6',
               modis_burned_frac_annual=str(1 / 6))
    c3.validate_row(row, observation_windows=windows)
    with pytest.raises(ValueError, match='sampled grid'):
        c3.validate_row(dict(row, modis_burnable_km2_annual='9', modis_burned_frac_annual=str(1 / 9)), observation_windows=windows)
    historical = make_row()
    with pytest.raises(ValueError, match='fixed-union'):
        c3.validate_row(dict(historical, modis_burnable_km2_annual='5', modis_burned_frac_annual='0.2'))


def write_future_sources(downloads):
    for domain in c3.DOMAIN_WINDOWS:
        for zone in c3.ZONES:
            for level in c3.LEVELS:
                rows = [future_row(domain=domain, level=level, zone=zone, month=month) for month in range(1, 13)]
                write_csv(downloads / f'rp1_ba_{level}_monthly_c3_{zone}_{domain}_2025_ext.csv', rows,
                          fields=[*c3.FIELDS, 'ba_annual_lc_source_index'])


def test_complete_declared_future_delivery_is_admitted_without_changing_union(tmp_path):
    downloads, units = write_delivery(tmp_path, full=True)
    write_future_sources(downloads)
    originals = {path.name: path.read_bytes() for path in downloads.glob('*.csv')}
    windows = c3.observation_windows(2001, 2025)
    target = tmp_path / 'bundle'
    report = core.consolidate(core.ConsolidationOptions(downloads, target, start_year=2001,
        end_year=2025, observation_windows=windows, scope='full', unit_universe=units))
    assert report['scope'] == 'full' and report['input_files'] == 390
    assert report['domain_windows'] == {'BA2001': [2001, 2024], 'BA2012': [2012, 2024]}
    assert report['windows'] == {'BA2001': [2001, 2025], 'BA2012': [2012, 2025]}
    assert {path.name: path.read_bytes() for path in (target / 'sources').glob('*.csv')} == originals
    handoff.verify_handoff(target, unit_universe=units, require_full=True)


def test_missing_future_month_or_source_cannot_publish(tmp_path):
    downloads, units = write_delivery(tmp_path, full=True)
    write_future_sources(downloads)
    missing = downloads / 'rp1_ba_district_monthly_c3_CZ_BA2001_2025_ext.csv'
    missing.unlink()
    with pytest.raises(ValueError, match='Missing annual'):
        core.consolidate(core.ConsolidationOptions(downloads, tmp_path / 'bundle', start_year=2001,
            end_year=2025, observation_windows=c3.observation_windows(2001, 2025), scope='full', unit_universe=units))
    assert not (tmp_path / 'bundle').exists()
    write_future_sources(downloads)
    with missing.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        rows, fields = list(reader), reader.fieldnames
    write_csv(missing, rows[:-1], fields=fields)
    with pytest.raises(ValueError, match='incomplete unit/calendar'):
        core.consolidate(core.ConsolidationOptions(downloads, tmp_path / 'bundle', start_year=2001,
            end_year=2025, observation_windows=c3.observation_windows(2001, 2025), scope='full', unit_universe=units))
    assert not (tmp_path / 'bundle').exists()


def test_unselected_sources_are_inventoried_and_never_enter_bundle(tmp_path):
    downloads, units = write_delivery(tmp_path, years=[2023, 2024])
    target = tmp_path / 'bundle'
    report = core.consolidate(core.ConsolidationOptions(downloads, target, start_year=2024,
        observation_windows=c3.observation_windows(2024, 2024), scope='full', unit_universe=units))
    assert report['input_files'] == 20
    assert len(report['unconsumed_sources']) == 20
    assert all(row['year'] == 2023 and row['validation_status'] == 'NOT_CONSUMED' for row in report['unconsumed_sources'])
    assert len(list((target / 'sources').glob('*.csv'))) == 20
    manifest = json.loads((target / 'manifest.json').read_text())
    assert manifest['unconsumed_sources'] == report['unconsumed_sources']


def test_future_validate_only_cli_requires_paired_declaration_and_writes_nothing(tmp_path):
    downloads, units = write_delivery(tmp_path, years=[2025])
    write_future_sources(downloads)
    target = tmp_path / 'not_written'
    script = Path(__file__).resolve().parents[1] / 'tools/consolidate_ba.py'
    command = [sys.executable, '-S', str(script), '--input-dir', str(downloads),
        '--output-dir', str(target), '--unit-universe', str(units), '--start-year', '2025',
        '--end-year', '2025', '--scope', 'full', '--validate-only',
        '--observation-start-year', '2025', '--observation-end-year', '2025']
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '20 annual c3 sources; scope=full' in result.stdout and not target.exists()
    rejected = subprocess.run(command[:-2], cwd=tmp_path, capture_output=True, text=True)
    assert rejected.returncode == 2 and 'both observation-period endpoints' in rejected.stderr
    assert not target.exists()
