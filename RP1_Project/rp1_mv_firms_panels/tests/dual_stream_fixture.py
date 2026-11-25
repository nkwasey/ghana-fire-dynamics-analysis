"""Synthetic receipt chain for command-layer tests, not scientific output."""
import json

import pandas as pd

from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.hashing import sha256_file, sha256_text, stable_json_dumps


def write_dual_stream_evidence(root, cfg_path, run_dir, run_id):
    cfg = load_config(cfg_path, validate_paths=False, repo_root=root).config
    digest = sha256_text(stable_json_dumps(cfg.to_canonical_dict()))
    source = root / "synthetic_source.csv"
    source.write_text("synthetic\n", encoding="utf-8")
    geography = []
    geography_paths = [root / polygon.path for polygon in cfg.io.inputs.polygons]
    if cfg.io.inputs.land_mask and cfg.processing.land_mask_policy.enabled_if_path_provided:
        geography_paths.append(root / cfg.io.inputs.land_mask)
    for path in geography_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic geography identity\n", encoding="utf-8")
        geography.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    count = run_dir / "fires_canonical/viirs/fires_canonical_viirs_2024.csv"
    frp = run_dir / "fires_frp_canonical/viirs/fires_frp_canonical_viirs_2024.csv"
    for path in (count, frp):
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=cfg.determinism.column_order["fires_canonical"]).to_csv(path, index=False)
    qa = run_dir / "qa/prepare_year_viirs_2024_summary.json"
    qa.write_text(json.dumps({"method_version":"viirs_frp_dual_stream_v1", "config_sha256":digest, "in_memory_inputs":False,
        "sensor":"viirs", "year":2024, "run_id":run_id,
        "source_file":source.relative_to(root).as_posix(), "source_selection":"explicit_path",
        "geography_file_identity":geography,
        "steps":{"frp_dedup":{"finite_frp_first":True, "tie_break":list(cfg.processing.deduplication.tie_break),
            "latlon_round_decimals":cfg.processing.deduplication.latlon_round_decimals,
            "include_satellite_in_key":cfg.processing.deduplication.include_satellite_in_key}},
        "source_file_identity":[{"path":source.relative_to(root).as_posix(),"sha256":sha256_file(source)}]}))
    def entry(path):
        return {"path":path.relative_to(root).as_posix(), "sha256":sha256_file(path)}
    receipt = {"method_version":"viirs_frp_dual_stream_v1", "sensor":"viirs", "year":2024,
        "run_id":run_id, "config_sha256":digest, "fires_canonical_csv":entry(count),
        "fires_frp_canonical_csv":entry(frp) | {"rows":0}, "qa_summary_json":entry(qa)}
    (run_dir / "qa/prepare_year_viirs_2024_manifest.json").write_text(json.dumps(receipt))
    policy_path = run_dir / "qa/aggregate_monthly_viirs_summary.json"
    policy = json.loads(policy_path.read_text())
    policy["steps"]["frp"].update(method_version="viirs_frp_dual_stream_v1", selection_stage="before_independent_deduplication")
    policy["steps"]["read_fires_canonical"] = {"partitions":[{"year":2024, **entry(count),
        "frp_path":frp.relative_to(root).as_posix(), "frp_sha256":sha256_file(frp)}]}
    policy_path.write_text(json.dumps(policy))
    manifest_path = run_dir / "qa/aggregate_monthly_viirs_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["qa_summary_json"] = entry(policy_path)
    manifest_path.write_text(json.dumps(manifest))
