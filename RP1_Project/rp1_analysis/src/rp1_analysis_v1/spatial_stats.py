"""Protocol-governed RQ1 spatial weights and Moran/LISA statistics.

The scientific authority is first-order Queen contiguity with row-standardised
weights.  Islands are explicit and are excluded from the inferential statistic;
no distance or nearest-neighbour repair is permitted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import AnalysisContract, rq1_spatial_parameters
from .inference import benjamini_hochberg


class SpatialStatsError(ValueError):
    """Raised when spatial weights or a spatial statistic violate the contract."""


@dataclass(frozen=True, slots=True)
class QueenWeights:
    """Immutable first-order Queen-contiguity neighbour authority."""

    ids: tuple[str, ...]
    neighbours: Mapping[str, tuple[str, ...]]
    islands: tuple[str, ...]
    transform: str
    island_policy: str

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def active_ids(self) -> tuple[str, ...]:
        if self.island_policy in {"exclude_from_inference", "exclude_from_statistic"}:
            island_set = set(self.islands)
            return tuple(x for x in self.ids if x not in island_set)
        return self.ids

    def row_standardised_matrix(self, ids: Sequence[str] | None = None) -> np.ndarray:
        """Return a dense row-standardised matrix for an ordered ID subset."""

        order = tuple(ids) if ids is not None else self.active_ids
        if len(order) != len(set(order)):
            raise SpatialStatsError("Weight matrix ID order contains duplicates")
        unknown = sorted(set(order).difference(self.ids))
        if unknown:
            raise SpatialStatsError(f"Weight matrix requested unknown IDs: {unknown!r}")
        index = {unit_id: i for i, unit_id in enumerate(order)}
        matrix = np.zeros((len(order), len(order)), dtype=float)
        for unit_id in order:
            retained = [n for n in self.neighbours[unit_id] if n in index]
            if not retained:
                continue
            weight = 1.0 / len(retained)
            i = index[unit_id]
            for neighbour in retained:
                matrix[i, index[neighbour]] = weight
        return matrix


@dataclass(frozen=True, slots=True)
class GlobalMoranResult:
    method: str
    role: str
    n_input: int
    n_effective: int
    island_count: int
    island_ids: tuple[str, ...]
    transform: str
    island_policy: str
    morans_i: float | None
    expected_i: float | None
    permutation_p: float | None
    permutations: int
    random_seed: int
    alternative: str
    diagnostic_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "role": self.role,
            "n_input": self.n_input,
            "n_effective": self.n_effective,
            "island_count": self.island_count,
            "island_ids": "|".join(self.island_ids),
            "transform": self.transform,
            "island_policy": self.island_policy,
            "morans_i": self.morans_i,
            "expected_i": self.expected_i,
            "permutation_p": self.permutation_p,
            "permutations": self.permutations,
            "random_seed": self.random_seed,
            "alternative": self.alternative,
            "diagnostic_status": self.diagnostic_status,
        }


@dataclass(frozen=True, slots=True)
class RQ1SpatialAssociationAuthorities:
    """Global and local RQ1 spatial-association authorities plus realised weights."""

    global_table: pd.DataFrame
    local_table: pd.DataFrame
    weights: QueenWeights


def _validate_geometry(gdf: gpd.GeoDataFrame, id_col: str) -> None:
    if id_col not in gdf.columns or "geometry" not in gdf.columns:
        raise SpatialStatsError(f"Geometry must contain {id_col!r} and geometry")
    if gdf.crs is None:
        raise SpatialStatsError("Geometry CRS is missing")
    if gdf[id_col].isna().any() or gdf[id_col].astype(str).duplicated().any():
        raise SpatialStatsError(f"Geometry IDs in {id_col!r} must be unique and non-missing")
    if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
        raise SpatialStatsError("Geometry contains missing or empty features")
    if not bool(gdf.geometry.is_valid.all()):
        raise SpatialStatsError("Geometry contains invalid features")
    allowed = {"Polygon", "MultiPolygon"}
    geometry_types = set(gdf.geometry.geom_type.unique())
    if not geometry_types.issubset(allowed):
        raise SpatialStatsError(
            f"Queen weights require polygon geometry; got {sorted(geometry_types)!r}"
        )


def queen_contiguity_weights(
    geometry: gpd.GeoDataFrame,
    *,
    id_col: str = "dist_id",
    island_policy: str = "exclude_from_statistic",
) -> QueenWeights:
    """Construct deterministic first-order Queen-contiguity neighbours.

    Queen neighbours share at least one boundary point.  No Rook sensitivity,
    distance threshold, k-nearest-neighbour fallback or island repair is used.
    """

    if island_policy not in {"exclude_from_inference", "exclude_from_statistic", "zero_row", "error"}:
        raise SpatialStatsError(f"Unsupported island policy: {island_policy!r}")
    _validate_geometry(geometry, id_col)
    ordered = geometry[[id_col, "geometry"]].copy()
    ordered[id_col] = ordered[id_col].astype(str)
    ordered = ordered.sort_values(id_col).reset_index(drop=True)
    ids = tuple(ordered[id_col].tolist())
    neighbours: dict[str, set[str]] = {unit_id: set() for unit_id in ids}
    spatial_index = ordered.sindex
    for i, geom in enumerate(ordered.geometry):
        candidates = spatial_index.query(geom, predicate="touches")
        for j_raw in candidates:
            j = int(j_raw)
            if j == i:
                continue
            left = ids[i]
            right = ids[j]
            neighbours[left].add(right)
            neighbours[right].add(left)
    frozen = {
        unit_id: tuple(sorted(values)) for unit_id, values in sorted(neighbours.items())
    }
    islands = tuple(sorted(unit_id for unit_id, values in frozen.items() if not values))
    if islands and island_policy == "error":
        raise SpatialStatsError(f"Queen-contiguity islands detected: {islands!r}")
    result = QueenWeights(
        ids=ids,
        neighbours=MappingProxyType(frozen),
        islands=islands,
        transform="row_standardised",
        island_policy=island_policy,
    )
    validate_weights(result)
    return result


def validate_weights(weights: QueenWeights) -> None:
    """Validate symmetry, self-neighbour absence and the governed transform."""

    if weights.transform != "row_standardised":
        raise SpatialStatsError("RQ1 spatial weights must be row-standardised")
    if len(weights.ids) != len(set(weights.ids)):
        raise SpatialStatsError("Spatial weight IDs are not unique")
    if set(weights.neighbours) != set(weights.ids):
        raise SpatialStatsError(
            "Spatial weight neighbour map does not cover exactly the ID authority"
        )
    for unit_id in weights.ids:
        neighbours = weights.neighbours[unit_id]
        if unit_id in neighbours:
            raise SpatialStatsError(f"Self-neighbour detected for {unit_id!r}")
        if len(neighbours) != len(set(neighbours)):
            raise SpatialStatsError(f"Duplicate neighbours detected for {unit_id!r}")
        for neighbour in neighbours:
            if neighbour not in weights.neighbours:
                raise SpatialStatsError(f"Unknown neighbour {neighbour!r}")
            if unit_id not in weights.neighbours[neighbour]:
                raise SpatialStatsError(
                    f"Asymmetric queen adjacency: {unit_id!r}, {neighbour!r}"
                )
    expected_islands = tuple(sorted(x for x in weights.ids if not weights.neighbours[x]))
    if expected_islands != weights.islands:
        raise SpatialStatsError("Island registry is inconsistent with neighbour map")
    matrix = weights.row_standardised_matrix()
    if matrix.size:
        row_sums = matrix.sum(axis=1)
        active_rows = np.asarray(
            [unit_id not in set(weights.islands) for unit_id in weights.active_ids], dtype=bool
        )
        if active_rows.size and not np.allclose(row_sums[active_rows], 1.0):
            raise SpatialStatsError("Non-island Queen rows are not row-standardised")


def _align_values(
    values: pd.Series | Mapping[str, float] | Sequence[float],
    weights: QueenWeights,
    *,
    ids: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], np.ndarray]:
    order = tuple(ids) if ids is not None else weights.active_ids
    if isinstance(values, pd.Series):
        if values.index.has_duplicates:
            raise SpatialStatsError("Spatial value Series index contains duplicates")
        mapping = {str(k): v for k, v in values.items()}
        missing = sorted(set(order).difference(mapping))
        if missing:
            raise SpatialStatsError(f"Spatial values missing governed IDs: {missing!r}")
        arr = np.asarray([mapping[x] for x in order], dtype=float)
    elif isinstance(values, Mapping):
        mapping = {str(k): v for k, v in values.items()}
        missing = sorted(set(order).difference(mapping))
        if missing:
            raise SpatialStatsError(f"Spatial values missing governed IDs: {missing!r}")
        arr = np.asarray([mapping[x] for x in order], dtype=float)
    else:
        arr = np.asarray(values, dtype=float)
        if arr.ndim != 1 or len(arr) != len(order):
            raise SpatialStatsError("Spatial value sequence length does not match weight IDs")
    if arr.ndim != 1 or not np.isfinite(arr).all():
        raise SpatialStatsError("Spatial values must be finite and one-dimensional")
    return order, arr


def _moran_i(values: np.ndarray, matrix: np.ndarray) -> float | None:
    centred = values - float(values.mean())
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        return None
    s0 = float(matrix.sum())
    if s0 <= 0.0:
        raise SpatialStatsError("Spatial weight matrix has non-positive total weight")
    n = len(values)
    numerator = float(centred @ matrix @ centred)
    return (n / s0) * numerator / denominator


def global_morans_i(
    values: pd.Series | Mapping[str, float] | Sequence[float],
    weights: QueenWeights,
    *,
    permutations: int,
    random_seed: int,
    alternative: str = "two_sided_centered_on_randomisation_expectation",
) -> GlobalMoranResult:
    """Compute Global Moran's I with deterministic two-sided permutation inference."""

    validate_weights(weights)
    if not isinstance(permutations, int) or isinstance(permutations, bool) or permutations < 1:
        raise SpatialStatsError("permutations must be a positive integer")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool) or random_seed < 0:
        raise SpatialStatsError("random_seed must be a non-negative integer")
    if alternative != "two_sided_centered_on_randomisation_expectation":
        raise SpatialStatsError(f"Unsupported Moran permutation alternative: {alternative!r}")
    if weights.islands and weights.island_policy == "error":
        raise SpatialStatsError("Island policy prohibits Moran calculation")
    order, arr = _align_values(values, weights)
    if len(order) < 3:
        raise SpatialStatsError("Global Moran's I requires at least three non-island observations")
    matrix = weights.row_standardised_matrix(order)
    observed = _moran_i(arr, matrix)
    expected = -1.0 / (len(arr) - 1)
    if observed is None:
        return GlobalMoranResult(
            method="global_morans_i_permutation",
            role="primary",
            n_input=weights.n,
            n_effective=len(arr),
            island_count=len(weights.islands),
            island_ids=weights.islands,
            transform=weights.transform,
            island_policy=weights.island_policy,
            morans_i=None,
            expected_i=expected,
            permutation_p=None,
            permutations=permutations,
            random_seed=random_seed,
            alternative=alternative,
            diagnostic_status="constant_series",
        )
    rng = np.random.default_rng(random_seed)
    observed_distance = abs(observed - expected)
    extreme = 0
    for _ in range(permutations):
        simulated = _moran_i(rng.permutation(arr), matrix)
        if simulated is None:
            raise SpatialStatsError("Permutation unexpectedly produced undefined Moran's I")
        if abs(simulated - expected) >= observed_distance - 1e-15:
            extreme += 1
    p_value = (extreme + 1.0) / (permutations + 1.0)
    return GlobalMoranResult(
        method="global_morans_i_permutation",
        role="primary",
        n_input=weights.n,
        n_effective=len(arr),
        island_count=len(weights.islands),
        island_ids=weights.islands,
        transform=weights.transform,
        island_policy=weights.island_policy,
        morans_i=float(observed),
        expected_i=float(expected),
        permutation_p=float(p_value),
        permutations=permutations,
        random_seed=random_seed,
        alternative=alternative,
        diagnostic_status="ok",
    )


def _local_class(z_value: float, spatial_lag_z: float, supported: bool) -> str:
    """Return an inferential LISA class only for an FDR-supported local result."""

    if not supported:
        return "NS"
    if z_value > 0.0 and spatial_lag_z > 0.0:
        return "HH"
    if z_value < 0.0 and spatial_lag_z < 0.0:
        return "LL"
    if z_value > 0.0 and spatial_lag_z < 0.0:
        return "HL"
    if z_value < 0.0 and spatial_lag_z > 0.0:
        return "LH"
    return "NS"


def local_moran_smaller_tail_plus_one(
    simulated: Sequence[float] | np.ndarray,
    observed: float,
    *,
    upper_tail_comparison: str,
    tie_allocation: str,
    multiply_smaller_tail_by_two: bool,
) -> float:
    """Apply the configured conditional Local Moran pseudo-p convention.

    The function is deliberately separated from simulation so tail, tie and plus-one
    semantics can be independently reference-tested.
    """

    values = np.asarray(simulated, dtype=float)
    if values.ndim != 1 or values.size < 1 or not np.isfinite(values).all():
        raise SpatialStatsError("Local Moran simulated statistics must be a non-empty finite vector")
    if not math.isfinite(float(observed)):
        raise SpatialStatsError("Local Moran observed statistic must be finite")
    if upper_tail_comparison == "greater_than_or_equal":
        above = int(np.count_nonzero(values >= float(observed)))
    elif upper_tail_comparison == "greater_than":
        above = int(np.count_nonzero(values > float(observed)))
    else:
        raise SpatialStatsError(f"Unsupported Local Moran upper-tail comparison: {upper_tail_comparison!r}")
    if tie_allocation == "upper_tail":
        below = int(values.size - above)
    elif tie_allocation == "lower_tail":
        below = int(np.count_nonzero(values <= float(observed)))
    else:
        raise SpatialStatsError(f"Unsupported Local Moran tie allocation: {tie_allocation!r}")
    p_value = (min(above, below) + 1.0) / (values.size + 1.0)
    if multiply_smaller_tail_by_two:
        p_value = min(1.0, 2.0 * p_value)
    return float(p_value)


def _conditional_without_replacement_means(
    pool: np.ndarray,
    *,
    sample_size: int,
    draws: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return means of uniform ordered samples without replacement.

    IID integer samples are retained only when every sampled index is distinct.
    Conditional on distinctness every ordered tuple is equiprobable, so the retained
    draws have the same sampling law as uniform sampling without replacement while
    avoiding one Python-level RNG call per permutation.
    """

    values = np.asarray(pool, dtype=float)
    if values.ndim != 1 or values.size < 1 or not np.isfinite(values).all():
        raise SpatialStatsError("Conditional permutation pool must be a finite vector")
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 1:
        raise SpatialStatsError("Conditional sample size must be a positive integer")
    if sample_size > values.size:
        raise SpatialStatsError("Conditional sample size exceeds permutation pool")
    if not isinstance(draws, int) or isinstance(draws, bool) or draws < 1:
        raise SpatialStatsError("Conditional permutation draws must be a positive integer")
    if sample_size == 1:
        idx = rng.integers(0, values.size, size=draws)
        return values[idx].astype(float, copy=False)

    out = np.empty(draws, dtype=float)
    filled = 0
    # Oversampling reduces iterations; the cap bounds temporary allocations.
    while filled < draws:
        remaining = draws - filled
        batch = min(max(remaining * 2, 256), 65536)
        idx = rng.integers(0, values.size, size=(batch, sample_size))
        ordered = np.sort(idx, axis=1)
        valid = np.all(np.diff(ordered, axis=1) != 0, axis=1)
        accepted = idx[valid]
        if accepted.size == 0:
            continue
        take = min(remaining, accepted.shape[0])
        out[filled : filled + take] = values[accepted[:take]].mean(axis=1)
        filled += take
    return out


def local_morans_i(
    values: pd.Series | Mapping[str, float] | Sequence[float],
    weights: QueenWeights,
    *,
    permutations: int,
    random_seed: int,
    alpha: float | None,
    family_name: str,
    upper_tail_comparison: str,
    tie_allocation: str,
    multiply_smaller_tail_by_two: bool,
) -> pd.DataFrame:
    """Compute Local Moran's I using conditional random permutations.

    Islands are not repaired and are emitted with undefined statistics.  The
    standardisation basis contains non-island observations only.  When ``alpha``
    is provided, all eligible local permutation p-values form one BH-FDR family;
    HH/LL/HL/LH labels are emitted only for FDR-supported results.
    """

    validate_weights(weights)
    if not isinstance(permutations, int) or isinstance(permutations, bool) or permutations < 0:
        raise SpatialStatsError("Local Moran permutations must be a non-negative integer")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool) or random_seed < 0:
        raise SpatialStatsError("random_seed must be a non-negative integer")
    if upper_tail_comparison not in {"greater_than_or_equal", "greater_than"}:
        raise SpatialStatsError(f"Unsupported Local Moran upper-tail comparison: {upper_tail_comparison!r}")
    if tie_allocation not in {"upper_tail", "lower_tail"}:
        raise SpatialStatsError(f"Unsupported Local Moran tie allocation: {tie_allocation!r}")
    if not isinstance(multiply_smaller_tail_by_two, bool):
        raise SpatialStatsError("multiply_smaller_tail_by_two must be boolean")
    if alpha is not None:
        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool):
            raise SpatialStatsError("alpha must be numeric")
        alpha = float(alpha)
        if not 0.0 < alpha < 1.0:
            raise SpatialStatsError("alpha must lie strictly between 0 and 1")
        if permutations < 1:
            raise SpatialStatsError("BH-FDR requires positive local permutation count")

    if isinstance(values, pd.Series):
        if values.index.has_duplicates:
            raise SpatialStatsError("Local Moran Series index contains duplicates")
        mapping = {str(k): float(v) for k, v in values.items()}
    elif isinstance(values, Mapping):
        mapping = {str(k): float(v) for k, v in values.items()}
    else:
        arr = np.asarray(values, dtype=float)
        if arr.ndim != 1 or len(arr) != weights.n:
            raise SpatialStatsError("Local Moran sequence must align to all weight IDs")
        mapping = dict(zip(weights.ids, arr.tolist(), strict=True))
    missing = sorted(set(weights.ids).difference(mapping))
    if missing:
        raise SpatialStatsError(f"Local Moran values missing IDs: {missing!r}")
    if not np.isfinite(np.asarray([mapping[x] for x in weights.ids], dtype=float)).all():
        raise SpatialStatsError("Local Moran values must be finite")

    active_ids = weights.active_ids
    active_values = np.asarray([mapping[x] for x in active_ids], dtype=float)
    if len(active_ids) < 3:
        raise SpatialStatsError("Local Moran requires at least three non-island observations")
    mean = float(active_values.mean())
    sd = float(np.std(active_values, ddof=0))
    if sd == 0.0:
        rows = []
        island_set = set(weights.islands)
        for unit_id in weights.ids:
            rows.append(
                {
                    "unit_id": unit_id,
                    "local_morans_i": None,
                    "permutation_p": None,
                    "bh_q": None,
                    "fdr_supported": False,
                    "lisa_class": "ISLAND" if unit_id in island_set else "UNDEFINED",
                    "z_value": None,
                    "spatial_lag_z": None,
                    "neighbour_count": len(weights.neighbours[unit_id]),
                    "permutations": permutations,
                    "random_seed": random_seed,
                    "role": "local_inference",
                    "diagnostic_status": "island" if unit_id in island_set else "constant_series",
                }
            )
        return pd.DataFrame(rows).sort_values("unit_id").reset_index(drop=True)

    z = {unit_id: (mapping[unit_id] - mean) / sd for unit_id in active_ids}
    rng = np.random.default_rng(random_seed)
    rows: list[dict[str, object]] = []
    active_p: list[float] = []
    active_row_indices: list[int] = []
    island_set = set(weights.islands)

    for unit_id in weights.ids:
        if unit_id in island_set:
            rows.append(
                {
                    "unit_id": unit_id,
                    "local_morans_i": None,
                    "permutation_p": None,
                    "bh_q": None,
                    "fdr_supported": False,
                    "lisa_class": "ISLAND",
                    "z_value": None,
                    "spatial_lag_z": None,
                    "neighbour_count": 0,
                    "permutations": permutations,
                    "random_seed": random_seed,
                    "role": "local_inference",
                    "diagnostic_status": "island",
                }
            )
            continue
        neighbours = tuple(n for n in weights.neighbours[unit_id] if n in z)
        if not neighbours:
            raise SpatialStatsError(
                f"Non-island unit {unit_id!r} has no retained Queen neighbours"
            )
        spatial_lag = float(np.mean([z[n] for n in neighbours]))
        observed = float(z[unit_id] * spatial_lag)
        p_value: float | None = None
        if permutations:
            other_z = np.asarray([z[x] for x in active_ids if x != unit_id], dtype=float)
            k = len(neighbours)
            if k > other_z.size:
                raise SpatialStatsError("Neighbour count exceeds conditional permutation pool")
            sampled_means = _conditional_without_replacement_means(
                other_z, sample_size=k, draws=permutations, rng=rng
            )
            simulated = float(z[unit_id]) * sampled_means
            p_value = local_moran_smaller_tail_plus_one(
                simulated,
                observed,
                upper_tail_comparison=upper_tail_comparison,
                tie_allocation=tie_allocation,
                multiply_smaller_tail_by_two=multiply_smaller_tail_by_two,
            )
        row_index = len(rows)
        rows.append(
            {
                "unit_id": unit_id,
                "local_morans_i": observed,
                "permutation_p": p_value,
                "bh_q": None,
                "fdr_supported": False,
                "lisa_class": "NS",
                "z_value": float(z[unit_id]),
                "spatial_lag_z": spatial_lag,
                "neighbour_count": len(neighbours),
                "permutations": permutations,
                "random_seed": random_seed,
                "role": "local_inference",
                "diagnostic_status": "ok",
            }
        )
        if p_value is not None:
            active_row_indices.append(row_index)
            active_p.append(float(p_value))

    if alpha is not None:
        if len(active_p) != len(active_ids):
            raise SpatialStatsError("Local FDR family does not cover every non-island district")
        fdr = benjamini_hochberg(active_p, family_name=family_name, alpha=alpha)
        for row_index, q_value, rejected in zip(
            active_row_indices, fdr.adjusted_p_values, fdr.rejected, strict=True
        ):
            row = rows[row_index]
            row["bh_q"] = float(q_value)
            row["fdr_supported"] = bool(rejected)
            row["lisa_class"] = _local_class(
                float(row["z_value"]), float(row["spatial_lag_z"]), bool(rejected)
            )

    return pd.DataFrame(rows).sort_values("unit_id").reset_index(drop=True)


def build_rq1_spatial_association_authorities(
    district_authority: pd.DataFrame,
    district_geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
) -> RQ1SpatialAssociationAuthorities:
    """Build the single primary Global Moran and FDR-controlled Local Moran authorities."""

    required = {"unit_id", "within_acz_absolute_departure"}
    missing = sorted(required.difference(district_authority.columns))
    if missing:
        raise SpatialStatsError(f"District RQ1 authority is missing spatial fields: {missing!r}")
    params = rq1_spatial_parameters(analysis)
    rq1 = analysis.research_questions["rq1"]
    spatial_cfg = rq1["spatial"]
    global_cfg = spatial_cfg["global"]
    local_cfg = spatial_cfg["local"]

    # Configuration supplies the scientific choices.  The implementation only
    # checks that this generic consumer can realise registered capabilities.
    if params.weight_method != "queen_contiguity" or params.weight_order != "first_order":
        raise SpatialStatsError("Configured spatial-weight capability is not implemented")
    if params.weight_transform != "row_standardised":
        raise SpatialStatsError("Configured spatial-weight transform is not implemented")
    if params.local_permutation_scheme != "conditional_without_replacement":
        raise SpatialStatsError("Configured Local Moran permutation capability is not implemented")
    if params.local_p_value_method != "local_moran_smaller_tail_plus_one":
        raise SpatialStatsError("Configured Local Moran p-value capability is not implemented")
    if params.multiplicity_method != "benjamini_hochberg":
        raise SpatialStatsError("Configured local multiplicity capability is not implemented")

    candidate_ids = set(district_authority["unit_id"].astype(str))
    geometry = district_geometry.loc[
        district_geometry["dist_id"].astype(str).isin(candidate_ids)
    ].copy()
    if len(geometry) != len(candidate_ids):
        raise SpatialStatsError("Eligible district geometry does not reconcile to RQ1 authority")
    weights = queen_contiguity_weights(
        geometry,
        id_col="dist_id",
        island_policy=params.island_policy,
    )
    values = district_authority.set_index("unit_id")["within_acz_absolute_departure"].astype(float)
    global_result = global_morans_i(
        values, weights, permutations=params.global_permutations,
        random_seed=params.random_seed, alternative=str(global_cfg["alternative"]),
    )
    global_table = pd.DataFrame([{
        "surface": "within_acz_absolute_departure",
        "specification_role": "primary",
        "candidate_units": len(candidate_ids),
        "weights": f"{params.weight_order}_{params.weight_method}",
        **global_result.to_dict(),
    }])

    local_table = local_morans_i(
        values, weights, permutations=params.local_permutations,
        random_seed=params.random_seed, alpha=params.alpha,
        family_name=str(local_cfg["multiplicity_family"]),
        upper_tail_comparison=params.local_upper_tail_comparison,
        tie_allocation=params.local_tie_allocation,
        multiply_smaller_tail_by_two=params.local_multiply_smaller_tail_by_two,
    )
    metadata_columns = [
        col
        for col in ("unit_id", "unit_name", "parent_id", "parent_code", "parent_name", "within_acz_absolute_departure")
        if col in district_authority.columns
    ]
    local_table = local_table.merge(
        district_authority[metadata_columns], on="unit_id", how="left", validate="one_to_one"
    )
    return RQ1SpatialAssociationAuthorities(global_table, local_table, weights)
