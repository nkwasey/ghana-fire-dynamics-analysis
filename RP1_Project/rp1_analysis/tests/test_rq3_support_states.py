import pandas as pd
import pytest
from _c3_analysis_fixture import fixture
from rp1_analysis_v1.validation import DataContractError, rq3_mcd64a1_support_audit


def test_monthly_audit_includes_guarded_records_and_scenario_zeros():
    side, _, _, district = fixture()
    original=district.copy(deep=True)
    summary=rq3_mcd64a1_support_audit(district,observation_support=side).set_index("month")
    assert summary.loc[1,"scenario_zero_rows"] == 1
    assert summary.loc[1,"no_supported_evidence_rows"] == 1
    assert summary.loc[3,"withheld_rows"] == 1
    assert summary.loc[3,"numeric_missing_rows"] == 1
    assert summary.loc[5,"zero_union_rows"] == 1
    pd.testing.assert_frame_equal(district,original)


def test_c3_audit_requires_unique_complete_evidence():
    side,_,_,district=fixture()
    with pytest.raises(DataContractError,match="mandatory"):
        rq3_mcd64a1_support_audit(district)
    part=side.loc[~(side.level.eq("district") & side.family.eq("ba2012") & side.month.eq("1"))]
    with pytest.raises(DataContractError,match="missing keys"):
        rq3_mcd64a1_support_audit(district,observation_support=part)
    with pytest.raises(DataContractError,match="duplicate keys"):
        rq3_mcd64a1_support_audit(district,observation_support=pd.concat([side,side.iloc[[-1]]]))


def test_withheld_ba_cannot_be_counted_as_absence():
    side,_,_,district=fixture()
    district.loc[district.month.eq(3),"modis_ba_km2_ba2012"]=0
    district.loc[district.month.eq(3),"modis_ba_any_ba2012"]=0
    with pytest.raises(DataContractError,match="cannot become model absence"):
        rq3_mcd64a1_support_audit(district,observation_support=side)

