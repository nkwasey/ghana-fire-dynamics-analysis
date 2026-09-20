"""Materialised publication-source authority for RP1 v1.1.0.

Scientific calculations are performed by the already-qualified RQ1/RQ2/RQ3
analysis modules during explicit source materialisation.  Publication rendering
loads and verifies these immutable CSV authorities; it never recomputes the
scientific statistics.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .config import ConfigurationBundle, load_configuration_bundle
from .data_io import DataAuthorities, load_data_authorities
from .observability import build_rq3_tables
from .paths import ProjectPaths
from .spatial_scale import build_rq1_tables
from .trend_robustness import build_rq2_tables
from .secondary_clusters import ScanScenario, build_cluster_membership_source, build_cluster_summary_source
from .satscan_io import ParsedSaTScanResults
from .validation import DataContractSummary, validate_data_authorities


class PublicationSourceError(RuntimeError):
    pass


PUBLICATION_AUTHORITY_DIR = Path("data/authorities/publication")
MANIFEST_NAME = "SOURCE_MANIFEST.json"


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _normalise_status(value: object) -> str:
    text = str(value)
    if text in {"eligible", "valid_nonzero"}:
        return "valid_nonzero"
    if text == "valid_zero":
        return "valid_zero"
    if text in {"excluded", "island"}:
        return "excluded"
    raise PublicationSourceError(f"Unknown support status {value!r}")


def _population_table(bundle: ConfigurationBundle) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for population_id, pop in bundle.analysis.study["populations"].items():
        source = pop.get("source_panel", pop.get("source_population", ""))
        rows.append({
            "population_id": str(population_id),
            "source_population": str(source),
            "units": int(pop["units"]),
            "rows": int(pop["rows"]),
            "start": str(pop["start"]),
            "end": str(pop["end"]),
            "eligibility_rule": str(pop["eligibility"]),
            "exclusion_reason": "" if population_id in {"acz_monthly", "district_monthly"} else "ineligible rows/units excluded prospectively by the stated rule",
        })
    return pd.DataFrame(rows)


def _table1(rq1, rq2) -> pd.DataFrame:
    a = rq1.acz_fire_pattern_reference[[
        "unit_code", "unit_name", "mean_annual_ba_per100km2_fixed_support",
        "circular_mean_month", "mean_resultant_length",
    ]].rename(columns={
        "unit_code":"parent_code", "unit_name":"parent_name",
        "mean_annual_ba_per100km2_fixed_support":"direct_long_run_rate",
    })
    h = rq1.within_acz_district_heterogeneity[[
        "parent_code", "district_rate_median", "district_rate_iqr", "district_rate_gini"
    ]]
    t = rq2.primary_trend_authority[["parent_code","sen_slope","raw_p","bh_q"]].rename(
        columns={"raw_p":"trend_permutation_p", "bh_q":"trend_bh_q"}
    )
    out = a.merge(h,on="parent_code",validate="one_to_one").merge(t,on="parent_code",validate="one_to_one")
    return out[[
        "parent_code","parent_name","direct_long_run_rate","district_rate_median",
        "district_rate_iqr","district_rate_gini","circular_mean_month",
        "mean_resultant_length","sen_slope","trend_permutation_p","trend_bh_q"
    ]].sort_values("parent_code").reset_index(drop=True)


def _long_run_spatial_rate_presentation_source(rq1, summary: DataContractSummary, authorities: DataAuthorities) -> pd.DataFrame:
    """Project only the two generated long-run rate panels from governed RQ1 authorities.

    The underlying spatial-support authority remains governed and available; manuscript
    Figure 1 is external and therefore the support-outline panel is not projected into
    the generated figure estate.
    """
    meta = authorities.district_panel[["unit_id","unit_name","parent_code"]].drop_duplicates("unit_id")
    mask = summary.long_run_mask.units[["unit_id","eligible","exclusion_reasons"]]
    base = meta.merge(mask,on="unit_id",validate="one_to_one")

    acz = rq1.acz_fire_pattern_reference[["unit_id","unit_name","unit_code","mean_annual_ba_per100km2_fixed_support"]].copy()
    acz = acz.rename(columns={"unit_code":"parent_code","mean_annual_ba_per100km2_fixed_support":"value"})
    acz["panel"]="direct_acz_long_run_rate"; acz["support_status"]="valid_nonzero"; acz["exclusion_reasons"]=""

    district = base.merge(rq1.district_metrics_source[["unit_id","long_run_rate"]],on="unit_id",how="left",validate="one_to_one")
    district["panel"]="district_long_run_rate"
    district["support_status"] = np.where(~district["eligible"],"excluded",np.where(district["long_run_rate"].fillna(0).eq(0),"valid_zero","valid_nonzero"))
    district["value"] = np.where(district["eligible"],district["long_run_rate"],np.nan)

    cols=["panel","unit_id","unit_name","parent_code","support_status","value","exclusion_reasons"]
    return pd.concat([acz[cols],district[cols]],ignore_index=True)

def _seasonality_spatial_organisation_presentation_source(rq1, summary: DataContractSummary, authorities: DataAuthorities) -> pd.DataFrame:
    cols=["panel","record_type","unit_id","unit_name","parent_code","month","value","circular_mean_month","mean_resultant_length","local_class","support_status","exclusion_reasons"]
    acz = rq1.seasonality_spatial_organisation_source.loc[rq1.seasonality_spatial_organisation_source["panel"].eq("acz_seasonality")].copy()
    acz["support_status"]="valid_nonzero"; acz["exclusion_reasons"]=""

    meta=authorities.district_panel[["unit_id","unit_name","parent_code"]].drop_duplicates("unit_id")
    mask=summary.long_run_mask.units[["unit_id","eligible","exclusion_reasons"]]
    base=meta.merge(mask,on="unit_id",validate="one_to_one")
    dep=base.merge(rq1.district_metrics_source[["unit_id","district_departure"]],on="unit_id",how="left",validate="one_to_one")
    dep["panel"]="district_departure"; dep["record_type"]="district_departure"; dep["month"]=np.nan
    dep["value"]=np.where(dep["eligible"],dep["district_departure"],np.nan); dep["circular_mean_month"]=np.nan; dep["mean_resultant_length"]=np.nan; dep["local_class"]=""
    dep["support_status"]=np.where(~dep["eligible"],"excluded",np.where(dep["value"].fillna(0).eq(0),"valid_zero","valid_nonzero"))

    spatial=rq1.spatial_statistics_authority.loc[rq1.spatial_statistics_authority["record_type"].eq("local_moran")].copy()
    lm=base.merge(spatial[["unit_id","local_class","island"]],on="unit_id",how="left",validate="one_to_one")
    lm["panel"]="local_moran"; lm["record_type"]="local_moran"; lm["month"]=np.nan; lm["value"]=np.nan; lm["circular_mean_month"]=np.nan; lm["mean_resultant_length"]=np.nan
    lm["local_class"]=lm["local_class"].fillna("")
    island_mask = lm["island"].map(lambda value: bool(value) if pd.notna(value) else False).to_numpy(dtype=bool)
    lm.loc[island_mask,"local_class"]="ISLAND"
    lm["support_status"]=np.where(~lm["eligible"],"excluded","valid_nonzero")
    return pd.concat([acz[cols],dep[cols],lm[cols]],ignore_index=True)


def _cross_product_observability_presentation_source(rq3, summary: DataContractSummary, authorities: DataAuthorities) -> pd.DataFrame:
    cols=["panel","record_type","unit_id","unit_name","parent_code","state","proportion","value","term","adjusted_or","or_lower_95","or_upper_95","p","support_status","exclusion_reasons"]
    states=rq3.four_state_summary_source.loc[rq3.four_state_summary_source["summary_scope"].eq("acz")].copy()
    states["panel"]="four_state_correspondence"; states["record_type"]="acz_four_state"; states["unit_id"]=""; states["unit_name"]=states["parent_name"]
    states["proportion"]=states["percentage"]/100.0; states["value"]=np.nan; states["term"]=""; states["adjusted_or"]=np.nan; states["or_lower_95"]=np.nan; states["or_upper_95"]=np.nan; states["p"]=np.nan; states["support_status"]="valid_nonzero"; states["exclusion_reasons"]=""

    meta=authorities.district_panel[["unit_id","unit_name","parent_code"]].drop_duplicates("unit_id")
    mask=summary.paired_mask.units[["unit_id","eligible","exclusion_reasons"]]
    mismatch=meta.merge(mask,on="unit_id",validate="one_to_one").merge(rq3.district_mismatch_source[["unit_id","viirs_only_share"]],on="unit_id",how="left",validate="one_to_one")
    mismatch["panel"]="mismatch_geography"; mismatch["record_type"]="district_viirs_only_share"; mismatch["state"]=""; mismatch["proportion"]=np.nan
    mismatch["value"]=np.where(mismatch["eligible"],mismatch["viirs_only_share"],np.nan); mismatch["term"]=""; mismatch["adjusted_or"]=np.nan; mismatch["or_lower_95"]=np.nan; mismatch["or_upper_95"]=np.nan; mismatch["p"]=np.nan
    mismatch["support_status"]=np.where(~mismatch["eligible"],"excluded",np.where(mismatch["value"].fillna(0).eq(0),"valid_zero","valid_nonzero"))

    focal=rq3.focal_effect_source.copy(); focal["term"]=focal["term"].replace({"log2_viirs_det_primary":"VIIRS detection count (per doubling)","log2_viirs_frp_mean_mw":"Mean FRP (per doubling)"}); focal["panel"]="focal_adjusted_associations"; focal["record_type"]="focal_pgee"; focal["unit_id"]=""; focal["unit_name"]=""; focal["parent_code"]=""; focal["state"]=""; focal["proportion"]=np.nan; focal["value"]=np.nan; focal["support_status"]="valid_nonzero"; focal["exclusion_reasons"]=""
    return pd.concat([states[cols],mismatch[cols],focal[cols]],ignore_index=True)


def _district_seasonal_diagnostics_source(rq1) -> pd.DataFrame:
    src=rq1.district_scale_authority
    rows=[]
    for r in src.itertuples(index=False):
        for m in range(1,13):
            rows.append({"record_type":"monthly_share","unit_id":r.unit_id,"unit_name":r.unit_name,"parent_code":r.parent_code,"month":m,"monthly_share":float(getattr(r,f"monthly_share_m{m:02d}")),"circular_mean_month":float(r.circular_mean_month),"mean_resultant_length":float(r.mean_resultant_length)})
    return pd.DataFrame(rows)


def _supplement_s5(rq3) -> pd.DataFrame:
    columns=["record_type","scope","parent_code","parent_name","state","count","denominator_n","proportion","month","y1","y0","term","term_role","beta","corrected_se","z","p","adjusted_or","or_lower_95","or_upper_95","diagnostic_name","diagnostic_value","comparison_variable","correlation","vif","predictor_id","quantile","raw_quantile_value","transformed_quantile_value","standardised_probability","n","districts","estimator","working_structure","covariance_method","reference_distribution"]
    chunks=[]
    fs=rq3.four_state_summary_source.copy(); fs["record_type"]="four_state"; fs["scope"]=fs["summary_scope"]; fs["proportion"]=fs["percentage"]/100.0; chunks.append(fs)
    mo=rq3.separation_diagnostics.loc[rq3.separation_diagnostics["factor"].eq("month")].copy(); mo["record_type"]="month_outcome"; mo["month"]=pd.to_numeric(mo["level"]); chunks.append(mo)
    corr=rq3.predictor_diagnostics_source.loc[rq3.predictor_diagnostics_source["record_type"].eq("correlation")].copy(); corr["record_type"]="correlation"; corr["term"]=corr["variable"]; chunks.append(corr)
    vif=rq3.predictor_diagnostics_source.loc[rq3.predictor_diagnostics_source["record_type"].eq("distribution")].copy(); vif["record_type"]="vif"; vif["term"]=vif["variable"]; chunks.append(vif)
    diag=rq3.fit_diagnostics_source.copy(); diag_long=[]
    for k,v in diag.iloc[0].items(): diag_long.append({"record_type":"diagnostic","diagnostic_name":k,"diagnostic_value":v})
    chunks.append(pd.DataFrame(diag_long))
    coef=rq3.full_coefficient_source.copy(); coef["record_type"]="coefficient"; chunks.append(coef)
    std=rq3.standardised_probability_source.copy(); std["record_type"]="standardised_probability"; chunks.append(std)
    out=[]
    for c in chunks:
        c=c.copy()
        rename={"count":"count","denominator_n":"denominator_n","level":"month","estimate":"beta","standard_error":"corrected_se","test_statistic":"z","p_value":"p","standardisation_predictor":"predictor_id","standardisation_quantile":"quantile"}
        # Fill absent canonical publication columns without changing native scientific values.
        for target in columns:
            if target not in c.columns: c[target]=np.nan
        out.append(c[columns])
    return pd.concat(out,ignore_index=True)



_SATSCAN_S6_COLUMNS = [
    "record_type", "model_id", "product", "model", "cluster_rank", "unit_id", "unit_name",
    "start_month", "end_month", "observed", "expected", "relative_risk", "likelihood_ratio",
    "p_value", "parameter_name", "parameter_value", "anchor_method", "x", "y", "file_role",
    "file_path", "sha256",
]


def _blank_s6_row() -> dict[str, object]:
    return {column: "" for column in _SATSCAN_S6_COLUMNS}


def _parse_parameter_assignments(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")) or "=" not in line:
            continue
        name, value = line.split("=", 1)
        rows.append((name.strip(), value.strip()))
    return rows



_CLUSTER_PRODUCT_MASK = {
    "mcd64a1": "long_run",
    "viirs": "paired",
}


def build_cluster_recurrence_source(
    cluster_membership_source: pd.DataFrame,
    data_contract: DataContractSummary,
    *,
    products: tuple[str, ...] | list[str] = ("mcd64a1", "viirs"),
    significance_alpha: float = 0.05,
) -> pd.DataFrame:
    """Project validated significant-cluster memberships to district recurrence counts.

    The source is purely descriptive: for each configured product and governed district,
    ``significant_cluster_count`` is the number of distinct validated significant
    ``cluster_id`` values containing that district.  Duplicate membership rows cannot
    inflate the count.  Eligible districts without membership are genuine zeroes;
    excluded/unsupported districts retain missing plotted values and their governed
    exclusion reason.

    ``cluster_membership_source`` is already a validated significant-membership authority.
    Optional ``p_value`` or ``is_significant`` columns are accepted only as additional
    fail-closed guards for controlled validation fixtures; they are never used to create a
    new threshold or reclassify a cluster.
    """
    required = {"product", "unit_id", "cluster_id"}
    missing = sorted(required.difference(cluster_membership_source.columns))
    if missing:
        raise PublicationSourceError(
            f"Cluster recurrence source requires validated membership columns: {missing!r}"
        )
    if not (0.0 < float(significance_alpha) < 1.0):
        raise PublicationSourceError("Cluster recurrence significance guard must lie in (0, 1)")

    ordered_products = tuple(str(x) for x in products)
    if not ordered_products or len(set(ordered_products)) != len(ordered_products):
        raise PublicationSourceError("Cluster recurrence products must be a non-empty unique sequence")
    unknown_products = sorted(set(ordered_products).difference(_CLUSTER_PRODUCT_MASK))
    if unknown_products:
        raise PublicationSourceError(f"Unsupported cluster-recurrence products: {unknown_products!r}")
    observed_products = set(cluster_membership_source["product"].dropna().astype(str))
    unexpected_products = sorted(observed_products.difference(ordered_products))
    if unexpected_products:
        raise PublicationSourceError(
            f"Validated membership contains products outside the recurrence projection: {unexpected_products!r}"
        )

    source = cluster_membership_source.copy()
    if "is_significant" in source.columns:
        significant = source["is_significant"]
        if significant.isna().any() or not significant.astype(bool).all():
            raise PublicationSourceError("Non-significant cluster membership cannot enter recurrence source")
    if "p_value" in source.columns:
        p_values = pd.to_numeric(source["p_value"], errors="coerce")
        if p_values.isna().any() or (~np.isfinite(p_values.to_numpy(dtype=float))).any():
            raise PublicationSourceError("Cluster recurrence membership p-values must be finite when supplied")
        if p_values.gt(float(significance_alpha)).any():
            raise PublicationSourceError("Non-significant cluster membership cannot enter recurrence source")

    cluster_numeric = pd.to_numeric(source["cluster_id"], errors="coerce")
    if cluster_numeric.isna().any() or (~np.isfinite(cluster_numeric.to_numpy(dtype=float))).any():
        raise PublicationSourceError("Cluster recurrence requires finite integer cluster IDs")
    if (cluster_numeric < 1).any() or not np.allclose(
        cluster_numeric.to_numpy(dtype=float), np.round(cluster_numeric.to_numpy(dtype=float)), atol=0.0, rtol=0.0
    ):
        raise PublicationSourceError("Cluster recurrence requires positive integer cluster IDs")
    source["cluster_id"] = cluster_numeric.astype("int64")
    source["unit_id"] = source["unit_id"].astype(str)
    source["product"] = source["product"].astype(str)

    rows: list[pd.DataFrame] = []
    for product in ordered_products:
        mask_name = _CLUSTER_PRODUCT_MASK[product]
        mask = data_contract.long_run_mask if mask_name == "long_run" else data_contract.paired_mask
        governed = mask.units[["unit_id", "eligible", "exclusion_reasons"]].copy()
        governed["unit_id"] = governed["unit_id"].astype(str)
        subset = source.loc[source["product"].eq(product), ["unit_id", "cluster_id"]].copy()

        unknown_units = sorted(set(subset["unit_id"]).difference(set(governed["unit_id"])))
        if unknown_units:
            raise PublicationSourceError(
                f"Cluster recurrence membership contains unknown {product} districts: {unknown_units[:5]!r}"
            )
        if not subset.empty:
            eligibility = governed.set_index("unit_id")["eligible"].astype(bool)
            excluded_members = sorted({u for u in subset["unit_id"] if not bool(eligibility.loc[u])})
            if excluded_members:
                raise PublicationSourceError(
                    f"Cluster recurrence membership contains excluded {product} districts: {excluded_members[:5]!r}"
                )

        total = int(subset["cluster_id"].nunique())
        counts = (
            subset.groupby("unit_id", sort=True, observed=True)["cluster_id"]
            .nunique()
            .astype("int64")
            .rename("significant_cluster_count")
            .reset_index()
            if not subset.empty
            else pd.DataFrame(columns=["unit_id", "significant_cluster_count"])
        )
        out = governed.merge(counts, on="unit_id", how="left", validate="one_to_one")
        eligible = out["eligible"].astype(bool)
        out.loc[eligible, "significant_cluster_count"] = (
            pd.to_numeric(out.loc[eligible, "significant_cluster_count"], errors="coerce").fillna(0).astype("int64")
        )
        out.loc[~eligible, "significant_cluster_count"] = pd.NA
        out["significant_cluster_count"] = out["significant_cluster_count"].astype("Int64")
        out["total_significant_clusters"] = pd.Series(total, index=out.index, dtype="Int64")
        out["significant_cluster_fraction"] = np.nan
        if total > 0:
            out.loc[eligible, "significant_cluster_fraction"] = (
                out.loc[eligible, "significant_cluster_count"].astype(float) / float(total)
            )
        positive = eligible & out["significant_cluster_count"].fillna(0).astype("Int64").gt(0)
        out["support_status"] = np.where(
            ~eligible,
            "excluded",
            np.where(positive, "valid_nonzero", "valid_zero"),
        )
        out.loc[eligible, "exclusion_reasons"] = ""
        out["product"] = product
        rows.append(
            out[[
                "product",
                "unit_id",
                "significant_cluster_count",
                "total_significant_clusters",
                "significant_cluster_fraction",
                "support_status",
                "exclusion_reasons",
            ]]
        )

    result = pd.concat(rows, ignore_index=True)
    if result.loc[result["significant_cluster_count"].notna(), "significant_cluster_count"].lt(0).any():
        raise PublicationSourceError("Cluster recurrence counts must be non-negative")
    return result.reset_index(drop=True)


def build_satscan_publication_sources(
    *,
    parsed_by_model: Mapping[str, ParsedSaTScanResults],
    scenarios: tuple[ScanScenario, ...] | list[ScanScenario],
    location_authority: pd.DataFrame,
    data_contract: DataContractSummary,
    run_registry: pd.DataFrame | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Build the three SaTScan-dependent publication sources from validated results.

    This function never parses unvalidated external files itself.  Callers must
    supply ``ParsedSaTScanResults`` objects produced by the fail-closed SaTScan
    validator.  The STP model retains a blank relative-risk field by design.
    """
    scenario_map = {scenario.scenario_id: scenario for scenario in scenarios}
    if set(parsed_by_model) != set(scenario_map):
        raise PublicationSourceError("Validated SaTScan models do not match the configured scenario set")
    cluster_summary = build_cluster_summary_source(parsed_by_model, scenarios)
    cluster_membership = build_cluster_membership_source(parsed_by_model, scenarios, location_authority)

    names = (
        cluster_membership.groupby(["model_id", "cluster_id"], sort=True, observed=True)["unit_name"]
        .agg(lambda values: "|".join(sorted({str(value) for value in values})))
        .rename("district_membership")
        .reset_index()
    ) if not cluster_membership.empty else pd.DataFrame(columns=["model_id", "cluster_id", "district_membership"])
    table3 = cluster_summary.merge(names, on=["model_id", "cluster_id"], how="left", validate="one_to_one")
    table3["district_membership"] = table3["district_membership"].fillna("")
    table3 = table3.rename(columns={
        "case_count": "observed", "likelihood_ratio": "likelihood_ratio",
    })[[
        "product", "model", "cluster_rank", "district_membership", "start_month", "end_month",
        "observed", "expected_count", "relative_risk", "likelihood_ratio", "p_value",
    ]].rename(columns={"expected_count": "expected"})

    cluster_membership_source = cluster_membership[["product", "unit_id", "cluster_id"]].copy()
    cluster_membership_source = cluster_membership_source.sort_values(["product", "cluster_id", "unit_id"], kind="mergesort").reset_index(drop=True)
    cluster_recurrence_source = build_cluster_recurrence_source(
        cluster_membership_source, data_contract, products=("mcd64a1", "viirs")
    )

    s6_rows: list[dict[str, object]] = []
    for row in cluster_summary.itertuples(index=False):
        item = _blank_s6_row()
        item.update({
            "record_type": "cluster", "model_id": row.model_id, "product": row.product,
            "model": row.model, "cluster_rank": row.cluster_rank, "start_month": row.start_month,
            "end_month": row.end_month, "observed": row.case_count, "expected": row.expected_count,
            "relative_risk": row.relative_risk, "likelihood_ratio": row.likelihood_ratio,
            "p_value": row.p_value,
        })
        s6_rows.append(item)
    for row in cluster_membership.itertuples(index=False):
        item = _blank_s6_row()
        item.update({
            "record_type": "membership", "model_id": row.model_id, "product": row.product,
            "model": row.model, "cluster_rank": row.cluster_rank, "unit_id": row.unit_id,
            "unit_name": row.unit_name, "start_month": row.start_month, "end_month": row.end_month,
            "p_value": row.p_value,
        })
        s6_rows.append(item)
    for row in location_authority.sort_values("location_id", kind="mergesort").itertuples(index=False):
        item = _blank_s6_row()
        item.update({
            "record_type": "coordinate", "unit_id": row.unit_id, "unit_name": row.unit_name,
            "anchor_method": row.anchor_method, "x": float(row.x), "y": float(row.y),
        })
        s6_rows.append(item)

    if run_registry is not None:
        if run_dir is None:
            raise PublicationSourceError("run_dir is required when a SaTScan run registry is supplied")
        root = Path(run_dir).resolve()
        for run in run_registry.sort_values("model_id", kind="mergesort").itertuples(index=False):
            model_id = str(run.model_id)
            if model_id not in scenario_map:
                raise PublicationSourceError(f"SaTScan run registry contains unknown model {model_id!r}")
            scenario = scenario_map[model_id]
            prm_path = (root / str(run.prm_path)).resolve()
            try:
                prm_path.relative_to(root)
            except ValueError as exc:
                raise PublicationSourceError("SaTScan parameter path escapes the governed run directory") from exc
            if not prm_path.is_file():
                raise PublicationSourceError(f"SaTScan parameter file is missing: {prm_path}")
            for name, value in _parse_parameter_assignments(prm_path):
                item = _blank_s6_row()
                item.update({
                    "record_type": "parameter", "model_id": model_id, "product": scenario.product,
                    "model": scenario.model, "parameter_name": name, "parameter_value": value,
                    "file_role": "parameter", "file_path": str(run.prm_path), "sha256": str(run.prm_sha256),
                })
                s6_rows.append(item)
            for role, path_attr, hash_attr in (
                ("parameter", "prm_path", "prm_sha256"),
                ("case", "case_path", "case_sha256"),
                ("coordinate", "coordinate_path", "coordinate_sha256"),
                ("population", "population_path", "population_sha256"),
            ):
                rel = str(getattr(run, path_attr, "") or "")
                digest = str(getattr(run, hash_attr, "") or "")
                if not rel:
                    continue
                item = _blank_s6_row()
                item.update({
                    "record_type": "file", "model_id": model_id, "product": scenario.product,
                    "model": scenario.model, "file_role": role, "file_path": rel, "sha256": digest,
                })
                s6_rows.append(item)

    s6 = pd.DataFrame(s6_rows, columns=_SATSCAN_S6_COLUMNS)
    if not s6.empty:
        s6 = s6.reset_index(drop=True)
    return {
        "table3_satscan_clusters": table3,
        "supplement_s6_satscan": s6,
        "cluster_membership_source": cluster_membership_source,
        "cluster_recurrence_source": cluster_recurrence_source,
    }


def materialise_satscan_publication_sources(
    *,
    parsed_by_model: Mapping[str, ParsedSaTScanResults],
    scenarios: tuple[ScanScenario, ...] | list[ScanScenario],
    location_authority: pd.DataFrame,
    run_registry: pd.DataFrame,
    run_dir: str | Path,
    paths: ProjectPaths | None = None,
    data_contract: DataContractSummary | None = None,
) -> dict[str, object]:
    """Reject legacy repository-authority materialisation.

    Genuine external SaTScan results are integrated only by the package-owned
    optional-integration state machine into the current run directory. Static
    repository publication authorities are immutable product bytes.
    """
    raise PublicationSourceError(
        "Repository SaTScan publication-authority mutation is prohibited; "
        "use validate_and_integrate_satscan_results_if_available() for run-local sources"
    )

def materialise_publication_authorities(
    *, paths: ProjectPaths | None=None, bundle: ConfigurationBundle | None=None,
    authorities: DataAuthorities | None=None, data_contract: DataContractSummary | None=None,
) -> dict[str, object]:
    governed=paths or ProjectPaths.discover(); bundle=bundle or load_configuration_bundle(governed.root/"config")
    authorities=authorities or load_data_authorities(governed,bundle.data_schema)
    data_contract=data_contract or validate_data_authorities(authorities,bundle.analysis,bundle.data_schema)
    rq1=build_rq1_tables(authorities,data_contract,bundle.analysis)
    rq2=build_rq2_tables(authorities,data_contract,bundle.analysis,bundle.methods,configuration_sha256=bundle.configuration_sha256)
    rq3=build_rq3_tables(authorities,data_contract,bundle.analysis,bundle.methods,configuration_sha256=bundle.configuration_sha256)
    sources: dict[str,pd.DataFrame]={
        "table1_acz_summary":_table1(rq1,rq2),
        "table2_rq3_model":rq3.continuous_model_summary_source.copy(),
        "supplement_s1_populations":_population_table(bundle),
        "supplement_s2_district_rq1":rq1.district_metrics_source[["unit_id","unit_name","parent_code","parent_name","dominant_overlap_share","long_run_rate","district_departure","circular_mean_month","mean_resultant_length"]].copy(),
        "supplement_s3_spatial":rq1.spatial_statistics_authority.copy(),
        "supplement_s4_rq2":rq2.rq2_full_authority[["parent_code","parent_name","year","annual_rate","sen_slope","u_n","long_run_variance","t_n","realised_bandwidth","permutation_count","seed","raw_p","bh_q"]].copy(),
        "supplement_s5_rq3":_supplement_s5(rq3),
        "long_run_spatial_rate_presentation_source":_long_run_spatial_rate_presentation_source(rq1,data_contract,authorities),
        "seasonality_spatial_organisation_presentation_source":_seasonality_spatial_organisation_presentation_source(rq1,data_contract,authorities),
        "annual_trend_source":rq2.annual_trend_source.copy(),
        "cross_product_observability_presentation_source":_cross_product_observability_presentation_source(rq3,data_contract,authorities),
        "district_seasonal_diagnostics_source":_district_seasonal_diagnostics_source(rq1),
    }
    root=governed.root/PUBLICATION_AUTHORITY_DIR; root.mkdir(parents=True,exist_ok=True)
    manifest_entries={}
    for name,frame in sorted(sources.items()):
        path=root/f"{name}.csv"; _write_csv(path,frame)
        manifest_entries[name]={"path":path.relative_to(governed.root).as_posix(),"rows":int(len(frame)),"columns":list(frame.columns),"sha256":_digest(path),"size_bytes":path.stat().st_size}
    manifest={"schema_version":bundle.analysis.schema_version,"authority":"qualified_analysis_results_for_publication","configuration_sha256":bundle.configuration_sha256,"sources":manifest_entries,"satscan_dependent_sources_materialised":False,"satscan_reason":"genuine_external_results_required"}
    (root/MANIFEST_NAME).write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return manifest


def load_publication_authorities(
    *,
    paths: ProjectPaths | None = None,
    run_local_source_dir: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load immutable repository authorities plus optional validated run-local SaTScan sources."""
    governed = paths or ProjectPaths.discover()
    root = governed.root / PUBLICATION_AUTHORITY_DIR
    mp = root / MANIFEST_NAME
    if not mp.is_file():
        raise PublicationSourceError(f"Publication source manifest missing: {mp}")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    out: dict[str, pd.DataFrame] = {}
    for name, entry in manifest["sources"].items():
        path = governed.root / entry["path"]
        if not path.is_file():
            raise PublicationSourceError(f"Publication source missing: {path}")
        if _digest(path) != entry["sha256"]:
            raise PublicationSourceError(f"Publication source hash mismatch: {name}")
        frame = pd.read_csv(path)
        if list(frame.columns) != entry["columns"] or len(frame) != entry["rows"]:
            raise PublicationSourceError(f"Publication source schema/row mismatch: {name}")
        out[str(name)] = frame

    if run_local_source_dir is not None:
        extra_root = Path(run_local_source_dir).resolve()
        run_root = governed.resolve_inside("out/runs").resolve()
        try:
            extra_root.relative_to(run_root)
        except ValueError as exc:
            raise PublicationSourceError("Run-local publication source directory escapes governed run root") from exc
        extra_manifest_path = extra_root / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
        if not extra_manifest_path.is_file():
            raise PublicationSourceError("Run-local SaTScan publication-source manifest is missing")
        extra = json.loads(extra_manifest_path.read_text(encoding="utf-8"))
        if extra.get("schema") != "rp1-satscan-run-local-publication-sources-v1":
            raise PublicationSourceError("Unsupported run-local SaTScan publication-source manifest")
        if extra.get("external_execution_state") != "RESULTS_VALIDATED":
            raise PublicationSourceError("Run-local SaTScan sources are not RESULTS_VALIDATED")
        for name, entry in extra.get("sources", {}).items():
            path = (extra_root.parent.parent / entry["path"]).resolve()
            try:
                path.relative_to(extra_root.parent.parent.resolve())
            except ValueError as exc:
                raise PublicationSourceError("Run-local publication source path escapes the secondary run") from exc
            if not path.is_file() or _digest(path) != entry["sha256"]:
                raise PublicationSourceError(f"Run-local publication source hash mismatch: {name}")
            frame = pd.read_csv(path)
            if list(frame.columns) != entry["columns"] or len(frame) != int(entry["rows"]):
                raise PublicationSourceError(f"Run-local publication source schema/row mismatch: {name}")
            out[str(name)] = frame
    return out
