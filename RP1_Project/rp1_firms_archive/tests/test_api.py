"""Reusable API, read-only accepted intake, scoped runs and standalone entrypoints."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ghana_fire_archive import api, cli, core
from test_archive import config, fixture_source, row, ROOT


def built(tmp_path):
    c = config(tmp_path)
    api.prepare_and_export(c, fixture_source(c, [row(), row(frp='0'), row(brightness='0')]))
    return c, Path(c['output']) / 'archive-manifest.json'


def inventory(root):
    return {p.relative_to(root).as_posix(): (core.sha(p), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def test_public_validation_is_read_only_and_records_distinct_producer_identity(tmp_path):
    c, manifest = built(tmp_path)
    root = manifest.parent
    qa_path = root / 'qa/qa-manifest.json'
    qa = json.loads(qa_path.read_text())
    qa['provenance']['scientific_module_sha256'] = 'a' * 64
    core.write_json(qa_path, qa)
    before = inventory(root)
    result = api.validate_archive(manifest)
    assert result['passed'] and result['annual_exports']['passed']
    assert result['manifest_sha256'] == core.sha(manifest)
    assert result['quality_assurance']['semantics_recomputed']
    assert result['quality_assurance']['flagged_records'] == 2
    assert result['quality_assurance']['producer_provenance']['scientific_module_sha256'] == 'a' * 64
    assert result['validator_code_sha256']['scientific.py'] != 'a' * 64
    assert inventory(root) == before


def test_qa_semantic_tampering_fails_even_after_declared_hash_is_updated(tmp_path):
    c, manifest = built(tmp_path)
    qa_path = manifest.parent / 'qa/qa-manifest.json'
    qa = json.loads(qa_path.read_text())
    part = qa['partitions'][0]
    sidecar = qa_path.parent / part['qa_path']
    text = sidecar.read_text().replace('frp_zero_source_reported', 'frp_mw_missing')
    sidecar.write_text(text, encoding='utf-8', newline='\n')
    part['qa_sha256'] = core.sha(sidecar)
    core.write_json(qa_path, qa)
    before = inventory(manifest.parent)
    with pytest.raises(ValueError, match='flags differ'):
        api.validate_archive(manifest)
    assert inventory(manifest.parent) == before


@pytest.mark.parametrize('remove', ['annual/annual-export.json', 'qa/qa-manifest.json'])
def test_required_annual_and_qa_artifacts_cannot_be_silently_skipped(tmp_path, remove):
    c, manifest = built(tmp_path)
    (manifest.parent / remove).unlink()
    with pytest.raises(FileNotFoundError):
        api.validate_archive(manifest)
    if remove.startswith('qa/'):
        assert api.validate_archive(manifest, verify_qa=False)['annual_exports']['passed']


def test_scope_paths_and_explicit_output_compatibility(tmp_path):
    path = tmp_path / 'configs/archive.yaml'
    path.parent.mkdir()
    base = 'schema_version: 1\nyears: 2024\nsources: [MODIS_SP]\n'
    path.write_text(base + 'output_root: ../out/runs\nrun_id: first\n')
    first = api.load_config(path)
    second = api.load_config(path, run_id='second')
    assert Path(first['output']) == tmp_path / 'out/runs/first'
    assert Path(second['output']) == tmp_path / 'out/runs/second'
    assert Path(first['downloads']) == tmp_path / 'data/raw'
    assert Path(first['geography']) == tmp_path / 'data/reference/geography'
    assert not (tmp_path / 'out').exists()
    for value in ('../escape', '/absolute', '.', '', 'a\\b', True):
        with pytest.raises(core.ArchiveError, match='run_id'):
            api.load_config(path, run_id=value)
    path.write_text(base + 'output: ../custom\n')
    assert Path(api.load_config(path)['output']) == tmp_path / 'custom'
    with pytest.raises(core.ArchiveError, match='explicit output'):
        api.load_config(path, run_id='ignored')


def test_writer_contention_does_not_change_accepted_archive_or_steal_lock(tmp_path):
    c, manifest = built(tmp_path)
    plan = fixture_source(c, [row()])
    before = inventory(manifest.parent)
    for directory in (manifest.parent, Path(c['downloads'])):
        lock = directory / '.archive-writer.lock'
        lock.write_text('another writer', encoding='utf-8')
        with pytest.raises(core.ArchiveError, match='holds the lock'):
            api.prepare_and_export(c, plan)
        assert lock.read_text() == 'another writer'
        lock.unlink()
        assert inventory(manifest.parent) == before
    assert not (manifest.parent / '.archive-writer.lock').exists()


def test_public_plan_and_download_use_cache_and_run_locks(tmp_path, monkeypatch):
    c = config(tmp_path)
    def work(selection, refresh):
        assert (Path(c['output']) / '.archive-writer.lock').is_file()
        assert (Path(c['downloads']) / '.archive-writer.lock').is_file()
        return {'items': [], 'refresh': refresh}
    monkeypatch.setattr(core, 'make_plan', work)
    monkeypatch.setattr(core, 'download', work)
    assert api.make_plan(c, False)['refresh'] is False
    assert api.download(c)['refresh'] is True
    assert not list(tmp_path.rglob('*.lock'))


@pytest.mark.parametrize('command', ['verify', 'qa', 'export', 'package'])
def test_manifest_only_cli_does_not_load_configuration(tmp_path, monkeypatch, capsys, command):
    c, manifest = built(tmp_path)
    capsys.readouterr()
    def forbidden(*args, **kwargs):
        raise AssertionError('Manifest-only command must not load a configuration or credential')
    monkeypatch.setattr(cli, 'load_config', forbidden)
    args = [command, '--manifest', str(manifest), '--config', str(tmp_path / 'missing.yaml')]
    if command == 'package':
        args += ['--output', str(tmp_path / 'collection.zip')]
    before = inventory(manifest.parent)
    cli.main(args)
    assert json.loads(capsys.readouterr().out)['passed']
    if command == 'verify':
        assert inventory(manifest.parent) == before


def test_module_entrypoint_and_source_import_from_another_directory(tmp_path):
    code = ("import sys; sys.path.insert(0, " + repr(str(ROOT / 'src')) + "); "
            "import ghana_fire_archive; print(ghana_fire_archive.__file__); "
            "import runpy; sys.argv=['ghana-fire-archive','--version']; "
            "runpy.run_module('ghana_fire_archive',run_name='__main__')")
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert str(ROOT / 'src/ghana_fire_archive/__init__.py') in result.stdout
    assert '1.1.0' in result.stdout


@pytest.mark.parametrize('subdirectory', ['', 'qa', 'canonical/report'])
def test_verify_report_cannot_write_inside_accepted_archive(tmp_path, capsys, subdirectory):
    c, manifest = built(tmp_path)
    capsys.readouterr()
    before = inventory(manifest.parent)
    with pytest.raises(SystemExit) as error:
        cli.main(['verify', '--manifest', str(manifest), '--output', str(manifest.parent / subdirectory)])
    assert error.value.code == 1
    assert inventory(manifest.parent) == before
