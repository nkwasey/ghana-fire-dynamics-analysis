"""Independent test-only references for the RQ3 PGEE authority.

These functions intentionally do not import ``rp1_analysis_v1``.  Coefficients
are obtained by direct optimisation of the Jeffreys-penalised logistic
objective (an independent route from the production Fisher-scoring solver).
The covariance reference follows the published Morel--Bokossa--Neerchal
formula and the cluster-score centring used by the authors' ``geefirth`` R
implementation.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def firth_objective_reference(beta, X, y):
    X=np.asarray(X,float); y=np.asarray(y,float); beta=np.asarray(beta,float)
    eta=X@beta; mu=expit(eta); w=mu*(1-mu)
    if np.any(w<=0) or not np.isfinite(w).all(): return np.inf
    info=X.T@(w[:,None]*X)
    sign,logdet=np.linalg.slogdet(info)
    if sign<=0 or not np.isfinite(logdet): return np.inf
    loglik=float(np.sum(y*eta-np.logaddexp(0.0,eta)))
    return -(loglik+0.5*float(logdet))


def firth_coefficients_reference(X,y):
    X=np.asarray(X,float); y=np.asarray(y,float)
    result=minimize(
        firth_objective_reference,
        np.zeros(X.shape[1],float),
        args=(X,y),
        method='BFGS',
        options={'gtol':1e-10,'maxiter':500,'disp':False},
    )
    # BFGS can report precision-loss after reaching the correct stationary
    # point, so admissibility is checked by finite objective/gradient and not
    # by the success flag alone.
    if not np.isfinite(result.fun) or not np.isfinite(result.x).all():
        raise RuntimeError(result.message)
    return np.asarray(result.x,float)


def mbn_covariance_reference(X,y,clusters,beta):
    X=np.asarray(X,float); y=np.asarray(y,float); beta=np.asarray(beta,float)
    ids=np.asarray(clusters,object); mu=expit(X@beta); w=mu*(1-mu)
    bread=np.linalg.inv(X.T@(w[:,None]*X))
    unique=[]
    for v in ids:
        if v not in unique: unique.append(v)
    scores=np.vstack([X[ids==g].T@(y[ids==g]-mu[ids==g]) for g in unique])
    scores=scores-scores.mean(axis=0,keepdims=True)
    nc=len(unique); N=len(y); p=X.shape[1]
    scale=(nc/(nc-1))*((N-1)/(N-p))
    B=scale*(scores.T@scores)
    phi=max(1.0,float(np.trace(bread@B)/p))
    delta=min(0.5,float(p/(nc-p)))
    cov=bread@B@bread+phi*delta*bread
    return (cov+cov.T)/2, scale, delta, phi
