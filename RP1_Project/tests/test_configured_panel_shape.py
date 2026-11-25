from pathlib import Path
import sys
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import merge_af_ba_panels as merger


@pytest.fixture(autouse=True)
def restore_study():
    yield
    merger.configure_study({})


def test_configured_spine_and_key_audit_use_months_and_units():
    merger.configure_study({
        'start_yyyymm': 202411, 'end_yyyymm': 202602,
        'viirs_support_start_yyyymm': 202411,
        'ba2012_support_start_yyyymm': 202411,
        'expected_units': {'acz': 2, 'district': 3},
    })
    units = pd.DataFrame([
        dict(level=level, unit_id=f'{level}-{i}', unit_code=str(i), unit_name=str(i),
             parent_level=None, parent_id=None, parent_code=None, parent_name=None)
        for level, count in [('acz', 2), ('district', 3)] for i in range(count)
    ])
    acz = merger.build_canonical_spine(units, 'acz')
    district = merger.build_canonical_spine(units, 'district')
    assert len(acz) == 32
    assert len(district) == 48
    assert acz.yyyymm.min() == 202411 and acz.yyyymm.max() == 202602
    def panel(spine):
        p = spine.copy()
        for col in merger.FINAL_OUTPUT_COLUMNS:
            if col not in p:
                p[col] = None
        return p[merger.FINAL_OUTPUT_COLUMNS]
    audit = merger.build_key_audit(panel(acz), panel(district)).set_index('level')
    assert audit.loc['acz', 'expected_rows'] == 32
    assert audit.loc['district', 'expected_rows'] == 48
    assert audit.passes_key_audit.all()
    incomplete_panel = panel(acz).iloc[:-1]
    incomplete = merger.build_key_audit(incomplete_panel, panel(district)).set_index('level')
    assert not incomplete.loc['acz', 'passes_key_audit']
    with pytest.raises(merger.ValidationError, match='expected 32 rows, got 31'):
        merger.validate_final_panel(incomplete_panel, 'acz')


def test_default_and_invalid_level():
    merger.configure_study({})
    with pytest.raises(merger.ValidationError, match='bound to selected geography'):
        merger.expected_panel_rows('district')
    merger.configure_study({'expected_units': {'acz': 5, 'district': 3}})
    assert merger.expected_panel_rows('acz') == 1440
    assert merger.expected_panel_rows('district') == 864
    with pytest.raises(merger.ValidationError):
        merger.expected_panel_rows('national')
