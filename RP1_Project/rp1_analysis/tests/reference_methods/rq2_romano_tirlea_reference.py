"""Independent exact-tail reference for RQ2 studentized permutation inference.

This module is test-only and deliberately imports no production inference code.
The Romano--Tirlea reference authority used by RP1 assumes no ties.  For tie-free
inputs, rank arithmetic is exact and the two-sided tail relation is compared via
exact squared studentized statistics rather than independently rounded square
roots.
"""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np


class ReferenceAdmissibilityError(ValueError):
    """Raised when a test-only reference input lies outside the no-ties authority."""


class ReferenceResult:
    __slots__ = ("n", "u_n", "bandwidth", "sigma2", "floor_used", "t_n", "extreme_count", "p_value")

    def __init__(self, *, n, u_n, bandwidth, sigma2, floor_used, t_n, extreme_count, p_value):
        self.n = n
        self.u_n = u_n
        self.bandwidth = bandwidth
        self.sigma2 = sigma2
        self.floor_used = floor_used
        self.t_n = t_n
        self.extreme_count = extreme_count
        self.p_value = p_value


def _bandwidth(n: int) -> int:
    return math.floor(n ** (1.0 / 3.0))


def _tie_free_ranks(values) -> tuple[int, ...]:
    x = [float(v) for v in values]
    if not x:
        raise ReferenceAdmissibilityError("reference series must not be empty")
    if not all(math.isfinite(v) for v in x):
        raise ReferenceAdmissibilityError("reference series must contain finite values")
    if len(set(x)) != len(x):
        raise ReferenceAdmissibilityError(
            "Romano-Tirlea reference qualification requires tie-free observations"
        )
    order = sorted(range(len(x)), key=x.__getitem__)
    ranks = [0] * len(x)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    return tuple(ranks)


def _exact_rank_components(ranks: tuple[int, ...], epsilon: float):
    n = len(ranks)
    pairs = n * (n - 1) // 2
    score = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            score += 1 if ranks[i] < ranks[j] else -1
    u = Fraction(score, pairs)
    g = [Fraction(n - 2 * rank, n) for rank in ranks]
    b = _bandwidth(n)
    covsum = Fraction(0, 1)
    for lag in range(1, b + 1):
        for j in range(n - lag):
            covsum += g[j] * g[j + lag]
    sigma2 = Fraction(4, 9) + Fraction(8, 3 * n) * covsum
    epsilon_exact = Fraction(str(float(epsilon)))
    effective_sigma2 = max(sigma2, epsilon_exact)
    t_squared = Fraction(n, 1) * u * u / effective_sigma2
    t_sign = 0 if score == 0 else (1 if score > 0 else -1)
    t_n = float(t_sign * math.sqrt(float(t_squared)))
    return u, b, sigma2, sigma2 < epsilon_exact, t_n, t_squared


def components(values, epsilon: float):
    ranks = _tie_free_ranks(values)
    u, b, sigma2, floor_used, t_n, _ = _exact_rank_components(ranks, epsilon)
    return float(u), b, float(sigma2), floor_used, t_n


def permutation_test(values, *, epsilon: float, replications: int, seed: int) -> ReferenceResult:
    ranks = _tie_free_ranks(values)
    u, b, sigma2, floor_used, t_n, observed_t_squared = _exact_rank_components(ranks, epsilon)
    rng = np.random.default_rng(seed)
    extreme = 0
    rank_array = np.asarray(ranks, dtype=np.int64)
    for _ in range(replications):
        # Independent direct-loop construction of the same seeded random-key
        # permutation sequence used for reproducibility in production.
        order = np.argsort(rng.random(len(ranks)), kind="stable")
        _, _, _, _, _, perm_t_squared = _exact_rank_components(
            tuple(int(v) for v in rank_array[order]), epsilon
        )
        if perm_t_squared >= observed_t_squared:
            extreme += 1
    return ReferenceResult(
        n=len(ranks),
        u_n=float(u),
        bandwidth=b,
        sigma2=float(sigma2),
        floor_used=floor_used,
        t_n=t_n,
        extreme_count=extreme,
        p_value=(extreme + 1) / (replications + 1),
    )


def exact_two_sided_extreme(values_observed, values_permuted, *, epsilon: float) -> bool:
    """Return exact ``abs(T_perm) >= abs(T_obs)`` for two tie-free rank sequences."""

    observed = _tie_free_ranks(values_observed)
    permuted = _tie_free_ranks(values_permuted)
    if sorted(observed) != sorted(permuted):
        raise ReferenceAdmissibilityError("permuted reference sequence must preserve the observed ranks")
    *_, observed_t_squared = _exact_rank_components(observed, epsilon)
    *_, permuted_t_squared = _exact_rank_components(permuted, epsilon)
    return permuted_t_squared >= observed_t_squared


def bh_reference(p_values):
    p = [float(v) for v in p_values]
    m = len(p)
    order = sorted(range(m), key=lambda i: (p[i], i))
    ordered = [p[i] for i in order]
    adj = [0.0] * m
    running = 1.0
    for rank_index in range(m - 1, -1, -1):
        rank = rank_index + 1
        running = min(running, ordered[rank_index] * m / rank)
        adj[order[rank_index]] = min(1.0, running)
    return adj
