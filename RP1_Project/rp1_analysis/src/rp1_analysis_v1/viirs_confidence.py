"""Compare VIIRS confidence policies on the common paired RQ3 panel."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import AnalysisContract
from .observability import classify_observation_states
from .paths import ProjectPaths
from .rq3_guard import require_rq3_inputs_acknowledged
from .variables import resolve_field_role


_CLASS_FIELDS = ("viirs_det_low", "viirs_det_nominal", "viirs_det_high")
_STAGE2_COUNT_FIELDS = (*_CLASS_FIELDS, "viirs_det_nh")
_COUNT_FIELDS = (*_STAGE2_COUNT_FIELDS, "viirs_det_all")
_POLICIES = ("nominal_high", "all_confidence", "high_only")
_SPARSE_COUNT = 10


class ViirsConfidenceError(ValueError):
    """Raised when confidence inputs or their source receipts are inconsistent."""


@dataclass(frozen=True, slots=True)
class ViirsConfidenceAudit:
    counts: pd.DataFrame
    correspondence: pd.DataFrame
    source_receipts: pd.DataFrame


def _field(analysis: AnalysisContract, role: str) -> str:
    field = resolve_field_role(analysis, role)
    if not isinstance(field, str):
        raise ViirsConfidenceError(f"Expected one field for {role}")
    return field


def _whole_counts(frame: pd.DataFrame, fields: tuple[str, ...], source: str) -> pd.DataFrame:
    counts = frame.loc[:, list(fields)].apply(pd.to_numeric, errors="coerce")
    values = counts.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(values).all() or (values < 0).any() or (values >= 2**63).any():
        raise ViirsConfidenceError(f"{source} contains missing, negative or invalid counts")
    if not (values == np.trunc(values)).all():
        raise ViirsConfidenceError(f"{source} contains fractional counts")
    return counts.astype("int64")


def _validate_paired_panel(paired_panel: pd.DataFrame, analysis: AnalysisContract) -> pd.DataFrame:
    roles = {
        name: _field(analysis, f"keys.{name}")
        for name in ("unit_id", "yyyymm", "year", "month", "parent_code", "parent_name")
    }
    roles.update({name: _field(analysis, f"rq3.{name}") for name in (
        "viirs_count", "viirs_presence", "ba_presence", "viirs_support", "ba2012_support", "burnable_area",
    )})
    required = set(roles.values()).union(_COUNT_FIELDS)
    missing = required.difference(paired_panel.columns)
    if missing:
        raise ViirsConfidenceError(f"Paired panel lacks confidence audit fields: {sorted(missing)!r}")

    panel = paired_panel.loc[:, list(dict.fromkeys((*roles.values(), *_COUNT_FIELDS)))].copy()
    panel = panel.rename(columns={field: name for name, field in roles.items()})
    if panel.empty:
        raise ViirsConfidenceError("Paired confidence panel is empty")

    integer_fields = (*_COUNT_FIELDS, "yyyymm", "year", "month", "viirs_count", "viirs_presence",
                      "ba_presence", "viirs_support", "ba2012_support")
    panel[list(integer_fields)] = _whole_counts(panel, integer_fields, "Paired confidence panel")
    for key in ("unit_id", "parent_code", "parent_name"):
        panel[key] = panel[key].astype("string")
        if panel[key].isna().any() or panel[key].str.strip().eq("").any():
            raise ViirsConfidenceError(f"Paired confidence panel contains an empty {key}")

    window = analysis.study["temporal_windows"]["overlap_monthly"]
    calendar = pd.period_range(str(window["start"]), str(window["end"]), freq="M")
    expected_months = [period.year * 100 + period.month for period in calendar]
    if (panel.duplicated(["unit_id", "yyyymm"]).any()
            or not panel["yyyymm"].isin(expected_months).all()
            or not panel.groupby("unit_id").size().eq(len(expected_months)).all()
            or not panel["year"].eq(panel["yyyymm"] // 100).all()
            or not panel["month"].eq(panel["yyyymm"] % 100).all()):
        raise ViirsConfidenceError("Paired confidence panel requires complete, unique district-month keys")

    population = analysis.study["populations"][analysis.research_questions["rq3"]["descriptive_population"]]
    if ((population["rows"] is not None and len(panel) != population["rows"])
            or (population["units"] is not None and panel["unit_id"].nunique() != population["units"])
            or not panel.groupby("unit_id")["parent_code"].nunique().eq(1).all()
            or not panel.groupby("parent_code")["parent_name"].nunique().eq(1).all()):
        raise ViirsConfidenceError("Paired confidence panel disagrees with the population or zone authority")

    burnable = pd.to_numeric(panel["burnable_area"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    if (not panel[["viirs_support", "ba2012_support"]].eq(1).all().all()
            or not (np.isfinite(burnable) & (burnable > 0)).all()
            or not panel["ba_presence"].isin((0, 1)).all()):
        raise ViirsConfidenceError("Paired confidence panel requires supported thermal and BA observations")

    low, nominal, high = (panel[field] for field in _CLASS_FIELDS)
    if (not panel["viirs_det_all"].eq(low + nominal + high).all()
            or not panel["viirs_det_nh"].eq(nominal + high).all()
            or not panel["viirs_count"].eq(panel["viirs_det_nh"]).all()
            or not panel["viirs_presence"].eq(panel["viirs_count"].gt(0)).all()):
        raise ViirsConfidenceError("Paired confidence counts or primary presence violate the class identities")
    return panel.sort_values(["unit_id", "yyyymm"], ignore_index=True)


def _read_source_receipts(manifest: Mapping, root: Path, years: tuple[int, ...]) -> tuple[pd.DataFrame, Path]:
    require_rq3_inputs_acknowledged(manifest, evidence_root=root)
    policy = manifest["active_fire_method"]
    firms_root = root / "RP1_Project" / "rp1_mv_firms_panels"
    evidence = {
        (root / item["path"]).resolve(): item
        for name in ("evidence_files", "viirs_preparation_evidence", "source_preparation_evidence")
        for item in policy.get(name, ())
    }

    def receipt_name(name: str) -> Mapping:
        matches = [item for path, item in evidence.items() if path.name == name]
        if len(matches) != 1:
            raise ViirsConfidenceError(f"Expected one admitted VIIRS evidence file named {name!r}")
        return matches[0]

    def read_json(item: Mapping) -> Mapping:
        value = json.loads((root / item["path"]).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ViirsConfidenceError(f"Invalid VIIRS receipt {item['path']}")
        return value

    def admitted_firms_file(item: Mapping) -> Mapping:
        path = (firms_root / item["path"]).resolve()
        if path not in evidence or evidence[path]["sha256"] != item["sha256"]:
            raise ViirsConfidenceError(f"VIIRS receipt refers to unbound evidence {item['path']}")
        return evidence[path]

    try:
        combine = read_json(policy["combine_receipt"])["active_fire_method"]
        count_population = "all_confidence_deduplicated"
        input_profiles = policy.get("input_profiles") or {}
        if (policy.get("count_population_viirs") != count_population
                or combine.get("count_population_viirs") != count_population
                or input_profiles.get("viirs") != "ghana_firms_archive_sp_v1"):
            raise ViirsConfidenceError("Confidence audit requires an admitted all-confidence Suomi-NPP SP count stream")

        aggregate_manifest = read_json(receipt_name("aggregate_monthly_viirs_manifest.json"))
        stage2 = admitted_firms_file(aggregate_manifest["panel_sensor_monthly"])
        aggregate_reference = admitted_firms_file(aggregate_manifest["qa_summary_json"])
        aggregate = read_json(aggregate_reference)
        aggregate_counts = aggregate["steps"]["read_fires_canonical"]
        partitions = aggregate_counts["partitions"]
        if (aggregate["sensor"] != "viirs" or aggregate_counts["n_files"] != len(years)
                or sorted(p["year"] for p in partitions) != list(years)):
            raise ViirsConfidenceError("VIIRS aggregate receipts do not cover the configured analysis years exactly")
        frp = aggregate["steps"]["frp"]
        if (frp["confidence_categories"] != policy["frp_confidence_categories"]
                or frp["selection_stage"] != policy["frp_selection_stage"]
                or frp["aggregation"] != policy["frp_aggregation"]
                or frp["method_version"] != policy["method_version"]):
            raise ViirsConfidenceError("VIIRS aggregate receipt disagrees with the admitted FRP policy")

        rows = []
        for partition in sorted(partitions, key=lambda item: item["year"]):
            year = partition["year"]
            prep_reference = receipt_name(f"prepare_year_viirs_{year}_manifest.json")
            prep = read_json(prep_reference)
            summary_reference = admitted_firms_file(prep["qa_summary_json"])
            summary = read_json(summary_reference)
            profile = summary["archive_record_profile"]
            archive = summary["input_profile_evidence"]
            coverage = [record for record in archive["selected_coverage"]
                        if record["source"] == "VIIRS_SNPP_SP" and record["year"] == year]
            type_filter = summary["steps"]["type_filter"]

            count_file = admitted_firms_file(prep["fires_canonical_csv"])
            frp_file = admitted_firms_file(prep["fires_frp_canonical_csv"])
            bound_count = admitted_firms_file(partition)
            bound_frp = admitted_firms_file({"path": partition["frp_path"], "sha256": partition["frp_sha256"]})
            if (count_file != bound_count or frp_file != bound_frp
                    or any(item["sensor"] != "viirs" or item["year"] != year
                           or item["run_id"] != aggregate["run_id"]
                           or item["config_sha256"] != policy["config_sha256"]
                           or item["method_version"] != policy["method_version"] for item in (prep, summary))
                    or profile["source"] != "VIIRS_SNPP_SP" or profile["processing"] != "SP"
                    or profile["platform_counts"] != {"Suomi-NPP": profile["n_points"]}
                    or profile["version_counts"] != {"2": profile["n_points"]}
                    or archive["profile"] != "ghana_firms_archive_sp_v1"
                    or len(coverage) != 1 or coverage[0]["status"] != "available"
                    or coverage[0]["processing_status"] != "SP"
                    or type_filter["keep_value"] != 0 or type_filter["applied_before_dedup"] is not True):
                raise ViirsConfidenceError(f"VIIRS annual source or processing evidence disagrees for {year}")

            rows.append({
                "year": year, "archive_source": profile["source"], "processing": profile["processing"],
                "platform": "Suomi-NPP", "archive_product_version": "2", "input_profile": archive["profile"],
                "archive_checked_start": coverage[0]["checked_start"],
                "archive_checked_end": coverage[0]["checked_end"], "archive_partial_year": coverage[0]["partial_year"],
                "vegetation_type": type_filter["keep_value"], "count_population": count_population,
                "primary_count_classes": "nominal|high", "frp_classes": "nominal|high",
                "configuration_sha256": policy["config_sha256"],
                "preparation_manifest_path": prep_reference["path"],
                "preparation_manifest_sha256": prep_reference["sha256"],
                "preparation_summary_path": summary_reference["path"],
                "preparation_summary_sha256": summary_reference["sha256"],
                "canonical_count_path": count_file["path"], "canonical_count_sha256": count_file["sha256"],
                "canonical_frp_path": frp_file["path"], "canonical_frp_sha256": frp_file["sha256"],
                "aggregate_summary_path": aggregate_reference["path"],
                "aggregate_summary_sha256": aggregate_reference["sha256"],
                "stage2_monthly_panel_path": stage2["path"], "stage2_monthly_panel_sha256": stage2["sha256"],
            })
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ViirsConfidenceError(f"Could not read the admitted VIIRS source receipts: {exc}") from exc
    return pd.DataFrame(rows), root / stage2["path"]


def _reconcile_stage2_counts(panel: pd.DataFrame, stage2_path: Path) -> None:
    keys = ["unit_id", "yyyymm"]
    try:
        stage2 = pd.read_csv(stage2_path, usecols=["level", *keys, *_STAGE2_COUNT_FIELDS])
    except (OSError, ValueError) as exc:
        raise ViirsConfidenceError(f"Could not read the admitted Stage 2 VIIRS counts: {exc}") from exc
    stage2 = stage2.loc[stage2["level"].eq("district")].drop(columns="level")
    stage2["unit_id"] = stage2["unit_id"].astype("string")
    stage2[["yyyymm", *_STAGE2_COUNT_FIELDS]] = _whole_counts(
        stage2, ("yyyymm", *_STAGE2_COUNT_FIELDS), "Stage 2 VIIRS counts",
    )
    if stage2.empty or stage2.duplicated(keys).any():
        raise ViirsConfidenceError("Stage 2 VIIRS counts require unique district-month evidence")
    observed = panel.set_index(keys).loc[:, list(_STAGE2_COUNT_FIELDS)]
    # Stage 2 has sparse detection groups. Only already-supported paired keys may receive zero here.
    source = stage2.set_index(keys).reindex(observed.index, fill_value=0)
    if not observed.eq(source).all().all():
        raise ViirsConfidenceError("Paired class counts disagree with the admitted Stage 2 VIIRS counts")


def _ratio_pct(numerator: int, denominator: int) -> float:
    return 100 * numerator / denominator if denominator else np.nan


def _summarise(panel: pd.DataFrame, analysis: AnalysisContract) -> tuple[pd.DataFrame, pd.DataFrame]:
    ba_field = _field(analysis, "rq3.ba_presence")
    viirs_field = _field(analysis, "rq3.viirs_presence")
    counts_rows = []
    correspondence_rows = []
    strata = [("national", None, None, panel)]
    strata.extend(("acz", str(acz), None, group) for acz, group in panel.groupby("parent_code", sort=True))
    strata.extend(("month", None, int(month), group) for month, group in panel.groupby("month", sort=True))
    strata.extend(("acz_month", str(acz), int(month), group)
                  for (acz, month), group in panel.groupby(["parent_code", "month"], sort=True))

    for scope, acz, month, group in strata:
        base = {
            "summary_scope": scope, "parent_code": acz,
            "parent_name": group["parent_name"].iloc[0] if acz is not None else None,
            "month": month, "paired_district_months": len(group), "paired_districts": group["unit_id"].nunique(),
        }
        low, nominal, high = (int(group[field].sum()) for field in _CLASS_FIELDS)
        all_count = int(group["viirs_det_all"].sum())
        primary = group["viirs_count"].gt(0)
        absence = group["ba_presence"].eq(0)
        primary_absence_pct = _ratio_pct(int((primary & absence).sum()), int(primary.sum()))
        counts_rows.append({
            **base, "low_detections": low, "nominal_detections": nominal, "high_detections": high,
            "nominal_high_detections": nominal + high, "all_confidence_detections": all_count,
            "detection_share_denominator": all_count,
            "low_detection_share_pct": _ratio_pct(low, all_count),
            "nominal_detection_share_pct": _ratio_pct(nominal, all_count),
            "high_detection_share_pct": _ratio_pct(high, all_count),
        })

        for policy, field in zip(_POLICIES, ("viirs_count", "viirs_det_all", "viirs_det_high"), strict=True):
            positive = group[field].gt(0)
            classified = classify_observation_states(
                pd.DataFrame({ba_field: group["ba_presence"], viirs_field: positive.astype(int)}), analysis,
            )
            by_state = classified.value_counts()
            neither = int(by_state.get("both_zero", 0))
            ba_only = int(by_state.get("mcd64a1_positive_viirs_zero", 0))
            viirs_only = int(by_state.get("viirs_positive_mcd64a1_zero", 0))
            both = int(by_state.get("both_positive", 0))
            n_positive = viirs_only + both
            absence_pct = _ratio_pct(viirs_only, n_positive)
            minority = min(viirs_only, both)
            correspondence_rows.append({
                **base, "confidence_policy": policy, "viirs_detections": int(group[field].sum()),
                "both_zero": neither, "mcd64a1_positive_viirs_zero": ba_only,
                "viirs_positive_mcd64a1_zero": viirs_only, "both_positive": both,
                "both_zero_pct_paired": _ratio_pct(neither, len(group)),
                "mcd64a1_positive_viirs_zero_pct_paired": _ratio_pct(ba_only, len(group)),
                "viirs_positive_mcd64a1_zero_pct_paired": _ratio_pct(viirs_only, len(group)),
                "both_positive_pct_paired": _ratio_pct(both, len(group)),
                "viirs_positive_district_months": n_positive,
                "viirs_positive_districts": group.loc[positive, "unit_id"].nunique(),
                "mcd64a1_absent_viirs_positive_districts": group.loc[positive & absence, "unit_id"].nunique(),
                "mcd64a1_present_viirs_positive_districts": group.loc[positive & ~absence, "unit_id"].nunique(),
                "mcd64a1_absence_pct_given_viirs_positive": absence_pct,
                "mcd64a1_absence_delta_pp_vs_nominal_high": absence_pct - primary_absence_pct,
                "viirs_positive_added_vs_nominal_high": int((positive & ~primary).sum()),
                "viirs_positive_lost_vs_nominal_high": int((~positive & primary).sum()),
                "minority_outcome_district_months": minority,
                "no_viirs_positive_rows": n_positive == 0,
                "single_ba_outcome_among_positives": n_positive > 0 and minority == 0,
                "viirs_positive_count_below_10": n_positive < _SPARSE_COUNT,
                "minority_outcome_count_below_10": minority < _SPARSE_COUNT,
            })

    counts = pd.DataFrame(counts_rows).astype({"month": "Int64"})
    correspondence = pd.DataFrame(correspondence_rows).astype({"month": "Int64"})
    return counts, correspondence


def build_viirs_confidence_audit(
    paired_panel: pd.DataFrame,
    analysis: AnalysisContract,
    manifest: Mapping,
    *,
    evidence_root: Path | None = None,
) -> ViirsConfidenceAudit:
    """Audit confidence policies on the same admitted district-months as RQ3.

    Count shares use pooled detections and observation-state proportions use all
    paired district-months. Conditional absence uses only rows positive under
    each policy. Sparse flags describe sample composition.
    """
    panel = _validate_paired_panel(paired_panel, analysis)
    root = (evidence_root if evidence_root is not None else ProjectPaths.discover().root.parent.parent).resolve()
    years = tuple(sorted(panel["year"].unique()))
    receipts, stage2_path = _read_source_receipts(manifest, root, years)
    _reconcile_stage2_counts(panel, stage2_path)
    counts, correspondence = _summarise(panel, analysis)
    return ViirsConfidenceAudit(counts, correspondence, receipts)
