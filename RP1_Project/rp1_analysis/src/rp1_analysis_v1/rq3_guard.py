"""Require recorded FRP population evidence from the generated merger handoff."""
from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
import re

class RQ3InputsUnverified(RuntimeError):
    """Raised when current input policy evidence is absent or inconsistent."""


def require_rq3_inputs_acknowledged(manifest: Mapping | None = None, *, evidence_root: Path | None = None) -> None:
    if manifest is None:
        from .paths import ProjectPaths
        from .data_io import load_data_authorities
        manifest = load_data_authorities(ProjectPaths.discover()).manifest
    policy = manifest.get("active_fire_method", {})
    if not isinstance(policy, Mapping):
        raise RQ3InputsUnverified("Active-fire method evidence must be an object")
    evidence = policy.get("evidence_files", [])
    valid_evidence = isinstance(evidence, (list, tuple)) and len(evidence) == 6 and all(
        isinstance(item, Mapping) and isinstance(item.get("path"), str) and bool(item["path"])
        and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
        for item in evidence
    )
    preparation = policy.get("viirs_preparation_evidence", [])
    dedup = policy.get("deduplication")
    threshold = policy.get("frp_min_mw")
    valid_preparation = isinstance(preparation, (list, tuple)) and len(preparation) >= 5 and all(
        isinstance(item, Mapping) and isinstance(item.get("path"), str) and bool(item["path"])
        and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) for item in preparation
    )
    if (policy.get("status") != "VERIFIED_AGGREGATION_INPUTS" or
        policy.get("method_version") != "viirs_frp_dual_stream_v1" or
        policy.get("frp_selection_stage") != "before_independent_deduplication" or
        policy.get("frp_population_viirs") != "nominal_high_independently_deduplicated" or
        policy.get("frp_deduplication_independent") is not True or
        policy.get("frp_finite_values_rank_first") is not True or
        re.fullmatch(r"[0-9a-f]{64}", str(policy.get("config_sha256", ""))) is None or
        not isinstance(dedup, Mapping) or not isinstance(dedup.get("tie_break"), list) or not dedup.get("tie_break") or
        not isinstance(dedup.get("latlon_round_decimals"), int) or not isinstance(dedup.get("include_satellite_in_key"), bool) or
        not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold < 0 or
        not valid_preparation or
        policy.get("frp_confidence_categories") != ["n", "h"] or
        policy.get("frp_aggregation") != "mean_of_daily_maxima_over_eligible_utc_days" or
        not valid_evidence):
        raise RQ3InputsUnverified(
            "Generated merger inputs lack nominal/high FRP policy evidence. "
            "Rebuild active-fire panels and merge them with the selected burned-area inputs. "
            "The generated manifest must record the checked Stage 2 QA files and their hashes. "
            "Policy evidence is a lineage check, not independent scientific validation."
        )
    profiles = policy.get("input_profiles")
    source_preparation = policy.get("source_preparation_evidence", [])
    if profiles is not None:
        if (not isinstance(profiles, Mapping) or set(profiles) != {"modis", "viirs"}
                or any(not isinstance(value, str) or value not in {"native_firms_v1", "ghana_firms_archive_sp_v1"} for value in profiles.values())
                or not isinstance(source_preparation, (list, tuple))
                or ("ghana_firms_archive_sp_v1" in profiles.values() and not source_preparation)
                or not all(isinstance(item, Mapping) and isinstance(item.get("path"), str) and item["path"]
                           and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) for item in source_preparation)):
            raise RQ3InputsUnverified("Archive SP inputs lack source preparation/profile evidence")
    elif source_preparation:
        raise RQ3InputsUnverified("Source preparation evidence requires explicit input profiles")
    receipt = policy.get("combine_receipt")
    if not isinstance(receipt, Mapping) or not isinstance(receipt.get("path"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256", ""))):
        raise RQ3InputsUnverified("Missing active-fire combine receipt identity")
    if evidence_root is None:
        from .paths import ProjectPaths
        evidence_root = ProjectPaths.discover().root.parent.parent
    root = Path(evidence_root).resolve()
    checked = {}
    for item in [*evidence, *preparation, *source_preparation, receipt]:
        relative = Path(item["path"])
        source = (root / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(root) or not source.is_file():
            raise RQ3InputsUnverified(f"Active-fire evidence is missing or outside the project: {relative}")
        if source in checked:
            if checked[source] != item["sha256"]:
                raise RQ3InputsUnverified(f"Conflicting active-fire evidence hashes: {relative}")
            continue
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != item["sha256"]:
            raise RQ3InputsUnverified(f"Active-fire evidence hash mismatch: {relative}")
        checked[source] = item["sha256"]
    try:
        combined = json.loads((root / receipt["path"]).read_text(encoding="utf-8"))["active_fire_method"]
        keys = ("status", "method_version", "frp_selection_stage", "frp_population_viirs",
                "frp_deduplication_independent", "frp_finite_values_rank_first",
                "frp_confidence_categories", "frp_aggregation", "config_sha256",
                "frp_min_mw", "deduplication", "input_profiles")
        if any(policy.get(key) != combined.get(key) for key in keys):
            raise ValueError("merger method differs from combine receipt")
        firms_root = root / "RP1_Project" / "rp1_mv_firms_panels"
        names = ["evidence_files", "viirs_preparation_evidence"]
        if profiles is not None:
            names.append("source_preparation_evidence")
        for name in names:
            expected = {(str((root if item.get("scope") == "workspace" else firms_root).joinpath(item["path"]).resolve()), item["sha256"])
                        for item in combined[name]}
            recorded = {(str((root / item["path"]).resolve()), item["sha256"]) for item in policy[name]}
            if expected != recorded:
                raise ValueError(f"{name} differs from combine receipt")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RQ3InputsUnverified(f"Active-fire combine receipt is inconsistent: {exc}") from exc
