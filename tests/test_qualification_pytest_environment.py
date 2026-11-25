"""Canonical pytest options must not erase qualification evidence or leak to children."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from rp1_analysis_v1.source_projection import projected_import_environment


ROOT = Path(__file__).resolve().parents[1]


def qualifier():
    spec = importlib.util.spec_from_file_location(
        'qualification_pytest_environment_test', ROOT / 'tools/qualify_environment.py',
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_disjoint(q, left: Path, right: Path):
    left, right = q._resolved_path(left), q._resolved_path(right)
    assert left != right and not left.is_relative_to(right) and not right.is_relative_to(left)


def report_at_runtime_boundary(q, source, proof, requested, monkeypatch):
    """Retain the real selection/reporting path without claiming qualification."""
    with monkeypatch.context() as context:
        context.setattr(q, '_environment_identity', lambda **kwargs: {
            'status': 'FAIL', 'reason': 'Deliberate test boundary before runtime qualification',
        })
        def stop_packages(_root):
            raise ValueError('Deliberate test boundary before package loading')
        context.setattr(q, '_bootstrap_package_specs', stop_packages)
        report, exit_code = q.qualify(repository_root=source, evidence_dir=proof,
                                     source_only=True, pytest_base_temp=requested)
    assert exit_code == 1 and report['status'] == 'FAIL'
    return report


@pytest.mark.parametrize('options', [
    '--basetemp proof/logs', '--basetemp=proof/logs', '-k absent_test --collect-only', '',
])
def test_canonical_child_environment_drops_inherited_pytest_options_without_mutating_parent(
    tmp_path, monkeypatch, options,
):
    q = qualifier()
    monkeypatch.setenv('PYTEST_ADDOPTS', options)
    monkeypatch.setenv('PYTEST_DEBUG_TEMPROOT', str(tmp_path / 'proof' / 'logs'))
    monkeypatch.setenv('RP1_ENVIRONMENT_CONTROL', 'preserve caller values')
    before = dict(os.environ)
    env = q._base_environment(tmp_path / 'runtime')
    assert 'PYTEST_ADDOPTS' not in env
    assert 'PYTEST_DEBUG_TEMPROOT' not in env
    assert env['RP1_ENVIRONMENT_CONTROL'] == 'preserve caller values'
    assert dict(os.environ) == before


def test_automatic_base_is_fresh_and_disjoint_without_reserving_or_touching_evidence(tmp_path):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    marker = proof / 'qualification_report.json'; marker.write_bytes(b'prior terminal evidence')
    first = q._select_pytest_base(source, proof, None)
    second = q._select_pytest_base(source, proof, None)
    assert first != second
    for path in (first, second):
        assert not path.exists()
        assert_disjoint(q, path, source)
        assert_disjoint(q, path, proof)
    assert marker.read_bytes() == b'prior terminal evidence'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['proof', 'source']


def test_automatic_base_ignores_ambient_temp_and_debug_roots(tmp_path, monkeypatch):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    marker = proof / 'prior.log'; marker.write_bytes(b'preserve evidence')
    for name, path in [('TEMP', proof), ('TMP', source), ('TMPDIR', proof / 'logs'),
                       ('PYTEST_DEBUG_TEMPROOT', source / 'temporary')]:
        monkeypatch.setenv(name, str(path))
    selected = q._select_pytest_base(source, proof, None)
    if os.name != 'nt':
        assert selected.parent == q._resolved_path(proof.parent)
    else:
        assert selected.parent != q._resolved_path(proof)
        assert selected.parent != q._resolved_path(source)
    assert not selected.exists()
    assert_disjoint(q, selected, source)
    assert_disjoint(q, selected, proof)
    assert marker.read_bytes() == b'preserve evidence'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['proof', 'source']


@pytest.mark.parametrize('mode', ['automatic', 'explicit'])
def test_qualify_records_the_effective_base_before_an_environment_failure(tmp_path, monkeypatch, mode):
    """Stop before expensive platform checks, retaining the real report contract."""
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'
    requested = tmp_path / 'explicit_pytest' if mode == 'explicit' else None
    selected = []
    original = q._select_pytest_base
    def select(repository_root, evidence_dir, requested):
        path = original(repository_root, evidence_dir, requested)
        selected.append(path)
        return path
    monkeypatch.setattr(q, '_select_pytest_base', select)
    report = report_at_runtime_boundary(q, source, proof, requested, monkeypatch)
    assert len(selected) == 1
    assert q._resolved_path(Path(report['pytest_base_temp'])) == selected[0]
    automatic_mode = 'automatic_platform_temp' if os.name == 'nt' else 'automatic_sibling'
    assert report['pytest_base_temp_mode'] == ('explicit' if requested else automatic_mode)
    assert q._resolved_path(report['pytest_base_temp_argument']) == selected[0]
    if requested:
        assert selected[0] == q._resolved_path(requested)
    assert_disjoint(q, selected[0], source)
    assert_disjoint(q, selected[0], proof)
    assert not selected[0].exists()
    persisted = json.loads((proof / 'qualification_report.json').read_text())
    assert persisted['pytest_base_temp'] == report['pytest_base_temp']
    assert persisted['pytest_base_temp_mode'] == report['pytest_base_temp_mode']


def test_automatic_base_collision_is_refused_before_any_prior_proof_is_cleared(tmp_path, monkeypatch):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    marker = proof / 'qualification_report.json'; marker.write_bytes(b'preserve prior proof')
    # Force a real candidate collision instead of relying on improbable UUID reuse.
    collision_id = q.uuid.uuid4().hex
    monkeypatch.setattr(q.uuid, 'uuid4', lambda: SimpleNamespace(hex=collision_id))
    collision = q._select_pytest_base(source, proof, None)
    native = q._native_path(collision)
    with native.open('xb') as stream:
        stream.write(b'unrelated existing data')
    try:
        with pytest.raises(ValueError, match='fresh dedicated'):
            q.qualify(repository_root=source, evidence_dir=proof, source_only=True)
        assert marker.read_bytes() == b'preserve prior proof'
        assert native.read_bytes() == b'unrelated existing data'
        assert sorted(p.name for p in proof.iterdir()) == ['qualification_report.json']
    finally:
        # Remove only this exact test-owned file, never a pre-existing entry.
        native.unlink()


def _tiny_project(project: Path):
    project.mkdir()
    (project / 'test_outer.py').write_text('''from pathlib import Path
import json, os, subprocess, sys

def test_outer_uses_real_tmp_path_and_nested_pytest(tmp_path, request):
    (tmp_path / 'outer_fixture_used.txt').write_text('actual fixture')
    nested = tmp_path / 'nested_project'; nested.mkdir()
    (nested / 'test_inner.py').write_text("""from pathlib import Path
import json, os

def test_inner_uses_real_tmp_path(tmp_path, request):
    (tmp_path / 'inner_fixture_used.txt').write_text('actual child fixture')
    Path(os.environ['RP1_TEST_INNER_OBSERVATION']).write_text(json.dumps({
        'basetemp': str(request.config._tmp_path_factory.getbasetemp()),
        'pytest_addopts': os.environ.get('PYTEST_ADDOPTS'),
        'pytest_debug_temproot': os.environ.get('PYTEST_DEBUG_TEMPROOT')}))
""")
    child = subprocess.run([sys.executable, '-m', 'pytest', '-o', 'addopts=',
                            '-p', 'no:cacheprovider', '-q', str(nested / 'test_inner.py')],
                           cwd=nested, env=os.environ.copy(), text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    assert child.returncode == 0, child.stdout
    Path(os.environ['RP1_TEST_OUTER_OBSERVATION']).write_text(json.dumps({
        'basetemp': str(request.config._tmp_path_factory.getbasetemp()),
        'pytest_addopts': os.environ.get('PYTEST_ADDOPTS'),
        'pytest_debug_temproot': os.environ.get('PYTEST_DEBUG_TEMPROOT')}))
''', encoding='utf-8')


@pytest.mark.parametrize('mode', ['automatic', 'explicit'])
@pytest.mark.parametrize('inherited', ['overlapping_base', 'test_selection', 'clean'])
def test_real_pytest_and_nested_child_preserve_evidence_with_effective_base(
    tmp_path, monkeypatch, mode, inherited,
):
    """The real deletion boundary is exercised; no tmp_path behavior is mocked."""
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; logs = proof / 'logs'; logs.mkdir(parents=True)
    marker = logs / 'pip_check.log'; marker.write_bytes(b'prior pip-check evidence\n')
    before = marker.read_bytes()
    requested = tmp_path / 'explicit_pytest' if mode == 'explicit' else None
    project = tmp_path / 'tiny_project'; _tiny_project(project)
    scratch = tmp_path / 'system_temp'; scratch.mkdir()
    # Child pytest uses its ordinary default. Only the uncontrolled pytest
    # options are dangerous here; give normal OS temporary allocation its own root.
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        monkeypatch.setenv(name, str(scratch))
    if inherited == 'overlapping_base':
        monkeypatch.setenv('PYTEST_ADDOPTS', '--basetemp "' + logs.as_posix() + '"')
    elif inherited == 'test_selection':
        monkeypatch.setenv('PYTEST_ADDOPTS', '-k impossible_selection --collect-only')
    else:
        monkeypatch.delenv('PYTEST_ADDOPTS', raising=False)
    monkeypatch.setenv('PYTEST_DEBUG_TEMPROOT', str(logs))
    outer_observation = tmp_path / 'outer_observation.json'
    inner_observation = tmp_path / 'inner_observation.json'
    monkeypatch.setenv('RP1_TEST_OUTER_OBSERVATION', str(outer_observation))
    monkeypatch.setenv('RP1_TEST_INNER_OBSERVATION', str(inner_observation))
    caller_environment = dict(os.environ)
    fresh_proof = tmp_path / 'fresh_proof'
    fresh_logs = fresh_proof / 'logs'
    report = report_at_runtime_boundary(q, source, fresh_proof, requested, monkeypatch)
    base = Path(report['pytest_base_temp'])
    # Use the actual projection handoff with real source roots, not a fake
    # replacement for the environment code used by the qualifier.
    contract = SimpleNamespace(packages=[SimpleNamespace(
        source_root='RP1_Project/rp1_analysis/src',
        project_root='RP1_Project/rp1_analysis', module='rp1_analysis_v1')])
    env = projected_import_environment(ROOT, contract,
                                       base_environment=q._base_environment(fresh_proof / 'runtime'))
    command = [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-p', 'no:cacheprovider',
               '-q', '--junitxml', str(fresh_logs / 'full_pytest.xml'), '--basetemp', report['pytest_base_temp_argument'],
               str(project / 'test_outer.py')]
    step = q.run_step('full_pytest', command, fresh_logs, cwd=project, env=env)
    assert step['status'] == 'PASS', Path(step['log']).read_text(encoding='utf-8')
    assert marker.read_bytes() == before
    assert (fresh_logs / 'full_pytest.xml').is_file()
    assert outer_observation.is_file() and inner_observation.is_file()
    outer = json.loads(outer_observation.read_text())
    inner = json.loads(inner_observation.read_text())
    assert os.path.samefile(outer['basetemp'], base)
    for observation in (outer, inner):
        assert observation['pytest_addopts'] is None
        assert observation['pytest_debug_temproot'] is None
        assert_disjoint(q, Path(observation['basetemp']), proof)
        assert_disjoint(q, Path(observation['basetemp']), fresh_proof)
        assert_disjoint(q, Path(observation['basetemp']), source)
    assert dict(os.environ) == caller_environment


def windows_spelling(path: Path, extended: bool):
    """Represent the same Windows location without requiring links or privileges."""
    ordinary = qualifier()._resolved_path(path)
    return Path('\\\\?\\' + str(ordinary)) if extended else ordinary


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
@pytest.mark.parametrize('extended_source', [False, True])
@pytest.mark.parametrize('extended_proof', [False, True])
@pytest.mark.parametrize('extended_base', [False, True])
@pytest.mark.parametrize('placement', ['proof_child', 'proof_equal', 'proof_ancestor', 'source_child'])
def test_mixed_dos_namespace_overlap_is_refused_before_evidence_mutation(
    tmp_path, monkeypatch, extended_source, extended_proof, extended_base, placement,
):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    logs = proof / 'logs'; logs.mkdir()
    prior = logs / 'pip_check.log'; prior.write_bytes(b'prior evidence survives namespace aliases')
    terminal = proof / 'qualification_report.json'; terminal.write_bytes(b'prior terminal proof')
    requested = {'proof_child': logs / 'fresh_pytest', 'proof_equal': proof,
                 'proof_ancestor': tmp_path, 'source_child': source / 'fresh_pytest'}[placement]
    mutations = []
    def must_not_claim(*args):
        mutations.append('evidence creation')
        raise AssertionError('Overlapping namespace alias reached evidence creation')
    monkeypatch.setattr(q, '_claim_fresh_evidence_directory', must_not_claim)
    expected = 'fresh dedicated' if placement == 'source_child' else 'disjoint'
    with pytest.raises(ValueError, match=expected):
        q.qualify(repository_root=windows_spelling(source, extended_source),
                  evidence_dir=windows_spelling(proof, extended_proof),
                  pytest_base_temp=windows_spelling(requested, extended_base), source_only=True)
    assert not mutations
    assert prior.read_bytes() == b'prior evidence survives namespace aliases'
    assert terminal.read_bytes() == b'prior terminal proof'
    assert not (logs / 'fresh_pytest').exists() and not (source / 'fresh_pytest').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
@pytest.mark.parametrize('extended_source', [False, True])
@pytest.mark.parametrize('extended_proof', [False, True])
def test_automatic_base_has_one_logical_identity_for_dos_aliases(tmp_path, extended_source, extended_proof):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    selected = q._select_pytest_base(windows_spelling(source, extended_source),
                                   windows_spelling(proof, extended_proof), None)
    assert not str(selected).startswith('\\\\?\\')
    if os.name != 'nt':
        assert selected.parent == q._resolved_path(proof.parent)
    else:
        assert selected.parent != q._resolved_path(proof)
        assert selected.parent != q._resolved_path(source)
    assert_disjoint(q, selected, proof)
    assert_disjoint(q, selected, source)
    assert not q._native_path(selected).exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
@pytest.mark.parametrize('role', ['source', 'proof', 'pytest_base'])
@pytest.mark.parametrize('namespace', [
    r'\\.\PIPE\rp1_unsupported',
    r'\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy1\rp1_unsupported',
    r'\\?\Volume{00000000-0000-0000-0000-000000000000}\rp1_unsupported',
    r'\??\C:\rp1_unsupported',
])
def test_unsupported_windows_namespaces_fail_before_any_evidence_cleanup(tmp_path, monkeypatch, role, namespace):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    prior = proof / 'qualification_report.json'; prior.write_bytes(b'preserve terminal evidence')
    args = {'repository_root': source, 'evidence_dir': proof,
            'pytest_base_temp': tmp_path / 'fresh_pytest'}
    args[{'source': 'repository_root', 'proof': 'evidence_dir', 'pytest_base': 'pytest_base_temp'}[role]] = Path(namespace)
    mutations = []
    def must_not_claim(*unused):
        mutations.append('creation')
        raise AssertionError('Unsupported namespace reached evidence creation')
    monkeypatch.setattr(q, '_claim_fresh_evidence_directory', must_not_claim)
    with pytest.raises(ValueError):
        q.qualify(**args, source_only=True)
    assert not mutations
    assert prior.read_bytes() == b'preserve terminal evidence'


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
@pytest.mark.parametrize('extended_input', [False, True])
def test_unc_resolution_has_one_logical_identity_without_requiring_a_network_share(monkeypatch, extended_input):
    """Check resolver output normalization; no live UNC share is accessed."""
    q = qualifier()
    ordinary = Path(r'\\rp1-unit-host\unit-share\proof')
    native = Path(r'\\?\UNC\rp1-unit-host\unit-share\proof')
    with monkeypatch.context() as context:
        context.setattr(Path, 'resolve', lambda self, *args, **kwargs: native)
        resolved = q._resolved_path(native if extended_input else ordinary)
    assert resolved == ordinary


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
def test_real_pytest_safe_extended_base_preserves_existing_evidence(tmp_path, monkeypatch):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; logs = proof / 'logs'; logs.mkdir(parents=True)
    marker = logs / 'pip_check.log'; marker.write_bytes(b'preserve prior log')
    project = tmp_path / 'tiny'; project.mkdir()
    observed = tmp_path / 'observed.json'
    monkeypatch.setenv('RP1_NAMESPACE_OBSERVATION', str(observed))
    (project / 'test_tmp.py').write_text('''import json, os
from pathlib import Path

def test_actual_tmp_path(tmp_path, request):
    (tmp_path / 'consumed.txt').write_text('actual fixture')
    Path(os.environ['RP1_NAMESPACE_OBSERVATION']).write_text(json.dumps({
        'base': str(request.config._tmp_path_factory.getbasetemp())}))
''', encoding='utf-8')
    fresh_proof = tmp_path / 'fresh_proof'
    report = report_at_runtime_boundary(q, source, fresh_proof,
                                        windows_spelling(tmp_path / 'safe_base', True), monkeypatch)
    selected = Path(report['pytest_base_temp'])
    argument = Path(report['pytest_base_temp_argument'])
    assert str(argument).startswith('\\\\?\\')
    step = q.run_step('safe_extended_pytest', [sys.executable, '-m', 'pytest', '-o', 'addopts=',
                      '-p', 'no:cacheprovider', '-q', '--basetemp', str(argument), str(project / 'test_tmp.py')],
                      fresh_proof / 'logs', cwd=project, env=q._base_environment(fresh_proof / 'runtime'))
    assert step['status'] == 'PASS', Path(step['log']).read_text()
    actual = Path(json.loads(observed.read_text())['base'])
    assert os.path.samefile(actual, argument)
    assert_disjoint(q, actual, proof)
    assert_disjoint(q, actual, fresh_proof)
    assert marker.read_bytes() == b'preserve prior log'


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
def test_existing_long_native_base_is_rejected_without_removing_unrelated_files(tmp_path):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    proof = tmp_path / 'proof'; proof.mkdir()
    prior = proof / 'qualification_report.json'; prior.write_bytes(b'preserve terminal proof')
    logical = q._resolved_path(tmp_path / ('long_parent_' * 8) / ('long_child_' * 8) / 'existing_base')
    assert len(str(logical)) > 260
    native = q._native_path(logical); native.mkdir(parents=True)
    unrelated = native / 'unrelated.txt'; unrelated.write_bytes(b'never erase unrelated content')
    with pytest.raises(ValueError, match='fresh dedicated'):
        q.qualify(repository_root=source, evidence_dir=proof,
                  pytest_base_temp=logical, source_only=True)
    assert prior.read_bytes() == b'preserve terminal proof'
    assert unrelated.read_bytes() == b'never erase unrelated content'


@pytest.mark.skipif(os.name != 'nt', reason='Windows filesystem namespace contract')
def test_native_argument_supports_a_shipped_fixture_beyond_max_path(tmp_path, monkeypatch):
    """Run a real self-contained package regression beneath a long native base."""
    q = qualifier()
    proof = tmp_path / 'proof'; logs = proof / 'logs'; logs.mkdir(parents=True)
    marker = logs / 'pip_check.log'; marker.write_bytes(b'preserve prior proof')
    logical = q._resolved_path(tmp_path / ('long_parent_' * 8) / ('long_child_' * 8) / 'fresh_base')
    assert len(str(logical)) > 260
    # Pytest creates its dedicated base, not an arbitrary missing parent chain.
    q._native_path(logical.parent).mkdir(parents=True)
    fresh_proof = tmp_path / 'fresh_proof'
    fresh_logs = fresh_proof / 'logs'
    report = report_at_runtime_boundary(q, ROOT, fresh_proof, windows_spelling(logical, True), monkeypatch)
    argument = Path(report['pytest_base_temp_argument'])
    assert str(argument).startswith('\\\\?\\')
    junit = fresh_logs / 'shipped_fixture.xml'
    target = 'tests/test_satscan_pending_markers.py::test_success_removes_only_configured_pending_markers_after_validation'
    contract = SimpleNamespace(packages=[SimpleNamespace(
        source_root='RP1_Project/rp1_analysis/src',
        project_root='RP1_Project/rp1_analysis', module='rp1_analysis_v1')])
    env = projected_import_environment(ROOT, contract,
                                       base_environment=q._base_environment(fresh_proof / 'runtime'))
    step = q.run_step('long_native_shipped_fixture', [sys.executable, '-m', 'pytest', '-o', 'addopts=',
                      '-p', 'no:cacheprovider', '-q', '--junitxml', str(junit), '--basetemp', str(argument), target],
                      fresh_logs, cwd=ROOT / 'RP1_Project/rp1_analysis', env=env)
    assert step['status'] == 'PASS', Path(step['log']).read_text()
    cases = list(ET.parse(junit).getroot().iter('testcase'))
    assert len(cases) == 1 and not list(cases[0])
    assert marker.read_bytes() == b'preserve prior proof'
