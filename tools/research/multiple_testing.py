"""Deterministic research statistics. Definitions and limitations: docs/v8/phase9-strategy-authority.md.

Input columns are ALL candidates' daily, cost-corrected returns on a common window.
Missing observations are not zero returns. No method changes deployment authority.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from statistics import NormalDist

import numpy as np

VERSION = "v8.multiple-testing/1"
UNAVAILABLE = "UNAVAILABLE_INSUFFICIENT_DATA"
NORMAL = NormalDist()


def seed(provenance):
    return int.from_bytes(hashlib.sha256(json.dumps(provenance, sort_keys=True, separators=(",", ":"),
                                                   allow_nan=False).encode()).digest()[:8], "big")


def unavailable(reason):
    return {"status": UNAVAILABLE, "reason": reason}


def dsr(returns, trials, trial_sharpe_variance, complete=False):
    """Bailey/Lopez de Prado (2014), daily SR, Pearson kurtosis (excess + 3).

    Across-trial Sharpe variance must be supplied; ordinary Sharpe is not a substitute.
    Incomplete census or unavailable historical trial returns block authority upstream.
    """
    x = np.asarray(returns, float)
    if x.ndim != 1 or len(x) < 3 or not np.isfinite(x).all() or x.std(ddof=1) <= 0:
        return unavailable("nondegenerate finite return series required")
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ValueError("positive integer trial count required")
    if trial_sharpe_variance is None or not math.isfinite(trial_sharpe_variance) or trial_sharpe_variance <= 0:
        return unavailable("across-trial Sharpe variance unavailable")
    sr = float(x.mean() / x.std(ddof=1))
    z = (x - x.mean()) / x.std(ddof=0)
    skew, kurt = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    g = 0.5772156649015329
    maximum = 0.0 if trials == 1 else math.sqrt(trial_sharpe_variance) * (
        (1 - g) * NORMAL.inv_cdf(1 - 1 / trials) + g * NORMAL.inv_cdf(1 - 1 / (trials * math.e)))
    variance = 1 - skew * sr + (kurt - 1) * sr * sr / 4
    if variance <= 0:
        return unavailable("nonpositive Sharpe variance")
    return {"status": "AVAILABLE", "observed_sharpe": sr, "sample_length": len(x), "skew": skew,
            "excess_kurtosis": kurt - 3, "expected_maximum_sharpe": maximum,
            "probability": NORMAL.cdf((sr - maximum) * math.sqrt((len(x) - 1) / variance)),
            "trial_count": trials, "trial_count_complete": complete,
            "trial_sharpe_variance": trial_sharpe_variance}


def fdr(pvalues):
    p = np.asarray(pvalues, float)
    if p.ndim != 1 or not len(p) or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
        raise ValueError("finite p-values in [0,1] required for every hypothesis")
    n = len(p)
    order = np.argsort(p, kind="stable")
    bh = np.minimum.accumulate((p[order] * n / np.arange(1, n + 1))[::-1])[::-1].clip(0, 1)
    by = (bh * sum(1 / i for i in range(1, n + 1))).clip(0, 1)
    out_bh, out_by = np.empty(n), np.empty(n)
    out_bh[order], out_by[order] = bh, by
    return {"raw_p": p.tolist(), "bh_q": out_bh.tolist(), "by_q": out_by.tolist(), "hypotheses": n}


def circular_indices(n, block, rng):
    if n < 1 or block < 1 or block > n:
        raise ValueError("invalid circular block size")
    starts = rng.integers(0, n, size=math.ceil(n / block))
    return ((starts[:, None] + np.arange(block)) % n).ravel()[:n]


def bootstrap_tests(returns, provenance, replications=5000, block=7, indices=None):
    """White RC and studentized Hansen SPA, consistent negative-mean recentering.

    Circular blocks preserve within-block serial dependence and cross-strategy dependence.
    The same sampled indices apply to all columns. Long-run variance is the circular
    block-bootstrap variance of sqrt(T) means; never the iid standard error.
    Plus-one Monte Carlo p-values avoid a claimed probability of zero.
    Optional explicit indices support independent finite-enumeration reference tests.
    """
    x = np.asarray(returns, float)
    if x.ndim != 2 or len(x) < max(28, block * 4) or x.shape[1] < 2 or not np.isfinite(x).all():
        return unavailable("finite common daily window, >=28 days and >=2 candidates required")
    if replications < 2:
        raise ValueError("at least two bootstrap replications")
    n, m = x.shape
    mu = x.mean(axis=0)
    rng = np.random.default_rng(seed(provenance))
    if indices is not None:
        indices = np.asarray(indices)
        if indices.ndim != 2 or indices.shape[1] != n or (indices < 0).any() or (indices >= n).any():
            raise ValueError("invalid bootstrap indices")
        replications = len(indices)
    means = np.empty((replications, m))
    for i in range(replications):
        ix = circular_indices(n, block, rng) if indices is None else indices[i]
        means[i] = x[ix].mean(axis=0)
    centered = math.sqrt(n) * (means - mu)
    omega = centered.std(axis=0, ddof=1)
    if (omega <= 1e-12).any():
        return unavailable("zero long-run variance in a candidate; family test not silently reduced")
    obs_rc = max(0.0, float(math.sqrt(n) * mu.max()))
    rc_dist = np.maximum(0, centered.max(axis=1))
    z = math.sqrt(n) * mu / omega
    # Hansen's consistent recentering retains the means of clearly inferior alternatives.
    inferior = z < -math.sqrt(2 * math.log(math.log(n)))
    recenter = np.where(inferior, math.sqrt(n) * mu, 0)
    spa_dist = np.maximum(0, ((centered + recenter) / omega).max(axis=1))
    obs_spa = max(0.0, float(z.max()))
    raw = ((centered >= math.sqrt(n) * mu).sum(axis=0) + 1) / (replications + 1)
    return {"status": "AVAILABLE", "white_rc_p": float((1 + (rc_dist >= obs_rc).sum()) / (replications + 1)),
            "hansen_spa_p": float((1 + (spa_dist >= obs_spa).sum()) / (replications + 1)),
            "raw_p": raw.tolist(), "long_run_sd": omega.tolist(), "inferior_recentered": inferior.tolist(),
            "white_statistic": obs_rc, "spa_statistic": obs_spa, "replications": replications,
            "block_days": block, "bootstrap": "circular", "seed": seed(provenance),
            "candidate_count": m, "days": n, "fdr": fdr(raw)}


def pbo(returns, names, segments=16, min_segment_days=14):
    """Full CSCV combinations of chronological blocks, SR selection, average OOS ties.

    No iid trade shuffle. All columns must have a common finite daily window.
    Zero-variance split scores make PBO unavailable, rather than dropping a competitor.
    """
    x = np.asarray(returns, float)
    if segments < 2 or segments % 2 or min_segment_days < 1:
        raise ValueError("positive even segments and positive minimum length required")
    if x.ndim != 2 or x.shape[1] < 2 or len(names) != x.shape[1] or len(set(names)) != len(names):
        return unavailable("at least two distinct candidate columns required")
    if len(x) < segments * min_segment_days or not np.isfinite(x).all():
        return unavailable("not enough finite daily observations for chronological segments")
    blocks = np.array_split(np.arange(len(x)), segments)
    rows = []
    for train in itertools.combinations(range(segments), segments // 2):
        test = [k for k in range(segments) if k not in train]
        a, b = x[np.concatenate([blocks[k] for k in train])], x[np.concatenate([blocks[k] for k in test])]
        sa, sb = a.std(axis=0, ddof=1), b.std(axis=0, ddof=1)
        if (sa <= 0).any() or (sb <= 0).any():
            return unavailable("zero variance in CSCV split")
        ia, ib = a.mean(axis=0) / sa, b.mean(axis=0) / sb
        winner = int(np.argmax(ia))  # canonical column order breaks equal IS scores
        rank = float((ib < ib[winner]).sum() + ((ib == ib[winner]).sum() + 1) / 2)
        omega = rank / (x.shape[1] + 1)
        rows.append({"train_segments": list(train), "selected_strategy": names[winner],
                     "test_rank": rank, "lambda": math.log(omega / (1 - omega))})
    return {"status": "AVAILABLE", "segments": segments, "combinations": len(rows), "splits": rows,
            "pbo": sum(r["lambda"] <= 0 for r in rows) / len(rows), "days": len(x)}
