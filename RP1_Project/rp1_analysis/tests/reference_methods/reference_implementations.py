"""Independent test-only reference calculations.

This module intentionally imports no production package code.  It implements
small transparent formulae and geometric predicates suitable for independent
method-parity fixtures.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np


def sen_reference(y, x=None, confidence_level=0.95):
    y = np.asarray(y, dtype=float)
    x = np.arange(len(y), dtype=float) if x is None else np.asarray(x, dtype=float)
    slopes = []
    for i in range(len(y) - 1):
        for j in range(i + 1, len(y)):
            if x[j] > x[i]:
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    slopes = np.sort(np.asarray(slopes, dtype=float))
    slope = float(np.median(slopes))
    intercept = float(np.median(y) - slope * np.median(x))
    alpha = 1.0 - confidence_level if confidence_level > 0.5 else confidence_level
    z = NormalDist().inv_cdf(alpha / 2.0)

    def tie_counts(a):
        _, c = np.unique(a, return_counts=True)
        return [int(v) for v in c if v > 1]

    n = len(y)
    nt = len(slopes)
    sigsq = (
        n * (n - 1) * (2 * n + 5)
        - sum(k * (k - 1) * (2 * k + 5) for k in tie_counts(x))
        - sum(k * (k - 1) * (2 * k + 5) for k in tie_counts(y))
    ) / 18.0
    sigma = math.sqrt(sigsq)
    ru = min(int(round((nt - z * sigma) / 2.0)), len(slopes) - 1)
    rl = max(int(round((nt + z * sigma) / 2.0)) - 1, 0)
    return {
        "slope": slope,
        "intercept": intercept,
        "ci_low": float(slopes[rl]),
        "ci_high": float(slopes[ru]),
    }


def bh_reference(p_values):
    p = np.asarray(p_values, dtype=float)
    m = len(p)
    order = np.argsort(p, kind="stable")
    q_sorted = np.empty(m, float)
    running = 1.0
    for reverse_rank in range(m - 1, -1, -1):
        rank = reverse_rank + 1
        candidate = float(p[order[reverse_rank]]) * m / rank
        running = min(running, candidate)
        q_sorted[reverse_rank] = min(1.0, running)
    q = np.empty(m, float)
    for pos, idx in enumerate(order):
        q[idx] = q_sorted[pos]
    return q.tolist()


def gini_reference(values):
    x = np.asarray(values, dtype=float)
    n = len(x)
    total = float(x.sum())
    if total == 0:
        return 0.0
    pairwise = sum(abs(float(a) - float(b)) for a in x for b in x)
    return pairwise / (2.0 * n * total)


def circular_reference(shares):
    p = np.asarray(shares, dtype=float)
    angles = 2 * math.pi * np.arange(12) / 12.0
    c = float(np.sum(p * np.cos(angles)))
    s = float(np.sum(p * np.sin(angles)))
    r = math.hypot(c, s)
    if r <= 1e-15:
        return {"mean_direction_radians": None, "mean_month": None, "resultant_length": r}
    angle = math.atan2(s, c) % (2 * math.pi)
    month = 1 + 12 * angle / (2 * math.pi)
    if month > 12:
        month -= 12
    return {"mean_direction_radians": angle, "mean_month": month, "resultant_length": r}


def queen_neighbours_reference(rectangles):
    """Independent Queen predicate for non-overlapping axis-aligned rectangles."""
    ids = [item["id"] for item in rectangles]
    result = {unit_id: [] for unit_id in ids}
    for i, left in enumerate(rectangles):
        lx0, ly0, lx1, ly1 = map(float, left["bounds"])
        for j in range(i + 1, len(rectangles)):
            right = rectangles[j]
            rx0, ry0, rx1, ry1 = map(float, right["bounds"])
            closed_intersection = max(lx0, rx0) <= min(lx1, rx1) and max(ly0, ry0) <= min(ly1, ry1)
            interior_overlap = max(lx0, rx0) < min(lx1, rx1) and max(ly0, ry0) < min(ly1, ry1)
            if closed_intersection and not interior_overlap:
                result[left["id"]].append(right["id"])
                result[right["id"]].append(left["id"])
    return {key: sorted(value) for key, value in result.items()}


def row_standardised_matrix(ids, neighbours):
    idx = {u: i for i, u in enumerate(ids)}
    w = np.zeros((len(ids), len(ids)), float)
    for u in ids:
        ns = [v for v in neighbours[u] if v in idx]
        for v in ns:
            w[idx[u], idx[v]] = 1.0 / len(ns)
    return w


def moran_statistic(values, matrix):
    x = np.asarray(values, dtype=float)
    z = x - x.mean()
    denominator = float(z @ z)
    if denominator == 0.0:
        return None
    s0 = float(matrix.sum())
    return (len(x) / s0) * float(z @ matrix @ z) / denominator


def global_moran_reference(values, ids, neighbours, permutations, seed):
    active = [u for u in ids if neighbours[u]]
    mapping = dict(zip(ids, values, strict=True))
    arr = np.asarray([mapping[u] for u in active], float)
    w = row_standardised_matrix(active, neighbours)
    observed = moran_statistic(arr, w)
    expected = -1.0 / (len(arr) - 1)
    if observed is None:
        return {"morans_i": None, "expected_i": expected, "permutation_p": None}
    rng = np.random.default_rng(seed)
    extreme = 0
    distance = abs(observed - expected)
    for _ in range(permutations):
        sim = moran_statistic(rng.permutation(arr), w)
        if abs(sim - expected) >= distance - 1e-15:
            extreme += 1
    return {
        "morans_i": observed,
        "expected_i": expected,
        "permutation_p": (extreme + 1) / (permutations + 1),
    }


def local_moran_reference(values, ids, neighbours, permutations, seed):
    """Independent population-standardised conditional Local Moran calculation.

    For each non-island observation, neighbour values are sampled without
    replacement from all other non-island standardised values.  The pseudo
    permutation p-value uses the smaller randomisation tail, consistent with
    common Local Moran randomisation implementations.
    """
    active = [u for u in ids if neighbours[u]]
    raw = dict(zip(ids, values, strict=True))
    x = np.asarray([raw[u] for u in active], dtype=float)
    sd = float(x.std(ddof=0))
    if sd == 0.0:
        return [
            {"unit_id": u, "local_morans_i": None, "permutation_p": None}
            for u in ids
        ]
    zarr = (x - x.mean()) / sd
    zm = dict(zip(active, zarr, strict=True))
    rng = np.random.default_rng(seed)
    out = []
    for u in ids:
        ns = [v for v in neighbours[u] if v in zm]
        if not ns:
            out.append({"unit_id": u, "local_morans_i": None, "permutation_p": None})
            continue
        obs = float(zm[u] * np.mean([zm[v] for v in ns]))
        p = None
        if permutations:
            other = np.asarray([zm[v] for v in active if v != u], float)
            simulated = np.empty(permutations, float)
            for i in range(permutations):
                sampled = rng.choice(other, size=len(ns), replace=False)
                simulated[i] = zm[u] * float(np.mean(sampled))
            above = int(np.count_nonzero(simulated >= obs))
            extreme_tail = min(above, permutations - above)
            p = (extreme_tail + 1) / (permutations + 1)
        out.append({"unit_id": u, "local_morans_i": obs, "permutation_p": p})
    return out
