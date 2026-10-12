"""Corrected, point-in-time research (v8 Phase 8): the legacy research next to what can actually be qualified.

    python tools/research/pit_research.py --md md --history hist [--cutoff UNIX] --out research_pit.json [--text]

`md` is an export of the market-data branch, `hist` an export of the v8-history branch (a folder holding obs/).
Nothing here overwrites quant_research.json or picks_research.json, promotes anything or changes a live engine.

Legacy results (qexport / picks_export rules: today's coin list, today's volume as the slippage of every past trade,
assumed funding, a fixed 0.19% for the coin picks) are reported as LEGACY_SURVIVORSHIP_UNQUALIFIED. The corrected
path runs the same strategies and trade rules on the point-in-time universe (v8.pit) with point-in-time costs
(pit_cost) and qualifies every trade (pit_sim). Only fully qualified trades are authoritative; zero is a valid
answer. A scenario (unknown liquidity at the worst tier, missing funding at 0.01% per 8 hours) is labelled
SCENARIO / NOT AUTHORITY and never enters an authoritative number."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import pit_cost as PC  # noqa: E402
import pit_sim as PS  # noqa: E402
from v8 import history as VH  # noqa: E402
from v8 import pit as PIT  # noqa: E402
from v8 import shadow_ledger as SL  # noqa: E402

VERSION = "v8.pit-research/2"
LEGACY = "LEGACY_SURVIVORSHIP_UNQUALIFIED"
SCENARIO = "SCENARIO / NOT AUTHORITY"
MIN_VOL = 1_000_000          # the live quant and coin-picks execution gate (CFG min_dex_vol), applied at each time
QUANT = ("TSMOM", "TREND_EMA", "XSMOM")
CODE_FILES = ("tools/research/pit_research.py", "tools/research/pit_sim.py", "tools/research/pit_cost.py",
              "tools/research/qsim.py", "tools/research/qstrat.py", "tools/research/qind.py",
              "tools/research/qdata.py", "tools/research/pk_trades.py", "tools/research/pk_data.py",
              "tools/research/pk_score.py", "tools/research/pk_day.py", "tools/research/picks_export.py",
              "v8/pit.py", "v8/history.py")


def code_hash():
    h = hashlib.sha256()
    for f in CODE_FILES:
        with open(os.path.join(ROOT, f), "rb") as fh:
            h.update(f.encode() + b"\0" + hashlib.sha256(fh.read()).hexdigest().encode() + b"\n")
    return h.hexdigest()


def tree_hash(folder, max_files=20000):
    """sha256 over (relative path, sha256) of every file under a folder: the dataset's identity."""
    h, n = hashlib.sha256(), 0
    for d, _, fs in sorted(os.walk(folder)):
        for f in sorted(fs):
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                h.update(os.path.relpath(p, folder).replace(os.sep, "/").encode() + b"\0" +
                         hashlib.sha256(fh.read()).hexdigest().encode() + b"\n")
            n += 1
            if n >= max_files:
                break
    return h.hexdigest(), n


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=30).stdout.decode().strip() or None
    except Exception:  # noqa: BLE001
        return None


def _r(x, k=4):
    return None if x is None or not np.isfinite(x) else round(float(x), k)


# --------------------------------------------------------------------------- quant (qexport rules)
def quant(md, hist, cutoff, out):
    import qsim
    import qstats
    import qstrat
    from qdata import Panel
    from qexport import TESTED
    p = Panel(md, end=cutoff)
    F = qstrat.Feat(p)
    end1 = int(p.t[-1]) + 3600
    w0 = end1 - 365 * 86400
    frate, fstate, fsrc = PC.funding_panel(md, p.t, p.coins, cutoff=cutoff)
    scen = PC.scenario_funding(p.t, fstate)
    _, lst_pt, slip_pt, _ = PC.liquidity_panel(hist, p.t, p.coins)
    slip_scen = np.where(np.isfinite(slip_pt), slip_pt, max(s for _, s in PC.SLIP_TIERS))
    G, uni = PS.corrected_feat(F, p, hist, MIN_VOL)
    out["market_data_1h"] = {"start": int(p.t[0]), "end": end1, "coins": p.N, "window_1y": [w0, end1],
                             "funding_sources": {k: fsrc.count(k) for k in sorted(set(fsrc))},
                             "funding_bars": {PC.FUNDING_STATES[k]: int((fstate == k).sum()) for k in PC.FUNDING_STATES},
                             "legacy_assumed_funding_coins": sum(1 for s in p.fund_src if s == "assumed")}
    res = {}
    for sid in QUANT:
        fn, kw = TESTED[sid][0], TESTED[sid][1]
        # legacy: exactly qexport's one-year run
        sig = fn(F, **kw)
        keep = p.t[sig["i"]] + 3600 >= w0
        sig = {k: v[keep] for k, v in sig.items()}
        s, r, tw = qsim.run(p, sig, elig=F.elig)
        d1 = qstats.table(p, s, r, tw, sid)
        leg = qstats.stats(d1, w0, end1)
        lq = PS.qualify(p, s, r, uni, slip_pt, frate, fstate, scen, lst_pt) if len(r) else {"n": 0}
        # corrected: point-in-time eligibility, unchanged rules, point-in-time costs
        sig2 = fn(G, **kw)
        keep = p.t[sig2["i"]] + 3600 >= w0
        sig2 = {k: v[keep] for k, v in sig2.items()}
        s2, r2 = PS.simulate(p, sig2)
        q = PS.qualify(p, s2, r2, uni, slip_pt, frate, fstate, scen, lst_pt)
        sc = PS.qualify(p, s2, r2, uni, slip_scen, frate + scen, np.where(fstate == PC.F_MISSING, PC.F_NOT_DUE, fstate))
        res[sid] = {
            "params": kw,
            "legacy": {"label": LEGACY, "trades": int(leg.get("n") or 0), "avg_R": _r(leg.get("avg")),
                       "win": _r(leg.get("wr")), "cost_R": _r(leg.get("cost")),
                       "qualification_of_legacy_trades": _counts(lq),
                       "why_not_qualified": PS.reasons(lq, hist)},
            "corrected": {"trades": int(q.get("n", 0)),
                          "fully_qualified": int((q["fully_qualified"] & q["closed"]).sum()) if q.get("n") else 0,
                          "components": _counts(q), "why_not_qualified": PS.reasons(q, hist),
                          "authoritative": PS.aggregate(q)},
            "scenario": {"label": SCENARIO, "note": "unknown liquidity at the worst tier, missing funding at 0.01% "
                                                     "per 8 hours; the point-in-time universe still applies",
                         "aggregate": PS.aggregate(sc, sc.get("universe_ok", np.zeros(0, bool)) &
                                                   sc.get("identity_ok", np.zeros(0, bool)))
                         if sc.get("n") else {"n": 0}},
        }
    return res


def _counts(q):
    if not q.get("n"):
        return {"n": 0}
    out = {"n": int(q["n"]), **{k: int(np.sum(q[k])) for k in ("universe_ok", "identity_ok", "liquidity_ok",
                                                                "funding_ok", "cost_ok", "fully_qualified")}}
    out["open_at_data_end"] = int(np.sum(~np.asarray(q.get("closed", np.ones(q["n"], bool)))))
    out["fully_qualified_closed"] = int(np.sum(q["fully_qualified"] & q.get("closed", True)))
    return out


# --------------------------------------------------------------------------- coin picks (picks_export / pk_day rules)
def _stop_dist(atr, c, k_stop, min_sd, max_sd):
    """pk_trades.sim's stop distance (fraction of the entry): k_stop ATR, bounded."""
    with np.errstate(all="ignore"):
        return np.minimum(np.maximum(k_stop * atr / c, min_sd), max_sd)


def _pk_qualify(uni, slip, R_legacy, RET_legacy, BARS, side, cost_legacy, sd_all, t_bar, frate_d, fmiss_d, mask,
                horizon, liq_state=None):
    """Point-in-time re-costing of pk_trades rows (k, j): entry at bar k+1 open, exit in bar k+BARS. The rows are
    exactly `mask` (a governed selection surface); costs and qualification change, the selection never does. A row
    is closed when its exit is known: its holding limit (`horizon` bars) ends inside the data, or it exited before the
    last bar. pk_trades.sim closes a trade still open at the last bar at that close: such a row (an exit on the last
    bar before its limit) is open at the data end and never in an authoritative aggregate."""
    K, N = R_legacy.shape
    kk, jj = np.where(mask & np.isfinite(R_legacy) & np.isfinite(BARS))
    if len(kk) == 0:
        return {"n": 0}
    i_ex = (kk + BARS[kk, jj]).astype(np.int64)
    ok = (kk + 1 < K) & (i_ex < K)
    kk, jj, i_ex = kk[ok], jj[ok], i_ex[ok]
    se, sx = slip[kk + 1, jj], slip[i_ex, jj]          # the slippage known at the entry bar's and exit bar's open
    cr = np.cumsum(np.vstack([np.zeros((1, N)), frate_d]), axis=0)
    cm = np.cumsum(np.vstack([np.zeros((1, N)), fmiss_d.astype(float)]), axis=0)
    fsum = cr[i_ex + 1, jj] - cr[kk + 1, jj]
    fmiss = cm[i_ex + 1, jj] - cm[kk + 1, jj]
    gross = RET_legacy[kk, jj] + cost_legacy
    sd = sd_all[kk, jj]
    cost = 2 * PC.FEE_SCHEDULE["taker"] + se + sx + side * fsum
    q = {"n": len(kk), "t_entry": t_bar[kk + 1],
         "universe_code": uni["code"][kk, jj], "universe_complete": uni["complete"][kk],
         "universe_ok": (uni["active"][kk, jj] == 1) & uni["complete"][kk],
         "identity_ok": uni["crypto"][kk, jj] == 1,
         "liquidity_ok": (uni["liq_gate"][kk, jj] == 1) & np.isfinite(se) & np.isfinite(sx),
         "funding_ok": fmiss == 0}
    q["cost_ok"] = np.isfinite(se) & np.isfinite(sx) & q["funding_ok"]
    q["fully_qualified"] = q["universe_ok"] & q["identity_ok"] & q["liquidity_ok"] & q["cost_ok"]
    with np.errstate(invalid="ignore", divide="ignore"):
        q["net_ret"] = gross - cost
        q["net_R"] = q["net_ret"] / sd
    closed = (kk + horizon <= K - 1) | (i_ex < K - 1)
    q.update(cost=cost, slippage=se + sx, funding=side * fsum, closed=closed, k=kk, j=jj)
    if liq_state is not None:
        g = uni["liq_gate"][kk, jj]
        q["liq_reason"] = [None if ok else PS.liquidity_reason(int(g[n]), int(liq_state[kk[n] + 1, jj[n]]),
                                                               int(liq_state[i_ex[n], jj[n]]))
                           for n, ok in enumerate(q["liquidity_ok"])]
    return q


def _daily_panel(md, cutoff):
    """pk_data.daily_panel with no candle after the cutoff (the same bars, eligibility, 4h trend and funding)."""
    import qind as I
    import qstrat
    from pk_data import DAYB
    from qdata import Panel, resample
    p = Panel(md, folder="h4", bar=14400, min_hours=24 * 60, end=cutoff)
    F = qstrat.Feat(p)
    t, o, h, l, c, v, end = resample(p, DAYB)
    elig = F.elig[end]
    e20, e100 = I.ema(p.c, 20), I.ema(p.c, 100)
    with np.errstate(all="ignore"):
        trend4h = (e20 / e100 - 1)[end]
    f = p.fund
    K = len(end)
    fund_d = np.zeros((K, p.N))
    for k in range(K):
        a = end[k] - DAYB + 1
        fund_d[k] = f[a:end[k] + 1].sum(axis=0)
    return p, {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "elig": elig, "trend4h": trend4h, "fund": fund_d,
               "coins": p.coins, "end": end}


DIAGNOSTIC = "DIAGNOSTIC / NOT DAY STRATEGY AUTHORITY"
SWING_DIAGNOSTIC = "DIAGNOSTIC / NOT SWING STRATEGY AUTHORITY"
MIN_BAND_ROWS = 30           # picks_export.band_stats and pk_day report a band of 30+ rows only
READY_BAND = (80, 101)       # the swing "ready" band: the 80-90 and 90+ rows together, reported on its own
SWING_HOLD = 30              # the swing trade's holding limit in days (picks_export / pk_trades.sim)


def _legacy_rows(R, RET, m):
    """picks_export / pk_day row statistics of one selection surface (net of the legacy fixed cost)."""
    if not m.any():
        return {"n": 0}
    return {"n": int(m.sum()), "R": _r(np.nanmean(R[m])), "ret": _r(np.nanmean(RET[m])),
            "win": _r(float(np.mean(RET[m] > 0)))}


def _corrected(q, hist):
    return {"components": _counts(q), "why_not_qualified": PS.reasons(q, hist), "authoritative": PS.aggregate(q)}


def _diagnostic(q, hist):
    """A diagnostic surface (not the strategy's selection): the same qualification, its aggregate never authoritative."""
    return {"components": _counts(q), "why_not_qualified": PS.reasons(q, hist), "aggregate": PS.aggregate(q)}


def _top5_corrected(q, top):
    """The corrected Top 5: a 4-hour sample is authoritative only when all five picks are fully qualified and closed."""
    if not top:
        return {"samples": 0, "qualified_samples": 0, "authoritative": {"n": 0}}
    by = {}
    if q.get("n"):
        for n in range(q["n"]):
            by[(int(q["k"][n]), int(q["j"][n]))] = n
    per = []
    for k, pk, _ in top:
        rows = [by.get((int(k), int(j))) for j in pk]
        if all(r is not None and q["fully_qualified"][r] and q["closed"][r] for r in rows):
            per.append(float(np.mean([q["net_R"][r] for r in rows])))
    agg = {"n": len(per), "avg_R": _r(float(np.mean(per)))} if per else {"n": 0}
    return {"samples": len(top), "qualified_samples": len(per), "pick_rows": 5 * len(top), "authoritative": agg}


def _rows_mask(shape, top):
    m = np.zeros(shape, dtype=bool)
    for k, pk, _ in top:
        m[k, pk] = True
    return m


def day_research(md, hist, cutoff, swing_t, swing_coins, SL, SS):
    """Corrected day-pick research on the day-pick selection authority itself (pk_day.surfaces: DAY_W over
    day_checks, the swing score mapped to each hour, the 4-hour sample, the score bands, the deterministic Top 5).
    Legacy: pk_day's own surfaces (its eligibility, the fixed cost). Corrected: the same surfaces selected on the
    strategy's eligibility AND point-in-time eligibility when each hour closes, every selected row re-costed and
    qualified. Returns (report, legacy surfaces, corrected surfaces, qualifications)."""
    import pk_day
    from pk_trades import COST
    ph, Fh, xh = pk_day.hourly(md, end=cutoff)
    if ph.T <= pk_day.FIRST + pk_day.HOLD:
        return {"status": "INSUFFICIENT_MARKET_DATA", "hours": int(ph.T)}, {}, {}, {}
    sims = pk_day.simulate(ph, Fh)
    surf_l = pk_day.surfaces(ph, Fh, xh, swing_t, swing_coins, SL, SS, sims=sims)
    uni = PS.universe_panel(hist, ph.t + 3600, ph.coins, MIN_VOL)          # decided when the hour closes
    elig_pit = Fh.elig & (uni["code"] == PS.U_ELIGIBLE) & uni["complete"][:, None]
    surf_p = pk_day.surfaces(ph, Fh, xh, swing_t, swing_coins, SL, SS, elig=elig_pit, sims=sims)
    frh, fsh, _ = PC.funding_panel(md, ph.t, ph.coins, cutoff=cutoff)
    _, lst, slip, _ = PC.liquidity_panel(hist, ph.t, ph.coins)              # known at each hour's open
    sd = _stop_dist(Fh.atr1, ph.c, 1.5, 0.015, 0.06)
    t_bar = ph.t.astype(np.int64)
    rep, quals = {"period": [int(ph.t[pk_day.FIRST]), int(ph.t[-1])], "coins": ph.N,
                  "selection_authority": "tools/research/pk_day.py surfaces() (shared with pk_day.run)"}, {}
    for side, sgn in (("long", 1), ("short", -1)):
        L, P_ = surf_l[side], surf_p[side]
        R, RET, BARS = L["R"], L["RET"], L["BARS"]

        def qual(mask):
            return _pk_qualify(uni, slip, R, RET, BARS, sgn, COST, sd, t_bar, frh, fsh == PC.F_MISSING, mask,
                               pk_day.HOLD, lst)

        q_base, q_top = qual(P_["base"]), qual(_rows_mask(R.shape, P_["top"]))
        lb = {(lo, hi): m for lo, hi, m in L["bands"]}
        pb = {(lo, hi): m for lo, hi, m in P_["bands"]}
        bands = []
        for lo, hi in pk_day.BANDS:
            qb = qual(pb[(lo, hi)]) if (lo, hi) in pb else {"n": 0}
            quals[(side, "band", lo, hi)] = qb
            bands.append({"lo": lo, "hi": hi, "label": "DAY STRATEGY SURFACE",
                          "legacy": {"label": LEGACY, **_legacy_rows(R, RET, lb[(lo, hi)])} if (lo, hi) in lb
                          else {"label": LEGACY, "n": 0, "note": "fewer than 30 rows: not reported by pk_day"},
                          "corrected": _corrected(qb, hist) if (lo, hi) in pb
                          else {"note": "fewer than 30 point-in-time eligible rows", "authoritative": {"n": 0}}})
        a = np.array([(R[k, pk].mean(), RET[k, pk].mean(), R[k, m].mean(), RET[k, m].mean()) for k, pk, m in L["top"]])
        rep[side] = {
            "base": {"label": DIAGNOSTIC, "legacy": {"label": LEGACY, **_legacy_rows(R, RET, L["base"])},
                     "corrected": _diagnostic(q_base, hist)},
            "bands": bands,
            "top5": {"label": "DAY STRATEGY SURFACE",
                     "legacy": {"label": LEGACY, "n": len(a), "R": _r(a[:, 0].mean()) if len(a) else None,
                                "ret": _r(a[:, 1].mean()) if len(a) else None,
                                "R_all": _r(a[:, 2].mean()) if len(a) else None},
                     "corrected": {**_top5_corrected(q_top, P_["top"]), "components": _counts(q_top),
                                   "why_not_qualified": PS.reasons(q_top, hist)}}}
        quals[(side, "base")], quals[(side, "top5")] = q_base, q_top
    return rep, surf_l, surf_p, quals


def picks(md, hist, cutoff):
    import qind as I
    from picks_export import BANDS as SWING_BANDS
    from picks_export import band_mask, base_mask
    from pk_data import factors, forward, regimes
    from pk_score import scores
    from pk_trades import COST, sim
    p, d = _daily_panel(md, cutoff)
    out = {"swing": {}, "day": {}, "legacy_cost_per_trade": COST, "label": LEGACY}
    Fx = factors(d)
    fw = forward(d)
    btc_up, _ = regimes(d)
    SL_, SS_, _, _ = scores(Fx, btc_up)
    atr = I.atr(d["h"], d["l"], d["c"], 14)
    # funding per day from the 4h grid: observed settlements, a day with a missing due settlement is missing
    frate4, fstate4, _ = PC.funding_panel(md, p.t, p.coins, bar=14400, cutoff=cutoff)
    end = d["end"]
    K = len(end)
    fr_d, fm_d = np.zeros((K, p.N)), np.zeros((K, p.N), bool)
    for k in range(K):
        a = end[k] - 5
        fr_d[k] = frate4[a:end[k] + 1].sum(axis=0)
        fm_d[k] = (fstate4[a:end[k] + 1] == PC.F_MISSING).any(axis=0)
    t_bar = d["t"].astype(np.int64)
    t_dec = t_bar + 86400
    sd_sw = _stop_dist(atr, d["c"], 2.0, 0.05, 0.25)
    uni_sw = PS.universe_panel(hist, t_dec, p.coins, MIN_VOL)          # decided at each day's close
    _, lst_sw, slip_sw, _ = PC.liquidity_panel(hist, t_bar, p.coins)    # known at each day's open
    elig_l = d["elig"]
    elig_p = elig_l & (uni_sw["code"] == PS.U_ELIGIBLE) & uni_sw["complete"][:, None]
    # swing: picks_export's own selection masks (base_mask / band_mask), legacy on its eligibility, corrected on the
    # strategy's eligibility AND point-in-time eligibility when the day closes
    for side, sgn, sc in (("long", 1, SL_), ("short", -1, SS_)):
        R, RET, _, BARS = sim(d["o"], d["h"], d["l"], d["c"], atr, sgn, 2.0, 3.0, SWING_HOLD, 0.05, 0.25, COST)

        def qual(mask):
            return _pk_qualify(uni_sw, slip_sw, R, RET, BARS, sgn, COST, sd_sw, t_bar, fr_d, fm_d, mask, SWING_HOLD,
                               lst_sw)

        o = {"base": {"label": SWING_DIAGNOSTIC,
                      "legacy": {"label": LEGACY, **_legacy_rows(R, RET, base_mask(R, fw, elig_l))},
                      "corrected": _diagnostic(qual(base_mask(R, fw, elig_p)), hist)},
             "bands": []}
        for lo, hi in SWING_BANDS + (READY_BAND,):
            ml, mp = band_mask(sc, R, fw, elig_l, lo, hi), band_mask(sc, R, fw, elig_p, lo, hi)
            o["bands"].append({"lo": lo, "hi": hi, "label": "SWING STRATEGY SURFACE" + (" (ready: 80+)" if (lo, hi)
                                                                                      == READY_BAND else ""),
                               "legacy": {"label": LEGACY, **_legacy_rows(R, RET, ml),
                                          "reported_by_picks_export": bool(ml.sum() >= MIN_BAND_ROWS)},
                               "corrected": _corrected(qual(mp), hist) if mp.sum() >= MIN_BAND_ROWS
                               else {"note": "fewer than 30 point-in-time eligible rows: picks_export would not "
                                             "report this band", "authoritative": {"n": 0}}})
        out["swing"][side] = o
    # day picks: the day-pick selection authority itself (pk_day.surfaces)
    out["day"], _, _, _ = day_research(md, hist, cutoff, d["t"], d["coins"], SL_, SS_)
    out["period"] = [int(d["t"][0]), int(d["t"][-1]) + 86400]
    return out


# --------------------------------------------------------------------------- report
def run(md, hist_dir, cutoff=None, skip_market=False):
    store = VH.DirStore(hist_dir) if hist_dir and os.path.isdir(os.path.join(hist_dir, VH.OBS_DIR)) else None
    hist = PIT.History(store, cutoff=cutoff) if store is not None else None
    hrep = hist.report if hist is not None else {"ok": False, "observations": 0, "problems": ["no history export"]}
    win = hist.window() if hist is not None else {"status": PIT.HISTORY_EMPTY, "reason": "NO_HISTORY", "start": None,
                                                   "end": None}
    view, view_why = hist.view_status if hist is not None else (PIT.HISTORY_EMPTY, "NO_HISTORY")
    md_hash, md_files = tree_hash(md) if md and os.path.isdir(md) else (None, 0)
    out = {"schema": VERSION, "generated": int(time.time()), "cutoff": cutoff,
           "provenance": {"code_hash": code_hash(), "code_files": list(CODE_FILES), "git_head": _git("rev-parse", "HEAD"),
                          "market_data": {"folder_sha256": md_hash, "files": md_files,
                                          "commit": _git("rev-parse", "origin/market-data")},
                          "history": {"writer_version": VH.VERSION, "readable_schemas": list(VH.SCHEMAS),
                                      "schemas": hrep.get("schemas"), "head_hash": hrep.get("head_hash"),
                                      "observations": hrep.get("observations"), "verified": hrep.get("ok"),
                                      "problems": hrep.get("problems", [])[:10]},
                          "pit_version": PIT.VERSION, "cost_model": PC.VERSION, "fee_schedule": PC.FEE_SCHEDULE,
                          "slippage_tiers": [list(x) for x in PC.SLIP_TIERS], "min_vol": MIN_VOL,
                          "max_staleness_s": PIT.MAX_STALENESS_S,
                          "liquidity_max_staleness_s": PIT.LIQUIDITY_MAX_STALENESS_S,
                          "reproduce": ("git archive <market-data commit> | tar -x -C md; git archive <v8-history "
                                        "commit> | tar -x -C hist; python tools/research/pit_research.py --md md "
                                        f"--history hist --cutoff {cutoff if cutoff is not None else '<unix>'} "
                                        "--out research_pit.json")},
           "history": {"verify": {k: hrep.get(k) for k in ("ok", "observations", "checkpoints", "liquidity_observations",
                                                           "backfilled", "bytes", "first_observed_at",
                                                           "last_observed_at", "problem_count")},
                       "window": win, "view_status": view, "view_reason": view_why,
                       "liquidity_precision": liquidity_precision(hist)},
           "promotion": "NONE: nothing here changes quant_research.json, picks_research.json or a live engine"}
    try:
        out["shadow_ledger"] = SL.summary(os.path.join(ROOT, SL.DIR))
    except Exception as e:  # noqa: BLE001
        out["shadow_ledger"] = {"error": f"{type(e).__name__}: {e}"}
    if not skip_market and md and os.path.isdir(md):
        out["quant"] = {}
        out["quant"] = quant(md, hist, cutoff, out)
        out["picks"] = picks(md, hist, cutoff)
    else:
        out["quant"] = out["picks"] = None
        out["market_data_1h"] = {"status": "MARKET_DATA_UNAVAILABLE"}
    out["qualified_window"] = qualified_window(out, win)
    out["health"] = health(out, hist, win)
    return out


def liquidity_precision(hist):
    """How many liquidity records of the view carry each precision, and what that means for cost authority."""
    counts = {}
    if hist is not None and hist.usable:
        for _, vs in hist._liq.values():
            for st, _, prec in vs:
                if st == "KNOWN":
                    counts[prec] = counts.get(prec, 0) + 1
    return {"known_values_by_precision": dict(sorted(counts.items())),
            "rule": ("v8.history/1 values were rounded to a whole dollar: PRECISION_LOST_V1, never a threshold or a "
                     "slippage tier (LIQUIDITY_PRECISION_UNQUALIFIED). v8.history/2 values carry the audit "
                     "registry's 8 significant digits: they decide a threshold unless it lies inside their rounding "
                     "interval.")}


def qualified_window(out, win):
    md = out.get("market_data_1h") or {}
    a = max(x for x in (win.get("start"), md.get("start")) if x is not None) if win.get("start") and md.get("start") \
        else None
    b = min(win.get("end") or 0, md.get("end") or 0) if win.get("end") and md.get("end") else None
    hours = max(0, (b - a) // 3600) if a is not None and b is not None else 0
    trades = 0
    for sid, r in (out.get("quant") or {}).items():
        trades += r["corrected"]["fully_qualified"]
    picks_rows, day_samples = 0, 0
    pk = out.get("picks") or {}
    for side, o in (pk.get("swing") or {}).items():
        picks_rows += sum((b["corrected"]["authoritative"] or {}).get("n", 0) for b in o["bands"]
                          if (b["lo"], b["hi"]) != READY_BAND)        # the ready band repeats the 80-90 and 90+ rows
    for side, o in (pk.get("day") or {}).items():
        if isinstance(o, dict) and "bands" in o:
            picks_rows += sum((b["corrected"]["authoritative"] or {}).get("n", 0) for b in o["bands"])
            day_samples += o["top5"]["corrected"]["qualified_samples"]
    return {"point_in_time_history_start": win.get("start"), "point_in_time_history_end": win.get("end"),
            "market_data_start": md.get("start"), "market_data_end": md.get("end"),
            "overlap_start": a if hours else None, "overlap_end": b if hours else None, "hours": int(hours),
            "days": round(hours / 24, 2), "observations": win.get("observations"),
            "assets_in_history": None, "qualified_quant_trades": trades,
            "qualified_pick_band_rows": picks_rows, "qualified_day_top5_samples": day_samples}


def health(out, hist, win):
    ok = hist is not None and hist.usable
    md = out.get("market_data_1h") or {}
    fb = md.get("funding_bars") or {}
    gaps = (win or {}).get("gaps") or []
    return {"PIT_UNIVERSE": PIT.PIT_UNIVERSE_OK if ok and not gaps else PIT.PIT_UNIVERSE_GAP,
            "LIQUIDITY_HISTORY": PIT.LIQUIDITY_HISTORY_OK if ok and (win or {}).get("liquidity_observations")
            else PIT.LIQUIDITY_HISTORY_GAP,
            "FUNDING_HISTORY": "FUNDING_HISTORY_OK" if fb and not fb.get("MISSING") else "FUNDING_HISTORY_GAP",
            "LIQUIDITY_PRECISION": ("LIQUIDITY_PRECISION_UNQUALIFIED_V1" if ok and any(
                prec == PIT.PRECISION_LOST_V1 for _, vs in hist._liq.values() for st, _, prec in vs if st == "KNOWN")
                else "LIQUIDITY_PRECISION_REGISTRY_8SIG" if ok else "NO_LIQUIDITY_IN_VIEW"),
            "gaps": gaps[:20], "history_status": (win or {}).get("status"), "history_reason": (win or {}).get("reason")}


def text(out):
    L = []
    w, q = out["history"]["window"], out["qualified_window"]
    L.append(f"v8 point-in-time research ({out['schema']}), cutoff {out['cutoff']}")
    L.append(f"history view: {out['history']['view_status']} ({out['history']['view_reason']}); liquidity precision "
             f"{json.dumps(out['history']['liquidity_precision']['known_values_by_precision'])}")
    L.append(f"history: {w.get('status')}, {w.get('observations')} observations "
             f"({w.get('backfilled', 0)} backfilled), {w.get('start')} .. {w.get('end')}")
    L.append(f"market data: {q['market_data_start']} .. {q['market_data_end']}")
    L.append(f"qualified window: {q['hours']} hours ({q['days']} days); qualified quant trades {q['qualified_quant_trades']}")
    L.append(f"health: {json.dumps({k: v for k, v in out['health'].items() if k != 'gaps'})}")
    for sid, r in (out.get("quant") or {}).items():
        lg, co = r["legacy"], r["corrected"]
        L.append(f"{sid}: legacy {lg['trades']} trades avg {lg['avg_R']}R [{lg['label']}] | corrected {co['trades']} "
                 f"trades, {co['fully_qualified']} fully qualified, authoritative {co['authoritative']} | "
                 f"why: {json.dumps(co['why_not_qualified'])}")
    pk = out.get("picks") or {}
    for side, o in (pk.get("swing") or {}).items():
        b = o["base"]
        L.append(f"picks swing {side} base [{b['label']}]: legacy {b['legacy']} | corrected "
                 f"{b['corrected']['aggregate']}")
        for x in o["bands"]:
            L.append(f"picks swing {side} {x['lo']}-{x['hi']}: legacy n={x['legacy'].get('n')} R={x['legacy'].get('R')}"
                     f" | corrected {x['corrected'].get('components')} authoritative {x['corrected']['authoritative']}")
    for side, o in (pk.get("day") or {}).items():
        if not (isinstance(o, dict) and "bands" in o):
            continue
        L.append(f"picks day {side} base [{o['base']['label']}]: legacy {o['base']['legacy']} | corrected "
                 f"{o['base']['corrected']['aggregate']}")
        for x in o["bands"]:
            L.append(f"picks day {side} band {x['lo']}-{x['hi']}: legacy n={x['legacy'].get('n')} "
                     f"R={x['legacy'].get('R')} | corrected {x['corrected'].get('authoritative')}")
        t5 = o["top5"]
        L.append(f"picks day {side} Top 5: legacy {t5['legacy']} | corrected samples {t5['corrected']['samples']}, "
                 f"qualified {t5['corrected']['qualified_samples']}, authoritative {t5['corrected']['authoritative']}")
    L.append(f"shadow ledger: {json.dumps(out.get('shadow_ledger'))}")
    L.append(out["promotion"])
    return "\n".join(L)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--md", default=None, help="export of the market-data branch")
    ap.add_argument("--history", default=None, help="export of the v8-history branch (holds obs/)")
    ap.add_argument("--cutoff", type=int, default=None, help="use nothing observed after this unix time")
    ap.add_argument("--out", default="research_pit.json")
    ap.add_argument("--text", action="store_true")
    a = ap.parse_args(argv)
    out = run(a.md, a.history, a.cutoff)
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, default=_default)
    print(text(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
