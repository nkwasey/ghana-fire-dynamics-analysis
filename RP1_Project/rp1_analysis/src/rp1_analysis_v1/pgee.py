"""Separation-resistant marginal logistic estimation for current RQ3.

The current RQ3 estimator is the working-independence Firth-type penalised GEE
of Mondol & Rahman (2019).  Under working independence its estimating equation
is equivalent to Firth's bias-reduced logistic score equation.  The coefficient estimator and Morel--Bokossa--Neerchal corrected covariance are
implemented independently of the coefficient-reference distribution.  A caller
selects the reference distribution through the executable analysis contract.

This module deliberately contains no predictor/category selection and no
working-correlation selection machinery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import norm


class PGEEError(RuntimeError):
    """Raised when the governed PGEE calculation is numerically inadmissible."""


@dataclass(frozen=True, slots=True)
class PGEEResult:
    coefficients: np.ndarray
    covariance: np.ndarray
    standard_errors: np.ndarray
    wald_z: np.ndarray
    standard_normal_p: np.ndarray
    standard_normal_ci_low: np.ndarray
    standard_normal_ci_high: np.ndarray
    converged: bool
    iterations: int
    score_max_abs: float
    penalized_loglikelihood: float
    n_observations: int
    n_clusters: int
    design_dimension: int
    covariance_scale_factor: float
    covariance_delta: float
    covariance_design_effect: float
    solver_tolerance: float
    solver_max_iterations: int
    solver_max_step_halvings: int
    step_halvings_total: int
    step_halvings_max_used: int

    @property
    def coefficients_finite(self) -> bool:
        """Return whether every coefficient-side inferential quantity is finite."""
        arrays = (
            self.coefficients,
            self.standard_errors,
            self.wald_z,
            self.standard_normal_p,
            self.standard_normal_ci_low,
            self.standard_normal_ci_high,
        )
        return all(np.isfinite(np.asarray(value, dtype=float)).all() for value in arrays)

    @property
    def covariance_finite(self) -> bool:
        """Return whether the corrected covariance contains only finite values."""
        return bool(np.isfinite(np.asarray(self.covariance, dtype=float)).all())

    @property
    def covariance_symmetric(self) -> bool:
        """Return whether the corrected covariance is numerically symmetric."""
        matrix = np.asarray(self.covariance, dtype=float)
        return bool(np.allclose(matrix, matrix.T, rtol=0.0, atol=1e-12))


@dataclass(frozen=True, slots=True)
class _PGEESolverDiagnostics:
    coefficients: np.ndarray
    iterations: int
    score_max_abs: float
    penalized_loglikelihood: float
    step_halvings_total: int
    step_halvings_max_used: int


@dataclass(frozen=True, slots=True)
class SeparationDiagnostics:
    outcome_n: int
    outcome_y1: int
    outcome_y0: int
    outcome_prevalence_y1: float
    complete_separation_levels: tuple[str, ...]
    all_y1_clusters: int
    all_y0_clusters: int
    cluster_size_min: int
    cluster_size_median: float
    cluster_size_mean: float
    cluster_size_max: int
    design_rank: int
    design_columns: int
    level_table: pd.DataFrame
    cluster_table: pd.DataFrame


def _as_design(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(X, dtype=float)
    out = np.asarray(y, dtype=float)
    if x.ndim != 2 or out.ndim != 1 or x.shape[0] != out.shape[0]:
        raise PGEEError("X must be two-dimensional and align with one-dimensional y")
    if x.shape[0] == 0 or x.shape[1] == 0:
        raise PGEEError("PGEE requires non-empty observations and design columns")
    if not np.isfinite(x).all() or not np.isfinite(out).all():
        raise PGEEError("PGEE input contains non-finite values")
    if not np.isin(out, [0.0, 1.0]).all():
        raise PGEEError("PGEE binary outcome must contain only 0/1")
    if np.linalg.matrix_rank(x) != x.shape[1]:
        raise PGEEError("PGEE design matrix is rank-deficient")
    return x, out


def _information_and_hat(x: np.ndarray, mu: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    w = mu * (1.0 - mu)
    if not np.isfinite(w).all() or np.any(w <= 0.0):
        raise PGEEError("PGEE logistic weights became non-positive or non-finite")
    info = x.T @ (w[:, None] * x)
    try:
        inv = np.linalg.inv(info)
    except np.linalg.LinAlgError as exc:
        raise PGEEError("PGEE information matrix is singular") from exc
    h = w * np.einsum("ij,jk,ik->i", x, inv, x, optimize=True)
    return info, inv, h


def firth_adjusted_score(X: np.ndarray, y: np.ndarray, beta: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return Firth/working-independence PGEE score and supporting matrices."""
    x, out = _as_design(X, y)
    b = np.asarray(beta, dtype=float)
    if b.shape != (x.shape[1],) or not np.isfinite(b).all():
        raise PGEEError("beta has invalid shape or values")
    mu = expit(x @ b)
    info, inv, h = _information_and_hat(x, mu)
    adjusted_residual = out - mu + h * (0.5 - mu)
    score = x.T @ adjusted_residual
    return score, info, inv, mu


def firth_penalized_loglikelihood(X: np.ndarray, y: np.ndarray, beta: np.ndarray) -> float:
    """Jeffreys-penalised logistic objective used only for deterministic line search."""
    x, out = _as_design(X, y)
    b = np.asarray(beta, dtype=float)
    eta = x @ b
    # stable Bernoulli log likelihood: y*eta - log(1+exp(eta))
    ll = float(np.sum(out * eta - np.logaddexp(0.0, eta)))
    mu = expit(eta)
    info, _, _ = _information_and_hat(x, mu)
    sign, logdet = np.linalg.slogdet(info)
    if sign <= 0 or not np.isfinite(logdet):
        raise PGEEError("PGEE information determinant is not positive")
    return ll + 0.5 * float(logdet)


def _solve_firth_pgee_independence(
    X: np.ndarray,
    y: np.ndarray,
    *,
    tolerance: float,
    max_iterations: int,
    max_step_halvings: int,
) -> _PGEESolverDiagnostics:
    """Solve the Firth-type PGEE and retain deterministic solver diagnostics."""
    x, out = _as_design(X, y)
    if tolerance <= 0 or max_iterations <= 0 or max_step_halvings < 0:
        raise PGEEError("Invalid PGEE solver controls")
    beta = np.zeros(x.shape[1], dtype=float)
    objective = firth_penalized_loglikelihood(x, out, beta)
    last_score = np.inf
    total_halvings = 0
    max_halvings_used = 0
    for iteration in range(1, max_iterations + 1):
        score, info, _, _ = firth_adjusted_score(x, out, beta)
        last_score = float(np.max(np.abs(score)))
        if last_score <= tolerance:
            return _PGEESolverDiagnostics(
                beta, iteration - 1, last_score, objective, total_halvings, max_halvings_used
            )
        try:
            step = np.linalg.solve(info, score)
        except np.linalg.LinAlgError as exc:
            raise PGEEError("PGEE scoring step could not be solved") from exc
        accepted = False
        scale = 1.0
        halvings_used = 0
        for attempt in range(max_step_halvings + 1):
            candidate = beta + scale * step
            try:
                candidate_obj = firth_penalized_loglikelihood(x, out, candidate)
            except PGEEError:
                candidate_obj = -np.inf
            if np.isfinite(candidate_obj) and candidate_obj >= objective - 1e-12:
                beta = candidate
                objective = candidate_obj
                accepted = True
                halvings_used = attempt
                break
            scale *= 0.5
        if not accepted:
            raise PGEEError("PGEE line search failed before convergence")
        total_halvings += halvings_used
        max_halvings_used = max(max_halvings_used, halvings_used)
        if float(np.max(np.abs(scale * step))) <= tolerance:
            score, _, _, _ = firth_adjusted_score(x, out, beta)
            last_score = float(np.max(np.abs(score)))
            if last_score <= max(tolerance, 1e-7):
                return _PGEESolverDiagnostics(
                    beta, iteration, last_score, objective, total_halvings, max_halvings_used
                )
    raise PGEEError(
        f"PGEE failed to converge in {max_iterations} iterations; max|score|={last_score:.6g}"
    )


def fit_firth_pgee_independence(
    X: np.ndarray,
    y: np.ndarray,
    *,
    tolerance: float,
    max_iterations: int,
    max_step_halvings: int,
) -> tuple[np.ndarray, int, float, float]:
    """Public coefficient-reference interface for the qualified Firth-type PGEE solver.

    The return contract remains coefficient-focused for independent-reference tests.
    Production diagnostics are captured by the full PGEE result.
    """
    solved = _solve_firth_pgee_independence(
        X, y, tolerance=tolerance, max_iterations=max_iterations,
        max_step_halvings=max_step_halvings,
    )
    return (
        solved.coefficients.copy(), solved.iterations, solved.score_max_abs,
        solved.penalized_loglikelihood,
    )


def morel_bokossa_neerchal_covariance(
    X: np.ndarray,
    y: np.ndarray,
    clusters: Iterable[object],
    beta: np.ndarray,
) -> tuple[np.ndarray, float, float, float]:
    """Morel--Bokossa--Neerchal corrected cluster sandwich at the PGEE root.

    This follows the published/``geefirth`` construction: cluster score
    contributions are centred, the finite-sample multiplicative factor is
    applied to the meat, and the Morel additive design-effect term is added to
    guarantee a full-rank covariance when the model-based bread is positive
    definite.
    """
    x, out = _as_design(X, y)
    ids = np.asarray(list(clusters), dtype=object)
    if ids.shape != (x.shape[0],):
        raise PGEEError("Cluster vector does not align with PGEE observations")
    b = np.asarray(beta, dtype=float)
    if b.shape != (x.shape[1],):
        raise PGEEError("beta does not align with PGEE design")
    unique = pd.unique(pd.Series(ids, dtype="object"))
    n_clusters = len(unique)
    n_obs, p = x.shape
    if n_clusters <= p:
        raise PGEEError("Morel covariance requires number of clusters > design dimension")
    if n_obs <= p or n_clusters <= 1:
        raise PGEEError("Morel covariance finite-sample factors are undefined")

    mu = expit(x @ b)
    _, bread, _ = _information_and_hat(x, mu)
    residual = out - mu
    cluster_scores = []
    for cluster in unique:
        mask = ids == cluster
        cluster_scores.append(x[mask].T @ residual[mask])
    score_matrix = np.vstack(cluster_scores)
    centred = score_matrix - score_matrix.mean(axis=0, keepdims=True)
    meat_raw = centred.T @ centred
    scale = (n_clusters / (n_clusters - 1.0)) * ((n_obs - 1.0) / (n_obs - p))
    meat = scale * meat_raw
    design_effect = max(1.0, float(np.trace(bread @ meat) / p))
    delta = min(0.5, float(p / (n_clusters - p)))
    covariance = bread @ meat @ bread + design_effect * delta * bread
    covariance = 0.5 * (covariance + covariance.T)
    if not np.isfinite(covariance).all():
        raise PGEEError("Morel covariance contains non-finite values")
    eig = np.linalg.eigvalsh(covariance)
    if float(eig.min()) <= 0.0:
        raise PGEEError("Morel covariance is not positive definite")
    return covariance, float(scale), float(delta), float(design_effect)


def fit_pgee_with_morel_standard_normal_inference(
    X: np.ndarray,
    y: np.ndarray,
    clusters: Iterable[object],
    *,
    alpha: float,
    tolerance: float,
    max_iterations: int,
    max_step_halvings: int,
) -> PGEEResult:
    """Fit Firth-type PGEE with MBN covariance and standard-normal Wald inference.

    No finite degrees-of-freedom quantity exists in this production result.
    """
    x, out = _as_design(X, y)
    ids = np.asarray(list(clusters), dtype=object)
    if ids.shape != (len(out),):
        raise PGEEError("Cluster vector does not align with observations")
    if not 0.0 < alpha < 1.0:
        raise PGEEError("alpha must lie strictly between 0 and 1")
    solved = _solve_firth_pgee_independence(
        x, out, tolerance=tolerance, max_iterations=max_iterations,
        max_step_halvings=max_step_halvings,
    )
    beta = solved.coefficients
    covariance, scale, delta, design_effect = morel_bokossa_neerchal_covariance(
        x, out, ids, beta
    )
    se = np.sqrt(np.diag(covariance))
    if np.any(se <= 0.0) or not np.isfinite(se).all():
        raise PGEEError("PGEE corrected standard errors are non-positive or non-finite")
    zstat = beta / se
    pvals = 2.0 * norm.sf(np.abs(zstat))
    critical = float(norm.ppf(1.0 - alpha / 2.0))
    low = beta - critical * se
    high = beta + critical * se
    arrays = (beta, covariance, se, zstat, pvals, low, high)
    if not all(np.isfinite(a).all() for a in arrays):
        raise PGEEError("PGEE inference produced non-finite quantities")
    n_clusters = int(pd.Series(ids).nunique())
    p = int(x.shape[1])
    return PGEEResult(
        coefficients=beta.copy(), covariance=covariance.copy(), standard_errors=se,
        wald_z=zstat, standard_normal_p=pvals, standard_normal_ci_low=low,
        standard_normal_ci_high=high, converged=True, iterations=solved.iterations,
        score_max_abs=solved.score_max_abs,
        penalized_loglikelihood=solved.penalized_loglikelihood,
        n_observations=int(len(out)), n_clusters=n_clusters, design_dimension=p,
        covariance_scale_factor=scale, covariance_delta=delta,
        covariance_design_effect=design_effect, solver_tolerance=float(tolerance),
        solver_max_iterations=int(max_iterations),
        solver_max_step_halvings=int(max_step_halvings),
        step_halvings_total=int(solved.step_halvings_total),
        step_halvings_max_used=int(solved.step_halvings_max_used),
    )


def separation_diagnostics(
    frame: pd.DataFrame,
    design_matrix: pd.DataFrame,
    outcome: pd.Series,
    clusters: pd.Series,
    *,
    factor_fields: Iterable[str] = ("month", "year", "parent_code"),
) -> SeparationDiagnostics:
    """Return exact RQ3 outcome-support diagnostics without threshold labelling.

    Factor levels are reported by observed counts of Y=1 and Y=0.  Complete
    separation is the exact structural condition that one outcome state is
    absent.  No arbitrary prevalence threshold is used to define a second
    category such as ``near separation`` and these diagnostics have no
    variable-selection authority.
    """
    y = pd.Series(outcome).astype(int).reset_index(drop=True)
    ids = pd.Series(clusters).astype(str).reset_index(drop=True)
    if len(frame) != len(y) or len(design_matrix) != len(y) or len(ids) != len(y):
        raise PGEEError("Separation diagnostic inputs are misaligned")
    if not y.isin([0, 1]).all():
        raise PGEEError("Separation diagnostic outcome must be binary 0/1")

    rows: list[dict[str, object]] = []
    complete_levels: list[str] = []
    for field in factor_fields:
        if field not in frame.columns:
            raise PGEEError(f"Missing diagnostic factor field: {field}")
        values = frame[field].reset_index(drop=True)
        levels = list(pd.unique(values))
        try:
            levels = sorted(levels)
        except TypeError:
            levels = sorted(levels, key=str)
        for level in levels:
            mask = values.eq(level)
            n = int(mask.sum())
            y1 = int(y[mask].sum())
            y0 = n - y1
            complete = bool(y1 == 0 or y0 == 0)
            if complete:
                complete_levels.append(f"{field}={level}")
            rows.append({
                "factor": str(field),
                "level": level,
                "n": n,
                "y1": y1,
                "y0": y0,
                "prevalence_y1": float(y1 / n),
                "complete_separation": complete,
            })

    cluster_table = (
        pd.DataFrame({"cluster": ids, "y": y})
        .groupby("cluster", sort=True, observed=True)["y"]
        .agg(["size", "sum"])
        .rename(columns={"size": "n", "sum": "y1"})
        .reset_index()
    )
    cluster_table["y1"] = cluster_table["y1"].astype(int)
    cluster_table["n"] = cluster_table["n"].astype(int)
    cluster_table["y0"] = cluster_table["n"] - cluster_table["y1"]
    cluster_table["all_y1"] = cluster_table["y0"].eq(0)
    cluster_table["all_y0"] = cluster_table["y1"].eq(0)
    X = np.asarray(design_matrix, dtype=float)
    return SeparationDiagnostics(
        outcome_n=int(len(y)),
        outcome_y1=int(y.sum()),
        outcome_y0=int(len(y) - y.sum()),
        outcome_prevalence_y1=float(y.mean()),
        complete_separation_levels=tuple(complete_levels),
        all_y1_clusters=int(cluster_table["all_y1"].sum()),
        all_y0_clusters=int(cluster_table["all_y0"].sum()),
        cluster_size_min=int(cluster_table["n"].min()),
        cluster_size_median=float(cluster_table["n"].median()),
        cluster_size_mean=float(cluster_table["n"].mean()),
        cluster_size_max=int(cluster_table["n"].max()),
        design_rank=int(np.linalg.matrix_rank(X)),
        design_columns=int(X.shape[1]),
        level_table=pd.DataFrame(rows),
        cluster_table=cluster_table,
    )

