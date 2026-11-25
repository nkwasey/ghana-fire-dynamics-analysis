import pytest
import hashlib
import json
from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified, require_rq3_inputs_acknowledged


def test_missing_or_wrong_policy_is_rejected():
    for manifest in ({}, {"active_fire_method":{"frp_confidence_categories":["l","n","h"]}}):
        with pytest.raises(RQ3InputsUnverified):
            require_rq3_inputs_acknowledged(manifest)


def test_recorded_current_policy_is_required(tmp_path):
    policy = {
        "status":"VERIFIED_AGGREGATION_INPUTS",
        "frp_confidence_categories":["n","h"],
        "frp_aggregation":"mean_of_daily_maxima_over_eligible_utc_days",
        "evidence_files":[{"path":f"qa{i}.json","sha256":"a"*64} for i in range(6)],
    }
    with pytest.raises(RQ3InputsUnverified):
        require_rq3_inputs_acknowledged({"active_fire_method": policy})
    policy.update(method_version="viirs_frp_dual_stream_v1", frp_selection_stage="before_independent_deduplication",
        frp_population_viirs="nominal_high_independently_deduplicated", frp_deduplication_independent=True,
        frp_finite_values_rank_first=True, viirs_preparation_evidence=[{"path":f"p{i}","sha256":"b"*64} for i in range(5)])
    policy.update(config_sha256="a"*64, frp_min_mw=0., deduplication={"tie_break":["stable_first"], "latlon_round_decimals":6, "include_satellite_in_key":True})
    for entry in [*policy["evidence_files"], *policy["viirs_preparation_evidence"]]:
        path = tmp_path / entry["path"]
        path.write_text(entry["path"])
        entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = tmp_path / "combine.json"
    combined = dict(policy)
    combined["evidence_files"] = [{**entry, "scope":"workspace"} for entry in policy["evidence_files"]]
    combined["viirs_preparation_evidence"] = [{**entry, "scope":"workspace"} for entry in policy["viirs_preparation_evidence"]]
    receipt.write_text(json.dumps({"active_fire_method":combined}))
    policy["combine_receipt"] = {"path":"combine.json", "sha256":hashlib.sha256(receipt.read_bytes()).hexdigest()}
    require_rq3_inputs_acknowledged({"active_fire_method": policy}, evidence_root=tmp_path)
    policy["frp_min_mw"] = 99
    with pytest.raises(RQ3InputsUnverified, match="inconsistent"):
        require_rq3_inputs_acknowledged({"active_fire_method": policy}, evidence_root=tmp_path)
    policy["frp_min_mw"] = 0.
    receipt.write_text("changed")
    with pytest.raises(RQ3InputsUnverified, match="hash mismatch"):
        require_rq3_inputs_acknowledged({"active_fire_method": policy}, evidence_root=tmp_path)
