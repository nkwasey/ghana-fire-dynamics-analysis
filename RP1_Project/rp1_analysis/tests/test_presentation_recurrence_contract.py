"""Recurrence presentation follows its current sources, without a saved run."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.presentation_rq4 import _recurrence_map_source
from rp1_analysis_v1.publication_sources import build_cluster_recurrence_source
from rp1_analysis_v1.satscan_integration import (
    OptionalSaTScanIntegrationError,
    RUN_LOCAL_SOURCE_DIR,
    RUN_LOCAL_SOURCE_MANIFEST,
    SECONDARY_SECTION,
    _validate_existing_integrated_sources,
)


PRODUCTS = ("mcd64a1", "viirs")


def _current_source(product: str, cluster_count: int):
    units = pd.DataFrame({
        "unit_id": ["member_a", "member_b", "nonmember", "excluded"],
        "eligible": [True, True, True, False],
        "exclusion_reasons": ["", "", "", "synthetic unsupported district"],
    })
    summary = SimpleNamespace(
        long_run_mask=SimpleNamespace(units=units.copy(deep=True)),
        paired_mask=SimpleNamespace(units=units.copy(deep=True)),
    )
    rows = []
    for position in range(cluster_count):
        cluster_id = 11 + position * 3
        rows.append({"product": product, "unit_id": "member_a", "cluster_id": cluster_id})
        if position % 2 == 0:
            rows.append({"product": product, "unit_id": "member_b", "cluster_id": cluster_id})
    if rows:
        rows.extend([rows[0].copy(), rows[-1].copy()])
    membership = pd.DataFrame(rows, columns=["product", "unit_id", "cluster_id"])
    recurrence = build_cluster_recurrence_source(membership, summary, products=(product,))
    spec = SimpleNamespace(export_id=f"rq4_{product}_recurrence", selector={"equals": product})
    return membership, recurrence, spec


def _editable(frame: pd.DataFrame) -> pd.DataFrame:
    # Permit deliberately malformed controls without pandas rejecting assignment
    # before the production presentation contract can inspect them.
    return frame.copy(deep=True).astype(object)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("cluster_count", (0, 3, 7))
def test_recurrence_render_source_uses_current_membership_denominator(product, cluster_count):
    membership, recurrence, spec = _current_source(product, cluster_count)
    before = recurrence.copy(deep=True)
    observed = _recurrence_map_source(recurrence, spec=spec).set_index("unit_id")
    expected_total = membership["cluster_id"].nunique()
    expected_counts = membership.groupby("unit_id")["cluster_id"].nunique()

    assert observed["total_significant_clusters"].eq(expected_total).all()
    for unit in ("member_a", "member_b", "nonmember"):
        count = int(expected_counts.get(unit, 0))
        assert observed.loc[unit, "significant_cluster_count"] == count
        assert observed.loc[unit, "support_status"] == ("valid_nonzero" if count else "valid_zero")
        fraction = observed.loc[unit, "significant_cluster_fraction"]
        if expected_total:
            assert fraction == pytest.approx(count / expected_total, abs=1e-12)
        else:
            assert pd.isna(fraction)
    assert observed.loc["excluded", "support_status"] == "excluded"
    assert observed.loc["excluded", ["significant_cluster_count", "significant_cluster_fraction"]].isna().all()
    pd.testing.assert_frame_equal(recurrence, before)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("value", (None, np.nan, np.inf, -np.inf, -1, 0.5, 3 + 1e-13, "not numeric"))
def test_recurrence_total_is_finite_nonnegative_integer(product, value):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work["total_significant_clusters"] = value
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
def test_recurrence_total_must_be_single_even_on_excluded_rows(product):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq("excluded"), "total_significant_clusters"] = 4
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("value", (None, np.nan, np.inf, -np.inf, -1, 0.5, 1 + 1e-13, "not numeric"))
def test_recurrence_counts_are_finite_nonnegative_integers(product, value):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq("member_a"), "significant_cluster_count"] = value
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
def test_recurrence_count_cannot_exceed_total_despite_concordant_fraction(product):
    membership, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    total = membership["cluster_id"].nunique()
    selected = work["unit_id"].eq("member_a")
    work.loc[selected, "significant_cluster_count"] = total + 1
    work.loc[selected, "significant_cluster_fraction"] = (total + 1) / total
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("value", (None, np.nan, np.inf, -np.inf, -0.1, 1.1, 0.5, "not numeric"))
def test_positive_total_recurrence_fraction_is_finite_and_concordant(product, value):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq("member_a"), "significant_cluster_fraction"] = value
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("unit,status", (("member_a", "valid_zero"), ("nonmember", "valid_nonzero")))
def test_recurrence_support_status_must_match_zero_or_positive_count(product, unit, status):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq(unit), "support_status"] = status
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
def test_zero_total_recurrence_cannot_carry_a_positive_count(product):
    _, recurrence, spec = _current_source(product, 0)
    work = _editable(recurrence)
    selected = work["unit_id"].eq("member_a")
    work.loc[selected, "significant_cluster_count"] = 1
    work.loc[selected, "support_status"] = "valid_nonzero"
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("fraction", (0.0, 1.0, np.inf))
def test_zero_total_recurrence_fraction_must_remain_missing(product, fraction):
    _, recurrence, spec = _current_source(product, 0)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq("nonmember"), "significant_cluster_fraction"] = fraction
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("column", ("significant_cluster_count", "significant_cluster_fraction"))
def test_excluded_recurrence_plot_values_remain_missing(product, column):
    _, recurrence, spec = _current_source(product, 3)
    work = _editable(recurrence)
    work.loc[work["unit_id"].eq("excluded"), column] = 0
    with pytest.raises(FigureRenderError):
        _recurrence_map_source(work, spec=spec)


def _write_integrated_source_shell(run_dir: Path, sources: dict[str, pd.DataFrame]):
    section = run_dir / SECONDARY_SECTION
    source_root = run_dir / RUN_LOCAL_SOURCE_DIR
    source_root.mkdir(parents=True)
    status = {"external_execution_state": "RESULTS_VALIDATED", "validated_model_count": 2}
    (section / "secondary_external_execution_status.json").write_text(json.dumps(status), encoding="utf-8")
    tables = section / "tables"
    tables.mkdir()
    pd.DataFrame([{"requires_results_validated": True, "availability": "AVAILABLE"}]).to_csv(
        tables / "secondary_output_registry.csv", index=False, lineterminator="\n")
    entries = {}
    for name, frame in sources.items():
        path = source_root / f"{name}.csv"
        path.write_text(frame.to_csv(index=False, lineterminator="\n"), encoding="utf-8", newline="\n")
        entries[name] = {"path": path.relative_to(run_dir).as_posix(),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "size_bytes": path.stat().st_size, "rows": len(frame), "columns": list(frame.columns)}
    manifest = {"schema": "rp1-satscan-run-local-publication-sources-v2",
                "external_execution_state": "RESULTS_VALIDATED", "secondary_run_id": run_dir.name,
                "model_count": 2, "source_policy": "run_local_only",
                "satscan_execution_performed_by_notebook": False, "sources": entries}
    manifest_path = source_root / RUN_LOCAL_SOURCE_MANIFEST
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry = pd.DataFrame([
        {"execution_state": "RESULTS_VALIDATED", "parameter_linkage_validated": True,
         "results_prefix": f"{SECONDARY_SECTION}/satscan/{model}/results/{model}"}
        for model in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY")
    ])
    return manifest_path, manifest, registry


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("corruption", ("total", "district_count"))
def test_rehashed_recurrence_must_still_match_membership_reconstruction(tmp_path, product, corruption):
    membership, recurrence, spec = _current_source(product, 3)
    membership = membership.drop_duplicates().reset_index(drop=True)
    sources = {"cluster_membership_source": membership, "cluster_recurrence_source": recurrence}
    run_dir = tmp_path / "synthetic_validated_sec"
    manifest_path, manifest, registry = _write_integrated_source_shell(run_dir, sources)
    bundle = load_configuration_bundle(Path(__file__).resolve().parents[1] / "config")
    before = {path: path.read_bytes() for path in run_dir.rglob("*") if path.is_file()}
    observed = _validate_existing_integrated_sources(
        run_dir=run_dir, bundle=bundle, registry=registry, sources=sources)
    assert set(observed) == set(sources)
    assert before == {path: path.read_bytes() for path in before}

    # A self-consistent false projection and matching hashes cannot substitute
    # for the sources reconstructed from validated membership authorities.
    wrong = _editable(recurrence)
    eligible = wrong["support_status"].ne("excluded")
    if corruption == "total":
        false_total = membership["cluster_id"].nunique() + 1
        wrong["total_significant_clusters"] = false_total
        wrong.loc[eligible, "significant_cluster_fraction"] = (
            wrong.loc[eligible, "significant_cluster_count"].astype(float) / false_total)
    else:
        selected = wrong["unit_id"].eq("nonmember")
        wrong.loc[selected, "significant_cluster_count"] = 1
        wrong.loc[selected, "significant_cluster_fraction"] = 1 / membership["cluster_id"].nunique()
        wrong.loc[selected, "support_status"] = "valid_nonzero"
    _recurrence_map_source(wrong, spec=spec)  # Locally plausible; the linked guard is decisive.
    entry = manifest["sources"]["cluster_recurrence_source"]
    path = run_dir / entry["path"]
    path.write_text(wrong.to_csv(index=False, lineterminator="\n"), encoding="utf-8", newline="\n")
    entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size_bytes=path.stat().st_size)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OptionalSaTScanIntegrationError, match="currently validated result family"):
        _validate_existing_integrated_sources(
            run_dir=run_dir, bundle=bundle, registry=registry, sources=sources)
