"""Evidence engine v1: the legacy strategies re-tested on a survivorship-free universe (research only).

    python tools/v9/evidence.py --md md_bn --out evidence [--replications 5000]

The legacy research (quant_research.json, picks_research.json) tested today's coin list: coins that died were never in
it, which flatters every long and trend strategy. v8 rightly labelled those numbers LEGACY_SURVIVORSHIP_UNQUALIFIED,
but then had no way to qualify anything until 180 days of its own recorded history exist. The Binance public archive
already holds every USD-M perpetual that ever traded, delisted ones included, from listing to delisting
(tools/v9/archive_fetch.py). On that universe this job runs:

  * every 4h and daily candidate of the governed Phase 9 catalogue (tools/research/strategy_census.catalog(), the
    exact implementations and parameters of qexport.TESTED), through the unchanged research simulator (qsim) with
    the same trade rules: signals on closed bars, entry at the next open, stop before target, trailing stops from the
    next bar, gaps at the open;
  * costs: 0.045% taker fee each way, slippage 0.10% each way for every coin and every trade (twice the live
    $1M+ tier, because a Binance volume is not a DEX volume), observed Binance funding while held; stress x1.5 / x2;
  * point-in-time eligibility only (Feat: alive, 30 days of history, $5M+ a day traded over the last 7 days);
  * a random twin for every trade (the same order on a random other eligible coin at the same moment);
  * the Phase 9 statistics on the same definitions: day-clustered 95% intervals, out-of-sample (last third),
    sides, cost stress, concentration, and the family tests over all evaluated candidates (White Reality Check,
    Hansen SPA, BH/BY FDR, CSCV PBO, deflated Sharpe with the census' 199 known trials);
  * the period split that matters most: Jan 2020 to Sep 2023 is BEFORE the legacy research window (Oct 2023 to Oct
    2026) in which these strategies were designed and tuned, so it is out of sample in time; delisted coins are out
    of sample in the cross-section;
  * the coin-picks swing score (chart part, 100 points) by score band, the way picks_research.json reports it, plus
    a non-overlapping version (one trade per coin at a time) and funding while held.

Nothing here promotes a strategy or changes a live engine. The numeric part of the Phase 9 gate is reported per
candidate; the governed adjudication (which also needs a complete trial census and prospective registration) is
reported unchanged next to it."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RESEARCH = os.path.join(ROOT, "tools", "research")
sys.path.insert(0, RESEARCH)
sys.path.insert(0, ROOT)

import qdata  # noqa: E402
import qsim  # noqa: E402
import qstrat  # noqa: E402
import multiple_testing as MT  # noqa: E402
import strategy_census as census  # noqa: E402
from v8 import strategy_authority as SA  # noqa: E402

VERSION = "v9.archive-evidence/1"
SLIP = 0.0010
BAR = 14400
DESIGN_START = int(datetime(2023, 10, 1, tzinfo=timezone.utc).timestamp())   # legacy research window start
WARMUP_DAYS = 120


class ArchivePanel(qdata.Panel):
    """qdata.Panel on the archive layout: 4h bars, observed Binance funding only, one slippage for every coin."""

    def __init__(self, md, slip=SLIP, **kw):
        self._slip = slip
        super().__init__(md, folder="h4", bar=BAR, min_hours=kw.pop("min_hours", 24 * 30), **kw)

    def _funding(self, md):
        T, N = len(self.t), len(self.coins)
        f = np.zeros((T, N))
        self.fund_src = []
        for j, c in enumerate(self.coins):
            path = os.path.join(md, "fund_bn", f"{c}.csv.gz")
            src = "missing"
            if os.path.exists(path):
                _, rows = qdata._read(path)
                for row in rows:
                    i = (int(row[0]) - int(self.t[0])) // self.bar
                    if 0 <= i < T and row[1] != "":
                        f[i, j] += float(row[1])
                src = "binance" if rows else "missing"
            self.fund_src.append(src)
        return f

    def slip(self):
        return np.full(self.N, self._slip)


# ------------------------------------------------------------------ statistics (Phase 9 definitions)
def clustered(values, days):
    """Day-clustered mean and 95% interval (needs >= 30 distinct days), as in strategy_adjudication.clustered."""
    v = np.asarray(values, float)
    out = {"n": int(len(v)), "mean_R": None, "lower_95": None, "upper_95": None, "se": None, "days": 0}
    if not len(v):
        return out
    mean = float(v.mean())
    d = np.asarray(days)
    uniq, inv = np.unique(d, return_inverse=True)
    out.update(mean_R=mean, days=int(len(uniq)))
    if len(uniq) >= 30:
        resid = np.bincount(inv, weights=v - mean)
        se = math.sqrt(len(uniq) / (len(uniq) - 1) * float((resid ** 2).sum())) / len(v)
        out.update(se=se, lower_95=mean - 1.96 * se, upper_95=mean + 1.96 * se)
    return out


def robustness(rows, start, end):
    net = np.array([r["net_R"] for r in rows], float)
    days = np.array([r["decision_time"] // 86400 for r in rows])
    if not len(rows):
        return {}
    oos_start = start + (end - start) * (1 - SA.GATE["oos_fraction"])
    sel = lambda m: clustered(net[m], days[m])  # noqa: E731
    dt = np.array([r["decision_time"] for r in rows])
    d = np.array([r["direction"] for r in rows])
    adverse = np.array([r["adverse_cost_R"] for r in rows], float)
    positive = np.sort(np.maximum(net, 0))[::-1]
    total = positive.sum()
    assets = sorted({r["asset"] for r in rows})
    asset_arr = np.array([r["asset"] for r in rows])
    leave = {}
    for a in assets:
        m = asset_arr != a
        leave[a] = float(net[m].mean()) if m.any() else None
    months = {}
    for r in rows:
        months[r["month"]] = months.get(r["month"], 0.0) + max(0.0, r["net_R"])
    years = {}
    for y in sorted({r["year"] for r in rows}):
        m = np.array([r["year"] == y for r in rows])
        years[str(y)] = sel(m)
    return {
        "oos_start": oos_start, "oos": sel(dt >= oos_start),
        "pre_design": sel(dt < DESIGN_START), "design_window": sel(dt >= DESIGN_START),
        "sides": {"long": sel(d == 1), "short": sel(d == -1)},
        "cost_stress": {str(k): float(np.mean(net - (k - 1) * adverse)) for k in (1.0, 1.5, 2.0)},
        "years": years,
        "delisted_coins": sel(np.array([r["delisted"] for r in rows])),
        "listed_coins": sel(~np.array([r["delisted"] for r in rows])),
        "concentration": {
            **{f"top{k}_positive_fraction": float(positive[:k].sum() / total) if total else None for k in (1, 5, 10)},
            "leave_one_asset_out_min_mean_R": min((v for v in leave.values() if v is not None), default=None),
            "month_positive_fraction": max(months.values()) / total if total else None,
            "winner_fraction": float((net > 0).mean()), "assets": len(assets)},
    }


def trades_of(p, F, sid, fn, kw, universe):
    signals = fn(F, **kw)
    s, res, tw = qsim.run(p, signals, elig=F.elig)
    rows = []
    for k in range(len(res)):
        i, j = int(s["i"][k]), int(s["j"][k])
        ex = int(res[k, qsim.R_EXIT])
        fund = float(res[k, qsim.R_FUND])
        cost = float(res[k, qsim.R_COST])
        decision = int(p.t[i] + p.bar)
        dt = datetime.fromtimestamp(decision, timezone.utc)
        coin = p.coins[j]
        rows.append({"asset": coin, "decision_time": decision, "exit_time": int(p.t[ex] + p.bar),
                     "direction": int(s["d"][k]), "net_R": float(res[k, qsim.R_NET]),
                     "gross_R": float(res[k, qsim.R_GROSS]), "cost_R": cost, "funding_R": fund,
                     "adverse_cost_R": cost - fund + max(0.0, fund), "stop": float(s["stop"][k]),
                     "reason": qsim.REASONS[int(res[k, qsim.R_REASON])], "hold_bars": int(res[k, qsim.R_HOLD]),
                     "twin_net_R": None if tw is None or np.isnan(tw[k, qsim.R_NET]) else float(tw[k, qsim.R_NET]),
                     "delisted": bool((universe.get(coin) or {}).get("delisted")),
                     "year": dt.year, "month": dt.strftime("%Y-%m")})
    return len(signals["i"]), rows


def numeric_gate(e):
    """The numeric checks of the Phase 9 gate (SA.CHECKS) on this evidence; None where not measured here."""
    out = {}
    for key, gate_key, op, kind in SA.CHECKS:
        v = e.get(key)
        thr = SA.GATE[gate_key]
        ok = None if v is None or (isinstance(v, float) and not math.isfinite(v)) else SA._passes(v, thr, op)
        out[key] = {"value": v, "threshold": thr, "op": op, "pass": ok}
    return out


def swing_picks(md, slip):
    """The coin-picks swing score (chart part) by band on the archive universe; the legacy method (every coin-day
    in the band) and one trade per coin at a time, with funding while held."""
    import pandas as pd
    import pk_data
    import pk_score
    import pk_trades
    import qind as I
    pk_data.Panel = lambda md_, folder="h4", bar=BAR, min_hours=24 * 60: ArchivePanel(md_, slip=slip, min_hours=min_hours)
    p, d = pk_data.daily_panel(md)
    F = pk_data.factors(d)
    fw = pk_data.forward(d)
    btc_up, _ = pk_data.regimes(d)
    SL, SS, _, _ = pk_score.scores(F, btc_up)
    atr = I.atr(d["h"], d["l"], d["c"], 14)
    cost = 2 * (qsim.FEE_T + slip)
    t = d["t"]
    years = pd.to_datetime(t, unit="s").year.to_numpy()
    elig = d["elig"]
    cumf = np.vstack([np.zeros((1, d["fund"].shape[1])), np.cumsum(np.nan_to_num(d["fund"]), axis=0)])
    with np.errstate(all="ignore"):
        sd = np.clip(2.0 * atr / d["c"], 0.05, 0.25)
    out = {"coins": len(d["coins"]), "days": int(len(t)), "cost_round_trip": cost,
           "period": [int(t[0]), int(t[-1])], "rules": "next daily open, stop 2 ATR (5%-25%), trail 3 ATR, 30 days max"}
    K, N = SL.shape
    for side, sgn, sc in (("long", 1, SL), ("short", -1, SS)):
        R, RET, MFE, BARS = pk_trades.sim(d["o"], d["h"], d["l"], d["c"], atr, sgn, 2.0, 3.0, 30, 0.05, 0.25, cost)
        kk = np.arange(K)[:, None]
        nb = np.nan_to_num(BARS).astype(int)
        hi = np.clip(kk + 1 + nb, 0, K)
        fsum = cumf[hi, np.arange(N)[None, :]] - cumf[np.clip(kk + 1, 0, K), np.arange(N)[None, :]]
        with np.errstate(all="ignore"):
            RF = R - sgn * fsum / sd
        base = elig & np.isfinite(RF)
        bands = []
        for lo, hi_ in ((0, 60), (60, 70), (70, 80), (80, 90), (90, 101)):
            m = base & np.isfinite(sc) & (sc >= lo) & (sc < hi_)
            if m.sum() < 30:
                continue
            rows_d = np.repeat(np.arange(K)[:, None], N, 1)[m]
            st = clustered(RF[m], rows_d)
            pre = m & (t[:, None] < DESIGN_START)
            post = m & (t[:, None] >= DESIGN_START)
            bands.append({"lo": lo, "hi": hi_, "coin_days": int(m.sum()), "all_coin_days": st,
                          "pre_design_mean_R": float(np.nanmean(RF[pre])) if pre.any() else None,
                          "design_window_mean_R": float(np.nanmean(RF[post])) if post.any() else None,
                          "years": {str(y): float(np.nanmean(RF[m & (years[:, None] == y)])) for y in sorted(set(years))
                                    if (m & (years[:, None] == y)).sum() >= 30}})
        # one trade per coin at a time (the way the page's paper trades work), score 80+
        trades = []
        for j in range(N):
            k = 0
            while k < K - 2:
                if base[k, j] and np.isfinite(sc[k, j]) and sc[k, j] >= 80:
                    trades.append((k, j, float(RF[k, j])))
                    k += max(1, int(nb[k, j]))
                else:
                    k += 1
        if trades:
            v = np.array([x[2] for x in trades])
            dd = np.array([x[0] for x in trades])
            tt = t[dd]
            yy = years[dd]
            ready = {"trades": len(trades), "all": clustered(v, dd),
                     "pre_design": clustered(v[tt < DESIGN_START], dd[tt < DESIGN_START]),
                     "design_window": clustered(v[tt >= DESIGN_START], dd[tt >= DESIGN_START]),
                     "years": {str(y): clustered(v[yy == y], dd[yy == y]) for y in sorted(set(yy.tolist()))}}
        else:
            ready = {"trades": 0}
        out[side] = {"bands": bands, "ready_80_one_at_a_time": ready}
    return out


def legacy_claims():
    try:
        q = json.load(open(os.path.join(ROOT, "quant_research.json")))
        return {sid: {"three_year": (row.get("three_year") or {}), "verdict": row.get("verdict")}
                for sid, row in (q.get("strategies") or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="md_bn")
    ap.add_argument("--out", default="evidence")
    ap.add_argument("--replications", type=int, default=SA.GATE["bootstrap_replications"])
    ap.add_argument("--only", default="", help="comma list of strategy ids (testing)")
    ap.add_argument("--skip-swing", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    uni_doc = json.load(open(os.path.join(a.md, "universe.json")))
    universe = {c["t"]: c for c in uni_doc["coins"]}
    p = ArchivePanel(a.md)
    F = qstrat.Feat(p)
    print(f"panel {p.T} x {p.N} ({time.time() - t0:.0f}s); {np.isfinite(p.c).any(axis=0).sum()} coins; "
          f"eligible coin-bars {int(F.elig.sum())}", flush=True)
    data_hash = hashlib.sha256()
    for arr in (p.t, p.o, p.h, p.l, p.c, p.v, p.fund):
        data_hash.update(np.ascontiguousarray(arr).tobytes())
    from qexport import TESTED
    catalog = [c for c in census.catalog() if c["timeframe"] in ("4h", "1d")]
    if a.only:
        catalog = [c for c in catalog if c["strategy_id"] in a.only.split(",")]
    start = int(p.t[0]) + WARMUP_DAYS * 86400
    end = int(p.t[-1]) + BAR
    claims = legacy_claims()
    cands, all_rows = [], {}
    for c in catalog:
        sid = c["strategy_id"]
        fn, kw = TESTED[sid][:2]
        n_sig, rows = trades_of(p, F, sid, fn, kw, universe)
        rows = [r for r in rows if r["decision_time"] >= start]
        all_rows[sid] = rows
        net = np.array([r["net_R"] for r in rows], float)
        days = np.array([r["decision_time"] // 86400 for r in rows])
        agg = clustered(net, days)
        rob = robustness(rows, start, end) if rows else {}
        tw = [(r["net_R"] - r["twin_net_R"], r["decision_time"] // 86400) for r in rows if r["twin_net_R"] is not None]
        twin = clustered([x[0] for x in tw], [x[1] for x in tw]) if tw else clustered([], [])
        cands.append({"strategy_id": sid, "family": c["family"], "timeframe": c["timeframe"], "params": c["params"],
                      "signals": n_sig, "trades": len(rows), "aggregate": agg, "robustness": rob,
                      "twin_edge": twin, "legacy_claim": claims.get(sid)})
        print(f"{sid:12s} trades {len(rows):6d} mean {agg['mean_R'] if agg['mean_R'] is not None else float('nan'):+.3f}R "
              f"lo95 {agg['lower_95'] if agg['lower_95'] is not None else float('nan'):+.3f} "
              f"pre-design {((rob.get('pre_design') or {}).get('mean_R') or float('nan')):+.3f} "
              f"design {((rob.get('design_window') or {}).get('mean_R') or float('nan')):+.3f} "
              f"twin edge {twin['mean_R'] if twin['mean_R'] is not None else float('nan'):+.3f} ({time.time() - t0:.0f}s)",
              flush=True)
    # family tests on a common contiguous daily window
    day0, day1 = start // 86400, (end - 1) // 86400
    ndays = day1 - day0 + 1
    names = [c["strategy_id"] for c in cands]
    matrix = np.zeros((ndays, len(cands)))
    for k, sid in enumerate(names):
        for r in all_rows[sid]:
            dd = r["exit_time"] // 86400 - day0
            if 0 <= dd < ndays:
                matrix[dd, k] += r["net_R"]
    provenance = {"schema": VERSION, "dataset_sha256": data_hash.hexdigest(), "archive_end": uni_doc.get("archive_end_month"),
                  "candidates": names, "slippage": SLIP, "window": [int(day0), int(day1)]}
    family, pbo = {"status": "UNAVAILABLE"}, {"status": "UNAVAILABLE"}
    if len(cands) >= 2:
        family = MT.bootstrap_tests(matrix, provenance, a.replications, SA.GATE["block_days"])
        if family.get("status") != "AVAILABLE":
            # a candidate without trades has zero long-run variance; test the others and name the ones left out
            live = [k for k in range(len(cands)) if matrix[:, k].std() > 0]
            if len(live) >= 2:
                sub = MT.bootstrap_tests(matrix[:, live], provenance, a.replications, SA.GATE["block_days"])
                if sub.get("status") == "AVAILABLE":
                    by_q = [None] * len(cands)
                    for pos, k in enumerate(live):
                        by_q[k] = sub["fdr"]["by_q"][pos]
                    family = dict(sub, fdr=dict(sub["fdr"], by_q=by_q), note="candidates without trades left out",
                                  left_out=[names[k] for k in range(len(cands)) if k not in live])
        pbo = MT.pbo(matrix, names, SA.GATE["cscv_segments"], SA.GATE["cscv_min_segment_days"])
        if pbo.get("status") != "AVAILABLE":
            # a sparse candidate with no trade in some half of a split has zero variance there; report PBO over the
            # candidates with enough trades and name the ones left out (never silently)
            keep = [k for k, c in enumerate(cands) if c["trades"] >= 100]
            if len(keep) >= 2:
                sub = MT.pbo(matrix[:, keep], [names[k] for k in keep], SA.GATE["cscv_segments"], SA.GATE["cscv_min_segment_days"])
                if sub.get("status") == "AVAILABLE":
                    pbo = dict(sub, note="candidates with fewer than 100 trades left out of PBO",
                               left_out=[names[k] for k in range(len(cands)) if k not in keep])
    sharpes = [float(matrix[:, k].mean() / matrix[:, k].std(ddof=1)) for k in range(len(cands)) if matrix[:, k].std(ddof=1) > 0]
    trial_var = float(np.var(sharpes, ddof=1)) if len(sharpes) > 1 else None
    trials = max(199, len(cands))
    for k, cand in enumerate(cands):
        dsr = MT.dsr(matrix[:, k], trials, trial_var, False) if trial_var else MT.unavailable("dispersion")
        rob, agg = cand["robustness"], cand["aggregate"]
        conc = rob.get("concentration") or {}
        e = {"pit_calendar_days": int(ndays), "qualified_closed_trades": cand["trades"], "mean_R": agg["mean_R"],
             "mean_R_lower_95": agg["lower_95"], "matched_edge": cand["twin_edge"]["mean_R"],
             "matched_lower_95": cand["twin_edge"]["lower_95"],
             # one random twin per signal is measured here; the gate's 50 matched controls per signal are not
             "full_matched_fraction": None, "controls_per_signal": None, "dsr_probability": dsr.get("probability"),
             "pbo": pbo.get("pbo"), "spa_p": family.get("hansen_spa_p"), "white_rc_p": family.get("white_rc_p"),
             "by_q": (family.get("fdr") or {}).get("by_q", [None] * len(cands))[k] if family.get("status") == "AVAILABLE" else None,
             "oos_mean_R": (rob.get("oos") or {}).get("mean_R"), "stress_1_5_mean_R": (rob.get("cost_stress") or {}).get("1.5"),
             "top1_positive_fraction": conc.get("top1_positive_fraction"),
             "top5_positive_fraction": conc.get("top5_positive_fraction"),
             "top10_positive_fraction": conc.get("top10_positive_fraction"),
             "month_positive_fraction": conc.get("month_positive_fraction"),
             "leave_one_asset_out_min_mean_R": conc.get("leave_one_asset_out_min_mean_R"),
             "sides": rob.get("sides"), "trial_census_complete": False, "trial_return_universe_complete": False,
             "pit_integrity_ok": True, "prospective_registration_valid": False, "full_feature_authority": False,
             "robustness_slices_complete": False}
        gate = numeric_gate(e)
        measured = {k_: v for k_, v in gate.items() if v["pass"] is not None}
        failing = sorted(k_ for k_, v in measured.items() if v["pass"] is False)
        not_measured = sorted(k_ for k_, v in gate.items() if v["pass"] is None)
        cand.update(dsr=dsr, evidence=e, numeric_gate=gate, failing_checks=failing, not_measured=not_measured,
                    archive_verdict=("PASSES_MEASURED_GATE" if not failing else "FAILS_MEASURED_GATE"),
                    governed_adjudication=SA.adjudicate(e, catalog[k]))
    swing = None
    if not a.skip_swing:
        try:
            swing = swing_picks(a.md, SLIP)
        except Exception as ex:  # noqa: BLE001
            swing = {"error": f"{type(ex).__name__}: {str(ex)[:300]}"}
    doc = {"schema": VERSION, "generated_at": int(time.time()), "seconds": round(time.time() - t0, 1),
           "provenance": provenance, "data": {"source": uni_doc.get("source"), "counts": uni_doc.get("counts"),
                                              "panel_coins": p.N, "bars": p.T, "first_bar": int(p.t[0]), "last_bar": int(p.t[-1]),
                                              "funding_sources": {s: p.fund_src.count(s) for s in set(p.fund_src)}},
           "costs": {"taker_fee": qsim.FEE_T, "slippage_each_way": SLIP, "funding": "observed Binance settlements",
                     "stress": [1.5, 2.0]},
           "design_window_start": DESIGN_START, "warmup_days": WARMUP_DAYS,
           "family": {"tests": family, "pbo": pbo, "trial_count_for_dsr": trials, "trial_sharpe_variance": trial_var,
                      "window_days": int(ndays)},
           "candidates": cands, "swing_picks": swing}
    with open(os.path.join(a.out, "evidence.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, default=lambda x: x.item() if hasattr(x, "item") else None)
    import gzip
    keep = ("asset", "decision_time", "exit_time", "direction", "net_R", "gross_R", "funding_R", "twin_net_R", "reason")
    with gzip.open(os.path.join(a.out, "trades.json.gz"), "wt") as fh:
        json.dump({sid: [[r[k] for k in keep] for r in rows] for sid, rows in all_rows.items()} | {"_columns": list(keep)},
                  fh, separators=(",", ":"))
    write_report(doc, os.path.join(a.out, "REPORT.md"))
    print(f"done in {time.time() - t0:.0f}s")


def fmt(x, d=3):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+.{d}f}"


def write_report(doc, path):
    L = [f"# Survivorship-free evidence ({doc['schema']})", "",
         f"Data: {doc['data']['source']}; {doc['data']['panel_coins']} coins in the research panel "
         f"({(doc['data']['counts'] or {}).get('delisted_research_coins')} delisted), 4h bars "
         f"{datetime.fromtimestamp(doc['data']['first_bar'], timezone.utc):%Y-%m-%d} to "
         f"{datetime.fromtimestamp(doc['data']['last_bar'], timezone.utc):%Y-%m-%d}. Costs: taker "
         f"{doc['costs']['taker_fee'] * 100:.3f}% + slippage {doc['costs']['slippage_each_way'] * 100:.2f}% each way, "
         "observed funding. R = net result in units of the stop distance.", "",
         "Pre-design = before Oct 2023 (the legacy strategies were designed on Oct 2023 to Oct 2026 data, on coins that "
         "survived): out of sample in time. Twin edge = trade minus the same order on a random eligible coin.", "",
         "| Strategy | TF | Trades | Mean R | 95% low | Pre-design | Design window | OOS (last third) | Long | Short | Delisted coins | Twin edge | x1.5 cost | Legacy claim (3y) | Measured gate |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in doc["candidates"]:
        r = c["robustness"] or {}
        g = lambda k: (r.get(k) or {}).get("mean_R")  # noqa: E731
        claim = ((c.get("legacy_claim") or {}).get("three_year") or {}).get("avg")
        L.append(f"| {c['strategy_id']} | {c['timeframe']} | {c['trades']} | {fmt(c['aggregate']['mean_R'])} | "
                 f"{fmt(c['aggregate']['lower_95'])} | {fmt(g('pre_design'))} | {fmt(g('design_window'))} | {fmt(g('oos'))} | "
                 f"{fmt(((r.get('sides') or {}).get('long') or {}).get('mean_R'))} | {fmt(((r.get('sides') or {}).get('short') or {}).get('mean_R'))} | "
                 f"{fmt(g('delisted_coins'))} | {fmt(c['twin_edge']['mean_R'])} | {fmt((r.get('cost_stress') or {}).get('1.5'))} | "
                 f"{fmt(claim)} | {'PASS' if c['archive_verdict'] == 'PASSES_MEASURED_GATE' else 'fails: ' + ', '.join(c['failing_checks'][:4])} |")
    fam = doc["family"]
    t = fam["tests"] or {}
    L += ["", f"Family tests over {len(doc['candidates'])} candidates, {fam['window_days']} days: White RC p "
          f"{t.get('white_rc_p')}, Hansen SPA p {t.get('hansen_spa_p')}, PBO {(fam['pbo'] or {}).get('pbo')}; "
          f"DSR uses {fam['trial_count_for_dsr']} trials (the census lower bound).", ""]
    strong = [c for c in doc["candidates"] if (c["aggregate"].get("lower_95") or -1) > 0]
    if strong:
        yrs = sorted({y for c in strong for y in ((c["robustness"] or {}).get("years") or {})})
        L += ["## Year by year (candidates whose 95% lower bound is above zero)", "",
              "| Strategy | " + " | ".join(yrs) + " |", "|---|" + "---|" * len(yrs)]
        for c in strong:
            ys = (c["robustness"] or {}).get("years") or {}
            L.append(f"| {c['strategy_id']} | " + " | ".join(
                f"{fmt((ys.get(y) or {}).get('mean_R'))} ({(ys.get(y) or {}).get('n', 0)})" for y in yrs) + " |")
        L.append("")
    sw = doc.get("swing_picks") or {}
    if sw and "error" not in sw:
        L += ["## Coin-picks swing score on the survivorship-free universe", "",
              f"{sw['coins']} coins, round-trip cost {sw['cost_round_trip'] * 100:.2f}% plus funding while held.", "",
              "| Side | Band | Coin-days | Mean R | 95% low | Pre-design | Design window |", "|---|---|---|---|---|---|---|"]
        for side in ("long", "short"):
            for b in sw[side]["bands"]:
                s = b["all_coin_days"]
                L.append(f"| {side} | {b['lo']}-{b['hi']} | {b['coin_days']} | {fmt(s['mean_R'])} | {fmt(s['lower_95'])} | "
                         f"{fmt(b['pre_design_mean_R'])} | {fmt(b['design_window_mean_R'])} |")
            rd = sw[side]["ready_80_one_at_a_time"]
            if rd.get("trades"):
                L.append(f"| {side} | 80+ one at a time | {rd['trades']} trades | {fmt(rd['all']['mean_R'])} | "
                         f"{fmt(rd['all']['lower_95'])} | {fmt(rd['pre_design']['mean_R'])} | {fmt(rd['design_window']['mean_R'])} |")
        L.append("")
        for side in ("long", "short"):
            rd = sw[side]["ready_80_one_at_a_time"]
            if rd.get("years"):
                L.append(f"{side.title()} 80+ one at a time, by year: " + ", ".join(
                    f"{y} {fmt(v['mean_R'])} ({v['n']})" for y, v in rd["years"].items()) + ".")
    elif sw:
        L += ["", f"Swing score: {sw.get('error')}"]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
