"""c3 admission binds actual consumer, source bytes, geography and requests."""
import json
from pathlib import Path
import shutil
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_fixture import write_delivery
from RP1_Project.rp1_ba_consolidator import core, handoff


@pytest.fixture(scope='module')
def admitted(tmp_path_factory):
    root = tmp_path_factory.mktemp('c3_admitted')
    source, units = write_delivery(root)
    bundle = root / 'bundle'
    core.consolidate(core.ConsolidationOptions(source, bundle, start_year=2024, unit_universe=units),
        pre_publish=lambda stage, report: handoff.admit_bundle(stage, report, unit_universe=units,
                                                            workflow_request_sha256='a' * 64))
    return bundle, units


@pytest.fixture
def copied(admitted, tmp_path):
    bundle, units = admitted
    destination = tmp_path / 'copied'
    shutil.copytree(bundle, destination)
    universe = tmp_path / 'units.csv'
    shutil.copyfile(units, universe)
    return destination, universe


def test_admitted_original_bytes_and_request_are_verified(admitted):
    bundle, units = admitted
    verified = handoff.verify_handoff(bundle, unit_universe=units, workflow_request_sha256='a' * 64)
    assert verified['scope'] == 'pilot'
    assert verified['profile_contract'] == handoff.PROFILE
    assert Path(verified['bundle_manifest']).name == 'manifest.json'
    with pytest.raises(ValueError, match='Workflow request'):
        handoff.verify_handoff(bundle, unit_universe=units, workflow_request_sha256='b' * 64)


@pytest.mark.parametrize('target', ['source', 'manifest', 'report', 'lock', 'geography', 'extra'])
def test_changed_bytes_or_unlisted_members_are_rejected(copied, target):
    bundle, units = copied
    if target == 'source': path = next((bundle / 'sources').glob('*.csv'))
    elif target == 'manifest': path = bundle / 'manifest.json'
    elif target == 'report': path = bundle / 'validation_report.json'
    elif target == 'lock': path = bundle / 'source_lock.json'
    elif target == 'geography': path = units
    else: path = bundle / 'unlisted.txt'
    path.write_bytes((path.read_bytes() if path.exists() else b'') + b'\n')
    with pytest.raises(ValueError):
        handoff.verify_handoff(bundle, unit_universe=units)


def test_pilot_full_study_and_wrong_profile_are_rejected(admitted):
    bundle, units = admitted
    with pytest.raises(ValueError, match='Pilot'):
        handoff.verify_handoff(bundle, unit_universe=units, require_full=True)
    with pytest.raises(ValueError):
        handoff.verify_handoff(bundle, unit_universe=units, study={'start_yyyymm': 200101, 'end_yyyymm': 202412})
    with pytest.raises(ValueError):
        handoff.verify_handoff(bundle, unit_universe=units, profile_id='c2')


def test_pilot_effective_availability_clips_to_selected_calendar(admitted):
    bundle, units = admitted
    result = handoff.verify_handoff(bundle, unit_universe=units, study={
        'start_yyyymm': 202401, 'end_yyyymm': 202412,
        'ba2012_support_start_yyyymm': 201201, 'viirs_support_start_yyyymm': 201201})
    assert result['study']['ba2012_support_start_yyyymm'] == 202401
    assert result['study']['viirs_support_start_yyyymm'] == 202401


@pytest.mark.parametrize('mutation', ['path', 'duplicate', 'year', 'missing'])
def test_manifest_source_matrix_cannot_be_changed(copied, mutation):
    bundle, units = copied
    path = bundle / 'manifest.json'
    value = json.loads(path.read_text())
    if mutation == 'path': value['outputs'][0]['path'] = '../escape.csv'
    elif mutation == 'duplicate': value['outputs'].append(value['outputs'][0])
    elif mutation == 'year': value['outputs'][0]['year'] = 2023
    else: value['outputs'].pop()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        handoff.verify_handoff(bundle, unit_universe=units)


def test_implementation_change_requires_new_admission(admitted, monkeypatch):
    bundle, units = admitted
    monkeypatch.setattr(handoff, '_implementation_hashes', lambda: {'different': 'implementation'})
    with pytest.raises(ValueError, match='implementation changed'):
        handoff.verify_handoff(bundle, unit_universe=units)


def test_technical_or_invalid_source_cannot_satisfy_consumer(tmp_path):
    from c3_fixture import make_row, write_csv
    source, units = write_delivery(tmp_path)
    path = next(source.glob('*district*CZ*BA2001*'))
    rows = [make_row(month=month, state='ACCOUNTING_INCONSISTENCY') for month in range(1, 13)]
    write_csv(path, rows)
    with pytest.raises(ValueError, match='accounting inconsistency'):
        core.consolidate(core.ConsolidationOptions(source, tmp_path / 'output', start_year=2024, unit_universe=units))
    assert not (tmp_path / 'output').exists()
