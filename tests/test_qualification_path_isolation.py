"""Pytest temporary-directory ownership must never overlap qualification proof."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def qualifier():
    spec = importlib.util.spec_from_file_location('qualification_path_isolation', ROOT / 'tools/qualify_environment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('subdirectory', ['', 'logs', 'logs/pytest', 'clean_projection',
                                       'runtime', 'wheels', 'isolated_install', 'scratch'])
def test_fresh_overlap_is_rejected_before_evidence_is_touched(tmp_path, subdirectory):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    evidence = tmp_path / 'proof'
    pytest_base = evidence / subdirectory
    assert not pytest_base.exists()
    with pytest.raises(ValueError, match='disjoint'):
        q.qualify(repository_root=source, evidence_dir=evidence, source_only=True,
                  pytest_base_temp=pytest_base)
    assert not evidence.exists()


@pytest.mark.parametrize('base_relation', ['equal', 'descendant', 'ancestor'])
def test_overlap_rejection_preserves_existing_proof(tmp_path, base_relation):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    evidence = tmp_path / 'proof'; evidence.mkdir()
    marker = evidence / 'qualification_report.json'
    marker.write_bytes(b'prior proof must survive\n')
    pytest_base = {'equal': evidence, 'descendant': evidence / 'logs',
                   'ancestor': tmp_path}[base_relation]
    with pytest.raises(ValueError, match='disjoint'):
        q.qualify(repository_root=source, evidence_dir=evidence, source_only=True,
                  pytest_base_temp=pytest_base)
    assert marker.read_bytes() == b'prior proof must survive\n'
    assert sorted(p.name for p in evidence.iterdir()) == ['qualification_report.json']


def test_disjoint_sibling_roots_reach_setup_without_reserving_pytest_base(tmp_path, monkeypatch):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    evidence = tmp_path / 'proof'; pytest_base = tmp_path / 'pytest'
    class ReachedSetup(Exception):
        pass
    def reached(evidence_dir):
        assert evidence_dir == evidence.resolve()
        assert not pytest_base.exists()
        raise ReachedSetup()
    monkeypatch.setattr(q, '_claim_fresh_evidence_directory', reached)
    with pytest.raises(ReachedSetup):
        q.qualify(repository_root=source, evidence_dir=evidence, source_only=True,
                  pytest_base_temp=pytest_base)
    assert not evidence.exists() and not pytest_base.exists()


def test_resolved_alias_into_evidence_is_rejected(tmp_path):
    q = qualifier()
    source = tmp_path / 'source'; source.mkdir()
    evidence = tmp_path / 'proof'; evidence.mkdir()
    alias = tmp_path / 'proof_alias'
    try:
        alias.symlink_to(evidence, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'Host cannot create directory symlinks: {exc}')
    marker = evidence / 'qualification_report.json'; marker.write_bytes(b'protected')
    with pytest.raises(ValueError, match='disjoint'):
        q.qualify(repository_root=source, evidence_dir=evidence, source_only=True,
                  pytest_base_temp=alias / 'new_temp')
    assert marker.read_bytes() == b'protected'
    assert not (evidence / 'new_temp').exists()
