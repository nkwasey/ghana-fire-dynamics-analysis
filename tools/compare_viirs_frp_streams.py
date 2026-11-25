"""Compare independent VIIRS FRP with filtering the count partition.

Both populations are reconstructed from partitions of the same run. The
comparison alone does not establish source lineage or scientific validity.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.metrics.frp import compute_daily_max_frp, compute_monthly_frp_metrics_from_daily
from mv_firms_panels.metrics.detections import compute_monthly_detection_metrics
from mv_firms_panels.metrics.persistence import compute_monthly_persistence_metrics_nh
from mv_firms_panels.stages.aggregate_monthly import _validate_viirs_partitions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--firms-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--monthly-panel", type=Path)
    args = parser.parse_args()
    script_sha256 = sha256_file(Path(__file__))
    root = args.firms_root.resolve()
    cfg = load_config(args.config.resolve(), validate_paths=False, repo_root=root).config
    run = root / cfg.outputs.base_dir / args.run_id
    annual = [(year, run / "fires_canonical" / "viirs" / f"fires_canonical_viirs_{year}.csv")
              for year in range(args.start_year, args.end_year + 1)]
    frp_paths = _validate_viirs_partitions(repo_root=root, cfg=cfg, run_dir=run,
        run_id=args.run_id, annual_paths=annual,
        explicit_paths=[run / "fires_frp_canonical" / "viirs" / f"fires_frp_canonical_viirs_{year}.csv" for year, _ in annual])
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    groups = ["level", "unit_id", "yyyymm"]
    columns = groups + ["date_utc", "conf_cat", "frp_mw", "dedup_key", "acq_datetime_utc", "latitude", "longitude"]
    comparisons = []
    reconstructed_count_metrics = []
    yearly = []
    threshold = float(cfg.processing.frp_policy.min_frp_mw)
    for year, path in annual:
        count = pd.read_csv(path, usecols=columns, dtype={"unit_id":"string"})
        independent = pd.read_csv(frp_paths[year], usecols=columns, dtype={"unit_id":"string"})
        count = count.loc[count.level.eq("district")].copy()
        independent = independent.loc[independent.level.eq("district")].copy()
        old = count.loc[count.conf_cat.isin(["n", "h"])].copy()
        det = compute_monthly_detection_metrics(count, sensor="viirs", group_cols=groups)
        persistence = compute_monthly_persistence_metrics_nh(count, group_cols=groups).rename(
            columns={"days_active_nh":"viirs_days_active_nh", "streak_max_nh":"viirs_streak_max_nh"})
        reconstructed_count_metrics.append(det.merge(persistence, on=groups, how="outer"))
        old_daily = compute_daily_max_frp(old, id_cols=["level", "unit_id"], min_frp_mw=threshold)
        new_daily = compute_daily_max_frp(independent, id_cols=["level", "unit_id"], min_frp_mw=threshold)
        old_month = compute_monthly_frp_metrics_from_daily(old_daily, sensor="viirs", id_cols=["level", "unit_id"])
        new_month = compute_monthly_frp_metrics_from_daily(new_daily, sensor="viirs", id_cols=["level", "unit_id"])
        panel = old_month.merge(new_month, on=groups, how="outer", suffixes=("_old", "_new"))
        for field in ("viirs_frp_active_days", "viirs_frp_sum_daily_max_mw"):
            for suffix in ("_old", "_new"):
                panel[field + suffix] = panel[field + suffix].fillna(0)
        for field in ("viirs_frp_active_days", "viirs_frp_sum_daily_max_mw", "viirs_frp_mean_mw", "viirs_frp_p95_daily_max_mw"):
            a = pd.to_numeric(panel[field + "_old"], errors="coerce")
            b = pd.to_numeric(panel[field + "_new"], errors="coerce")
            aa = a.to_numpy(dtype=float, na_value=np.nan)
            bb = b.to_numpy(dtype=float, na_value=np.nan)
            panel[field + "_changed"] = ~((aa == bb) | (np.isnan(aa) & np.isnan(bb)))
            panel[field + "_delta"] = b - a
        comparisons.append(panel)
        daily_keys = groups + ["date_utc"]
        daily_support = new_daily.merge(old_daily[daily_keys], on=daily_keys, how="left", indicator=True)
        recovered_days = int(daily_support["_merge"].eq("left_only").sum())
        row_keys = ["dedup_key", "unit_id", "acq_datetime_utc", "latitude", "longitude", "conf_cat", "frp_mw"]
        survivors = independent.merge(old[row_keys].drop_duplicates(), on=row_keys, how="left", indicator=True)
        yearly.append({"year": year, "count_partition_sha256": sha256_file(path),
            "frp_partition_sha256": sha256_file(frp_paths[year]),
            "frp_records_not_in_count_nh": int(survivors["_merge"].eq("left_only").sum()),
            "new_eligible_unit_days": recovered_days})
    panel = pd.concat(comparisons, ignore_index=True).sort_values(groups)
    panel_path = output / "district_month_frp_comparison.csv"
    panel.to_csv(panel_path, index=False)
    summary = {"method":"old_frp_reconstructed_from_same_run_count_stream",
        "run_id":args.run_id, "config_sha256":sha256_file(args.config), "script_sha256":script_sha256, "yearly":yearly,
        "district_unit_months_with_frp_in_either_method":len(panel),
        "frp_records_not_in_count_nh":sum(row["frp_records_not_in_count_nh"] for row in yearly),
        "new_eligible_unit_days":sum(row["new_eligible_unit_days"] for row in yearly),
        "comparison_sha256":sha256_file(panel_path), "fields":{}}
    if args.monthly_panel is not None:
        metrics = ["viirs_det_low", "viirs_det_nominal", "viirs_det_high", "viirs_det_nh",
                   "viirs_pct_high_conf", "viirs_days_active_nh", "viirs_streak_max_nh"]
        actual = pd.read_csv(args.monthly_panel, usecols=groups + metrics + ["viirs_frp_mean_mw"], dtype={"unit_id":"string"})
        actual = actual.loc[actual.level.eq("district") & (actual.yyyymm // 100).between(args.start_year, args.end_year)]
        count = pd.to_numeric(actual["viirs_det_nh"], errors="coerce")
        means = pd.to_numeric(actual["viirs_frp_mean_mw"], errors="coerce")
        summary["rq3_active_fire_support"] = {
            "scope":"observed district-months in the VIIRS sensor panel; not the BA-paired population",
            "district_unit_months":int(len(actual)),
            "positive_count":int(count.gt(0).sum()),
            "zero_count_with_frp":int((count.eq(0) & means.notna()).sum()),
            "positive_count_missing_frp":int((count.gt(0) & means.isna()).sum()),
            "positive_count_nonpositive_frp":int((count.gt(0) & means.notna() & means.le(0)).sum()),
        }
        reference = pd.concat(reconstructed_count_metrics, ignore_index=True)
        count_check = reference.merge(actual, on=groups, how="outer", suffixes=("_count_stream", "_monthly"))
        summary["count_persistence_check"] = {"method":"reconstructed_same_run_count_stream_vs_new_monthly_panel",
            "monthly_panel_sha256":sha256_file(args.monthly_panel),
            "mismatched_unit_months":{field:int((~np.isclose(
                pd.to_numeric(count_check[field + "_count_stream"], errors="coerce").fillna(0),
                pd.to_numeric(count_check[field + "_monthly"], errors="coerce").fillna(0),
                rtol=1e-12, atol=1e-12)).sum()) for field in metrics}}
    for field in ("viirs_frp_active_days", "viirs_frp_sum_daily_max_mw", "viirs_frp_mean_mw", "viirs_frp_p95_daily_max_mw"):
        old = panel[field + "_old"]
        new = panel[field + "_new"]
        delta = panel[field + "_delta"].abs().dropna()
        summary["fields"][field] = {"changed_unit_months":int(panel[field + "_changed"].sum()),
            "became_available":int((old.isna() & new.notna()).sum()),
            "became_missing":int((old.notna() & new.isna()).sum()),
            "maximum_absolute_change_when_both_present":float(delta.max()) if len(delta) else None,
            "mean_absolute_change_when_both_present":float(delta.mean()) if len(delta) else None}
    (output / "comparison_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
