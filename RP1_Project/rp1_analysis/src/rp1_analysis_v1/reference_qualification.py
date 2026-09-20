#!/usr/bin/env python3
"""Qualify implemented numerical capabilities against independent references.

RQ2 qualification uses a separate direct-loop Romano–Tirlea implementation from the
test-only reference estate; it does not call the production implementation as its oracle.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from rp1_analysis_v1.config import load_configuration_bundle, rq1_spatial_parameters, rq2_trend_parameters, rq3_model_parameters
from rp1_analysis_v1.inequality import gini_coefficient
from rp1_analysis_v1.inference import benjamini_hochberg, sens_slope, studentized_global_mann_kendall_permutation
from rp1_analysis_v1.method_authority import method_is_implemented, require_method_authority
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.pgee import fit_firth_pgee_independence, morel_bokossa_neerchal_covariance
from rp1_analysis_v1.seasonality import circular_mean_resultant
from rp1_analysis_v1.spatial_stats import QueenWeights, global_morans_i, local_morans_i, queen_contiguity_weights


def _close(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)


def _load(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / name).read_text(encoding="utf-8"))


def _module(project_root: Path, relative: str, name: str):
    path = project_root / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load independent reference module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _weights(spec: dict[str, Any]) -> QueenWeights:
    return QueenWeights(
        ids=tuple(spec["ids"]),
        neighbours=MappingProxyType({key: tuple(value) for key, value in spec["neighbours"].items()}),
        islands=tuple(spec.get("islands", ())),
        transform="row_standardised",
        island_policy="exclude_from_inference",
    )


def qualify(root: Path) -> dict[str, Any]:
    paths = ProjectPaths(root)
    fixtures = paths.reference_fixture_root
    bundle = load_configuration_bundle(root / "config")
    pgee_ref = _module(
        root,
        "tests/reference_methods/pgee_reference_implementations.py",
        "rp1_pgee_reference_implementations",
    )
    rq2_ref = _module(
        root,
        "tests/reference_methods/rq2_romano_tirlea_reference.py",
        "rp1_rq2_romano_tirlea_reference",
    )
    spatial_params = rq1_spatial_parameters(bundle.analysis)
    results: list[dict[str, Any]] = []

    fixture = _load(fixtures, "sen_slope.json")
    result = sens_slope(
        fixture["input"]["y"],
        x=fixture["input"]["x"],
        confidence_level=fixture["input"]["confidence_level"],
    )
    passed = all(_close(getattr(result, k), v) for k, v in fixture["expected"].items())
    results.append({"family": "sens_slope", "status": "PASS" if passed else "FAIL"})

    fixture = _load(fixtures, "benjamini_hochberg.json")
    result = benjamini_hochberg(
        fixture["input"]["p_values"], family_name="reference", alpha=fixture["input"]["alpha"]
    )
    passed = all(
        _close(a, b)
        for a, b in zip(
            result.adjusted_p_values,
            fixture["expected"]["adjusted_p_values"],
            strict=True,
        )
    )
    results.append({"family": "benjamini_hochberg", "status": "PASS" if passed else "FAIL"})

    rq2_params = rq2_trend_parameters(bundle.analysis)
    rq2_method = require_method_authority(bundle.methods, rq2_params.inferential_test)
    rq2_values = [1.0, 4.0, 2.0, 3.0, 6.0, 5.0, 8.0, 7.0]
    rq2_prod = studentized_global_mann_kendall_permutation(
        rq2_values,
        bandwidth_rule=rq2_params.bandwidth_rule,
        variance_floor=rq2_params.variance_floor,
        replications=199,
        alternative=rq2_params.alternative,
        seed=7319,
        p_value_rule=rq2_params.p_value_method,
        empirical_cdf=rq2_params.empirical_cdf,
        studentisation=rq2_params.studentisation,
        method_id=rq2_method.method_id,
        implementation_id=rq2_method.implementation_id,
    )
    rq2_expected = rq2_ref.permutation_test(
        rq2_values, epsilon=rq2_params.variance_floor, replications=199, seed=7319
    )
    rq2_ok = bool(
        _close(rq2_prod.u_n, rq2_expected.u_n)
        and rq2_prod.realised_bandwidth == rq2_expected.bandwidth
        and _close(rq2_prod.long_run_variance, rq2_expected.sigma2)
        and _close(rq2_prod.t_n, rq2_expected.t_n)
        and rq2_prod.extreme_count == rq2_expected.extreme_count
        and _close(rq2_prod.raw_p, rq2_expected.p_value)
        and rq2_prod.raw_p > 0.0
    )
    results.append({"family": "rq2_romano_tirlea_studentized_mk", "status": "PASS" if rq2_ok else "FAIL"})

    fixture = _load(fixtures, "gini.json")
    passed = _close(gini_coefficient(fixture["input"]["values"]), fixture["expected"]["gini"])
    results.append({"family": "gini_coefficient", "status": "PASS" if passed else "FAIL"})

    fixture = _load(fixtures, "circular_statistics.json")
    result = circular_mean_resultant(fixture["input"]["shares"])
    passed = all(_close(getattr(result, k), v) for k, v in fixture["expected"].items())
    results.append({"family": "circular_statistics", "status": "PASS" if passed else "FAIL"})

    fixture = _load(fixtures, "queen_contiguity.json")
    import geopandas as gpd
    from shapely.geometry import box

    qframe = gpd.GeoDataFrame(
        {
            "dist_id": [x["id"] for x in fixture["input"]["rectangles"]],
            "geometry": [box(*x["bounds"]) for x in fixture["input"]["rectangles"]],
        },
        geometry="geometry",
        crs="EPSG:32630",
    )
    qweights = queen_contiguity_weights(qframe, island_policy=spatial_params.island_policy)
    expected = {str(k): tuple(v) for k, v in fixture["expected"]["neighbours"].items()}
    passed = dict(qweights.neighbours) == expected and qweights.islands == tuple(fixture["expected"]["islands"])
    results.append({"family": "queen_contiguity", "status": "PASS" if passed else "FAIL"})

    fixture = _load(fixtures, "global_moran.json")
    spec = fixture["input"]
    result = global_morans_i(
        spec["values"],
        _weights(spec),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
        alternative="two_sided_centered_on_randomisation_expectation",
    )
    passed = all(_close(getattr(result, k), v) for k, v in fixture["expected"].items())
    results.append({"family": "global_moran", "status": "PASS" if passed else "FAIL"})

    fixture = _load(fixtures, "local_moran.json")
    spec = fixture["input"]
    result = local_morans_i(
        spec["values"],
        _weights(spec),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
        alpha=None,
        family_name="reference_local_family",
        upper_tail_comparison=spatial_params.local_upper_tail_comparison,
        tie_allocation=spatial_params.local_tie_allocation,
        multiply_smaller_tail_by_two=spatial_params.local_multiply_smaller_tail_by_two,
    )
    repeated = local_morans_i(
        spec["values"],
        _weights(spec),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
        alpha=None,
        family_name="reference_local_family",
        upper_tail_comparison=spatial_params.local_upper_tail_comparison,
        tie_allocation=spatial_params.local_tie_allocation,
        multiply_smaller_tail_by_two=spatial_params.local_multiply_smaller_tail_by_two,
    )
    expected_by_id = {r["unit_id"]: r for r in fixture["expected"]}
    repeated_by_id = {r["unit_id"]: r for r in repeated.to_dict("records")}
    passed = True
    for row in result.to_dict("records"):
        expected_row = expected_by_id[row["unit_id"]]
        repeated_row = repeated_by_id[row["unit_id"]]
        ref_p = float(expected_row["permutation_p"])
        mc_se = math.sqrt(ref_p * (1.0 - ref_p) / (spec["permutations"] + 1.0))
        passed = (
            passed
            and _close(row["local_morans_i"], expected_row["local_morans_i"])
            and _close(row["permutation_p"], repeated_row["permutation_p"])
            and abs(float(row["permutation_p"]) - ref_p) <= 4.0 * mc_se
        )
    results.append({"family": "local_moran", "status": "PASS" if passed else "FAIL"})

    # RQ3 separation-resistant coefficient and covariance authorities.
    n_ref = 80
    sep = (np.arange(n_ref) >= n_ref // 2).astype(float)
    nuisance = (np.arange(n_ref) % 2 == 0).astype(float)
    X_ref = np.column_stack([np.ones(n_ref), sep, nuisance])
    y_ref = sep.copy()
    rq3_params = rq3_model_parameters(bundle.analysis)
    prod_beta, _, prod_score, _ = fit_firth_pgee_independence(
        X_ref, y_ref,
        tolerance=rq3_params.tolerance,
        max_iterations=rq3_params.max_iterations,
        max_step_halvings=rq3_params.max_step_halvings,
    )
    expected_beta = pgee_ref.firth_coefficients_reference(X_ref, y_ref)
    coeff_ok = bool(
        np.isfinite(prod_beta).all()
        and prod_score < 1e-6
        and np.allclose(prod_beta, expected_beta, rtol=2e-5, atol=2e-5)
    )
    results.append({"family": "pgee_independence_coefficients", "status": "PASS" if coeff_ok else "FAIL"})

    rng = np.random.default_rng(7319)
    cluster_sizes = [3, 4, 5, 3, 6, 4, 5, 4, 3, 5, 4, 6]
    ids = np.concatenate([[i] * size for i, size in enumerate(cluster_sizes)])
    n_cov = len(ids)
    x1 = rng.normal(size=n_cov)
    x2 = (np.arange(n_cov) % 3 == 0).astype(float)
    X_cov = np.column_stack([np.ones(n_cov), x1, x2])
    lin = -0.25 + 0.6 * x1 - 0.4 * x2
    p_cov = 1.0 / (1.0 + np.exp(-lin))
    y_cov = rng.binomial(1, p_cov).astype(float)
    y_cov[ids == 0] = 1.0
    beta_cov, _, _, _ = fit_firth_pgee_independence(
        X_cov, y_cov,
        tolerance=rq3_params.tolerance,
        max_iterations=rq3_params.max_iterations,
        max_step_halvings=rq3_params.max_step_halvings,
    )
    prod_cov, prod_scale, prod_delta, prod_phi = morel_bokossa_neerchal_covariance(
        X_cov, y_cov, ids, beta_cov
    )
    ref_cov, ref_scale, ref_delta, ref_phi = pgee_ref.mbn_covariance_reference(
        X_cov, y_cov, ids, beta_cov
    )
    cov_ok = bool(
        np.isfinite(prod_cov).all()
        and np.allclose(prod_cov, ref_cov, rtol=1e-10, atol=1e-10)
        and _close(prod_scale, ref_scale)
        and _close(prod_delta, ref_delta)
        and _close(prod_phi, ref_phi)
        and np.allclose(prod_cov, prod_cov.T, rtol=0.0, atol=1e-12)
        and float(np.linalg.eigvalsh(prod_cov).min()) > 0.0
    )
    results.append({"family": "pgee_morel_covariance", "status": "PASS" if cov_ok else "FAIL"})

    rq2_method_id = str(bundle.analysis.research_questions["rq2"]["inferential_test"]["method"])
    rq2_authority = require_method_authority(bundle.methods, rq2_method_id)
    rq2_implemented = method_is_implemented(bundle.methods, rq2_method_id)
    rq2_state = {
        "method_id": rq2_method_id,
        "implementation_id": rq2_authority.implementation_id,
        "implemented": rq2_implemented,
        "qualification_status": rq2_authority.qualification_status,
        "status": "PASS" if rq2_implemented and rq2_ok else "FAIL",
    }

    passed = all(x["status"] == "PASS" for x in results)
    return {
        "schema": "rp1-reference-method-qualification-v1.1",
        "available_reference_families": results,
        "rq2_method_qualification": rq2_state,
        "scientifically_frozen_pending_methods": [],
        "method_authority_count": len(bundle.methods.authorities),
        "status": "PASS" if passed else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    root = ProjectPaths.discover(Path(__file__).resolve()).root
    report = qualify(root)
    payload = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.json_out is not None:
        destination = args.json_out.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    print(f"RP1_REFERENCE_METHOD_QUALIFICATION={report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
