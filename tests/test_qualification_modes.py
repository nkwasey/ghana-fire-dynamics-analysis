"""Source-only scope must never imply validation of generated analytical data."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def qualifier():
    spec = importlib.util.spec_from_file_location('qualification_modes_test', ROOT / 'tools/qualify_environment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_only_records_absent_analysis_gate_without_running_it(tmp_path, monkeypatch):
    q = qualifier()
    monkeypatch.setattr(q, 'run_step', lambda *a, **k: (_ for _ in ()).throw(AssertionError('unexpected scientific-input check')))
    result = q._source_input_validation(source_only=True, repository_root=tmp_path, logs_dir=tmp_path, env={})
    assert result['status'] == 'NOT_APPLICABLE'
    assert 'no input or scientific-result validation is claimed' in result['reason']
    assert 'handoff' in result['required_stage']


def test_default_scope_retains_hard_analysis_input_gate(tmp_path, monkeypatch):
    q = qualifier(); calls = []
    def failed(name, command, logs, **kwargs):
        calls.append((name, command, kwargs))
        return {'status': 'FAIL', 'returncode': 1}
    monkeypatch.setattr(q, 'run_step', failed)
    operational = tmp_path / 'operational_with_handoff'
    result = q._source_input_validation(source_only=False, repository_root=operational, logs_dir=tmp_path, env={})
    assert result['status'] == 'FAIL'
    assert calls[0][0] == 'validate_inputs'
    assert calls[0][1][-1].endswith('validate_inputs.py')
    assert Path(calls[0][1][-1]).is_relative_to(operational)
    assert calls[0][2]['cwd'] == operational


def test_explicit_prefix_is_verified_without_faking_conda_name(tmp_path, monkeypatch):
    q = qualifier(); prefix = tmp_path / 'dedicated'
    (prefix / 'conda-meta').mkdir(parents=True)
    (prefix / 'conda-meta/history').write_text('explicit package transaction\n')
    monkeypatch.setattr(sys, 'prefix', str(prefix))
    monkeypatch.delenv('CONDA_DEFAULT_ENV', raising=False)
    result = q._environment_identity(defer_native_environment=False, validation_env_prefix=prefix)
    assert result['status'] == 'PASS'
    assert result['actual_conda_env'] is None
    assert result['identity_mode'] == 'explicit_conda_prefix'
    assert result['declared_validation_prefix'] == str(prefix.resolve())


def test_explicit_wrong_or_non_conda_prefix_cannot_be_deferred(tmp_path, monkeypatch):
    q = qualifier(); monkeypatch.setattr(sys, 'prefix', str(tmp_path))
    for prefix in [tmp_path, tmp_path / 'wrong']:
        result = q._environment_identity(defer_native_environment=True, validation_env_prefix=prefix)
        assert result['status'] == 'FAIL'
