"""Invalid acquisition settings fail before any network or credential access."""
import copy

import pytest

from ghana_fire_archive import core
from ghana_fire_archive.configuration import ConfigurationError, runtime_options


@pytest.mark.parametrize('value', [0, -1, True, 1.5, '3', None])
def test_retry_count_is_a_positive_integer(value):
    with pytest.raises(ConfigurationError, match='retries'):
        runtime_options({'retries': value})


@pytest.mark.parametrize('name', ['timeout_seconds', 'api_batch_max_age_hours'])
@pytest.mark.parametrize('value', [0, -1, True, float('nan'), float('inf'), '24', None])
def test_intervals_are_finite_positive_numbers(name, value):
    with pytest.raises(ConfigurationError, match=name):
        runtime_options({name: value})


@pytest.mark.parametrize('value', ['false', 0, 1, None])
def test_refresh_requires_boolean(value):
    with pytest.raises(ConfigurationError, match='refresh_api_batches'):
        runtime_options({'refresh_api_batches': value})


def test_valid_settings_and_defaults_do_not_mutate_configuration():
    c = {'retries': 2, 'timeout_seconds': .5, 'api_batch_max_age_hours': 1,
         'refresh_api_batches': True}
    before = copy.deepcopy(c)
    assert runtime_options(c) == c
    assert c == before
    assert runtime_options({}) == {'retries': 3, 'timeout_seconds': 120.0,
                                   'api_batch_max_age_hours': 24.0,
                                   'refresh_api_batches': False}


def test_bad_request_settings_fail_before_request(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('network must not be called')
    monkeypatch.setattr(core.requests, 'get', forbidden)
    with pytest.raises(core.ArchiveError, match='retries'):
        core.get_bytes('https://example.invalid', {'retries': 0})


@pytest.mark.parametrize('setting,value', [('schema_version','true'), ('output','null'),
                                           ('geography','false'), ('downloads','12')])
def test_invalid_yaml_structure_fails_cleanly(tmp_path, setting, value):
    c = {'schema_version': '1', 'years': '2024', 'sources': '[MODIS_SP]',
         setting: value}
    path = tmp_path/'config.yaml'
    path.write_text(''.join(f'{k}: {v}\n' for k,v in c.items()),encoding='utf-8')
    with pytest.raises(core.ArchiveError):
        core.load_config(path)


def test_rp1_preset_resolves_two_sp_families_and_scoped_native_paths():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    c = core.load_config(root / 'configs/rp1.yaml', run_id='study-rp1')
    assert c['sources'] == ['MODIS_SP', 'VIIRS_SNPP_SP']
    assert c['selected_years'] == list(range(2000, 2026))
    assert Path(c['output']) == root / 'out/runs/study-rp1'
    assert Path(c['downloads']) == root / 'data/raw'
    assert Path(c['geography']) == root / 'data/reference/geography'
