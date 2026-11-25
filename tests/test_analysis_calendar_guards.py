"""Declared handoff dates cannot silently shrink to incomplete source coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'RP1_Project/rp1_analysis/scripts/configure_generated_inputs.py'
SPEC = importlib.util.spec_from_file_location('analysis_calendar_guards', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def selection(end=202512, start=200101):
    manifest = {'study': {'start_yyyymm': start, 'end_yyyymm': end,
                         'viirs_support_start_yyyymm': 201201,
                         'ba2012_support_start_yyyymm': 201201,
                         'analysis_overlap_start_yyyymm': 201202}}
    calendar, _ = MODULE.declared_calendar(manifest, {})
    return manifest, calendar


def source_supports(end='2025-12', start='2001-01'):
    return {'modis_af': (start, end), 'ba2001': (start, end),
            'viirs_af': (max(start, '2012-01'), end),
            'ba2012': (max(start, '2012-01'), end)}


@pytest.mark.parametrize('source', ['modis_af', 'viirs_af', 'ba2001', 'ba2012'])
def test_each_source_must_cover_declared_final_year(source):
    manifest, calendar = selection()
    supports = source_supports()
    supports[source] = (supports[source][0], '2024-12')
    with pytest.raises(ValueError, match=source + ' support does not cover'):
        MODULE.validate_declared_source_coverage(manifest, supports, calendar)


@pytest.mark.parametrize('source', ['modis_af', 'viirs_af', 'ba2001', 'ba2012'])
def test_each_source_must_cover_declared_start(source):
    manifest, calendar = selection()
    supports = source_supports()
    supports[source] = ('2014-01', supports[source][1])
    with pytest.raises(ValueError, match=source + ' support does not cover'):
        MODULE.validate_declared_source_coverage(manifest, supports, calendar)


@pytest.mark.parametrize('source', ['modis_af', 'viirs_af', 'ba2001', 'ba2012'])
def test_declared_study_requires_all_four_families(source):
    manifest, calendar = selection()
    supports = source_supports()
    del supports[source]
    with pytest.raises(ValueError, match='missing required source families: ' + source):
        MODULE.validate_declared_source_coverage(manifest, supports, calendar)


@pytest.mark.parametrize('start,end', [(200101, 202412), (200101, 202512), (201401, 202512)])
def test_complete_declared_windows_accept_full_source_coverage(start, end):
    manifest, calendar = selection(end=end, start=start)
    MODULE.validate_declared_source_coverage(
        manifest, source_supports(calendar['end'], calendar['start']), calendar)


def test_broader_support_is_allowed_when_declared_selection_is_complete():
    manifest, calendar = selection(end=202412, start=201401)
    MODULE.validate_declared_source_coverage(manifest, source_supports(), calendar)


@pytest.mark.parametrize('start,end,expected', [
    ('2012-02', '2024-12', {'start': 2013, 'end': 2024}),
    ('2012-02', '2025-11', {'start': 2013, 'end': 2024}),
    ('2024-01', '2024-12', {'start': 2024, 'end': 2024}),
])
def test_annual_paired_window_excludes_partial_endpoint_years(start, end, expected):
    assert MODULE.complete_paired_years(start, end) == expected


@pytest.mark.parametrize('start,end', [('2024-02', '2024-12'), ('2024-01', '2024-11')])
def test_no_complete_paired_calendar_year_is_rejected(start, end):
    with pytest.raises(ValueError, match='no complete calendar year'):
        MODULE.complete_paired_years(start, end)


@pytest.mark.parametrize('value', [True, 200101.5, '200101'])
def test_declared_calendar_does_not_coerce_noninteger_dates(value):
    manifest, _ = selection()
    manifest['study']['start_yyyymm'] = value
    with pytest.raises(ValueError, match='integer YYYYMM'):
        MODULE.declared_calendar(manifest, {})
