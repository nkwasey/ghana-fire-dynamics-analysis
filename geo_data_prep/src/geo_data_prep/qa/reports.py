"""geo_data_prep.qa.reports

Audit-friendly QA report writers.

Assignment QA responsibilities
------------------------------
- Preserve the main overlap CSV writer.
- Emit richer CSV/JSON sidecars next to the overlap table.
- Evaluate assignment validators and serialise their results for audit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from geo_data_prep.qa.defensibility import build_sliver_diagnostics
from geo_data_prep.qa.validators import (
    DEFAULT_SHARE_BOUND_TOL,
    normalise_share_series_for_validation,
    run_assignment_validators,
)


class ReportError(RuntimeError):
    """Raised when a report cannot be written."""


@dataclass(frozen=True)
class ReportResult:
    """Metadata about a written report."""

    path: Path
    rows: int
    sidecars: Mapping[str, Path] = field(default_factory=dict)
    summary: Mapping[str, object] = field(default_factory=dict)


def _coerce_dataframe(overlap_table: object):
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ReportError(f"pandas is required for report writing: {e}") from e

    try:
        df = (
            overlap_table
            if isinstance(overlap_table, pd.DataFrame)
            else pd.DataFrame(overlap_table)
        )
    except Exception as e:
        raise ReportError(f"Invalid overlap_table; expected DataFrame-like: {e}") from e
    return pd, df


def _jsonable(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _status_rank(status: object) -> int:
    order = {"fail": 3, "warn": 2, "pass": 1, "na": 0}
    return order.get(str(status), 0)


def _overall_status(results: list[dict[str, object]]) -> str:
    if not results:
        return "na"
    best = max(results, key=lambda r: _status_rank(r.get("status")))
    return str(best.get("status", "na"))


def _stable_sort_overlap(df: object):
    sort_candidates = [
        c for c in ["district_id", "rank", "zone_id"] if c in getattr(df, "columns", [])
    ]
    if not sort_candidates:
        return df
    ascending = [True] * len(sort_candidates)
    return df.sort_values(sort_candidates, ascending=ascending, kind="mergesort").reset_index(
        drop=True
    )


def _bool_mask(series: object):
    try:
        return series.astype("boolean").fillna(False)
    except Exception:
        try:
            return series.notna()
        except Exception:
            return series


def build_assignment_validation_payload(
    overlap_table: object,
    *,
    qa_enabled: bool = True,
    share_warn_below: float = 0.95,
    share_fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
    area_warn_above: float = 0.01,
    area_fail_above: float = 0.05,
    missing_warn_above: int = 0,
    missing_fail_above: int = 0,
    invalid_geometry_warn_above: int = 0,
    invalid_geometry_fail_above: int = 0,
    invalid_geometry_layer_counts: Mapping[str, object] | None = None,
    legacy_disagreement_warn_above: int = 0,
    legacy_disagreement_fail_above: int = 0,
) -> dict[str, object]:
    """Build one serialisable assignment-QA payload shared by reports and runtime."""

    if not qa_enabled:
        return {
            "qa_enabled": False,
            "status": "na",
            "ok": True,
            "results": [],
        }

    validation_summaries = run_assignment_validators(
        overlap_table,
        share_warn_below=share_warn_below,
        share_fail_below=share_fail_below,
        share_bound_tol=share_bound_tol,
        area_warn_above=area_warn_above,
        area_fail_above=area_fail_above,
        missing_warn_above=missing_warn_above,
        missing_fail_above=missing_fail_above,
        invalid_geometry_warn_above=invalid_geometry_warn_above,
        invalid_geometry_fail_above=invalid_geometry_fail_above,
        invalid_geometry_layer_counts=invalid_geometry_layer_counts,
        legacy_disagreement_warn_above=legacy_disagreement_warn_above,
        legacy_disagreement_fail_above=legacy_disagreement_fail_above,
    )
    payload_results = [
        {
            "message": s.message,
            "ok": bool(s.ok),
            "status": str(s.status),
            "details": _jsonable(dict(s.details or {})),
        }
        for s in validation_summaries
    ]
    status = _overall_status(payload_results)
    return {
        "qa_enabled": True,
        "status": status,
        "ok": status != "fail",
        "results": payload_results,
    }


def _build_summary_payload(
    df: object,
    *,
    validation_payload: Mapping[str, object] | None = None,
    qa_enabled: bool = True,
    share_warn_below: float = 0.95,
    share_fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
    area_warn_above: float = 0.01,
    area_fail_above: float = 0.05,
    missing_warn_above: int = 0,
    missing_fail_above: int = 0,
    invalid_geometry_warn_above: int = 0,
    invalid_geometry_fail_above: int = 0,
    invalid_geometry_layer_counts: Mapping[str, object] | None = None,
    legacy_disagreement_warn_above: int = 0,
    legacy_disagreement_fail_above: int = 0,
) -> dict[str, object]:
    if validation_payload is None:
        validation_payload = build_assignment_validation_payload(
            df,
            qa_enabled=qa_enabled,
            share_warn_below=share_warn_below,
            share_fail_below=share_fail_below,
            share_bound_tol=share_bound_tol,
            area_warn_above=area_warn_above,
            area_fail_above=area_fail_above,
            missing_warn_above=missing_warn_above,
            missing_fail_above=missing_fail_above,
            invalid_geometry_warn_above=invalid_geometry_warn_above,
            invalid_geometry_fail_above=invalid_geometry_fail_above,
            invalid_geometry_layer_counts=invalid_geometry_layer_counts,
            legacy_disagreement_warn_above=legacy_disagreement_warn_above,
            legacy_disagreement_fail_above=legacy_disagreement_fail_above,
        )

    assigned_rows = int(_bool_mask(df["is_assigned"]).sum()) if "is_assigned" in df.columns else 0
    candidate_rows = int(len(df))
    districts = int(df["district_id"].nunique()) if "district_id" in df.columns else 0
    assigned_districts = (
        int(df.loc[_bool_mask(df["is_assigned"]), "district_id"].nunique())
        if {"district_id", "is_assigned"}.issubset(set(df.columns))
        else 0
    )
    tie_rows = (
        int(_bool_mask(df["tie_break_applied"]).sum()) if "tie_break_applied" in df.columns else 0
    )
    legacy_disagreements = (
        int(_bool_mask(df["legacy_assignment_disagreement"]).sum())
        if "legacy_assignment_disagreement" in df.columns
        else 0
    )

    return {
        "ok": bool(validation_payload["ok"]),
        "status": str(validation_payload["status"]),
        "rows": candidate_rows,
        "districts": districts,
        "assigned_rows": assigned_rows,
        "assigned_districts": assigned_districts,
        "tie_break_rows": tie_rows,
        "legacy_assignment_disagreement_rows": legacy_disagreements,
        "validations": list(validation_payload["results"]),
    }


def _empty_issue_table(pd: object):
    return pd.DataFrame(
        columns=[
            "district_id",
            "zone_id",
            "zone_name",
            "legacy_zone_id",
            "legacy_zone_name",
            "ovl_share",
            "district_uncovered_frac",
            "issue_type",
        ]
    )


def _empty_metrics_table(pd: object):
    return pd.DataFrame(columns=["validator", "status", "ok"])


def _build_issue_table(
    df: object,
    *,
    qa_enabled: bool = True,
    share_warn_below: float = 0.95,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
    area_warn_above: float = 0.01,
):
    pd, _ = _coerce_dataframe(df)
    if not qa_enabled:
        return _empty_issue_table(pd)

    issues: list[dict[str, object]] = []

    if {"district_id", "is_assigned", "ovl_share"}.issubset(set(df.columns)):
        assigned = df.loc[_bool_mask(df["is_assigned"])].copy()
        if not assigned.empty:
            share_view = normalise_share_series_for_validation(
                assigned["ovl_share"], bound_tol=share_bound_tol
            )
            assigned = assigned.loc[~share_view.invalid_mask].copy()
            if not assigned.empty:
                assigned["_normalised_ovl_share"] = share_view.normalised_shares.loc[assigned.index]
                weak = assigned.loc[
                    assigned["_normalised_ovl_share"] < float(share_warn_below),
                    ["district_id", "zone_id", "ovl_share"],
                ].copy()
                weak["issue_type"] = "low_assignment_share"
                issues.extend(weak.to_dict(orient="records"))

    if {"district_id", "district_uncovered_frac"}.issubset(set(df.columns)):
        gap = (
            df[["district_id", "district_uncovered_frac"]]
            .drop_duplicates(subset=["district_id"])
            .loc[lambda x: x["district_uncovered_frac"].astype(float) > float(area_warn_above)]
            .copy()
        )
        if not gap.empty:
            gap["issue_type"] = "area_closure_gap"
            issues.extend(gap.to_dict(orient="records"))

    if {"district_id", "legacy_assignment_disagreement"}.issubset(set(df.columns)):
        legacy = df.loc[_bool_mask(df["legacy_assignment_disagreement"])].copy()
        if not legacy.empty:
            keep = [
                c
                for c in [
                    "district_id",
                    "legacy_zone_id",
                    "zone_id",
                    "legacy_zone_name",
                    "zone_name",
                ]
                if c in legacy.columns
            ]
            legacy = legacy[keep].drop_duplicates().copy()
            legacy["issue_type"] = "legacy_assignment_disagreement"
            issues.extend(legacy.to_dict(orient="records"))

    if not issues:
        return _empty_issue_table(pd)

    return pd.DataFrame(issues).reindex(columns=_empty_issue_table(pd).columns)


def write_district_zone_overlap_csv(
    overlap_table: object,
    *,
    out_csv: str | Path,
    validation_payload: Mapping[str, object] | None = None,
    qa_enabled: bool = True,
    share_warn_below: float = 0.95,
    share_fail_below: float = 0.80,
    share_bound_tol: float = DEFAULT_SHARE_BOUND_TOL,
    area_warn_above: float = 0.01,
    area_fail_above: float = 0.05,
    missing_warn_above: int = 0,
    missing_fail_above: int = 0,
    invalid_geometry_warn_above: int = 0,
    invalid_geometry_fail_above: int = 0,
    invalid_geometry_layer_counts: Mapping[str, object] | None = None,
    legacy_disagreement_warn_above: int = 0,
    legacy_disagreement_fail_above: int = 0,
    sliver_enabled: bool = True,
    sliver_share_cutoffs: Sequence[float] = (1e-6, 1e-4, 1e-3, 1e-2),
    sliver_area_sqkm_cutoffs: Sequence[float] = (0.001, 0.01, 0.1, 1.0),
    sliver_example_limit: int = 10,
) -> ReportResult:
    """Write ``district_zone_overlap.csv`` and assignment QA sidecars.

    Sidecars are written next to the main CSV so downstream audit can inspect QA
    without inflating shapefile schemas.
    """

    p = Path(out_csv)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise ReportError(f"Failed to create report directory {p.parent}: {e}") from e

    pd, df = _coerce_dataframe(overlap_table)
    df = _stable_sort_overlap(df)

    try:
        df.to_csv(p, index=False, encoding="utf-8")
    except Exception as e:
        raise ReportError(f"Failed to write CSV report {p}: {e}") from e

    resolved_validation_payload = dict(validation_payload or {})
    if not resolved_validation_payload:
        resolved_validation_payload = build_assignment_validation_payload(
            df,
            qa_enabled=qa_enabled,
            share_warn_below=share_warn_below,
            share_fail_below=share_fail_below,
            share_bound_tol=share_bound_tol,
            area_warn_above=area_warn_above,
            area_fail_above=area_fail_above,
            missing_warn_above=missing_warn_above,
            missing_fail_above=missing_fail_above,
            invalid_geometry_warn_above=invalid_geometry_warn_above,
            invalid_geometry_fail_above=invalid_geometry_fail_above,
            invalid_geometry_layer_counts=invalid_geometry_layer_counts,
            legacy_disagreement_warn_above=legacy_disagreement_warn_above,
            legacy_disagreement_fail_above=legacy_disagreement_fail_above,
        )

    summary_payload = _build_summary_payload(
        df,
        validation_payload=resolved_validation_payload,
        qa_enabled=qa_enabled,
        share_warn_below=share_warn_below,
        share_fail_below=share_fail_below,
        share_bound_tol=share_bound_tol,
        area_warn_above=area_warn_above,
        area_fail_above=area_fail_above,
        missing_warn_above=missing_warn_above,
        missing_fail_above=missing_fail_above,
        invalid_geometry_warn_above=invalid_geometry_warn_above,
        invalid_geometry_fail_above=invalid_geometry_fail_above,
        invalid_geometry_layer_counts=invalid_geometry_layer_counts,
        legacy_disagreement_warn_above=legacy_disagreement_warn_above,
        legacy_disagreement_fail_above=legacy_disagreement_fail_above,
    )
    issues_df = _build_issue_table(
        df,
        qa_enabled=qa_enabled,
        share_warn_below=share_warn_below,
        share_bound_tol=share_bound_tol,
        area_warn_above=area_warn_above,
    )

    sidecars: dict[str, Path] = {}

    summary_path = p.with_name(f"{p.stem}_summary.json")
    try:
        summary_path.write_text(
            __import__("json").dumps(_jsonable(summary_payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as e:
        raise ReportError(f"Failed to write summary JSON {summary_path}: {e}") from e
    sidecars["summary_json"] = summary_path

    validations_path = p.with_name(f"{p.stem}_validations.json")
    try:
        validations_path.write_text(
            __import__("json").dumps(
                _jsonable(summary_payload.get("validations", [])), indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception as e:
        raise ReportError(f"Failed to write validations JSON {validations_path}: {e}") from e
    sidecars["validations_json"] = validations_path

    issues_path = p.with_name(f"{p.stem}_issues.csv")
    try:
        issues_df.to_csv(issues_path, index=False, encoding="utf-8")
    except Exception as e:
        raise ReportError(f"Failed to write issues CSV {issues_path}: {e}") from e
    sidecars["issues_csv"] = issues_path

    metrics_path = p.with_name(f"{p.stem}_metrics.csv")
    metrics_rows = []
    for item in summary_payload.get("validations", []):
        row = {
            "validator": item.get("message", "validator"),
            "status": item.get("status"),
            "ok": item.get("ok"),
        }
        details = item.get("details", {}) if isinstance(item, dict) else {}
        if isinstance(details, dict):
            for key, value in details.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    row[str(key)] = value
        metrics_rows.append(row)
    metrics_df = pd.DataFrame(metrics_rows)
    if metrics_df.empty:
        metrics_df = _empty_metrics_table(pd)
    try:
        metrics_df.to_csv(metrics_path, index=False, encoding="utf-8")
    except Exception as e:
        raise ReportError(f"Failed to write metrics CSV {metrics_path}: {e}") from e
    sidecars["metrics_csv"] = metrics_path

    if bool(sliver_enabled):
        sliver_path = p.with_name(f"{p.stem}_sliver_summary.json")
        try:
            sliver_payload = build_sliver_diagnostics(
                df,
                share_cutoffs=sliver_share_cutoffs,
                area_sqkm_cutoffs=sliver_area_sqkm_cutoffs,
                example_limit=sliver_example_limit,
            )
            sliver_path.write_text(
                __import__("json").dumps(_jsonable(sliver_payload), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            raise ReportError(f"Failed to write sliver summary JSON {sliver_path}: {e}") from e
        sidecars["sliver_summary_json"] = sliver_path

    return ReportResult(path=p, rows=int(len(df)), sidecars=sidecars, summary=summary_payload)
