"""Register the forward test of an archive-confirmed strategy side in the shadow ledger (append-only, authority NONE).

    python tools/v9/register_forward_test.py --strategy XSMOM --side long --risk-multiplier 0.5

The registration must exist before the side's first probation trade (docs/v9/HANDOVER.md, B2). It records what is
tested (the runtime parameters, the side, the size multiplier), the evidence it rests on (the probation evidence file
and the archive dataset, by hash), from which commit, the forward-only evaluation start (the next 00:00 UTC daily
close after registration: the side's first signal that can count) and the pass and fail rules, including the
demotion band. The reviewed policy then binds this record by its SHA-256 (v8/strategy_policy.py)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from v8 import shadow_ledger as SL  # noqa: E402

DAY = 86400
EVIDENCE = os.path.join("research", "v9", "probation_evidence.json")


def experiment_id(strategy, side, n=1):
    return f"V9-PROBATION-{strategy}-{side.upper()}-{n}"


def registration(strategy, side, risk_multiplier, now, commit, root=ROOT):
    raw = open(os.path.join(root, EVIDENCE), "rb").read()
    ev = json.loads(raw)
    rows = [h for h in ev["hypotheses"] if h["strategy_id"] == strategy and h["side"] == side]
    if len(rows) != 1 or rows[0]["verdict"] != "CONFIRMED":
        raise SystemExit(f"{strategy} {side} is not CONFIRMED in {EVIDENCE}: nothing to register")
    h = rows[0]
    sys.path.insert(0, root)
    import quant
    start = (now // DAY + 1) * DAY          # the next 00:00 UTC daily close: the first signal that can count
    params = {"strategy_id": strategy, "side": side, "runtime_params": quant.STRATS[strategy]["params"],
              "risk_multiplier": risk_multiplier, "trade_window_hours": h["late_entry"]["trade_window_hours"],
              "evidence_sha256": hashlib.sha256(raw).hexdigest(), "dataset_sha256": ev["inputs"]["dataset_sha256"]}
    exp = h["expectation"]
    band = h["demotion_band"]
    return {
        "experiment_id": experiment_id(strategy, side), "registered_at": int(now), "registration_commit": commit,
        "name": f"{strategy} {side} on probation: forward test of the archive-confirmed side",
        "params": params, "param_hash": SL.param_hash(params),
        "code_files": ["quant.py"], "code_hash": SL.files_hash(root, ["quant.py"]),
        "data_cutoff": int(ev["window"][1]), "evaluation_start": int(start), "evaluation_end": None,
        "universe_history_version": "quant.py live universe at each scan (scanner crypto universe on the trade DEXs, "
                                    "v8.identity/4), recorded in the scan's quant audit",
        "cost_model_version": "quant.py paper trades: taker fee and the liquidity slippage tier on both sides, "
                              "funding as recorded by the journal",
        "hypothesis": (f"{strategy} {side} paper trades on the live universe have a positive mean net R. Archive "
                       f"expectation per trade: {exp['out_of_sample_mean_R']:+.3f}R out of sample (95% interval "
                       f"{exp['out_of_sample_lower_95']:+.3f} to {exp['out_of_sample_upper_95']:+.3f}), "
                       f"{exp['all_windows_mean_R']:+.3f}R over every window."),
        "primary_metric": f"mean net R (journal r) of closed {strategy} {side} paper trades entered at or after "
                          "evaluation_start",
        "secondary_metrics": ["closed trades and days covered", "win rate",
                              "mean R of qualified trades (entry-time identity, execution path and funding proof)",
                              "worst cumulative drawdown in R", "mean R against the archive median for the same n"],
        "pass_rule": "after at least 100 closed trades and 180 days: mean R > 0 and day-clustered 95% lower bound > 0. "
                     "Passing only makes the side eligible for the full Phase 9 requalification review; nothing is "
                     "promoted automatically.",
        "fail_rule": (f"after at least {band['min_trades']} closed trades: mean R below the archive's 5th-percentile "
                      "band for the largest tabulated n not above the live n (demotion_band in the evidence file). "
                      "The desk then caps the side at WATCH (PROBATION_FORWARD_TEST_FAILED); a FAILED status record "
                      "follows."),
        "status": "REGISTERED",
        "multiple_testing": {
            "family": ev["family"]["hypotheses"],
            "variants_tried_before_registration": 2 * len(ev["family"]["catalogue_examined"]),
            "variant_ids": [f"{c}:{s}" for c in ev["family"]["catalogue_examined"] for s in ("long", "short")],
            "selection": "Holm over the six runtime side hypotheses on the 2020-01..2023-09 holdout, then the design "
                         "window, recent third, cost stress, random twin, concentration, deployable-universe proxy and "
                         "late-entry checks (research/v9/probation_evidence.json)",
            "corrections_planned": ["Holm (applied)", "forward test with a demotion band",
                                    "Phase 9 gate (DSR, PBO, SPA, matched controls) before any full requalification"]},
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--side", required=True, choices=("long", "short"))
    ap.add_argument("--risk-multiplier", type=float, required=True)
    ap.add_argument("--commit", help="registration commit (default: HEAD)")
    ap.add_argument("--now", type=int, help="registration time (default: now)")
    a = ap.parse_args(argv)
    if not 0 < a.risk_multiplier <= 0.5:
        raise SystemExit("a probation risk multiplier is in (0, 0.5]")
    commit = a.commit or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True,
                                        text=True).stdout.strip()
    rec = registration(a.strategy, a.side, a.risk_multiplier, a.now or int(time.time()), commit)
    name, r = SL.append(os.path.join(ROOT, SL.DIR), SL.REGISTRATION, **rec)
    raw = open(os.path.join(ROOT, SL.DIR, name), "rb").read()
    print(f"registered {r['experiment_id']} as {SL.DIR}/{name} (sha256 {hashlib.sha256(raw).hexdigest()}); "
          f"evaluation starts {r['evaluation_start']}")
    problems = SL.validate(os.path.join(ROOT, SL.DIR))
    if problems:
        raise SystemExit("ledger invalid: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
