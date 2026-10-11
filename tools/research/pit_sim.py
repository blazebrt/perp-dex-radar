"""Point-in-time research engine (v8 Phase 8): the universe and costs a past trade could actually have known.

Universe  universe_panel(): for every time and asset, from the v8 history only (v8.pit): 1 eligible (an active
          perpetual on a venue that loaded, verified crypto identity, a KNOWN trade-DEX volume of at least min_vol),
          0 known not eligible, -1 unknown (no fresh observation, an unavailable venue, unknown liquidity). `complete`
          says whether every asset eligible then has candles in the panel: a cross-section with an eligible asset
          missing from the candles (a coin delisted before the market data was fetched) is not the universe of that
          time, so nothing traded then is authoritative.
Signals   corrected_feat(): the strategy's own eligibility (qstrat.Feat.elig) AND the point-in-time eligibility at
          the moment the bar closes - the strategies themselves are unchanged.
Trades    simulate(): the unchanged trade rules of qsim (exits depend on prices only), costs recomputed per trade
          with pit_cost (time-varying slippage at entry and at exit, observed funding, the governed fee schedule).
Qualify   qualify(): per trade - universe, identity, liquidity, funding, cost, fully_qualified - with the reason of
          every failed component. Unqualified trades are kept; only fully qualified ones enter the authoritative
          aggregate."""
from __future__ import annotations

import copy
import os
import sys

import numpy as np

import pit_cost as PC
import qsim

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from v8 import pit as PIT  # noqa: E402

VERSION = "v8.pit-research/1"
U_ELIGIBLE, U_NOT_ELIGIBLE, U_UNKNOWN = 1, 0, -1
ST_ACTIVE, ST_INACTIVE, ST_UNKNOWN = 1, 0, -1


def _obs_index(hist, times):
    """Index of the latest observation at or before each time, and whether it is fresh enough."""
    ht = np.asarray(hist.times, dtype=np.float64)
    i = np.searchsorted(ht, np.asarray(times, dtype=np.float64), side="right") - 1
    ii = np.where(i >= 0, i, 0)
    fresh = (i >= 0) & (np.asarray(times) - ht[ii] <= hist.max_staleness_s)
    return i, fresh


def _rl_codes(index, key, i, fresh, code_of):
    """Run-length lookup vectorised: code_of(value) in force at each observation index; -1 where nothing is known
    (no fresh observation, or none of this key yet)."""
    ix, vs = index.get(key, ((), ()))
    if not ix:
        return np.full(len(i), -1, dtype=np.int8)
    codes = np.array([code_of(v) for v in vs], dtype=np.int8)
    k = np.searchsorted(np.asarray(ix), i, side="right") - 1
    ok = fresh & (k >= 0)
    return np.where(ok, codes[np.where(ok, k, 0)], -1).astype(np.int8)


def _active_code(p):
    return {PIT.KNOWN_ACTIVE: 1, PIT.KNOWN_INACTIVE: 0}.get(p[0], -1)


def _crypto_code(r):
    if r[2] is None:                 # no identity state recorded then (v8.audit/1 and /2): unknown, never 0
        return -1
    return int(r[2] == PIT.VERIFIED_CRYPTO and r[1] == "CRYPTO")


def universe_panel(hist, times, coins, min_vol):
    """Point-in-time panels at the given decision times, for `coins` (columns):
        active    1 KNOWN_ACTIVE, 0 KNOWN_INACTIVE, -1 UNKNOWN
        crypto    1 verified crypto identity recorded then, 0 another identity, -1 unknown
        liq_gate  1 KNOWN trade-DEX volume >= min_vol, 0 known below it or not on a trade DEX, -1 unknown
        code      1 eligible (all three 1), 0 known not eligible, -1 unknown
        complete  [T] every asset eligible then (in the whole history, not only `coins`) has a column
        missing   [T] how many eligible assets have no column"""
    times = np.asarray(times, dtype=np.int64)
    T, N = len(times), len(coins)
    out = {k: np.full((T, N), -1, dtype=np.int8) for k in ("active", "crypto", "liq_gate", "code")}
    out["complete"] = np.zeros(T, dtype=bool)
    out["missing"] = np.zeros(T, dtype=np.int64)
    if hist is None or not hist.ok:
        return out
    i, fresh = _obs_index(hist, times)
    col = {c: j for j, c in enumerate(coins)}
    assets = sorted(set(hist._asset) | set(coins))
    vol, lst, _ = PC.liquidity_panel(hist, times, assets)
    for a_idx, a in enumerate(assets):
        st = _rl_codes(hist._asset, a, i, fresh, _active_code)
        crypto = _rl_codes(hist._ident, a, i, fresh, _crypto_code)
        lv, ls = vol[:, a_idx], lst[:, a_idx]
        gate = np.full(T, -1, dtype=np.int8)
        known = ls == PC.L_KNOWN
        gate[(ls == PC.L_NOT_ON_TRADE_DEX) | (known & (lv < min_vol))] = 0
        gate[known & (lv >= min_vol)] = 1
        c = np.full(T, U_UNKNOWN, dtype=np.int8)
        c[(st == 0) | ((st == 1) & (crypto == 0)) | ((st == 1) & (crypto == 1) & (gate == 0))] = U_NOT_ELIGIBLE
        yes = (st == 1) & (crypto == 1) & (gate == 1)
        c[yes] = U_ELIGIBLE
        if a in col:
            j = col[a]
            out["active"][:, j], out["crypto"][:, j], out["liq_gate"][:, j], out["code"][:, j] = st, crypto, gate, c
        else:
            out["missing"] += yes
    out["complete"] = fresh & (out["missing"] == 0)
    return out


def corrected_feat(F, p, hist, min_vol):
    """A copy of qstrat.Feat whose eligibility also requires point-in-time eligibility when each hourly bar closes
    (the moment a signal on it is known), plus the universe panel used."""
    t_known = p.t + p.bar                     # a signal on bar i is known at its close (the next bar's open)
    uni = universe_panel(hist, t_known, p.coins, min_vol)
    G = copy.copy(F)
    G.elig = F.elig & (uni["code"] == U_ELIGIBLE) & uni["complete"][:, None]
    uni["t_known"] = t_known
    return G, uni


def simulate(p, sig):
    """Trades by the unchanged qsim rules with no costs (exits depend on prices only): (signals, results)."""
    order = np.lexsort((sig["j"], sig["i"]))
    s = {k: np.asarray(v)[order] for k, v in sig.items()}
    if len(s["i"]) == 0:
        return s, np.zeros((0, qsim.NCOL))
    z = np.zeros_like(p.c)
    res = qsim.sim_batch(p.o, p.h, p.l, p.c, z, np.zeros(p.N), s["i"].astype(np.int64), s["j"].astype(np.int64),
                         s["d"].astype(np.float64), s["stop"].astype(np.float64), s["target"].astype(np.float64),
                         s["trail"].astype(np.float64), s["be"].astype(np.float64), s["hold"].astype(np.int64),
                         True, 0.0, 0.0)
    taken = ~np.isnan(res[:, qsim.R_EXIT])
    return {k: v[taken] for k, v in s.items()}, res[taken]


def qualify(p, s, res, uni, slip_pt, frate, fstate, scen=None):
    """Per-trade point-in-time costs and qualification for qsim trades. Returns a dict of arrays."""
    n = len(res)
    if n == 0:
        return {"n": 0}
    i0 = s["i"].astype(np.int64) + 1
    ex = res[:, qsim.R_EXIT].astype(np.int64)
    j = s["j"].astype(np.int64)
    d = s["d"].astype(float)
    stop = res[:, qsim.R_STOPP]
    gross = res[:, qsim.R_GROSS] * stop                     # fraction of notional
    target = res[:, qsim.R_REASON].astype(int) == 1
    c = PC.trade_costs(i0, ex, j, d, target, slip_pt, frate, fstate, scen)
    si = s["i"].astype(np.int64)
    code = uni["code"][si, j]
    complete = uni["complete"][si]
    q = {"n": n, "t_entry": p.t[i0], "t_exit": p.t[ex] + p.bar, "j": j, "d": d, "gross_ret": gross, "stop": stop,
         "universe_code": code, "universe_complete": complete,
         "universe_ok": (uni["active"][si, j] == 1) & complete,
         "identity_ok": uni["crypto"][si, j] == 1,
         "liquidity_ok": (uni["liq_gate"][si, j] == 1) & c["liquidity_known"],
         "funding_ok": c["funding_known"]}
    q["cost_ok"] = c["liquidity_known"] & q["funding_ok"]
    q["closed"] = res[:, qsim.R_REASON].astype(int) != qsim.REASONS.index("end")     # still open when data ends
    q["fully_qualified"] = q["universe_ok"] & q["identity_ok"] & q["liquidity_ok"] & q["cost_ok"]
    q.update({k: c[k] for k in ("fee", "slip_entry", "slip_exit", "slippage", "funding", "cost",
                                "funding_missing_bars", "scenario_funding")})
    with np.errstate(invalid="ignore"):
        q["net_ret"] = gross - c["cost"]
        q["net_R"] = q["net_ret"] / stop
    return q


def reasons(q, hist):
    """Why trades are not fully qualified: {component: {reason: count}}."""
    out = {"universe": {}, "identity": {}, "liquidity": {}, "funding": {}}
    if not q.get("n"):
        return out
    start = hist.times[0] if hist is not None and hist.ok and hist.times else None

    def add(comp, r):
        out[comp][r] = out[comp].get(r, 0) + 1

    for k in range(q["n"]):
        t = q["t_entry"][k]
        before = start is None or t < start
        why_hist = "NO_VERIFIED_HISTORY" if start is None else "BEFORE_PIT_HISTORY"
        if not q["universe_ok"][k]:
            add("universe", why_hist if before else ("PIT_UNIVERSE_CANDLES_MISSING" if not q["universe_complete"][k]
                                                     else "NOT_ACTIVE_OR_UNKNOWN_THEN"))
        if not q["identity_ok"][k]:
            add("identity", why_hist if before else "IDENTITY_NOT_VERIFIED_CRYPTO_OR_UNKNOWN_THEN")
        if not q["liquidity_ok"][k]:
            add("liquidity", why_hist if before else "LIQUIDITY_HISTORY_UNKNOWN_OR_BELOW_GATE")
        if not q["funding_ok"][k]:
            add("funding", "FUNDING_HISTORY_GAP")
    return out


def aggregate(q, mask=None):
    """Authoritative aggregate over fully qualified CLOSED trades (or `mask`, closed ones): n, mean net R, win rate,
    mean cost. A trade still open when the data ends is never in an aggregate (as qstats.stats)."""
    if not q.get("n"):
        return {"n": 0}
    m = (q["fully_qualified"] if mask is None else mask) & q.get("closed", True)
    n = int(m.sum())
    if n == 0:
        return {"n": 0}
    r = q["net_R"][m]
    return {"n": n, "avg_R": round(float(np.mean(r)), 4), "win": round(float(np.mean(r > 0)), 4),
            "sum_R": round(float(np.sum(r)), 3), "avg_cost": round(float(np.mean(q["cost"][m])), 6),
            "avg_slippage": round(float(np.mean(q["slippage"][m])), 6),
            "avg_funding": round(float(np.mean(q["funding"][m])), 6)}
