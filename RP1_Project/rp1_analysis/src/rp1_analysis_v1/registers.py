"""Config-projected publication registries with explicit dependency injection."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from .contracts import FigureContract, OutputContract
from .outputs import OutputRecord
from .presentation import load_figure_specs

EVIDENCE_CLASSES = frozenset({
    "DESCRIPTIVE", "PRIMARY_INFERENCE", "SENSITIVITY", "EXPLORATORY",
    "PRIMARY_AND_DESCRIPTIVE", "PRIMARY_INFERENCE_AND_DIAGNOSTIC",
    "SECONDARY_INFERENCE", "DATA_AUTHORITY",
})
OUTPUT_ROLES = frozenset({"manuscript", "supplementary", "internal_authority"})


class RegistryError(ValueError):
    pass


def table_specs(output_contract: OutputContract) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return tuple(
        (item.output_id, item.rq, item.title, item.role, item.family_id, item.evidence_class)
        for item in output_contract.tables
    )


def figure_specs(figure_contract: FigureContract) -> tuple[tuple[str, str, str, str, str], ...]:
    return tuple(spec.registry_tuple() for spec in load_figure_specs(figure_contract))


def _assert_unique(values: Iterable[str], label: str) -> None:
    materialised = list(values)
    duplicates = sorted({x for x in materialised if materialised.count(x) > 1})
    if duplicates:
        raise RegistryError(f"Duplicate {label}: {duplicates!r}")


def validate_publication_specs(output_contract: OutputContract, figure_contract: FigureContract) -> None:
    tables = table_specs(output_contract); figures = figure_specs(figure_contract)
    _assert_unique((x[0] for x in tables), "table IDs")
    _assert_unique((x[0] for x in figures), "figure IDs")
    for _, _, _, role, _, evidence in tables:
        if role not in OUTPUT_ROLES:
            raise RegistryError(f"Unsupported output role: {role}")
        if evidence not in EVIDENCE_CLASSES:
            raise RegistryError(f"Unsupported evidence class: {evidence}")
    for _, _, _, role, evidence in figures:
        if role not in OUTPUT_ROLES:
            raise RegistryError(f"Unsupported figure role: {role}")
        if evidence not in EVIDENCE_CLASSES:
            raise RegistryError(f"Unsupported evidence class: {evidence}")


def _manuscript_table_for_rq(output_contract: OutputContract, rq: str) -> str:
    matches = [
        item.output_id for item in output_contract.tables
        if item.role == "manuscript" and rq in item.rq.split("_")
    ]
    if len(matches) != 1:
        raise RegistryError(f"Expected one manuscript table covering {rq!r}; got {matches!r}")
    return matches[0]


def _output_id_for_source_attribute(output_contract: OutputContract, source_attribute: str) -> str:
    matches = [
        item.output_id for item in output_contract.tables
        if item.source_attribute == source_attribute
    ]
    if len(matches) != 1:
        raise RegistryError(
            f"Expected one publication table for semantic source {source_attribute!r}; got {matches!r}"
        )
    return matches[0]


def _figure_id_for_source_attribute(figure_contract: FigureContract, source_attribute: str) -> str:
    matches = [
        item.figure_id for item in figure_contract.figures
        if item.source_attribute == source_attribute and item.role == "manuscript"
    ]
    if len(matches) != 1:
        raise RegistryError(
            f"Expected one manuscript figure for semantic source {source_attribute!r}; got {matches!r}"
        )
    return matches[0]


def table_registry(
    records: Mapping[str, OutputRecord],
    *,
    output_contract: OutputContract,
    deferred: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    deferred = deferred or {}
    rows: list[dict[str, object]] = []
    for table_id, rq, title, role, family_id, evidence in table_specs(output_contract):
        record = records.get(table_id); state = deferred.get(table_id)
        if record is None and state is None:
            raise RegistryError(f"Missing registered table output: {table_id}")
        rows.append({
            "table_id": table_id, "rq": rq, "title": title, "role": role,
            "family_id": family_id, "evidence_class": evidence,
            "availability": state or "AVAILABLE",
            "path": "" if record is None else record.path,
            "sha256": "" if record is None else record.sha256,
            "size_bytes": 0 if record is None else int(record.size_bytes),
        })
    return pd.DataFrame(rows)


def figure_registry(manifests: Mapping[str, dict], *, figure_contract: FigureContract) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for figure_id, rq, title, role, evidence in figure_specs(figure_contract):
        manifest = manifests.get(figure_id)
        if manifest is None:
            raise RegistryError(f"Missing registered figure output: {figure_id}")
        images = {item["format"]: item for item in manifest.get("images", [])}
        fd = manifest.get("figure_data", {})
        rows.append({
            "figure_id": figure_id, "rq": rq, "title": title, "role": role,
            "evidence_class": evidence, "availability": manifest.get("availability", "AVAILABLE"),
            "figure_data_path": fd.get("path", ""), "figure_data_sha256": fd.get("sha256", ""),
            "png_path": images.get("png", {}).get("path", ""), "pdf_path": images.get("pdf", {}).get("path", ""),
            "manifest_path": manifest.get("manifest_path", ""),
        })
    return pd.DataFrame(rows)


def result_registry(
    rq1_spatial: pd.DataFrame,
    rq2_primary: pd.DataFrame,
    rq3_focal: pd.DataFrame | None = None,
    *,
    output_contract: OutputContract,
    figure_contract: FigureContract,
) -> pd.DataFrame:
    """Build a compact cross-RQ registry from governed result authorities."""
    # Result provenance is tied to the semantic presentation source that actually
    # contains the result, never to the first table/figure associated with an RQ.
    rq1_table = f"{_output_id_for_source_attribute(output_contract, 'supplement_s3_spatial')}.csv"
    rq2_table = f"{_output_id_for_source_attribute(output_contract, 'table1_acz_summary')}.csv"
    rq3_table = (
        f"{_output_id_for_source_attribute(output_contract, 'table2_rq3_model')}.csv"
        if rq3_focal is not None else None
    )
    # Global Moran is not directly displayed in a generated manuscript figure.
    rq1_figure = ""
    rq2_figure = _figure_id_for_source_attribute(figure_contract, "annual_trend_source")
    rq3_figure = _figure_id_for_source_attribute(
        figure_contract, "cross_product_observability_presentation_source"
    )
    rows: list[dict[str, object]] = []
    primary = rq1_spatial
    if "specification_role" in primary.columns:
        primary = primary.loc[primary["specification_role"].astype(str).eq("primary")]
    if len(primary) != 1:
        raise RegistryError("RQ1 result registry requires exactly one primary Global Moran authority")
    rec = primary.iloc[0]
    rows.append({
        "result_id":"RQ1_GLOBAL_MORAN_PRIMARY","rq":"RQ1","analysis_type":"global_morans_i",
        "metric":"within_acz_absolute_departure","estimate":rec["morans_i"],"lower_ci":None,"upper_ci":None,
        "p_value":rec["permutation_p"],"q_value":None,"sample_n":rec["n_effective"],
        "evidence_class":"PRIMARY_INFERENCE","source_table":rq1_table,"source_figure":rq1_figure or "",
    })
    for rec in rq2_primary.to_dict(orient="records"):
        rows.append({
            "result_id":f"RQ2_TREND_{rec['parent_code']}","rq":"RQ2","analysis_type":"trend",
            "metric":"annual_ba_rate_fixed_support","estimate":rec["sen_slope"],
            "lower_ci":None,"upper_ci":None,
            "p_value":rec["raw_p"],"q_value":rec["bh_q"],
            "sample_n":rec["n"],"evidence_class":"PRIMARY_INFERENCE","source_table":rq2_table,
            "source_figure":rq2_figure or "",
        })
    if rq3_focal is not None:
        required={"term","adjusted_or","or_lower_95","or_upper_95","p","n"}; missing=sorted(required.difference(rq3_focal.columns))
        if missing: raise RegistryError(f"RQ3 focal result authority missing columns: {missing!r}")
        for rec in rq3_focal.to_dict(orient="records"):
            rows.append({
                "result_id":f"RQ3_PGEE_{rec['term']}","rq":"RQ3","analysis_type":"firth_type_pgee",
                "metric":str(rec["term"]),"estimate":rec["adjusted_or"],"lower_ci":rec["or_lower_95"],
                "upper_ci":rec["or_upper_95"],"p_value":rec["p"],"q_value":None,"sample_n":rec["n"],
                "evidence_class":"PRIMARY_INFERENCE","source_table":rq3_table or "","source_figure":rq3_figure or "",
            })
    frame=pd.DataFrame(rows); _assert_unique(frame["result_id"].astype(str),"result IDs")
    if not set(frame["evidence_class"]).issubset(EVIDENCE_CLASSES): raise RegistryError("Result registry contains an invalid evidence class")
    return frame


def artefact_registry(run_dir: str | Path) -> pd.DataFrame:
    import hashlib
    root=Path(run_dir).resolve(); rows=[]
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel=path.relative_to(root).as_posix()
        if rel.endswith("T_ARTEFACT_REGISTRY.csv"): continue
        rows.append({"path":rel,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size_bytes":path.stat().st_size})
    return pd.DataFrame(rows)
