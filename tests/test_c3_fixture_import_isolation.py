"""Fixture imports preserve the runtime's package and distribution identities."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _probe(source):
    result = subprocess.run([sys.executable, '-c', source], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_c3_fixture_preserves_doctor_distribution_and_import_identity():
    script = '''
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys
from rp1_analysis_v1.operations import doctor_report
from rp1_ba_contracts import c3 as shared_c3

root = Path.cwd()
def snapshot():
    report = doctor_report()
    distribution = metadata.distribution('rp1-analysis-v1')
    return {'status':report['status'], 'hard_failures':report['hard_failures'],
            'imports':[row for row in report['checks'] if row['check'].startswith('import:')],
            'distribution_path':str(distribution._path),
            'direct_url':distribution.read_text('direct_url.json'), 'sys_path':list(sys.path)}

before = snapshot()
spec = importlib.util.spec_from_file_location('isolated_c3_fixture', root / 'tests/c3_fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
after = snapshot()
assert fixture.c3 is shared_c3
assert before == after, {'before':before, 'after':after}
print(json.dumps({'runtime_identity_unchanged':True, 'shared_module_identity_preserved':True,
                  'doctor_status':after['status'], 'distribution_path':after['distribution_path']}))
'''
    result = _probe(script)
    assert result['runtime_identity_unchanged'] is True
    assert result['shared_module_identity_preserved'] is True


def test_c3_fixture_restores_import_path_when_contract_origin_is_wrong():
    script = '''
import importlib.util
import json
from pathlib import Path
import sys
import types
import rp1_ba_contracts

root = Path.cwd()
wrong = types.ModuleType('rp1_ba_contracts.c3')
wrong.__file__ = str(root / 'unrelated_checkout/c3.py')
rp1_ba_contracts.c3 = wrong
sys.modules['rp1_ba_contracts.c3'] = wrong
before = sys.path[:]
spec = importlib.util.spec_from_file_location('wrong_origin_c3_fixture', root / 'tests/c3_fixture.py')
fixture = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(fixture)
except RuntimeError as exc:
    assert 'from this checkout' in str(exc)
else:
    raise AssertionError('wrong-origin contract was accepted')
assert sys.path == before
assert rp1_ba_contracts.c3 is wrong
print(json.dumps({'wrong_origin_rejected':True, 'import_path_restored':True}))
'''
    result = _probe(script)
    assert result == {'wrong_origin_rejected':True, 'import_path_restored':True}


@pytest.mark.parametrize('relative', (
    'tools/run_workflow.py', 'RP1_Project/merge_af_ba_panels.py',
    'RP1_Project/rp1_ba_consolidator/core.py', 'RP1_Project/create_ba_source_lock.py',
))
def test_operational_script_import_preserves_doctor_and_distribution_identity(relative):
    script = '''
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys
from rp1_analysis_v1.operations import doctor_report
from rp1_ba_contracts import c3 as shared_c3

root = Path.cwd()
def snapshot():
    report = doctor_report()
    dist = metadata.distribution('rp1-analysis-v1')
    return {'status':report['status'], 'hard_failures':report['hard_failures'],
            'imports':[row for row in report['checks'] if row['check'].startswith('import:')],
            'distribution_path':str(dist._path), 'direct_url':dist.read_text('direct_url.json')}

before = snapshot()
before_path = sys.path[:]
target = root / TARGET
spec = importlib.util.spec_from_file_location('operational_script_oracle', target)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
after = snapshot()
assert before == after, {'before':before, 'after':after}
assert set(sys.path) - set(before_path) <= {str(root), str(root / 'tools')}
if hasattr(module, 'c3'):
    assert module.c3 is shared_c3
print(json.dumps({'identity_unchanged':True, 'doctor_status':after['status']}))
'''.replace('TARGET', repr(relative))
    assert _probe(script)['identity_unchanged'] is True


@pytest.mark.parametrize('relative', (
    'RP1_Project/merge_af_ba_panels.py', 'RP1_Project/rp1_ba_consolidator/core.py',
    'RP1_Project/create_ba_source_lock.py',
))
def test_contract_import_failure_restores_operational_import_scope(relative):
    script = '''
import builtins
import importlib.util
import json
from pathlib import Path
import sys

root = Path.cwd()
before = sys.path[:]
original_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'rp1_ba_contracts':
        raise ImportError('simulated contract import failure')
    return original_import(name, *args, **kwargs)
builtins.__import__ = blocked
spec = importlib.util.spec_from_file_location('failed_operational_import', root / TARGET)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
try:
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        assert 'simulated contract import failure' in str(exc)
    else:
        raise AssertionError('contract import did not fail')
finally:
    builtins.__import__ = original_import
assert set(sys.path) - set(before) <= {str(root), str(root / 'tools')}
assert (str(root / 'RP1_Project/rp1_analysis/src') in sys.path) == (str(root / 'RP1_Project/rp1_analysis/src') in before)
print(json.dumps({'scope_restored_after_failure':True}))
'''.replace('TARGET', repr(relative))
    assert _probe(script)['scope_restored_after_failure'] is True
