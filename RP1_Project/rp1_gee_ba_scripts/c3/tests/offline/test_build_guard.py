#!/usr/bin/env python3
"""Verify a build check detects stale outputs without changing project files."""
import importlib.util
import shutil
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('rp1_offline_runner', PROJECT / 'tests/run_offline.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

with tempfile.TemporaryDirectory(prefix='rp1_c3_guard_test_') as tmp:
    fixture = Path(tmp)
    shutil.copy2(PROJECT / 'build.py', fixture / 'build.py')
    shutil.copytree(PROJECT / 'src', fixture / 'src')
    for name in runner.PRODUCTS:
        destination = fixture / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / name, destination)
    runner.ROOT = fixture
    originals = {name: (fixture / name).read_bytes() for name in runner.PRODUCTS}
    runner.check_generated_products()
    assert originals == {name: (fixture / name).read_bytes() for name in runner.PRODUCTS}
    stale = fixture / runner.PRODUCTS[1]
    stale.write_bytes(stale.read_bytes() + b'\n// stale fixture\n')
    stale_bytes = stale.read_bytes()
    try:
        runner.check_generated_products()
    except SystemExit as error:
        assert 'stale or build was not deterministic' in str(error), str(error)
    else:
        raise AssertionError('A stale generated script was not detected')
    assert stale.read_bytes() == stale_bytes, 'The stale generated script was overwritten'
    for name in (runner.PRODUCTS[0], runner.PRODUCTS[2]):
        assert (fixture / name).read_bytes() == originals[name], f'Unexpected change to {name}'

print('PASS build guard: clean outputs accepted; stale output detected without overwrite')
