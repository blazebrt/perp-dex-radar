"""Probation evidence (v9.probation-evidence/1): which side of which runtime strategy the archive confirms.

    python tools/v9/confirm.py --evidence DIR [--out research/v9/probation_evidence.json]
    python tools/v9/confirm.py --from-branch evidence-results      # the files of the latest evidence run

Reads one evidence run (evidence.json and trades.json.gz, v9.archive-evidence/2, tools/v9/evidence.py) and applies
the probation gate of docs/v9/HANDOVER.md (phase B) to every side of every strategy that has a live implementation
(the rows of v8/quant_strategy_policy.json):

  (a) the definition was fixed before the holdout was examined: the runtime parameters (quant.STRATS) equal the
      tested ones (qexport.TESTED), and the legacy research that chose them started inside the design window
  (b) holdout (before 2023-10) mean R > 0, Holm-adjusted one-sided p < 0.05 over all submitted side hypotheses
  (c) design window (2023-10 on) mean R > 0, one-sided p < 0.10
  (d) the most recent third: mean R > 0
  (e) costs x1.5 (fees, slippage and paid funding): mean R > 0
  (f) edge over the random twin (the same order on a random eligible coin at the same time): mean > 0
  (g) the Phase 9 concentration limits (v8/strategy_authority.py GATE)
  (h) at least 500 trades, at least 100 in the holdout
  (i) deployable-universe proxy (the 80 most traded eligible coins): mean R > 0 in the holdout and the design window
  (j) late entry: entered 4h, 8h, 12h, 24h late, mean R > 0 overall and in the holdout; the TRADE window is the longest
      delay that passes together with every shorter one (4h must pass)

p-values are one-sided, from the day-clustered standard error (the Phase 9 interval). The family for the Holm
correction is every side of every runtime strategy: they are the only hypotheses that could be deployed, and they were
chosen by the legacy research on 2023-12..2026-10 data, after the holdout period and without it.

Disclosure, kept in the output: the gate was written after a first look at the archive results; (i) and (j) were
added before their first measurement. The protection is therefore not the backtest alone: a confirmed side may only
trade at a reduced size (risk multiplier), with a forward test registered in the shadow ledger before its first
probation trade, and with automatic demotion when the live record falls below the archive's 5th-percentile band.

The output is canonical JSON and deterministic for given inputs and code; v8/strategy_policy.py binds it by SHA-256.
Nothing here edits the policy, the ledger or a live engine."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import inspect
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "research"))

from v8 import strategy_authority as SA  # noqa: E402
from v8 import strategy_policy as SP  # noqa: E402

VERSION = "v9.probation-evidence/1"
EVIDENCE_SCHEMA = "v9.archive-evidence/2"
OUT = os.path.join("research", "v9", "probation_evidence.json")
DESIGN_START = int(datetime(2023, 10, 1, tzinfo=timezone.utc).timestamp())
SIDES = (("long", 1), ("short", -1))
GATE = {
    "holdout_holm_p_max": 0.05, "design_p_max": 0.10, "recent_mean_min": 0.0, "stress_multiplier": 1.5,
    "stress_mean_min": 0.0, "twin_edge_min": 0.0, "min_trades": 500, "min_holdout_trades": 100,
    "proxy_variant": "top80", "delay_variants": [["delay1", 4], ["delay2", 8], ["delay3", 12], ["delay6", 24]],
    "concentration": {k: SA.GATE[k] for k in ("max_top1_positive_fraction", "max_top5_positive_fraction",
                                               "max_top10_positive_fraction", "max_month_positive_fraction",
                                               "leave_one_asset_out_min_mean_R")},
}
BAND_TRADES = (30, 50, 75, 100, 150, 200, 300, 500)
BAND_REPLICATIONS = 20000
BAND_SEED = 20261014
# Constants of the research implementation that the runtime declares as parameters (tools/research/qstrat.py):
# tsmom() uses a 50-day EMA, xs_momentum() a 30-day volatility; quant.py's stops are bounded like qstrat's.
RESEARCH_CONSTANTS = {("TSMOM", "ema"): 50, ("XSMOM", "vol_days"): 30}
RESEARCH_CODE = ("tools/v9/evidence.py", "tools/v9/archive_fetch.py", "tools/research/qsim.py",
                 "tools/research/qstrat.py", "tools/research/qdata.py", "tools/research/qind.py")


# ------------------------------------------------------------------ statistics
def clustered(values, days):
    """Day-clustered mean and 95% interval (needs >= 30 distinct days): tools/v9/evidence.clustered."""
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


def p_one_sided(stat):
    """P(mean <= 0) under the normal approximation of the day-clustered mean; None without an interval."""
    if stat.get("se") is None or stat.get("mean_R") is None:
        return None
    if stat["se"] == 0:
        return 0.0 if stat["mean_R"] > 0 else 1.0
    return 0.5 * math.erfc(stat["mean_R"] / stat["se"] / math.sqrt(2))


def holm(pvalues):
    """Holm step-down adjusted p-values (None stays None and counts as a hypothesis with p = 1)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda k: (1.0 if pvalues[k] is None else pvalues[k], k))
    out, running = [None] * m, 0.0
    for rank, k in enumerate(order):
        p = 1.0 if pvalues[k] is None else pvalues[k]
        running = max(running, min(1.0, (m - rank) * p))
        out[k] = running
    return out


def concentration(net, assets, months):
    positive = np.sort(np.maximum(net, 0))[::-1]
    total = float(positive.sum())
    leave = [float(net[assets != a].mean()) for a in sorted(set(assets.tolist())) if (assets != a).any()]
    by_month = {}
    for r, m in zip(net, months):
        by_month[m] = by_month.get(m, 0.0) + max(0.0, float(r))
    return {"top1_positive_fraction": float(positive[:1].sum() / total) if total else None,
            "top5_positive_fraction": float(positive[:5].sum() / total) if total else None,
            "top10_positive_fraction": float(positive[:10].sum() / total) if total else None,
            "month_positive_fraction": max(by_month.values()) / total if total else None,
            "leave_one_asset_out_min_mean_R": min(leave) if leave else None, "assets": len(set(assets.tolist()))}


def demotion_band(net, days, rng):
    """For n live trades: the 5th / 50th percentile of the mean R of n archive trades, resampled by whole days
    (trades of one day stay together, because they share the market)."""
    by_day = {}
    for r, d in zip(net, days):
        by_day.setdefault(int(d), []).append(float(r))
    groups = [np.array(by_day[d]) for d in sorted(by_day)]
    sizes = np.array([len(g) for g in groups])
    sums = np.array([g.sum() for g in groups])
    out = []
    for n in BAND_TRADES:
        means = np.empty(BAND_REPLICATIONS)
        draws = int(math.ceil(n / sizes.mean() * 3)) + 10
        for k in range(BAND_REPLICATIONS):
            pick = rng.integers(0, len(groups), draws)
            cs = np.cumsum(sizes[pick])
            last = int(np.searchsorted(cs, n))
            if last >= len(pick):      # not enough draws (never with the 3x margin; kept exact anyway)
                pick = np.concatenate([pick, rng.integers(0, len(groups), draws)])
                cs = np.cumsum(sizes[pick])
                last = int(np.searchsorted(cs, n))
            whole = sums[pick[:last]].sum()
            got = int(cs[last - 1]) if last else 0
            part = groups[pick[last]][: n - got].sum()
            means[k] = (whole + part) / n
        out.append({"trades": n, "p05_mean_R": float(np.percentile(means, 5)),
                    "p50_mean_R": float(np.percentile(means, 50))})
    return out


# ------------------------------------------------------------------ inputs
def load_trades(path):
    raw = gzip.open(path, "rb").read()
    doc = json.loads(raw)
    cols = doc.pop("_columns")
    return {sid: [dict(zip(cols, row)) for row in rows] for sid, rows in doc.items()}, hashlib.sha256(raw).hexdigest()


def adverse(row):
    """Fees, slippage and paid funding of one trade in R (tools/v9/evidence.trades_of adverse_cost_R)."""
    if row.get("adverse_cost_R") is not None:
        return float(row["adverse_cost_R"])
    fees = row["gross_R"] - row["net_R"] - row["funding_R"]
    return fees + max(0.0, row["funding_R"])


def definition_check(sid):
    """(a): the runtime definition equals the tested one, parameter by parameter; the legacy research that chose it
    started inside the design window."""
    import qexport
    import quant
    fn, kw = qexport.TESTED[sid][:2]
    defaults = {k: v.default for k, v in inspect.signature(fn).parameters.items() if v.default is not inspect._empty}
    tested = dict(defaults, **kw)
    runtime = quant.STRATS[sid]["params"]
    compared, mismatches = {}, []
    for k, v in sorted(runtime.items()):
        if k == "hold_h":
            want = tested.get("hold_days", 0) * 24
        elif k in tested:
            want = tested[k]
        elif (sid, k) in RESEARCH_CONSTANTS:
            want = RESEARCH_CONSTANTS[(sid, k)]
        else:
            want = None
        compared[k] = {"runtime": v, "tested": want}
        if want is None or float(want) != float(v):
            mismatches.append(k)
    for k, want in (("min_stop", "MIN_STOP"), ("max_stop", "MAX_STOP")):
        import qstrat
        compared[k] = {"runtime": quant.CFG[k], "tested": getattr(qstrat, want)}
        if float(quant.CFG[k]) != float(getattr(qstrat, want)):
            mismatches.append(k)
    research = json.load(open(os.path.join(ROOT, "quant_research.json")))
    window = research.get("window_3y") or [None, None]
    design_ok = isinstance(window[0], (int, float)) and window[0] >= DESIGN_START
    return {"pass": not mismatches and design_ok, "parameters": compared, "mismatches": mismatches,
            "legacy_research_window": window, "legacy_research_inside_design_window": design_ok}


def files_sha(paths):
    return {p: hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest() for p in paths}


# ------------------------------------------------------------------ the gate
def hypothesis(sid, side, sgn, trades, start, end):
    rows = [r for r in trades.get(sid) or [] if r["direction"] == sgn]
    net = np.array([r["net_R"] for r in rows], float)
    days = np.array([r["decision_time"] // 86400 for r in rows])
    dt = np.array([r["decision_time"] for r in rows])
    oos_start = start + (end - start) * (1 - SA.GATE["oos_fraction"])
    win = lambda m: clustered(net[m], days[m])  # noqa: E731
    stats = {"all": win(np.ones(len(rows), bool)), "holdout": win(dt < DESIGN_START),
             "design_window": win(dt >= DESIGN_START), "recent_third": win(dt >= oos_start)}
    for k in ("holdout", "design_window", "all"):
        stats[k]["p_one_sided"] = p_one_sided(stats[k])
    adv = np.array([adverse(r) for r in rows], float)
    stress = float(np.mean(net - (GATE["stress_multiplier"] - 1) * adv)) if len(rows) else None
    tw = [(r["net_R"] - r["twin_net_R"], r["decision_time"] // 86400) for r in rows if r.get("twin_net_R") is not None]
    twin = clustered([x[0] for x in tw], [x[1] for x in tw])
    assets = np.array([r["asset"] for r in rows])
    months = [datetime.fromtimestamp(r["decision_time"], timezone.utc).strftime("%Y-%m") for r in rows]
    conc = concentration(net, assets, months) if len(rows) else {}
    variants = {}
    for name in [GATE["proxy_variant"]] + [v for v, _ in GATE["delay_variants"]]:
        vr = [r for r in trades.get(f"{sid}@{name}") or [] if r["direction"] == sgn]
        vnet = np.array([r["net_R"] for r in vr], float)
        vdays = np.array([r["decision_time"] // 86400 for r in vr])
        vdt = np.array([r["decision_time"] for r in vr])
        variants[name] = {"available": f"{sid}@{name}" in trades,
                          "all": clustered(vnet, vdays), "holdout": clustered(vnet[vdt < DESIGN_START], vdays[vdt < DESIGN_START]),
                          "design_window": clustered(vnet[vdt >= DESIGN_START], vdays[vdt >= DESIGN_START])}
    return {"strategy_id": sid, "side": side, "trades": len(rows), "windows": stats, "cost_stress_1_5_mean_R": stress,
            "twin_edge": twin, "concentration": conc, "variants": variants,
            "_net": net, "_days": days}


def checks(h, definition, holm_p):
    g, w, c = GATE, h["windows"], h["concentration"]
    pos = lambda x: x is not None and x > 0  # noqa: E731
    cg = g["concentration"]
    out = {
        "a_definition_frozen": definition["pass"],
        "b_holdout_holm": pos(w["holdout"]["mean_R"]) and holm_p is not None and holm_p < g["holdout_holm_p_max"],
        "c_design_window": pos(w["design_window"]["mean_R"]) and w["design_window"]["p_one_sided"] is not None
                           and w["design_window"]["p_one_sided"] < g["design_p_max"],
        "d_recent_third": pos(w["recent_third"]["mean_R"]),
        "e_cost_stress": pos(h["cost_stress_1_5_mean_R"]),
        "f_twin_edge": pos(h["twin_edge"]["mean_R"]),
        "g_concentration": bool(c) and all(c.get(k) is not None for k in (
            "top1_positive_fraction", "top5_positive_fraction", "top10_positive_fraction", "month_positive_fraction",
            "leave_one_asset_out_min_mean_R"))
                           and c["top1_positive_fraction"] <= cg["max_top1_positive_fraction"]
                           and c["top5_positive_fraction"] <= cg["max_top5_positive_fraction"]
                           and c["top10_positive_fraction"] <= cg["max_top10_positive_fraction"]
                           and c["month_positive_fraction"] <= cg["max_month_positive_fraction"]
                           and c["leave_one_asset_out_min_mean_R"] > cg["leave_one_asset_out_min_mean_R"],
        "h_sample_size": h["trades"] >= g["min_trades"] and w["holdout"]["n"] >= g["min_holdout_trades"],
    }
    proxy = h["variants"][g["proxy_variant"]]
    out["i_deployable_universe"] = (proxy["available"] and pos(proxy["holdout"]["mean_R"])
                                    and pos(proxy["design_window"]["mean_R"]))
    window_h, delays = 0, {}
    for name, hours in g["delay_variants"]:
        v = h["variants"][name]
        ok = v["available"] and pos(v["all"]["mean_R"]) and pos(v["holdout"]["mean_R"])
        delays[name] = ok
        if all(delays.values()):        # this delay and every shorter one pass
            window_h = hours
    out["j_late_entry"] = delays.get(g["delay_variants"][0][0], False)
    return out, window_h, delays


def build(evidence_dir, out_path=None, evidence_commit=None):
    ev_raw = open(os.path.join(evidence_dir, "evidence.json"), "rb").read()
    ev = json.loads(ev_raw)
    if ev.get("schema") != EVIDENCE_SCHEMA:
        raise SystemExit(f"evidence schema {ev.get('schema')!r}: {EVIDENCE_SCHEMA} required (it has the "
                         "deployable-universe and late-entry variants)")
    trades, trades_sha = load_trades(os.path.join(evidence_dir, "trades.json.gz"))
    if evidence_commit is None and os.path.exists(os.path.join(evidence_dir, "run_meta.txt")):
        meta = open(os.path.join(evidence_dir, "run_meta.txt")).read().split()
        evidence_commit = meta[1] if len(meta) > 1 else None
    start = int(ev["data"]["first_bar"]) + int(ev["warmup_days"]) * 86400
    end = int(ev["data"]["last_bar"]) + 14400
    policy = json.load(open(SP.PATH))
    runtime = [r["strategy_id"] for r in policy["strategies"]]
    hyps = [hypothesis(sid, side, sgn, trades, start, end) for sid in runtime for side, sgn in SIDES]
    holm_p = holm([h["windows"]["holdout"]["p_one_sided"] for h in hyps])
    defs = {sid: definition_check(sid) for sid in runtime}
    rng = np.random.default_rng(BAND_SEED)
    import quant
    out_h = []
    for h, hp in zip(hyps, holm_p):
        ck, window_h, delays = checks(h, defs[h["strategy_id"]], hp)
        failing = sorted(k for k, v in ck.items() if not v)
        verdict = "CONFIRMED" if not failing else "NOT_CONFIRMED"
        row = {k: v for k, v in h.items() if not k.startswith("_")}
        row.update(holdout_holm_p=hp, checks=ck, failing=failing, verdict=verdict,
                   late_entry={"passes": delays, "trade_window_hours": window_h if verdict == "CONFIRMED" else 0},
                   runtime_definition_hash=SP.digest(quant.STRATS[h["strategy_id"]]))
        if verdict == "CONFIRMED":
            row["expectation"] = {"out_of_sample_mean_R": h["windows"]["holdout"]["mean_R"],
                                  "out_of_sample_lower_95": h["windows"]["holdout"]["lower_95"],
                                  "out_of_sample_upper_95": h["windows"]["holdout"]["upper_95"],
                                  "all_windows_mean_R": h["windows"]["all"]["mean_R"],
                                  "all_windows_lower_95": h["windows"]["all"]["lower_95"],
                                  "all_windows_upper_95": h["windows"]["all"]["upper_95"],
                                  "basis": "archive net R per trade (costs and observed funding included), "
                                           "out of sample = 2020-01..2023-09, before the strategy was designed"}
            row["demotion_band"] = {"rule": "after n >= 30 closed forward-test trades: demote when their mean R is "
                                            "below p05_mean_R of the largest tabulated n not above the live n",
                                    "min_trades": BAND_TRADES[0], "resampling": "whole days, with replacement",
                                    "replications": BAND_REPLICATIONS, "seed": BAND_SEED,
                                    "table": demotion_band(h["_net"], h["_days"], rng)}
        out_h.append(row)
    doc = {
        "schema": VERSION, "as_of": int(ev["generated_at"]),
        "statement": "Archive confirmation of runtime strategy sides for the v9 probation tier. A CONFIRMED side may "
                     "be deployed only as ACTIVE_PROBATION at a reduced size, after its forward test is registered; "
                     "this file itself grants nothing (the reviewed policy binds it by hash).",
        "disclosure": "The gate (a)-(h) was written after a first look at the archive results; (i) and (j) were "
                      "written before their first measurement. The protection is the reduced size, the forward test "
                      "registered before the first probation trade and automatic demotion, not the backtest alone.",
        "gate": GATE, "design_window_start": DESIGN_START, "holdout": [start, DESIGN_START], "window": [start, end],
        "family": {"hypotheses": [f"{h['strategy_id']}:{h['side']}" for h in hyps],
                   "rule": "every side of every strategy with a live implementation (v8/quant_strategy_policy.json); "
                           "Holm over the holdout one-sided p-values",
                   "catalogue_examined": [c["strategy_id"] for c in ev.get("candidates") or []]},
        "hypotheses": out_h,
        "confirmed": [f"{h['strategy_id']}:{h['side']}" for h in out_h if h["verdict"] == "CONFIRMED"],
        "definitions": defs,
        "inputs": {"evidence_schema": ev["schema"], "evidence_sha256": hashlib.sha256(ev_raw).hexdigest(),
                   "trades_sha256": trades_sha, "dataset_sha256": (ev.get("provenance") or {}).get("dataset_sha256"),
                   "evidence_generated_at": ev.get("generated_at"), "evidence_commit": evidence_commit,
                   "archive_end": (ev.get("provenance") or {}).get("archive_end"),
                   "costs": ev.get("costs"), "panel_coins": (ev.get("data") or {}).get("panel_coins"),
                   "delisted_research_coins": ((ev.get("data") or {}).get("counts") or {}).get("delisted_research_coins")},
        "code": {"confirm": files_sha(["tools/v9/confirm.py"])["tools/v9/confirm.py"],
                 "research": files_sha(RESEARCH_CODE),
                 "runtime_implementation_files": list(SP.RUNTIME_IMPLEMENTATION_FILES),
                 "runtime_implementation_hash": SP.runtime_implementation_hash()},
        "authority": "NONE: evidence only; deployment is the reviewed policy's decision",
    }
    raw = canonical(doc)
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(raw)
    return doc, raw


def canonical(doc):
    """Canonical bytes: sorted keys, two-space indent for review, no NaN, newline at the end."""
    return (json.dumps(doc, sort_keys=True, indent=1, allow_nan=False,
                       default=lambda x: x.item() if hasattr(x, "item") else None) + "\n").encode()


def from_branch(branch):
    """Extract the evidence files of the latest run on a results branch into a temporary folder."""
    tmp = tempfile.mkdtemp(prefix="evidence-")
    subprocess.run(["git", "fetch", "-q", "origin", branch], cwd=ROOT, check=True)
    commit = subprocess.run(["git", "rev-parse", f"origin/{branch}"], cwd=ROOT, check=True, capture_output=True,
                            text=True).stdout.strip()
    for name in ("evidence.json", "trades.json.gz", "run_meta.txt"):
        data = subprocess.run(["git", "show", f"origin/{branch}:{name}"], cwd=ROOT, capture_output=True).stdout
        with open(os.path.join(tmp, name), "wb") as fh:
            fh.write(data)
    return tmp, commit


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", help="folder with evidence.json and trades.json.gz")
    ap.add_argument("--from-branch", help="read the evidence run from this results branch (e.g. evidence-results)")
    ap.add_argument("--out", default=os.path.join(ROOT, OUT))
    a = ap.parse_args(argv)
    if not a.evidence and not a.from_branch:
        ap.error("--evidence or --from-branch")
    folder = a.evidence
    if a.from_branch:
        folder, _ = from_branch(a.from_branch)
    doc, raw = build(folder, a.out)
    print(f"wrote {a.out} ({len(raw)} bytes, sha256 {hashlib.sha256(raw).hexdigest()})")
    for h in doc["hypotheses"]:
        w = h["windows"]
        print(f"{h['strategy_id']:10s} {h['side']:5s} {h['verdict']:13s} holdout {w['holdout']['mean_R']:+.3f} "
              f"(Holm p {h['holdout_holm_p']:.4f}) design {w['design_window']['mean_R']:+.3f} "
              f"(p {w['design_window']['p_one_sided']:.4f}) window {h['late_entry']['trade_window_hours']}h "
              f"failing {','.join(h['failing']) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
