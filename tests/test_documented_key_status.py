"""Execute the documented local status command with dummy inputs and no network.

No real MAP_KEY or user key file is read. Each subprocess receives an isolated
configuration and explicitly selected dummy environment/file values.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SOURCE = ROOT / 'RP1_Project/rp1_firms_archive/src'
DUMMY_ENV = 'DUMMY_ENV_KEY_123456789'
DUMMY_FILE = 'DUMMY_FILE_KEY_123456789'
MALFORMED = 'DUMMY INVALID KEY WITH SPACES'


def status_command():
    matches = [shlex.split(line) for line in (ROOT / 'README.md').read_text(encoding='utf-8').splitlines()
               if line.startswith('python -c ') and 'workflow=json.load' in line and 'map_key' in line]
    assert len(matches) == 1
    return matches[0][2]


def inventory(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize('environment_key,file_value,file_missing,expected,exit_code', [
    (DUMMY_ENV, None, False, 'FIRMS key is configured', 0),
    (None, DUMMY_FILE, False, 'FIRMS key is configured', 0),
    (DUMMY_ENV, MALFORMED, False, 'FIRMS key is configured', 0),
    ('  ', DUMMY_FILE, False, 'FIRMS key is configured', 0),
    (None, None, False, 'FIRMS key is missing', 1),
    (None, None, True, 'FIRMS key is missing', 1),
    (None, '', False, 'FIRMS key is missing', 1),
    (MALFORMED, DUMMY_FILE, False, '', 1),
    (None, MALFORMED, False, '', 1),
])
def test_documented_status_uses_effective_selected_key_without_network_or_outputs(
        tmp_path, environment_key, file_value, file_missing, expected, exit_code):
    checkout = tmp_path / 'checkout'
    producer = checkout / 'RP1_Project/rp1_firms_archive/configs/selected.yaml'
    producer.parent.mkdir(parents=True)
    private_key = tmp_path / 'private/key.txt'
    settings = {'schema_version': 1, 'years': 2024, 'country': 'Ghana',
                'sources': ['MODIS_SP'], 'output_root': '../generated',
                'downloads': '../download_cache', 'geography': '../reference'}
    if file_value is not None or file_missing:
        settings['key_file'] = private_key.as_posix()
    if file_value is not None:
        private_key.parent.mkdir(parents=True)
        private_key.write_text(file_value + '\n', encoding='utf-8')
    producer.write_text(yaml.safe_dump(settings), encoding='utf-8')
    # File-only success depends on following the workflow's selected producer,
    # rather than silently hard-coding the distributed rp1.yaml example.
    (producer.parent / 'rp1.yaml').write_text(yaml.safe_dump({
        key: value for key, value in settings.items() if key != 'key_file'}), encoding='utf-8')
    workflow = checkout / 'configs/workflow.json'
    workflow.parent.mkdir()
    workflow.write_text(json.dumps({'firms_archive': {
        'mode': 'build', 'producer_config': producer.relative_to(checkout).as_posix()}}), encoding='utf-8')
    before = inventory(tmp_path)
    allowed_environment = ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP',
                           'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HOME', 'LANG', 'LC_ALL')
    environment = {name: os.environ[name] for name in allowed_environment if name in os.environ}
    environment.update(PYTHONPATH=str(ARCHIVE_SOURCE), PYTHONDONTWRITEBYTECODE='1')
    if environment_key is not None:
        environment['FIRMS_MAP_KEY'] = environment_key
    block_network = (
        'import socket, requests\n'
        'def denied(*args, **kwargs):\n'
        '    raise AssertionError("Network access is not permitted in the local key check")\n'
        'socket.create_connection = denied\n'
        'socket.socket.connect = denied\n'
        'requests.sessions.Session.request = denied\n'
    )
    result = subprocess.run([sys.executable, '-c', block_network + status_command()],
                            cwd=checkout, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == exit_code, result.stderr
    assert result.stdout.strip() == expected
    if not expected:
        assert 'Invalid local MAP_KEY format' in result.stderr
    else:
        assert result.stderr == ''
    for value in (DUMMY_ENV, DUMMY_FILE, MALFORMED):
        assert value not in result.stdout and value not in result.stderr
    assert inventory(tmp_path) == before
