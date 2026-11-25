from pathlib import Path
import pandas as pd
import pytest
from rp1_analysis_v1.config import load_data_schema_contract
from rp1_analysis_v1.validation import reconcile_district_to_acz, DataContractError

SCHEMA = Path(__file__).resolve().parents[1] / 'config/data_schema_contract.yml'
UNION = 'modis_burnable_km2_union_ba2001'
COUNT = 'modis_det_primary'

def frames(delta):
    district = pd.DataFrame({'unit_id':['district_1'], 'parent_code':['CZ'], 'yyyymm':[200101], UNION:[1.0], COUNT:[1.]})
    acz = pd.DataFrame({'unit_code':['CZ'], 'yyyymm':[200101], UNION:[1.0+delta], COUNT:[1.]})
    return district, acz

def test_union_tolerance_config_and_reporting():
    schema=load_data_schema_contract(SCHEMA)
    d,a=frames(0.000009)
    result=reconcile_district_to_acz(d,a,fields=[UNION,COUNT],data_schema=schema).set_index('field')
    assert result.loc[UNION,'absolute_tolerance']==1e-5
    assert result.loc[UNION,'relative_tolerance']==0
    assert result.loc[COUNT,'absolute_tolerance']==1e-8
    d,a=frames(0.000011)
    with pytest.raises(DataContractError): reconcile_district_to_acz(d,a,fields=[UNION],data_schema=schema)

def test_missing_null_and_explicit_override_rejected():
    schema=load_data_schema_contract(SCHEMA)
    d,a=frames(0.000009)
    with pytest.raises(DataContractError): reconcile_district_to_acz(d,a,fields=[UNION],absolute_tolerance=1e-8,relative_tolerance=0,data_schema=schema)
    d.loc[0,UNION]=None
    with pytest.raises(DataContractError): reconcile_district_to_acz(d,a,fields=[UNION],data_schema=schema)
    d,a=frames(0);d.loc[0,'parent_code']='BAD'
    with pytest.raises(DataContractError): reconcile_district_to_acz(d,a,fields=[UNION],data_schema=schema)
