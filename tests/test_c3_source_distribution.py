"""Pinned c3 source and its independent fixture survive source distribution."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
C3 = ROOT / 'RP1_Project/rp1_gee_ba_scripts/c3'


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pinned_c3_identity_covers_sources_and_explicit_adaptations():
    identity = json.loads((C3 / 'UPSTREAM_IDENTITY.json').read_text())
    adaptations = {entry['path']: entry for entry in identity['adaptations']}
    for relative, record in identity['files'].items():
        expected = adaptations.get(relative, {}).get('vendored_sha256', record['sha256'])
        assert _sha(C3 / relative) == expected, relative
    for relative, record in identity.get('local_files', {}).items():
        assert _sha(C3 / relative) == record['sha256'], relative
        assert (C3 / relative).stat().st_size == record['bytes'], relative
    assert identity['csv_schema'] == 'rp1_ba_c3_extended_v2'
    assert len(list((C3 / 'scripts').glob('*.js'))) == 2
    assert not list(C3.parent.glob('*.js'))


def test_checker_uses_synthetic_fixture_without_generated_outputs():
    checker_test = (C3 / 'tests/offline/test_extended_checker.py').read_text()
    assert 'sample=base.copy()' in checker_test
    assert 'annual eligible area exceeds' in checker_test
    assert 'asutifi_north_ba2012_202401.csv' not in checker_test
    assert "evidence/live_test_review/inputs/" not in checker_test
