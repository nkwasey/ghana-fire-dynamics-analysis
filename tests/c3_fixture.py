"""Independent small c3 observations, never research data or expected results."""
from __future__ import annotations
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
_source_root = ROOT / 'RP1_Project/rp1_analysis/src'
_original_import_path = sys.path[:]
try:
    # The fixture uses this checkout's shared contract without leaving its source
    # metadata ahead of the installed editable distribution for unrelated tests.
    sys.path.insert(0, str(_source_root))
    from rp1_ba_contracts import c3
    if Path(c3.__file__).resolve() != (_source_root / 'rp1_ba_contracts/c3.py').resolve():
        raise RuntimeError('c3 fixture requires the shared contract from this checkout')
finally:
    sys.path[:] = _original_import_path


def make_row(domain='BA2001', level='district', zone='CZ', year=2024, month=1, state='partial'):
    start = 2001 if domain == 'BA2001' else 2012
    row = dict.fromkeys(c3.FIELDS, '0')
    row.update(run_id=f'synthetic_{domain}_{level}_{zone}_{year}', schema_version='rp1_ba_c3_extended_v2',
        level=level, unit_id=c3.ZONES[zone] if level == 'acz' else 'D_' + zone,
        unit_code=zone if level == 'acz' else '', unit_name=zone + (' ZONE' if level == 'acz' else ' DISTRICT'),
        parent_level='' if level == 'acz' else 'acz', parent_id='' if level == 'acz' else c3.ZONES[zone],
        parent_code='' if level == 'acz' else zone, parent_name='' if level == 'acz' else zone + ' ZONE',
        year=str(year), month=str(month), yyyymm=str(year * 100 + month), ba_domain=domain,
        ba_domain_start_year=str(start), ba_domain_end_year='2024', ba_source_status='ADMITTED',
        ba_source_count='1', ba_source_index=f'{year}_{month:02d}_01',
        ba_lc_source_indexes='|'.join(str(y) for y in range(start, 2025)),
        ba_product='MODIS/061/MCD64A1', ba_lc_product='MODIS/061/MCD12Q1',
        ba_boundary_asset='projects/synthetic/assets/' + ('acz' if level == 'acz' else 'districts'),
        ba_ghana_asset='projects/synthetic/assets/ghana', ba_grid_crs='SR-ORG:6974',
        ba_grid_transform='463.3127165279165,0,-20015109.354,0,-463.3127165279167,7783653.6376640005',
        ba_reducer='sum_unweighted_centroid', ba_status='ADMITTED', ba_coverage_status='PARTIAL_EVIDENCE',
        ba_sampled_pixel_count='4', ba_known_union_area_km2='4', ba_known_union_burned_km2='1',
        ba_state_qa_missing_km2='1', ba_state_burndate_masked_km2='1', ba_state_explicit_zero_km2='1',
        ba_state_accepted_km2='1', ba_reason_qa_missing_km2='1', ba_reason_burndate_masked_km2='1',
        ba_reason_shortened_km2='1', ba_shortened_km2='1', ba_full_period_only_km2='0',
        ba_supported_area_km2='2', ba_supported_fraction='0.5', modis_ba_km2='1',
        modis_burned_pixel_count='1', modis_ba_any='1', modis_burnable_km2_union='4',
        modis_burnable_km2_annual='2', modis_burned_frac_union='0.25', modis_burned_frac_annual='0.5',
        modis_aoi_area_land_km2='4')
    if state in ('none', 'no_supported'):
        row.update(ba_coverage_status='NO_SUPPORTED_EVIDENCE', ba_known_union_burned_km2='0',
            ba_state_burndate_masked_km2='3', ba_reason_burndate_masked_km2='3',
            ba_state_explicit_zero_km2='0', ba_state_accepted_km2='0', ba_reason_shortened_km2='0',
            ba_shortened_km2='0', ba_supported_area_km2='0', ba_supported_fraction='',
            modis_ba_km2='0', modis_burned_pixel_count='0', modis_ba_any='0',
            modis_burned_frac_union='0', modis_burned_frac_annual='0')
    elif state == 'anomaly':
        row.update(ba_status='SOURCE_PIXEL_ANOMALY', ba_anomaly_area_km2='1', ba_anomaly_pixel_count='1',
            ba_state_unsupported_km2='1', ba_state_explicit_zero_km2='0',
            ba_reason_unexpected_burndate_km2='1', ba_reason_positive_special_km2='1', ba_reason_special_km2='1',
            ba_supported_area_km2='1', ba_supported_fraction='1', modis_ba_km2='', modis_burned_pixel_count='',
            modis_ba_any='', modis_burnable_km2_union='', modis_burned_frac_union='', modis_burned_frac_annual='')
    elif state == 'unresolved':
        row.update(ba_status='DOMAIN_UNRESOLVED', ba_domain_unresolved_km2='1',
            modis_ba_km2='', modis_burned_pixel_count='', modis_ba_any='', modis_burnable_km2_union='',
            modis_burned_frac_union='', modis_zero_union_den_flag='', modis_burned_frac_annual='')
    elif state == 'annual_unknown':
        row.update(ba_annual_unknown_km2='1', modis_burnable_km2_annual='',
                   modis_burned_frac_annual='', modis_zero_annual_den_flag='')
    elif state == 'zero_union':
        for name in c3.STATES + c3.REASONS:
            row[name] = '0'
        row.update(ba_status='ZERO_UNION_DENOMINATOR', ba_coverage_status='NO_KNOWN_UNION_PIXELS',
            ba_known_union_area_km2='0', ba_known_union_burned_km2='0', ba_domain_excluded_km2='4', ba_shortened_km2='0',
            ba_full_period_only_km2='0', ba_supported_area_km2='0', ba_supported_fraction='',
            modis_ba_km2='0', modis_burned_pixel_count='0', modis_ba_any='0', modis_burnable_km2_union='0',
            modis_burnable_km2_annual='0', modis_burned_frac_union='', modis_burned_frac_annual='',
            modis_zero_union_den_flag='1', modis_zero_annual_den_flag='1')
    elif state == 'no_pixels' or state in c3.TECHNICAL_STATUSES:
        for name in c3.RASTER_FIELDS:
            row[name] = ''
        status = 'NO_PIXEL_CENTRES' if state == 'no_pixels' else state
        row.update(ba_status=status, ba_coverage_status=status,
                   ba_sampled_pixel_count='0' if state == 'no_pixels' else '')
    elif state == 'full':
        row.update(ba_coverage_status='FULL_EVIDENCE_NO_SHORTENING', ba_state_qa_missing_km2='0',
            ba_reason_qa_missing_km2='0', ba_state_burndate_masked_km2='0', ba_reason_burndate_masked_km2='0',
            ba_state_explicit_zero_km2='3', ba_supported_area_km2='4', ba_supported_fraction='0.25',
            ba_reason_shortened_km2='0', ba_shortened_km2='0', ba_full_period_only_km2='1')
    elif state != 'partial':
        raise ValueError('Unknown synthetic c3 state: ' + state)
    return row


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fields or c3.FIELDS), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def write_delivery(root, *, full=False, years=None, states=None, end_year=None):
    root = Path(root)
    source, universe = root / 'downloads', root / 'unit_universe.csv'
    units = []
    for code in c3.ZONES:
        for level in c3.LEVELS:
            row = make_row(level=level, zone=code)
            identity = {name: row[name] for name in ('level', 'unit_id', 'unit_code', 'unit_name', 'parent_level', 'parent_id', 'parent_code', 'parent_name')}
            units.append({'unit_type': 'zone' if level == 'acz' else 'district', **identity, 'area_sqkm': '4'})
    write_csv(universe, units, fields=list(units[0]))
    for domain, (start, end) in c3.DOMAIN_WINDOWS.items():
        selected_years = list(range(start, (end_year or end) + 1)) if full else list(years or [2024])
        for year in selected_years:
            if year < start:
                continue
            for code in c3.ZONES:
                for level in c3.LEVELS:
                    rows = [make_row(domain, level, code, year, month, (states or {}).get((domain, level, code, month), 'partial')) for month in range(1, 13)]
                    extra = ['ba_annual_lc_source_index'] if year > end else []
                    for row in rows:
                        if extra:
                            row['ba_annual_lc_source_index'] = f'{year}_01_01'
                    write_csv(source / f'rp1_ba_{level}_monthly_c3_{code}_{domain}_{year}_ext.csv', rows, fields=[*c3.FIELDS, *extra])
    return source, universe
