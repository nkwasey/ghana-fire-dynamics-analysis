"""Source-only c3 guards for inventory, aggregation and frozen research scope."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from _c3_analysis_fixture import fixture
from rp1_analysis_v1.config import ConfigurationError, governed_input_paths, load_configuration_bundle
from rp1_analysis_v1.integration import IntegrationError, validate_governed_inputs
from rp1_analysis_v1.validation import DataContractError, _check_validation_rules, reconcile_district_to_acz

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=load_configuration_bundle(ROOT/"config")


def script(name):
    spec=importlib.util.spec_from_file_location("c3_test_"+name,ROOT/"scripts"/(name+".py"))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_c3_schema_keeps_111_roles_and_exact_18_file_inventory():
    schema=BUNDLE.data_schema
    assert schema.field_count == 111
    assert schema.data_schema_version == "rp1-data-schema-v1.2"
    assert schema.panel_schema_version == "rp1_fire_panel_consolidated_v3"
    assert len(governed_input_paths(schema)) == 18
    assert "data/raw/ba_observation_support.csv" in governed_input_paths(schema)
    assert not schema.field("modis_ba_km2_ba2001").required_when_supported
    assert schema.field("modis_burned_frac_annual_ba2001").maximum is None


@pytest.mark.parametrize("path", ["/absolute/panel.csv", "../panel.csv", r"C:\\panel.csv", r"\\server\share\panel.csv"])
def test_governed_input_paths_reject_nonportable_paths(path):
    schema = SimpleNamespace(panels={"panel": SimpleNamespace(path=path)}, auxiliary_inputs={},
                             geometries={}, provenance={"expected_governed_files": 1})
    with pytest.raises(ConfigurationError, match="Invalid governed staged input path"):
        governed_input_paths(schema)


def test_omitted_companion_fails_runtime_before_any_input_mutation(tmp_path):
    items=[{"staged_path":p,"origin_path":p,"sha256":"a"*64,"size_bytes":1}
           for p in governed_input_paths(BUNDLE.data_schema) if "ba_observation_support" not in p]
    path=tmp_path/"inventory.json"
    path.write_text(json.dumps({"schema_version":BUNDLE.analysis.schema_version,
        "provenance_schema_version":"rp1-input-provenance-v2","files":items}))
    original=path.read_bytes()
    with pytest.raises(IntegrationError,match="exact configured c3 input set"):
        validate_governed_inputs(SimpleNamespace(root=tmp_path,input_hash_inventory=path),bundle=BUNDLE)
    assert path.read_bytes() == original


@pytest.mark.parametrize(("field", "value", "message"), [
    ("staged_path", "", "Malformed input-hash inventory staged_path"),
    ("origin_path", "", "Malformed input-hash inventory origin_path"),
    ("sha256", "not-a-sha256", "Malformed input-hash inventory SHA-256"),
    ("sha256", "g" * 64, "Malformed input-hash inventory SHA-256"),
    ("size_bytes", "1", "Malformed input-hash inventory size_bytes"),
    ("size_bytes", True, "Malformed input-hash inventory size_bytes"),
    ("size_bytes", -1, "Malformed input-hash inventory size_bytes"),
])
def test_governed_input_validation_rejects_malformed_identity(tmp_path, field, value, message):
    items = [{"staged_path": p, "origin_path": p, "sha256": "a" * 64, "size_bytes": 1}
             for p in governed_input_paths(BUNDLE.data_schema)]
    items[0][field] = value
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"schema_version": BUNDLE.analysis.schema_version,
        "provenance_schema_version": "rp1-input-provenance-v2", "files": items}))
    original = path.read_bytes()
    with pytest.raises(IntegrationError, match=message):
        validate_governed_inputs(SimpleNamespace(root=tmp_path, input_hash_inventory=path), bundle=BUNDLE)
    assert path.read_bytes() == original


def test_old_existing_inventory_cannot_be_rehashed_without_companion():
    module=script("regenerate_data_provenance")
    items=[{"staged_path":p,"origin_path":p} for p in governed_input_paths(BUNDLE.data_schema)
           if "ba_observation_support" not in p]
    with pytest.raises(ValueError,match="exact configured c3 input set"):
        module.rebuild_input_inventory({"schema_version":BUNDLE.analysis.schema_version,"files":items},
            subproject_root=ROOT,panel_manifest={})


def test_positive_annual_denominator_does_not_force_rate_for_withheld_primary():
    _,_,_,frame=fixture()
    frame=frame.loc[frame.month.le(4)].copy()
    for sensor in ('modis','viirs'):
        frame[sensor+'_det_primary']=2
        frame[sensor+'_det_primary_any']=1
        frame[sensor+'_frp_sum_daily_max_mw']=5
    for family in ("ba2001","ba2012"):
        for domain in ("union","annual"):
            frame[f"modis_ba_km2_per100km2_{domain}_{family}"] = (
                100*frame[f"modis_ba_km2_{family}"]/frame[f"modis_burnable_km2_{domain}_{family}"].where(
                    frame[f"modis_burnable_km2_{domain}_{family}"].gt(0)))
    for rule in BUNDLE.data_schema.validation_rules['normalizations']:
        frame[rule['field']]=float(rule['scale'])*frame[rule['numerator']]/frame[rule['denominator']].where(frame[rule['denominator']].gt(0))
    for rule in BUNDLE.data_schema.validation_rules['binary_products']:
        available=frame[rule['left']].notna() & frame[rule['right']].notna()
        frame[rule['field']]=(frame[rule['left']].eq(rule['left_value']) & frame[rule['right']].eq(rule['right_value'])).astype(float).where(available)
    _check_validation_rules(frame,"fixture",BUNDLE.data_schema)
    frame.loc[frame.month.eq(3),"modis_ba_km2_per100km2_annual_ba2012"]=0
    with pytest.raises(DataContractError,match="withheld inputs"):
        _check_validation_rules(frame,"fixture",BUNDLE.data_schema)


def test_fixed_union_denominator_must_not_vary_within_unit():
    schema = BUNDLE.data_schema
    field = "modis_burnable_km2_union_ba2001"
    temporal = next(rule for rule in schema.validation_rules["temporal_consistency"] if rule["field"] == field)
    normal = next(rule for rule in schema.validation_rules["normalizations"]
                  if rule["field"] == "modis_ba_km2_per100km2_union_ba2001")
    support = schema.source_supports[temporal["support"]]
    first = pd.Period(str(support["start"]), freq="M")
    assert first + 1 <= pd.Period(str(support["end"]), freq="M")
    months = [int(period.strftime("%Y%m")) for period in (first, first + 1)]
    frame = pd.DataFrame({"unit_id": ["synthetic", "synthetic"], "yyyymm": months,
                          field: [10.0, 10.0], normal["numerator"]: [2.0, 2.0],
                          normal["field"]: [20.0, 20.0]})
    selected = SimpleNamespace(source_supports=schema.source_supports,
        validation_rules={"normalizations": [normal], "temporal_consistency": [temporal]})
    _check_validation_rules(frame, "synthetic", selected)
    frame.loc[1, field] = 11.0
    frame.loc[1, normal["field"]] = float(normal["scale"]) * frame.loc[1, normal["numerator"]] / frame.loc[1, field]
    with pytest.raises(DataContractError, match="fixed field .* varies within units"):
        _check_validation_rules(frame, "synthetic", selected)


def test_reconciliation_never_compares_partial_null_skipping_sum():
    field="modis_ba_km2_ba2001"
    districts=pd.DataFrame({"unit_id":["a","b"],"parent_code":["CZ","CZ"],
        "yyyymm":[202401,202401],field:[1,np.nan]})
    acz=pd.DataFrame({"unit_code":["CZ"],"yyyymm":[202401],field:[1.]})
    row=reconcile_district_to_acz(districts,acz,fields=[field],data_schema=BUNDLE.data_schema,allow_c3_withheld=True).iloc[0]
    assert row.rows_compared == 0
    assert row.incomplete_constituent_rows == 1
    assert row.not_comparable_rows == 1
    assert row.comparison_status == "WITHHELD_ROWS_NOT_COMPARED"


def test_pilot_cannot_rewrite_operational_research_configuration(tmp_path):
    _,manifest,_,_=fixture()
    manifest["ba_bundle"]["scope"]="pilot"
    raw=tmp_path/"data/raw";raw.mkdir(parents=True)
    (raw/"fire_panel_manifest.json").write_text(json.dumps(manifest))
    config=tmp_path/"config";config.mkdir()
    for name in ("analysis_contract.yml","data_schema_contract.yml"):
        (config/name).write_bytes((ROOT/"config"/name).read_bytes())
    before={p.name:p.read_bytes() for p in config.iterdir()}
    with pytest.raises(ValueError,match="Pilot c3"):
        script("configure_generated_inputs").configure(tmp_path)
    assert before == {p.name:p.read_bytes() for p in config.iterdir()}


def test_publication_contract_declares_c3_evidence_without_changing_model_roles():
    sources={s.source_attribute for s in BUNDLE.output.tables}
    assert {"c3_evidence_summary","c3_population_exclusions","c3_reconciliation_eligibility","c3_diagnostic_reconciliation"} <= sources
    assert BUNDLE.analysis.field_roles["rq3"]["ba_area"] == "modis_ba_km2_ba2012"

