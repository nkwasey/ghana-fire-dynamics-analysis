#!/usr/bin/env python3
"""Run repeatable local regression checks. Requires Python 3 and Node.js."""
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = ['scripts/01_ghana_viewer_c3.js', 'scripts/02_monthly_csv_exporter_c3.js', 'tests/gee_synthetic_c3.js']

def run(*args):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)

def digest(root, path):
    return hashlib.sha256((root / path).read_bytes()).hexdigest()

def check_generated_products():
    # A build writes its output paths. Build in an isolated directory so that a
    # stale or intentionally edited project copy is never overwritten by tests.
    with tempfile.TemporaryDirectory(prefix='rp1_c3_build_check_') as tmp:
        build_root = Path(tmp)
        shutil.copy2(ROOT / 'build.py', build_root / 'build.py')
        shutil.copytree(ROOT / 'src', build_root / 'src')
        print('+ isolated build.py (two runs)', flush=True)
        subprocess.run([sys.executable, 'build.py'], cwd=build_root, check=True)
        first = {p: digest(build_root, p) for p in PRODUCTS}
        subprocess.run([sys.executable, 'build.py'], cwd=build_root, check=True)
        second = {p: digest(build_root, p) for p in PRODUCTS}
        checked = {p: digest(ROOT, p) for p in PRODUCTS}
        if first != second or first != checked:
            raise SystemExit('FAIL: generated products were stale or build was not deterministic; project files were not overwritten')

def main():
    check_generated_products()
    print('PASS deterministic regeneration', flush=True)
    js = "const fs=require('fs'),vm=require('vm');let c={};vm.createContext(c);vm.runInContext(fs.readFileSync('src/ee_core.js','utf8'),c);console.log(JSON.stringify(c.C3_SELECTORS));"
    fields = json.loads(subprocess.check_output(['node', '-e', js], cwd=ROOT, text=True))
    if len(fields) != 69 or len(set(fields)) != 69 or any(x.startswith('c3_') for x in fields):
        raise SystemExit('FAIL: expected 69 unique headers without c3_ prefix')
    with (ROOT / 'docs/HEADER_MAP_ALL.csv').open(encoding='utf-8', newline='') as f:
        inventory = list(csv.DictReader(f))
    if len(inventory) != 69 or [r['field_name'] for r in inventory] != fields:
        raise SystemExit('FAIL: CSV field inventory and ordered selectors differ')
    documented = re.findall(r'^\| `([^`]+)` \|', (ROOT / 'docs/CSV_DICTIONARY.md').read_text(encoding='utf-8'), re.M)
    if len(documented) != 69 or len(set(documented)) != 69 or set(documented) != set(fields):
        raise SystemExit('FAIL: CSV dictionary and selectors differ')
    for path in PRODUCTS[:2]:
        text = (ROOT / path).read_text(encoding='utf-8')
        for source in ['scientific_logic.js', 'ee_core.js']:
            expected = (ROOT / 'src' / source).read_text(encoding='utf-8').strip()
            if text.count(expected) != 1:
                raise SystemExit(f'FAIL: {path} does not contain exactly one shared {source}')
        if re.search(r'\b(?:const|let)\b|=>|`', text):
            raise SystemExit(f'FAIL: non-ES5 token in {path}')
        if re.search(r'pilot', text, re.I):
            raise SystemExit(f'FAIL: obsolete wording in {path}')
        run('node', '--check', path)
    print('PASS 69 ordered documented headers, field inventory and common core in both scripts', flush=True)
    d = 'tests/offline/'
    run(sys.executable, d+'test_build_guard.py')
    run('node', d+'test_schema_equivalence.cjs')
    run('node', d+'test_exporter_behavior.cjs', 'src/scientific_logic.js', 'src/ee_core.js', 'src/exporter.js')
    run('node', d+'test_compact_names.cjs', 'src/scientific_logic.js', 'src/ee_core.js', 'src/exporter.js')
    run('node', d+'test_viewer_behavior.cjs', 'src/scientific_logic.js', 'src/ee_core.js', 'src/viewer_app.js', 'src/viewer_lst.js', 'src/viewer_footer.js')
    for name in ['test_logic.cjs', 'test_mock_ee.cjs', 'test_policy_independent.cjs', 'test_observation_period.cjs']:
        run('node', d+name)
    run(sys.executable, d+'test_extended_checker.py')
    run('node', '--check', PRODUCTS[2])
    print('PASS local checks; live Earth Engine checks remain required', flush=True)

if __name__ == '__main__':
    main()
