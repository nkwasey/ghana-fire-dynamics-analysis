import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from rp1_analysis_v1.config import load_analysis_contract
from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified
from rp1_analysis_v1 import viirs_confidence as audit_module


@pytest.fixture
def analysis():
    return load_analysis_contract(Path(__file__).resolve().parents[1] / "config" / "analysis_contract.yml")


@pytest.fixture
def paired_panel(analysis):
    window = analysis.study["temporal_windows"]["overlap_monthly"]
    months = pd.period_range(window["start"], window["end"], freq="M")
    records = []
    for unit, code, name in (("A", "CZ", "Coastal"), ("B", "GS", "Guinea Savannah")):
        for period in months:
            key = period.year * 100 + period.month
            records.append({
                "unit_id": unit, "parent_code": code, "parent_name": name,
                "yyyymm": key, "year": period.year, "month": period.month,
                "viirs_det_low": 2 if (unit, key) == ("A", 201202) else 0,
                "viirs_det_nominal": {("A", 201203): 3, ("B", 201202): 1}.get((unit, key), 0),
                "viirs_det_high": 2 if (unit, key) == ("A", 201203) else 0,
                "modis_ba_any_ba2012": int(key == 201203),
                "modis_burnable_km2_union_ba2012": 100.0,
                "viirs_supported_flag": 1, "ba2012_supported_flag": 1,
            })
    frame = pd.DataFrame(records)
    frame["viirs_det_nh"] = frame["viirs_det_nominal"] + frame["viirs_det_high"]
    frame["viirs_det_all"] = frame["viirs_det_nh"] + frame["viirs_det_low"]
    frame["viirs_det_primary"] = frame["viirs_det_nh"]
    frame["viirs_det_primary_any"] = frame["viirs_det_primary"].gt(0).astype(int)
    return frame


def _stage2(tmp_path, panel):
    path = tmp_path / "panel_monthly_viirs.csv"
    populated = panel["viirs_det_all"].gt(0)
    fields = ["unit_id", "yyyymm", "viirs_det_low", "viirs_det_nominal", "viirs_det_high", "viirs_det_nh"]
    panel.loc[populated, fields].assign(level="district").to_csv(path, index=False)
    return path


def test_paired_scope_counts_and_denominators(tmp_path, monkeypatch, analysis, paired_panel):
    path = _stage2(tmp_path, paired_panel)
    receipt = pd.DataFrame({"year": range(2012, 2025)})
    monkeypatch.setattr(audit_module, "_read_source_receipts", lambda *args: (receipt, path))
    original = paired_panel.copy(deep=True)
    result = audit_module.build_viirs_confidence_audit(paired_panel, analysis, {}, evidence_root=tmp_path)
    output = result.correspondence
    national = output.loc[output["summary_scope"].eq("national")].set_index("confidence_policy")

    assert result.counts["summary_scope"].value_counts().to_dict() == {
        "national": 1, "acz": 2, "month": 12, "acz_month": 24,
    }
    national_counts = result.counts.iloc[0]
    assert national_counts["all_confidence_detections"] == 8
    assert national_counts["low_detection_share_pct"] == 25
    assert national["paired_district_months"].tolist() == [310, 310, 310]
    assert national["viirs_positive_district_months"].tolist() == [2, 3, 1]
    assert national["mcd64a1_absence_pct_given_viirs_positive"].tolist() == pytest.approx([50, 200 / 3, 0])
    assert national["mcd64a1_absence_delta_pp_vs_nominal_high"].tolist() == pytest.approx([0, 50 / 3, -50])
    assert national["viirs_positive_added_vs_nominal_high"].tolist() == [0, 1, 0]
    assert national["viirs_positive_lost_vs_nominal_high"].tolist() == [0, 0, 1]
    assert national["single_ba_outcome_among_positives"].tolist() == [False, False, True]
    state_fields = ["both_zero", "mcd64a1_positive_viirs_zero", "viirs_positive_mcd64a1_zero", "both_positive"]
    assert output[state_fields].sum(axis=1).eq(output["paired_district_months"]).all()
    january = output.loc[output["summary_scope"].eq("month") & output["month"].eq(1)]
    assert january["no_viirs_positive_rows"].all()
    assert january["mcd64a1_absence_pct_given_viirs_positive"].isna().all()
    assert not january["single_ba_outcome_among_positives"].any()

    shuffled = audit_module.build_viirs_confidence_audit(
        paired_panel.sample(frac=1, random_state=8), analysis, {}, evidence_root=tmp_path,
    )
    pd.testing.assert_frame_equal(result.counts, shuffled.counts)
    pd.testing.assert_frame_equal(result.correspondence, shuffled.correspondence)
    pd.testing.assert_frame_equal(paired_panel, original)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [("viirs_det_all", 100, "class identities"),
     ("viirs_det_low", float("nan"), "missing, negative or invalid"),
     ("viirs_det_high", -1, "missing, negative or invalid"),
     ("viirs_det_nominal", 0.5, "fractional counts"),
     ("viirs_det_primary_any", 1, "class identities"),
     ("ba2012_supported_flag", 0, "supported thermal and BA observations")],
)
def test_rejects_invalid_paired_states(analysis, paired_panel, field, replacement, message):
    paired_panel[field] = paired_panel[field].astype(float)
    paired_panel.loc[0, field] = replacement
    with pytest.raises(audit_module.ViirsConfidenceError, match=message):
        audit_module.build_viirs_confidence_audit(paired_panel, analysis, {})


def test_rejects_missing_key_and_unbound_source(analysis, paired_panel, tmp_path):
    with pytest.raises(audit_module.ViirsConfidenceError, match="complete, unique district-month keys"):
        audit_module.build_viirs_confidence_audit(paired_panel.iloc[1:], analysis, {})
    with pytest.raises(RQ3InputsUnverified):
        audit_module.build_viirs_confidence_audit(paired_panel, analysis, {}, evidence_root=tmp_path)


def test_disagreement_with_stage2_counts_fails(tmp_path, monkeypatch, analysis, paired_panel):
    path = _stage2(tmp_path, paired_panel)
    counts = pd.read_csv(path)
    counts.loc[0, "viirs_det_low"] += 1
    counts.to_csv(path, index=False)
    monkeypatch.setattr(audit_module, "_read_source_receipts", lambda *args: (pd.DataFrame(), path))
    with pytest.raises(audit_module.ViirsConfidenceError, match="disagree with the admitted Stage 2 VIIRS counts"):
        audit_module.build_viirs_confidence_audit(paired_panel, analysis, {}, evidence_root=tmp_path)


def test_aggregate_receipts_require_every_analysis_year(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_module, "require_rq3_inputs_acknowledged", lambda *args, **kwargs: None)
    firms_root = tmp_path / "RP1_Project" / "rp1_mv_firms_panels"
    firms_root.mkdir(parents=True)

    def write(name, value):
        path = firms_root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        reference = {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return reference, {**reference, "path": path.relative_to(tmp_path).as_posix()}

    panel, panel_reference = write("panel_monthly_viirs.csv", {})
    aggregate, aggregate_reference = write("aggregate_monthly_viirs_summary.json", {
        "sensor": "viirs", "steps": {"read_fires_canonical": {"n_files": 1, "partitions": [{"year": 2012}]}},
    })
    _, aggregate_manifest = write("aggregate_monthly_viirs_manifest.json", {
        "panel_sensor_monthly": panel, "qa_summary_json": aggregate,
    })
    policy = {"count_population_viirs": "all_confidence_deduplicated"}
    _, combine = write("combine_panels_manifest.json", {"active_fire_method": policy})
    manifest = {"active_fire_method": {
        **policy, "input_profiles": {"viirs": "ghana_firms_archive_sp_v1"}, "combine_receipt": combine,
        "evidence_files": [aggregate_manifest, aggregate_reference, panel_reference],
    }}
    with pytest.raises(audit_module.ViirsConfidenceError, match="do not cover the configured analysis years"):
        audit_module._read_source_receipts(manifest, tmp_path, tuple(range(2012, 2025)))
