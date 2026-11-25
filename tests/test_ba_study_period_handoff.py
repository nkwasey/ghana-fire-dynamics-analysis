"""Analysis overlap survives source admission and its immutable identity."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_fixture import make_row, write_csv, write_delivery
from rp1_ba_contracts import c3
from RP1_Project.rp1_ba_consolidator import core, handoff


def study(end=2024):
    return {'start_yyyymm': 200101, 'end_yyyymm': end * 100 + 12,
        'viirs_support_start_yyyymm': 201201, 'ba2012_support_start_yyyymm': 201201,
        'analysis_overlap_start_yyyymm': 201202}


def manifest(end=2024):
    return {'windows': {'BA2001': [2001, end], 'BA2012': [2012, end]},
        'zones': sorted(c3.ZONES), 'levels': sorted(c3.LEVELS)}


@pytest.mark.parametrize('end', [2024, 2025])
def test_default_and_future_study_preserve_configured_analysis_overlap(end):
    selected = handoff._study(study(end), {'acz': 5, 'district': 5}, manifest(end))
    assert selected['analysis_overlap_start_yyyymm'] == 201202
    assert selected['end_yyyymm'] == end * 100 + 12


@pytest.mark.parametrize('value', [201113, 202501, True, '201202'])
def test_invalid_analysis_overlap_is_rejected(value):
    requested = dict(study(), analysis_overlap_start_yyyymm=value)
    with pytest.raises(ValueError, match='overlap|analysis_overlap'):
        handoff._study(requested, {'acz': 5, 'district': 5}, manifest())


def test_earliest_overlap_floor_can_precede_selected_calendar():
    selected_manifest = {'windows': {'BA2001': [2024, 2024], 'BA2012': [2024, 2024]},
        'zones': sorted(c3.ZONES), 'levels': sorted(c3.LEVELS)}
    requested = dict(study(), start_yyyymm=202401)
    selected = handoff._study(requested, {'acz': 5, 'district': 5}, selected_manifest)
    assert selected['analysis_overlap_start_yyyymm'] == 201202
    assert selected['ba2012_support_start_yyyymm'] == 202401


@pytest.mark.parametrize('end', [2024, 2025])
def test_actual_five_field_study_admission_preserves_overlap_and_rejects_changed_identity(tmp_path, end):
    downloads, units = write_delivery(tmp_path, full=True)
    if end == 2025:
        for domain in c3.DOMAIN_WINDOWS:
            for zone in c3.ZONES:
                for level in c3.LEVELS:
                    rows = [dict(make_row(domain=domain, zone=zone, level=level, year=end, month=month),
                        ba_annual_lc_source_index='2025_01_01') for month in range(1, 13)]
                    write_csv(downloads / f'rp1_ba_{level}_monthly_c3_{zone}_{domain}_{end}_ext.csv', rows,
                        fields=[*c3.FIELDS, 'ba_annual_lc_source_index'])
    target = tmp_path / 'bundle'
    requested = study(end)
    def admit(stage, report):
        handoff.admit_bundle(stage, report, unit_universe=units, study=requested)
    core.consolidate(core.ConsolidationOptions(downloads, target, unit_universe=units,
        start_year=2001, end_year=end, scope='full', observation_windows=c3.observation_windows(2001, end)),
        pre_publish=admit)
    receipt = json.loads((target / 'handoff.json').read_text())
    assert {key: receipt['study'][key] for key in requested} == requested
    checked = handoff.verify_handoff(target, unit_universe=units, study=requested, require_full=True)
    assert checked['study']['analysis_overlap_start_yyyymm'] == 201202
    with pytest.raises(ValueError, match='Study differs'):
        handoff.verify_handoff(target, unit_universe=units,
            study=dict(requested, analysis_overlap_start_yyyymm=201301))
