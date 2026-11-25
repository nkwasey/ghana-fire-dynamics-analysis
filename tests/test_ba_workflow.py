"""c3 workflow request, geography, recovery and publication bindings."""
from argparse import Namespace
import importlib.util
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
from rp1_ba_contracts import c3
spec = importlib.util.spec_from_file_location('ba_workflow', ROOT / 'tools/run_workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source, unit = write_delivery(tmp_path / 'inputs')
    monkeypatch.setattr(w, 'ROOT', tmp_path)
    firms = tmp_path / 'RP1_Project/rp1_mv_firms_panels'
    monkeypatch.setattr(w, 'FIRMS', firms)
    destination = firms / 'data/metadata/unit_universe.csv'
    destination.parent.mkdir(parents=True)
    shutil.copyfile(unit, destination)
    state = tmp_path / 'out/workflows/check'
    state.mkdir(parents=True)
    (state / 'geo.json').write_text('{}')
    (tmp_path / 'merge.json').write_text(json.dumps({'profiles': {'c3': dict(c3.PROFILE)}}))
    cfg = {'study': {'start_yyyymm': 202401, 'end_yyyymm': 202412,
           'viirs_support_start_yyyymm': 201201, 'ba2012_support_start_yyyymm': 202401},
           'merge_config': 'merge.json', 'ba_preparation': {'c3': {'input_dir': str(source),
           'boundary_label': 'synthetic_boundaries', 'scope': 'pilot'}}}
    args = Namespace(step='consolidate-ba', profile='c3', ba_input_dir=None,
        boundary_label=None, ba_output_root=None, run_id='check')
    monkeypatch.setattr(w, 'verified_geo', lambda _: {})
    return state, cfg, args


def test_actual_preparation_binds_sources_and_repeated_verification(setup):
    state, cfg, args = setup
    w.prepare_ba(state, cfg, args)
    receipt = json.loads((state / 'ba_c3.json').read_text())
    request = json.loads((state / 'ba_c3_request.json').read_text())
    assert request['schema'] == 'rp1-ba-c3-preparation-request-v1'
    assert receipt['schema'] == 'rp1-workflow-ba-v2'
    assert receipt['request_sha256'] == w.sha(state / 'ba_c3_request.json')
    original = (state / 'ba/c3/manifest.json').read_bytes()
    w.prepare_ba(state, cfg, args)
    assert (state / 'ba/c3/manifest.json').read_bytes() == original
    assert w.verify_ba_handoff(state, 'c3', cfg['study'])['scope'] == 'pilot'


def test_changed_request_and_late_binding_are_rejected(setup):
    state, cfg, args = setup
    w.prepare_ba(state, cfg, args)
    args.boundary_label = 'different_boundaries'
    with pytest.raises(ValueError, match='request changed'):
        w.prepare_ba(state, cfg, args)


def test_no_preparation_after_merge_started(setup):
    state, cfg, args = setup
    (state / 'merge_c3.json').write_text('{}')
    with pytest.raises(ValueError, match='Merge already started'):
        w.prepare_ba(state, cfg, args)


def test_published_bundle_without_small_receipt_recovers(setup):
    state, cfg, args = setup
    w.prepare_ba(state, cfg, args)
    receipt = (state / 'ba_c3.json').read_bytes()
    (state / 'ba_c3.json').unlink()
    w.prepare_ba(state, cfg, args)
    assert (state / 'ba_c3.json').read_bytes() == receipt


def test_changed_geography_receipt_stops_reuse(setup):
    state, cfg, args = setup
    w.prepare_ba(state, cfg, args)
    (state / 'geo.json').write_text('{"changed": true}')
    with pytest.raises(ValueError, match='request changed'):
        w.prepare_ba(state, cfg, args)


@pytest.mark.parametrize('profile,step', [('c1', 'stage-ba'), ('c2', 'consolidate-ba'), ('c3', 'stage-ba')])
def test_legacy_or_wrong_operation_cannot_prepare(setup, profile, step):
    state, cfg, args = setup
    args.profile, args.step = profile, step
    with pytest.raises(ValueError, match='annual c3'):
        w.prepare_ba(state, cfg, args)


def test_unbound_output_and_relative_external_root_are_rejected(setup):
    state, cfg, args = setup
    args.ba_output_root = 'relative/path'
    with pytest.raises(ValueError, match='absolute'):
        w.prepare_ba(state, cfg, args)
    args.ba_output_root = None
    (state / 'ba/c3').mkdir(parents=True)
    with pytest.raises(ValueError, match='already exists without'):
        w.prepare_ba(state, cfg, args)


def test_external_output_root_is_bound_and_verified(setup, tmp_path):
    state, cfg, args = setup
    args.ba_output_root = str(tmp_path / 'external')
    w.prepare_ba(state, cfg, args)
    receipt = json.loads((state / 'ba_c3.json').read_text())
    assert Path(receipt['output_dir']) == tmp_path / 'external/check/c3'
    w.prepare_ba(state, cfg, args)


def test_legacy_configuration_block_is_rejected(setup):
    state, cfg, args = setup
    cfg['ba_consolidation'] = {}
    with pytest.raises(ValueError, match='one c3'):
        w.prepare_ba(state, cfg, args)
