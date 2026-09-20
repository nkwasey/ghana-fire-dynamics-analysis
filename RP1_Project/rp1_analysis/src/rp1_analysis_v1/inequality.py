"""Generic inequality summaries used by protocol-governed analyses."""

from __future__ import annotations

from collections.abc import Iterable
import math
import numpy as np


class InequalityInputError(ValueError):
    """Raised when a Gini summary is not defined for the supplied values."""


def gini_coefficient(values: Iterable[float]) -> float:
    """Return the standard Gini coefficient for finite non-negative values.

    The definition is sum_i sum_j |x_i-x_j| / (2*n*sum_i x_i).  An
    all-zero distribution has no inequality and returns 0.0.
    """

    arr = np.asarray(list(values), dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise InequalityInputError("values must be a non-empty one-dimensional sequence")
    if not np.isfinite(arr).all():
        raise InequalityInputError("values must be finite")
    if np.any(arr < 0.0):
        raise InequalityInputError("Gini values must be non-negative")
    total = float(arr.sum())
    if total == 0.0:
        return 0.0
    ordered = np.sort(arr)
    n = ordered.size
    ranks = np.arange(1, n + 1, dtype=float)
    value = (2.0 * float(np.dot(ranks, ordered)) / (n * total)) - (n + 1.0) / n
    if value < -1e-12 or value > 1.0 + 1e-12:
        raise InequalityInputError(f"computed Gini outside [0,1]: {value!r}")
    return min(1.0, max(0.0, float(value)))
