"""Phase D2 evidence: the pre-registered XS_TOP_DIV and XS_CROWD_FADE, tested once on the survivorship-free archive
with Binance's metrics.

    python tools/v9/evidence_d2.py --md md_bn --metrics md_metrics --out evidence_d2 [--phase-b-evidence FILE]

The definitions are in tools/v9/d2.py, pre-registered in docs/v9/phase-d2-preregistration.md before any test on
market data. The method is D1's (tools/v9/evidence_d1.py):
- the phase B probation gate, checks (b) to (j); the Holm family is these four sides;
- each side is simulated on every eligible coin, on the 80 most traded coins (i), and entered 4h, 8h, 12h and 24h
  late (j), with the evidence engine's trade rules and costs.

The data section records:
- the phase B dataset fingerprint, to show the candles and funding are phase B's;
- the metrics fingerprint and provenance digest;
- the coverage, meaning the share of eligible coin-days that had a signal value.

Output: evidence_d2.json (v9.d2-evidence/1), trades_d2.json.gz and REPORT_D2.md. Research only: a CONFIRMED side is
a candidate for the probation tier, never a trade by itself."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "research"))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import qstrat  # noqa: E402
import confirm as C  # noqa: E402
import d2  # noqa: E402
import evidence as EV  # noqa: E402

VERSION = "v9.d2-evidence/1"
PREREG = os.path.join("docs", "v9", "phase-d2-preregistration.md")
SIDES = (("long", 1), ("short", -1))
SIGNALS = {"XS_TOP_DIV": lambda p: d2.lagged_mean(p, d2._ln(p.m["top_pos_ls"]) - d2._ln(p.m["acct_ls"])),
           "XS_CROWD_FADE": lambda p: d2.lagged_mean(p, d2._ln(p.m["acct_ls"]))}


def _hash(arrays):
    h = hashlib.sha256()
    for arr in arrays:
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def coverage(p, F, start):
    """Per strategy: eligible coin-days from `start`, how many had a signal value, and the first day with one."""
    end = F.bd["end"]
    keep = p.t[end] + p.bar >= start
    elig = F.elig[end][keep]
    out = {}
    for sid, fn in SIGNALS.items():
        has = np.isfinite(fn(p)[end][keep]) & elig
        days = np.where(has.any(axis=1))[0]
        out[sid] = {"eligible_coin_days": int(elig.sum()), "with_signal": int(has.sum()),
                    "share": float(has.sum() / elig.sum()) if elig.sum() else None,
                    "first_day": int(p.t[end][keep][days[0]] + p.bar) if len(days) else None}
    return out


def run(md, metrics, out, phase_b=None):
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    uni = json.load(open(os.path.join(md, "universe.json")))
    universe = {c["t"]: c for c in uni["coins"]}
    p = d2.D2Panel(md, metrics)
    F = qstrat.Feat(p)
    F_top = copy.copy(F)
    F_top.elig = EV.top_n_eligibility(F)
    start = int(p.t[0]) + EV.WARMUP_DAYS * 86400
    end = int(p.t[-1]) + EV.BAR
    dataset = _hash((p.t, p.o, p.h, p.l, p.c, p.v, p.fund))
    mhash = _hash(p.m[k] for k in d2.METRICS)
    meta_path = os.path.join(metrics, "meta.json")
    mmeta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}
    cov = coverage(p, F, start)
    print(f"panel {p.T} x {p.N} ({time.time() - t0:.0f}s); metrics for {p.metrics_coins} coins; dataset {dataset[:12]}; "
          f"coverage " + ", ".join(f"{k} {v['share']:.0%}" if v["share"] is not None else f"{k} none" for k, v in cov.items()),
          flush=True)
    trades = {}
    for sid, (fn, kw) in d2.STRATEGIES.items():
        for name, FF, delay in [("", F, 0), (f"@top{EV.TOP_N}", F_top, 0)] + [(f"@delay{k}", F, k) for k in EV.DELAYS]:
            _, rows = EV.trades_of(p, FF, sid, fn, kw, universe, delay=delay)
            trades[sid + name] = [r for r in rows if r["decision_time"] >= start]
            print(f"  {sid + name:24s} trades {len(trades[sid + name]):6d} ({time.time() - t0:.0f}s)", flush=True)
    hyps = [C.hypothesis(sid, side, sgn, trades, start, end) for sid in d2.STRATEGIES for side, sgn in SIDES]
    holm = C.holm([h["windows"]["holdout"]["p_one_sided"] for h in hyps])
    prereg = open(os.path.join(ROOT, PREREG), "rb").read()
    definition = {"pass": True, "preregistration": PREREG, "preregistration_sha256": hashlib.sha256(prereg).hexdigest(),
                  "rule": "definitions fixed in the pre-registration commit before this run"}
    out_h = []
    for h, hp in zip(hyps, holm):
        ck, window_h, delays = C.checks(h, definition, hp)
        failing = sorted(k for k, v in ck.items() if not v)
        row = {k: v for k, v in h.items() if not k.startswith("_")}
        row.update(holdout_holm_p=hp, checks=ck, failing=failing, verdict="CONFIRMED" if not failing else "NOT_CONFIRMED",
                   late_entry={"passes": delays, "trade_window_hours": window_h if not failing else 0})
        out_h.append(row)
    pb = None
    if phase_b and os.path.exists(phase_b):
        pb = (json.load(open(phase_b)).get("provenance") or {}).get("dataset_sha256")
    doc = {"schema": VERSION, "generated_at": int(time.time()), "seconds": round(time.time() - t0, 1),
           "preregistration": definition, "gate": C.GATE, "design_window_start": C.DESIGN_START,
           "window": [start, end], "family": [f"{h['strategy_id']}:{h['side']}" for h in out_h],
           "lag_bars": d2.LAG_BARS, "window_bars": d2.WINDOW_BARS, "min_bars": d2.MIN_BARS,
           "data": {"panel_coins": p.N, "bars": p.T, "first_bar": int(p.t[0]), "last_bar": int(p.t[-1]),
                    "archive_end": uni.get("archive_end_month"), "counts": uni.get("counts"),
                    "dataset_sha256": dataset, "phase_b_dataset_sha256": pb,
                    "same_dataset_as_phase_b": (pb == dataset) if pb else None,
                    "metrics_coins": p.metrics_coins, "metrics_sha256": mhash,
                    "metrics_schema": mmeta.get("schema"), "metrics_provenance_sha256": (mmeta.get("provenance") or {}).get("overall_sha256"),
                    "metrics_files": (mmeta.get("provenance") or {}).get("files"), "coverage": cov},
           "costs": {"taker_fee": 0.00045, "slippage_each_way": EV.SLIP, "funding": "observed Binance settlements"},
           "hypotheses": out_h, "confirmed": [f"{h['strategy_id']}:{h['side']}" for h in out_h if h["verdict"] == "CONFIRMED"]}
    with open(os.path.join(out, "evidence_d2.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, default=lambda x: x.item() if hasattr(x, "item") else None)
    keep = ("asset", "decision_time", "exit_time", "direction", "net_R", "gross_R", "funding_R", "twin_net_R", "reason",
            "adverse_cost_R", "delisted")
    with gzip.open(os.path.join(out, "trades_d2.json.gz"), "wt") as fh:
        json.dump({k: [[r[c] for c in keep] for r in v] for k, v in trades.items()} | {"_columns": list(keep)}, fh,
                  separators=(",", ":"))
    report(doc, os.path.join(out, "REPORT_D2.md"))
    print(f"done in {time.time() - t0:.0f}s; confirmed: {doc['confirmed'] or 'none'}")
    return doc


def fmt(x, d=3):
    return "–" if x is None else f"{x:+.{d}f}"


def report(doc, path):
    data = doc["data"]
    same = {True: "the same candles and funding as phase B", False: "NOT the candles and funding phase B used",
            None: "phase B's dataset digest not available"}[data.get("same_dataset_as_phase_b")]
    day = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else "–"  # noqa: E731
    L = ["# Phase D2: pre-registered positioning hypotheses (Binance metrics) on the survivorship-free archive", "",
         f"Pre-registration: `{doc['preregistration']['preregistration']}` (sha256 "
         f"{doc['preregistration']['preregistration_sha256'][:12]}). {data['panel_coins']} coins, "
         f"{datetime.fromtimestamp(doc['window'][0], timezone.utc):%Y-%m} to "
         f"{datetime.fromtimestamp(doc['window'][1], timezone.utc):%Y-%m}. Holm over the four sides in the holdout. "
         f"Signals use the metrics through the previous UTC day ({doc['lag_bars']} bars of lag).", "",
         f"Data: dataset sha256 {data['dataset_sha256'][:12]} ({same}); metrics for {data['metrics_coins']} coins "
         f"(sha256 {data['metrics_sha256'][:12]}, {data.get('metrics_files') or '–'} daily files).", ""]
    for sid, c in data["coverage"].items():
        L.append(f"- {sid}: a signal value on {c['with_signal']} of {c['eligible_coin_days']} eligible coin-days "
                 f"({(c['share'] or 0):.0%}), from {day(c['first_day'])}.")
    L += ["", "| Side | Verdict | Trades | All | Holdout (Holm p) | Design window (p) | Recent third | Cost x1.5 | Twin edge | Top-80 holdout / design | Late 4h/8h/12h/24h | Failing |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in doc["hypotheses"]:
        w = h["windows"]
        v = h["variants"]
        late = " / ".join(fmt(v[k]["all"]["mean_R"], 2) for k in ("delay1", "delay2", "delay3", "delay6"))
        dp = w["design_window"]["p_one_sided"]
        L.append(f"| {h['strategy_id']} {h['side']} | {h['verdict']} | {h['trades']} | {fmt(w['all']['mean_R'])} | "
                 f"{fmt(w['holdout']['mean_R'])} ({h['holdout_holm_p']:.3f}) | {fmt(w['design_window']['mean_R'])} "
                 f"({dp if dp is None else f'{dp:.3f}'}) | "
                 f"{fmt(w['recent_third']['mean_R'])} | {fmt(h['cost_stress_1_5_mean_R'])} | {fmt(h['twin_edge']['mean_R'])} | "
                 f"{fmt(v['top80']['holdout']['mean_R'])} / {fmt(v['top80']['design_window']['mean_R'])} | {late} | "
                 f"{', '.join(h['failing']) or '-'} |")
    L += ["", "A CONFIRMED side is a candidate for the probation tier only: it needs a runtime implementation (reading "
          "the daily metrics files with the same one-day lag), re-bound evidence, a forward-test registration before its "
          "first trade and the owner's merge."]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="md_bn")
    ap.add_argument("--metrics", default="md_metrics")
    ap.add_argument("--out", default="evidence_d2")
    ap.add_argument("--phase-b-evidence", default=None, help="phase B's evidence.json, to compare dataset digests")
    a = ap.parse_args(argv)
    run(a.md, a.metrics, a.out, a.phase_b_evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
