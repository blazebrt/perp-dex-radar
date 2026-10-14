"""Phase D1 evidence: the pre-registered XS_FUND_FADE and XS_FLOW_MOM tested once on the survivorship-free archive.

    python tools/v9/evidence_d1.py --md md_bn --out evidence_d1

The definitions are tools/v9/d1.py, pre-registered in docs/v9/phase-d1-preregistration.md before any test. The gate
is the phase B probation gate, checks (b) to (j). Check (a) holds by the pre-registration's commit order, and this run
records the pre-registration's sha256. The Holm family is these four side hypotheses. Each side is simulated three
ways, with the evidence engine's trade rules and costs:

- on every eligible coin;
- on the deployable-universe proxy, the 80 most traded coins (i);
- entered 4h, 8h, 12h and 24h late (j).

Output: evidence_d1.json (v9.d1-evidence/1, every statistic and verdict), trades_d1.json.gz and REPORT_D1.md.
Research only: a CONFIRMED side is a candidate for the probation tier, never a trade by itself."""
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
import d1  # noqa: E402
import evidence as EV  # noqa: E402

VERSION = "v9.d1-evidence/1"
PREREG = os.path.join("docs", "v9", "phase-d1-preregistration.md")
SIDES = (("long", 1), ("short", -1))


def run(md, out, phase_b=None):
    """phase_b: phase B's evidence.json (the evidence-results branch), to record whether both ran on one dataset."""
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    uni = json.load(open(os.path.join(md, "universe.json")))
    universe = {c["t"]: c for c in uni["coins"]}
    p = d1.D1Panel(md)
    F = qstrat.Feat(p)
    F_top = copy.copy(F)
    F_top.elig = EV.top_n_eligibility(F)
    # the phase B fingerprint (tools/v9/evidence.py): equal digests mean the same candles and funding as phase B
    dataset = hashlib.sha256()
    for arr in (p.t, p.o, p.h, p.l, p.c, p.v, p.fund):
        dataset.update(np.ascontiguousarray(arr).tobytes())
    extra = hashlib.sha256()
    for arr in (p.tb, p.fund_n):
        extra.update(np.ascontiguousarray(arr).tobytes())
    traded = np.isfinite(p.c) & (p.v > 0)
    print(f"panel {p.T} x {p.N} ({time.time() - t0:.0f}s); taker volume known on {int(np.isfinite(p.tb[traded]).sum())} "
          f"of {int(traded.sum())} traded bars; funding settlements {int(p.fund_n.sum())}; dataset {dataset.hexdigest()[:12]}",
          flush=True)
    start = int(p.t[0]) + EV.WARMUP_DAYS * 86400
    end = int(p.t[-1]) + EV.BAR
    trades = {}
    for sid, (fn, kw) in d1.STRATEGIES.items():
        for name, FF, delay in [("", F, 0), (f"@top{EV.TOP_N}", F_top, 0)] + [(f"@delay{k}", F, k) for k in EV.DELAYS]:
            _, rows = EV.trades_of(p, FF, sid, fn, kw, universe, delay=delay)
            trades[sid + name] = [r for r in rows if r["decision_time"] >= start]
            print(f"  {sid + name:22s} trades {len(trades[sid + name]):6d} ({time.time() - t0:.0f}s)", flush=True)
    hyps = [C.hypothesis(sid, side, sgn, trades, start, end) for sid in d1.STRATEGIES for side, sgn in SIDES]
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
    doc = {"schema": VERSION, "generated_at": int(time.time()), "seconds": round(time.time() - t0, 1),
           "preregistration": definition, "gate": C.GATE, "design_window_start": C.DESIGN_START,
           "window": [start, end], "family": [f"{h['strategy_id']}:{h['side']}" for h in out_h],
           "data": {"panel_coins": p.N, "bars": p.T, "first_bar": int(p.t[0]), "last_bar": int(p.t[-1]),
                    "archive_end": uni.get("archive_end_month"), "counts": uni.get("counts"),
                    "dataset_sha256": dataset.hexdigest(), "d1_inputs_sha256": extra.hexdigest(),
                    "traded_bars": int(traded.sum()), "traded_bars_with_taker_volume": int(np.isfinite(p.tb[traded]).sum()),
                    "funding_settlements": int(p.fund_n.sum()), "phase_b_dataset_sha256": None,
                    "same_dataset_as_phase_b": None},
           "costs": {"taker_fee": 0.00045, "slippage_each_way": EV.SLIP, "funding": "observed Binance settlements"},
           "hypotheses": out_h, "confirmed": [f"{h['strategy_id']}:{h['side']}" for h in out_h if h["verdict"] == "CONFIRMED"]}
    if phase_b and os.path.exists(phase_b):
        pb = (json.load(open(phase_b)).get("provenance") or {}).get("dataset_sha256")
        doc["data"].update(phase_b_dataset_sha256=pb, same_dataset_as_phase_b=pb == dataset.hexdigest() if pb else None)
    with open(os.path.join(out, "evidence_d1.json"), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True, default=lambda x: x.item() if hasattr(x, "item") else None)
    keep = ("asset", "decision_time", "exit_time", "direction", "net_R", "gross_R", "funding_R", "twin_net_R", "reason",
            "adverse_cost_R", "delisted")
    with gzip.open(os.path.join(out, "trades_d1.json.gz"), "wt") as fh:
        json.dump({k: [[r[c] for c in keep] for r in v] for k, v in trades.items()} | {"_columns": list(keep)}, fh,
                  separators=(",", ":"))
    report(doc, os.path.join(out, "REPORT_D1.md"))
    print(f"done in {time.time() - t0:.0f}s; confirmed: {doc['confirmed'] or 'none'}")
    return doc


def fmt(x, d=3):
    return "–" if x is None else f"{x:+.{d}f}"


def report(doc, path):
    data = doc["data"]
    same = {True: "the same dataset as phase B", False: "NOT the dataset phase B used",
            None: "phase B's dataset digest not available"}[data.get("same_dataset_as_phase_b")]
    L = ["# Phase D1: pre-registered funding and taker-flow hypotheses on the survivorship-free archive", "",
         f"Pre-registration: `{doc['preregistration']['preregistration']}` (sha256 "
         f"{doc['preregistration']['preregistration_sha256'][:12]}). {data['panel_coins']} coins, "
         f"{datetime.fromtimestamp(doc['window'][0], timezone.utc):%Y-%m} to "
         f"{datetime.fromtimestamp(doc['window'][1], timezone.utc):%Y-%m}. Holm over the four sides in the holdout.", "",
         f"Data: dataset sha256 {data['dataset_sha256'][:12]} ({same}); taker volume on "
         f"{data['traded_bars_with_taker_volume']} of {data['traded_bars']} traded bars; "
         f"{data['funding_settlements']} funding settlements.", "",
         "| Side | Verdict | Trades | All | Holdout (Holm p) | Design window (p) | Recent third | Cost x1.5 | Twin edge | Top-80 holdout / design | Late 4h/8h/12h/24h | Failing |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for h in doc["hypotheses"]:
        w = h["windows"]
        v = h["variants"]
        late = " / ".join(fmt(v[k]["all"]["mean_R"], 2) for k in ("delay1", "delay2", "delay3", "delay6"))
        L.append(f"| {h['strategy_id']} {h['side']} | {h['verdict']} | {h['trades']} | {fmt(w['all']['mean_R'])} | "
                 f"{fmt(w['holdout']['mean_R'])} ({h['holdout_holm_p']:.3f}) | {fmt(w['design_window']['mean_R'])} "
                 f"({(w['design_window']['p_one_sided'] if w['design_window']['p_one_sided'] is not None else float('nan')):.3f}) | "
                 f"{fmt(w['recent_third']['mean_R'])} | {fmt(h['cost_stress_1_5_mean_R'])} | {fmt(h['twin_edge']['mean_R'])} | "
                 f"{fmt(v['top80']['holdout']['mean_R'])} / {fmt(v['top80']['design_window']['mean_R'])} | {late} | "
                 f"{', '.join(h['failing']) or '-'} |")
    L += ["", "A CONFIRMED side is a candidate for the probation tier only: it needs a runtime implementation, re-bound "
          "evidence, a forward-test registration before its first trade and the owner's merge."]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="md_bn")
    ap.add_argument("--out", default="evidence_d1")
    ap.add_argument("--phase-b-evidence", default=None, help="phase B's evidence.json, to compare dataset digests")
    a = ap.parse_args(argv)
    run(a.md, a.out, a.phase_b_evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
