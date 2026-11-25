"""Validation and deterministic selection of fixed-area denominators."""
import math
import numpy as np

def fixed_denominator(values, tolerance):
    tolerance = float(tolerance)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Fixed denominator tolerance must be finite and nonnegative")
    values = np.asarray(values, dtype=float)
    if values.size == 0 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Fixed denominator values must all be finite and positive")
    lo, hi = float(values.min()), float(values.max())
    if hi - lo > tolerance:
        raise ValueError(f"Fixed denominator spread {hi - lo} exceeds {tolerance} km²")
    return float(values[0]), lo, hi, hi - lo

def constancy_policy(analysis):
    policy = analysis.research_questions["rq1"]["annual_rate"]
    tol = float(policy["fixed_denominator_constancy_absolute_tolerance_km2"])
    if not math.isfinite(tol) or tol < 0:
        raise ValueError("Invalid fixed denominator constancy tolerance")
    if policy["fixed_denominator_representative"] != "earliest_month":
        raise ValueError("Unknown fixed denominator representative")
    return tol
