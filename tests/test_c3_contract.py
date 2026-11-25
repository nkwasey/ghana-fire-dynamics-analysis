"""Shared source-contract guards use independent designed observations."""
import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_fixture import make_row
from rp1_ba_contracts import c3


@pytest.mark.parametrize('state', ['partial', 'none', 'anomaly', 'unresolved', 'annual_unknown', 'zero_union', 'no_pixels', 'full'])
@pytest.mark.parametrize('domain', ['BA2001', 'BA2012'])
def test_valid_guarded_records_preserve_exact_values(state, domain):
    row = make_row(domain=domain, state=state)
    original = copy.deepcopy(row)
    c3.validate_row(row)
    assert row == original


@pytest.mark.parametrize('status', sorted(c3.TECHNICAL_STATUSES))
def test_technical_records_can_be_inspected_but_never_admitted(status):
    row = make_row(state=status)
    c3.validate_row(row, allow_technical=True)
    with pytest.raises(ValueError):
        c3.validate_row(row)
    row['modis_ba_km2'] = '0'
    with pytest.raises(ValueError, match='must be null'):
        c3.validate_row(row, allow_technical=True)


@pytest.mark.parametrize('field,value', [
    ('schema_version', 'rp1_ba_monthly_stage1_generic_v2'), ('ba_source_count', '2'),
    ('ba_coverage_status', 'COMPLETE_SUPPORT'), ('ba_grid_transform', '500,0,0,0,-500,0'),
    ('ba_lc_source_indexes', 'wrong'), ('ba_known_union_area_km2', 'NaN'),
    ('ba_state_accepted_km2', '2'), ('modis_ba_any', '0'),
    ('modis_burned_pixel_count', '0'), ('ba_supported_fraction', '1'),
    ('ba_reason_shortened_km2', '-1'), ('month', '13')])
def test_invalid_source_states_fail(field, value):
    row = make_row()
    row[field] = value
    with pytest.raises(ValueError):
        c3.validate_row(row)


def test_anomaly_retains_annual_area_and_union_zero_flag():
    row = make_row(state='anomaly')
    c3.validate_row(row)
    assert row['modis_burnable_km2_annual'] == '2'
    assert row['modis_zero_union_den_flag'] == '0'
    assert row['modis_burnable_km2_union'] == ''
    row['modis_ba_km2'] = '0'
    with pytest.raises(ValueError):
        c3.validate_row(row)


def test_annual_ratio_is_not_a_fraction_and_reason_areas_overlap():
    row = make_row()
    row.update(modis_burnable_km2_annual='0.5', modis_burned_frac_annual='2',
               ba_reason_qa_nonland_km2='4', ba_reason_qa_invalid_km2='4')
    c3.validate_row(row)


def test_exact_headers_and_optional_earth_engine_fields():
    assert len(c3.FIELDS) == 69
    c3.validate_header(['system:index', *c3.FIELDS, '.geo'])
    for invalid in ([*c3.FIELDS, 'unknown'], [*c3.FIELDS, c3.FIELDS[0]], list(reversed(c3.FIELDS)), c3.FIELDS[:-1]):
        with pytest.raises(ValueError):
            c3.validate_header(invalid)


def test_annual_names_and_complete_matrix():
    identity = c3.parse_filename('rp1_ba_district_monthly_c3_TZ_BA2012_2024_ext.csv')
    assert identity == dict(family='ba2012', domain='BA2012', level='district', partition='TZ', year=2024, role='extended')
    assert len(c3.expected_identities(c3.DOMAIN_WINDOWS)) == 370
    assert len(c3.expected_identities({'BA2001': (2024, 2024), 'BA2012': (2024, 2024)})) == 20
    for bad in ('rp1_ba_district_monthly_c2_TZ_BA2012_2024_ext.csv',
                'rp1_ba_acz_monthly_c3_ALL_ACZ_BA2001_2024_ext.csv',
                'rp1_ba_acz_monthly_c3_CZ_BA2012_2001_ext.csv'):
        with pytest.raises(ValueError):
            c3.parse_filename(bad)
