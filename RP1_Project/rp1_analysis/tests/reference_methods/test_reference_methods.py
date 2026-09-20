from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from types import MappingProxyType

import geopandas as gpd
from shapely.geometry import box

from rp1_analysis_v1.config import load_configuration_bundle, rq1_spatial_parameters
from rp1_analysis_v1.inequality import gini_coefficient
from rp1_analysis_v1.inference import benjamini_hochberg, sens_slope
from rp1_analysis_v1.seasonality import circular_mean_resultant
from rp1_analysis_v1.spatial_stats import QueenWeights, global_morans_i, local_morans_i, queen_contiguity_weights

from .reference_implementations import (
    bh_reference,
    circular_reference,
    gini_reference,
    global_moran_reference,
    local_moran_reference,
    queen_neighbours_reference,
    sen_reference,
)

HERE = Path(__file__).resolve().parent
FIX = HERE.parent / "fixtures/reference_methods"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def close(a: float, b: float, tol: float = 1e-12) -> None:
    assert math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol), (a, b)


def test_reference_implementation_has_no_production_imports() -> None:
    tree = ast.parse((HERE / "reference_implementations.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("rp1_analysis_v1")
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("rp1_analysis_v1") for alias in node.names)


def test_sen_reference_fixture_and_production_parity() -> None:
    fixture = load("sen_slope.json")
    reference = sen_reference(
        fixture["input"]["y"],
        fixture["input"]["x"],
        fixture["input"]["confidence_level"],
    )
    for key, value in fixture["expected"].items():
        close(reference[key], value)
    result = sens_slope(
        fixture["input"]["y"],
        x=fixture["input"]["x"],
        confidence_level=fixture["input"]["confidence_level"],
    )
    for key in ("slope", "intercept", "ci_low", "ci_high"):
        close(getattr(result, key), fixture["expected"][key])


def test_bh_reference_fixture_and_production_parity() -> None:
    fixture = load("benjamini_hochberg.json")
    reference = bh_reference(fixture["input"]["p_values"])
    for observed, expected in zip(
        reference, fixture["expected"]["adjusted_p_values"], strict=True
    ):
        close(observed, expected)
    result = benjamini_hochberg(
        fixture["input"]["p_values"],
        family_name="reference",
        alpha=fixture["input"]["alpha"],
    )
    for observed, expected in zip(result.adjusted_p_values, reference, strict=True):
        close(observed, expected)


def test_gini_reference_fixture_and_production_parity() -> None:
    fixture = load("gini.json")
    reference = gini_reference(fixture["input"]["values"])
    close(reference, fixture["expected"]["gini"])
    close(gini_coefficient(fixture["input"]["values"]), reference)


def test_circular_reference_fixture_and_production_parity() -> None:
    fixture = load("circular_statistics.json")
    reference = circular_reference(fixture["input"]["shares"])
    result = circular_mean_resultant(fixture["input"]["shares"])
    for key in ("mean_direction_radians", "mean_month", "resultant_length"):
        close(reference[key], fixture["expected"][key])
        close(getattr(result, key), reference[key])


def _weights(fixture: dict) -> QueenWeights:
    spec = fixture["input"]
    return QueenWeights(
        ids=tuple(spec["ids"]),
        neighbours=MappingProxyType(
            {key: tuple(value) for key, value in spec["neighbours"].items()}
        ),
        islands=(),
        transform="row_standardised",
        island_policy="exclude_from_statistic",
    )


def test_global_moran_reference_fixture_and_production_parity() -> None:
    fixture = load("global_moran.json")
    spec = fixture["input"]
    reference = global_moran_reference(
        spec["values"],
        spec["ids"],
        spec["neighbours"],
        spec["permutations"],
        spec["seed"],
    )
    result = global_morans_i(
        spec["values"],
        _weights(fixture),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
    )
    for key in ("morans_i", "expected_i", "permutation_p"):
        close(reference[key], fixture["expected"][key])
        close(getattr(result, key), reference[key])


def test_local_moran_reference_fixture_and_production_parity() -> None:
    fixture = load("local_moran.json")
    spec = fixture["input"]
    reference = local_moran_reference(
        spec["values"],
        spec["ids"],
        spec["neighbours"],
        spec["permutations"],
        spec["seed"],
    )
    params = rq1_spatial_parameters(load_configuration_bundle(HERE.parents[1] / "config").analysis)
    result = local_morans_i(
        spec["values"],
        _weights(fixture),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
        alpha=None,
        family_name="reference_fixture",
        upper_tail_comparison=params.local_upper_tail_comparison,
        tie_allocation=params.local_tie_allocation,
        multiply_smaller_tail_by_two=params.local_multiply_smaller_tail_by_two,
    )
    expected_by_id = {row["unit_id"]: row for row in reference}
    repeated = local_morans_i(
        spec["values"],
        _weights(fixture),
        permutations=spec["permutations"],
        random_seed=spec["seed"],
        alpha=None,
        family_name="reference_fixture",
        upper_tail_comparison=params.local_upper_tail_comparison,
        tie_allocation=params.local_tie_allocation,
        multiply_smaller_tail_by_two=params.local_multiply_smaller_tail_by_two,
    )
    for row, row2 in zip(result.to_dict("records"), repeated.to_dict("records"), strict=True):
        expected = expected_by_id[row["unit_id"]]
        close(row["local_morans_i"], expected["local_morans_i"])
        # The independent reference and production implementation use different
        # valid uniform-without-replacement generators.  A fixed seed therefore
        # does not imply identical Monte-Carlo streams.  Require deterministic
        # production output and agreement within four binomial Monte-Carlo SEs.
        close(row["permutation_p"], row2["permutation_p"])
        ref_p = float(expected["permutation_p"])
        mc_se = (ref_p * (1.0 - ref_p) / (spec["permutations"] + 1.0)) ** 0.5
        assert abs(float(row["permutation_p"]) - ref_p) <= 4.0 * mc_se


def test_queen_reference_fixture_and_production_parity() -> None:
    fixture = load("queen_contiguity.json")
    rectangles = fixture["input"]["rectangles"]
    reference = queen_neighbours_reference(rectangles)
    assert reference == fixture["expected"]["neighbours"]
    geometry = gpd.GeoDataFrame(
        [
            {"dist_id": item["id"], "geometry": box(*item["bounds"])}
            for item in rectangles
        ],
        geometry="geometry",
        crs="EPSG:32630",
    )
    result = queen_contiguity_weights(geometry, island_policy="exclude_from_statistic")
    observed = {key: list(value) for key, value in result.neighbours.items()}
    assert observed == reference
    assert list(result.islands) == fixture["expected"]["islands"]
    matrix = result.row_standardised_matrix()
    assert matrix.shape == (4, 4)
    assert all(math.isclose(float(x), 1.0, abs_tol=1e-12) for x in matrix.sum(axis=1))
