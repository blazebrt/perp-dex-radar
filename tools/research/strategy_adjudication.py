"""Phase 9 research job: all canonical candidates, governed PIT trades, no runtime mutation.

python tools/research/strategy_adjudication.py --md md --history hist_prod --cutoff UNIX --out .
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import tracemalloc

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import strategy_census as census
import multiple_testing as MT
import matched_controls as MC
import pit_cost as PC
import pit_sim as PS
from v8 import history as H, pit as PIT, shadow_ledger as SL
from v8 import strategy_authority as SA, strategy_policy as SP


def save(folder, name, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    (folder / name).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def clustered(rows, key="net_R"):
    """Day-clustered sandwich SE of the trade-weighted mean; no iid-trade t-test.

    Small samples are unavailable. 1.96 is used only with >=30 distinct day clusters.
    """
    if not rows:
        return {"n": 0, "mean_R": None, "lower_95": None, "upper_95": None, "se": None, "days": 0}
    values = np.asarray([r[key] for r in rows], float)
    mean = float(values.mean())
    days = sorted({r["decision_time"] // 86400 for r in rows})
    out = {"n": len(rows), "mean_R": mean, "days": len(days), "lower_95": None, "upper_95": None, "se": None}
    if len(days) >= 30:
        residual = [sum(r[key] - mean for r in rows if r["decision_time"] // 86400 == d) for d in days]
        se = math.sqrt(len(days) / (len(days) - 1) * sum(r * r for r in residual)) / len(rows)
        out.update(se=se, lower_95=mean - 1.96 * se, upper_95=mean + 1.96 * se)
    return out


def robustness(rows, start, end):
    if not rows:
        return {"oos": clustered([]), "sides": {s: clustered([]) for s in ("long", "short")},
                "cost_stress": {str(k): None for k in (1.0, 1.5, 2.0)}, "slices": {}, "concentration": {}}
    oos_start = start + (end - start) * (1 - SA.GATE["oos_fraction"])
    slices = {}
    for dim in ("btc_trend", "volatility", "liquidity", "funding", "listing_age", "calendar_month"):
        keys = sorted({str(r.get(dim, "UNKNOWN")) for r in rows})
        slices[dim] = {k: clustered([r for r in rows if str(r.get(dim, "UNKNOWN")) == k]) for k in keys}
    positive = sorted((max(0.0, r["net_R"]) for r in rows), reverse=True)
    total = sum(positive)
    assets = sorted({r["asset"] for r in rows})
    leave = {a: clustered([r for r in rows if r["asset"] != a])["mean_R"] for a in assets}
    monthly = {}
    for r in rows:
        key = r["calendar_month"]
        monthly[key] = monthly.get(key, 0) + max(0.0, r["net_R"])
    concentration = {f"top{k}_positive_fraction": sum(positive[:k]) / total if total else None for k in (1, 5, 10)}
    concentration.update(leave_one_asset_out=leave,
                         leave_one_asset_out_min_mean_R=min((v for v in leave.values() if v is not None), default=None),
                         month_positive_fraction=max(monthly.values()) / total if total else None,
                         winner_fraction=sum(r["net_R"] > 0 for r in rows) / len(rows),
                         positive_R=total, net_R=sum(r["net_R"] for r in rows))
    return {"oos": clustered([r for r in rows if r["decision_time"] >= oos_start]),
            "oos_start": oos_start, "sides": {side: clustered([r for r in rows if r["direction"] == d])
                                              for side, d in (("long", 1), ("short", -1))},
            # Stress adverse funding payments and fees/slippage; never amplify a funding credit as a benefit.
            "cost_stress": {str(k): float(np.mean([r["net_R"] - (k - 1) * r["adverse_cost_R"] for r in rows]))
                            for k in (1.0, 1.5, 2.0)}, "slices": slices, "concentration": concentration}


def registration_plan(catalog, trial_census, cutoff):
    return {"schema": "v8.strategy-registration-plan/1", "authority": "NONE", "state": "PLAN_NOT_REGISTERED",
            "entries": [{"experiment_id": "PHASE9-" + c["strategy_id"], "strategy_id": c["strategy_id"],
                         "params": c["params"], "parameter_hash": c["parameter_hash"], "code_hash": c["code_hash"],
                         "code_files": c["code_files"], "family": c["family"], "data_cutoff": cutoff,
                         "evaluation_start": None, "start_rule": "AFTER_AUTHORITATIVE_MAIN_REGISTRATION_COMMIT",
                         "evaluation_horizon_days": 180, "minimum_qualified_closed_trades": 100,
                         "primary_metric": "day_clustered_95_lower_net_mean_R", "secondary_metrics": list(SA.GATE),
                         "pass_rule": SA.GATE, "fail_rule": "failed complete gate => REJECTED; missing => INSUFFICIENT_EVIDENCE",
                         "multiple_testing_family": "ALL_PHASE9_CANDIDATES_AND_KNOWN_HISTORICAL_TRIALS",
                         "historical_trial_count": trial_census["known_lower_bound"],
                         "historical_trial_census_complete": trial_census["complete"],
                         "corrections_planned": ["DSR", "CSCV_PBO", "WHITE_RC", "HANSEN_SPA", "BH", "BY"]}
                        for c in catalog]}


def validate_plan(plan, catalog, trial_census=None):
    """Validate the entire frozen plan, including corrections and prospective rules."""
    entries = plan.get("entries") if isinstance(plan, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("registration plan entries")
    cutoff = entries[0].get("data_cutoff")
    if isinstance(cutoff, bool) or not isinstance(cutoff, int) or cutoff <= 0:
        raise ValueError("registration plan cutoff")
    trials = census.build() if trial_census is None else trial_census
    expected = registration_plan(catalog, trials, cutoff)
    if plan != expected:
        raise ValueError("registration plan differs from canonical parameters, family, corrections or prospective gate")
    return True


def feature_rows(p, hist, G, funding, i, direction):
    """Only bars closed by decision time; first candle is never called listing inception."""
    t = int(p.t[i] + p.bar)
    lo = max(0, i - 24 * 30)
    prices = p.c[lo:i + 1]
    with np.errstate(all="ignore"):
        returns = prices[1:] / prices[:-1] - 1
    btc = p.coins.index("BTC") if "BTC" in p.coins else None
    rows = []
    for j, asset in enumerate(p.coins):
        if not G.elig[i, j]:
            continue
        f = {}
        def add(name, value, when=t):
            if value is not None and np.isfinite(value):
                f[name] = MC.feature(float(value), int(when), "PIT_OBSERVED")
        liq = hist.liquidity_at(t, asset)
        if liq.get("state") == "KNOWN" and liq.get("precision") == PIT.PRECISION_REGISTRY_8SIG:
            add("pit_liquidity", liq["value"], liq["observed_at"])
        if len(returns) >= 24 * 30 and np.isfinite(returns[:, j]).all():
            add("realized_volatility", returns[:, j].std(ddof=1))
            add("trend_state", np.sign(prices[-1, j] / prices[0, j] - 1))
            if btc is not None and np.isfinite(returns[:, btc]).all() and returns[:, btc].var(ddof=1) > 0:
                add("btc_beta", np.cov(returns[:, j], returns[:, btc], ddof=1)[0, 1] / returns[:, btc].var(ddof=1))
                add("market_regime", np.sign(prices[-1, btc] / prices[0, btc] - 1))
        add("funding", funding[i, j])
        rows.append({"asset": asset, "decision_time": t, "direction": direction, "eligible": True, "features": f})
    return rows


def controls_for_trade(p, hist, G, funding, s, k, q, uni, slip, fr, fs, ls):
    i, j, direction = int(s["i"][k]), int(s["j"][k]), int(s["d"][k])
    population = feature_rows(p, hist, G, funding, i, direction)
    signal = next((r for r in population if r["asset"] == p.coins[j]),
                  {"asset": p.coins[j], "decision_time": int(p.t[i] + p.bar), "direction": direction, "features": {}})
    matching = MC.match(signal, population)
    selected = matching["controls"]
    outcomes = []
    if selected:
        cs = {key: np.repeat(value[k], len(selected)) for key, value in s.items()}
        cs["j"] = np.array([p.coins.index(r["asset"]) for r in selected], dtype=np.int64)
        taken, res = PS.simulate(p, cs)
        qualified = PS.qualify(p, taken, res, uni, slip, fr, fs, liq_state=ls)
        if qualified.get("n"):
            for a in range(qualified["n"]):
                outcomes.append({"asset": p.coins[int(taken["j"][a])], "decision_time": signal["decision_time"],
                                 "direction": direction, "net_R": float(qualified["net_R"][a]),
                                 "fully_qualified": bool(qualified["fully_qualified"][a] and qualified["closed"][a]),
                                 "same_geometry": True})
    match = MC.outcome(matching, float(q["net_R"][k]), outcomes)
    values = signal["features"]
    vol = MC.known(signal, "realized_volatility", signal["decision_time"])
    vols = [MC.known(r, "realized_volatility", signal["decision_time"]) for r in population]
    vols = [v for v in vols if v is not None]
    liq = MC.known(signal, "pit_liquidity", signal["decision_time"])
    liqs = [MC.known(r, "pit_liquidity", signal["decision_time"]) for r in population]
    liqs = [v for v in liqs if v is not None]
    regime = MC.known(signal, "market_regime", signal["decision_time"])
    return match, {"btc_trend": "UNKNOWN" if regime is None else "up" if regime > 0 else "down",
                   "volatility": "UNKNOWN" if vol is None or not vols else "high" if vol >= np.median(vols) else "low",
                   "liquidity": "UNKNOWN" if liq is None or not liqs else "high" if liq >= np.median(liqs) else "low"}


def run(md, hist_dir, cutoff, folder, replications=5000):
    from qdata import Panel
    import qstrat
    from qexport import TESTED
    from pit_research import funding_signal
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    catalog = census.catalog()
    trial_census = census.build()
    chash = save(folder, "research_strategy_trial_census.json", trial_census)
    hist = PIT.History(H.DirStore(hist_dir), cutoff=cutoff)
    if not hist.ok:
        raise ValueError("PIT history failed verification")
    p = Panel(md, end=cutoff - 3600, min_hours=0)  # only bars closed by the cutoff
    if not len(p.t):
        raise ValueError("no closed market-data bars at cutoff")
    # Eligibility to enter the panel must itself be evaluated at cutoff. Future candles
    # cannot make a newly long-enough file appear in an old-cutoff candidate matrix.
    keep = np.isfinite(p.c).sum(axis=0) >= 24 * 45
    for name in ("o", "h", "l", "c", "v", "fund"):
        setattr(p, name, getattr(p, name)[:, keep])
    p.coins = [c for c, ok in zip(p.coins, keep) if ok]
    p.N = len(p.coins)
    if not p.N:
        raise ValueError("no asset has 45 days of closed observations at cutoff")
    # Do not let legacy assumed/carried funding become a signal for funding-sensitive candidates.
    fr, fs, sources = PC.funding_panel(md, p.t, p.coins, cutoff=cutoff)
    observed_signal, known_funding, _ = funding_signal(fr, fs)
    p_corrected = copy.copy(p)
    p_corrected.fund = np.where(np.isfinite(fr), fr, 0.0)
    F = qstrat.Feat(p_corrected)
    G, uni = PS.corrected_feat(F, p, hist, 1_000_000)
    _, ls, slip, _ = PC.liquidity_panel(hist, p.t, p.coins)
    # Bind analysis to cutoff data, not future files/branch tips. Full branch SHAs go into run provenance separately.
    dataset_hash = hashlib.sha256()
    for value in (p.t, p.o, p.h, p.l, p.c, p.v, fr, fs):
        dataset_hash.update(np.ascontiguousarray(value).tobytes())
    dataset_hash.update(census.digest(p.coins).encode())
    provenance = {"dataset_sha256": dataset_hash.hexdigest(),
                  "trial_census_sha256": chash, "method_version": MT.VERSION,
                  "strategy_code_hash": catalog[0]["code_hash"], "cutoff": cutoff}
    provenance["method_code_hash"] = census.digest({name: hashlib.sha256((HERE / name).read_text(encoding="utf-8").encode()).hexdigest()
        for name in ("strategy_adjudication.py", "multiple_testing.py", "matched_controls.py", "strategy_census.py",
                     "../../v8/strategy_authority.py", "../../v8/strategy_policy.py")})
    # History's public report covers the complete store; the view uses observations <= cutoff.
    # Use canonical observed view timestamps plus file hashes at/before cutoff for deterministic seeds.
    view_records = []
    for path in sorted(Path(hist_dir).rglob("*.json.gz")):
        import gzip
        with gzip.open(path, "rt", encoding="utf-8") as f:
            row = json.load(f)
        if row.get("observed_at", cutoff + 1) <= cutoff:
            view_records.append((row["seq"], row["record_hash"]))
    view_records.sort()
    provenance["history_cutoff_head_hash"] = view_records[-1][1] if view_records else None
    provenance["history_cutoff_view_hash"] = census.digest(view_records)
    start, end = int(p.t[0]), int(p.t[-1] + p.bar)
    overlap_bars = uni["complete"] & np.any(uni["code"] == 1, axis=1)
    overlap_days = len(set((p.t[overlap_bars] // 86400).tolist()))
    # A whole day is admitted to family inference only if every hourly cross-section is qualified.
    day_ids = sorted(set((p.t // 86400).tolist()))
    complete_days = [d for d in day_ids if sum((p.t // 86400) == d) == 24 and
                     bool(overlap_bars[(p.t // 86400) == d].all())]
    all_rows, match_reports, candidate_info = {}, {}, {}
    for c in catalog:
        sid = c["strategy_id"]
        fn, kw = TESTED[sid][:2]
        FG = G
        if sid in ("FUND_FADE", "FUND_CARRY"):
            FG = copy.copy(G)
            FG.elig = G.elig & known_funding
            if sid == "FUND_CARRY":
                FG.elig = FG.elig & (~(G.elig & ~known_funding).any(axis=1))[:, None]
        signals = fn(FG, **kw)
        s, result = PS.simulate(p, signals)
        q = PS.qualify(p, s, result, uni, slip, fr, fs, liq_state=ls)
        rows = []
        matches = []
        if q.get("n"):
            ok = q["fully_qualified"] & q["closed"]
            for k in np.flatnonzero(ok):
                si, j = int(s["i"][k]), int(s["j"][k])
                decision = int(p.t[si] + p.bar)
                # Market cap and genuine listing inception have no governed input in this repository.
                # They remain missing. First candle/first history observation is not a listing date.
                match, regimes = controls_for_trade(p, hist, G, observed_signal, s, k, q, uni, slip, fr, fs, ls)
                matches.append(match)
                rows.append({"asset": p.coins[j], "decision_time": decision, "exit_time": int(q["t_exit"][k]),
                             "direction": int(s["d"][k]), "net_R": float(q["net_R"][k]),
                             "adverse_cost_R": float((q["fee"][k] + q["slippage"][k] + max(0, q["funding"][k])) / q["stop"][k]),
                             "fully_qualified": True, "components": {name: bool(q[name][k]) for name in
                              ("universe_ok", "identity_ok", "liquidity_ok", "funding_ok", "cost_ok")},
                             "funding": "positive" if observed_signal[si, j] > 0 else "negative" if observed_signal[si, j] < 0 else "zero",
                             "listing_age": "UNKNOWN", **regimes,
                             "calendar_month": datetime.fromtimestamp(decision, timezone.utc).strftime("%Y-%m")})
        all_rows[sid], match_reports[sid] = rows, matches
        candidate_info[sid] = {"signals": len(signals["i"]), "simulated_trades": int(q.get("n", 0)),
                               "fully_qualified_closed_trades": len(rows), "unqualified_reasons": PS.reasons(q, hist)}
    # No missing calendar days compressed together across a gap: family bootstrap requires continuous complete days.
    contiguous = bool(complete_days) and complete_days == list(range(complete_days[0], complete_days[-1] + 1))
    matrix = np.array([[sum(r["net_R"] for r in all_rows[c["strategy_id"]] if r["exit_time"] // 86400 == day)
                        for c in catalog] for day in complete_days], float).reshape((-1, len(catalog)))
    statistics = MT.bootstrap_tests(matrix, provenance, replications) if contiguous else MT.unavailable("no continuous fully qualified common daily window")
    pbo = MT.pbo(matrix, [c["strategy_id"] for c in catalog]) if contiguous else MT.unavailable("no continuous fully qualified common daily window")
    # Historical grid return columns are absent. Do not estimate DSR dispersion from the three holdovers.
    multiple = {"schema": MT.VERSION, "provenance": provenance, "family_tests": statistics, "pbo": pbo,
                "candidate_count": len(catalog), "known_historical_trials": trial_census["known_lower_bound"],
                "trial_return_universe_complete": False, "blocking_reason": "HISTORICAL_TRIAL_RETURN_MATRIX_MISSING"}
    multiple["white_reality_check"] = {"status": statistics["status"], "p": statistics.get("white_rc_p")}
    multiple["hansen_spa"] = {"status": statistics["status"], "p": statistics.get("hansen_spa_p")}
    multiple["fdr"] = {"status": statistics["status"], "values": statistics.get("fdr")}
    mhash = save(folder, "research_multiple_testing.json", multiple)
    matched = {"schema": MC.VERSION, "provenance": provenance, "status": "FULL_MATCHED_CONTROL_UNAVAILABLE",
               "market_cap_status": "MATCHED_CONTROL_MARKET_CAP_MISSING", "listing_age_status": "GENUINE_LISTING_INCEPTION_MISSING",
               "strategies": match_reports, "full_signal_fraction": 0.0}
    match_hash = save(folder, "research_matched_controls.json", matched)
    import quant
    policy = SP.load(quant.STRATS)
    deployment = {r["strategy_id"]: r["deployment_state"] for r in policy["strategies"]}
    results = []
    for i, c in enumerate(catalog):
        sid = c["strategy_id"]
        rows = all_rows[sid]
        agg = clustered(rows)
        robust = robustness(rows, start, end)
        partial_edges = [{"decision_time": m["decision_time"], "net_R": m["matched_edge"]}
                         for m in match_reports[sid] if m["matched_edge"] is not None]
        matched_diagnostic = {"label": "PARTIAL_DIAGNOSTIC / NOT FULL MATCHED AUTHORITY",
                              "edge": clustered(partial_edges), "signals": len(match_reports[sid]),
                              "full_signals": sum(m["full"] for m in match_reports[sid])}
        evidence = {"trial_census_complete": trial_census["complete"], "trial_return_universe_complete": False,
                    "pit_integrity_ok": True, "prospective_registration_valid": False, "full_feature_authority": False,
                    "robustness_slices_complete": False, "pit_calendar_days": overlap_days,
                    "qualified_closed_trades": len(rows), "mean_R": agg["mean_R"], "mean_R_lower_95": agg["lower_95"],
                    "full_matched_fraction": 0, "both_sides": c["params"].get("sides", "both") == "both",
                    "sides": robust["sides"], "oos_mean_R": robust["oos"]["mean_R"],
                    "stress_1_5_mean_R": robust["cost_stress"]["1.5"], **robust["concentration"]}
        dsr = MT.dsr(matrix[:, i], trial_census["known_lower_bound"], None, False)
        if statistics["status"] == "AVAILABLE":
            evidence.update(spa_p=statistics["hansen_spa_p"], white_rc_p=statistics["white_rc_p"],
                            by_q=statistics["fdr"]["by_q"][i])
        if pbo["status"] == "AVAILABLE":
            evidence["pbo"] = pbo["pbo"]
        verdict = SA.adjudicate(evidence)
        bindings = {"runtime_definition_hash": SP.digest(quant.STRATS[sid]) if sid in quant.STRATS else None,
                    "adjudicated_definition_hash": SP.adjudicated_definition_hash(c)}
        results.append({**c, **verdict, **bindings, "dataset_provenance": provenance, "pit_version": PIT.VERSION,
                        "cost_model": PC.VERSION, "trial_census_version": census.VERSION, "trial_census_hash": chash,
                        "matched_control_version": MC.VERSION, "matched_control_hash": match_hash,
                        "multiple_testing_version": MT.VERSION, "multiple_testing_hash": mhash,
                        "sample_counts": candidate_info[sid], "aggregate": agg, "robustness": robust, "dsr": dsr,
                        "matched_control_diagnostic": matched_diagnostic,
                        "evidence": evidence, "deployment_state": deployment.get(sid, "DISABLED"),
                        "trace": {"definition": c, **bindings, "trial_history": trial_census["status"], "pit_evidence": candidate_info[sid],
                                  "data_completeness": "INCOMPLETE", "costs": PC.VERSION,
                                  "matched_controls": matched["status"], "multiple_testing": {"hash": mhash, "status": statistics["status"]},
                                  "oos": robust["oos"], "robustness": robust,
                                  "prospective_evidence": "PLAN_NOT_REGISTERED", "final_research_state": verdict["research_state"],
                                  "runtime_deployment_state": deployment.get(sid, "DISABLED"), "blocking_reasons": verdict["blocking_reasons"]}})
    plan = registration_plan(catalog, trial_census, cutoff)
    validate_plan(plan, catalog, trial_census)
    save(folder, "research_phase9_registration_plan.json", plan)
    report = {"schema": SA.VERSION, "provenance": provenance, "gate": SA.GATE,
              "strategies": results, "candidate_count": len(catalog), "requalified_count": sum(r["status"] == "REQUALIFIED" for r in results),
              "legacy_diagnostics": {"label": "LEGACY_SURVIVORSHIP_UNQUALIFIED", "source": "quant_research.json",
                                     "portfolio": "LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY"},
              "pit_overlap_calendar_days": overlap_days, "common_complete_days": len(complete_days),
              "market_data_start": start, "market_data_end": end, "history_window": {k: v for k, v in hist.window().items() if k != "observations_in_store"},
              "runtime_policy_schema": SP.VERSION, "runtime_policy_hash": SP.digest(policy),
              "runtime_order": policy["runtime_order"], "shadow_ledger": SL.summary(str(ROOT / SL.DIR)),
              "promotion": "NONE: reviewed main-branch policy change required"}
    ahash = save(folder, "research_strategy_adjudication.json", report)
    summary = {"schema": "v8.phase9-summary/1", "adjudication_hash": ahash,
               "trial_census_hash": chash, "known_historical_trials": trial_census["known_lower_bound"],
               "trial_census_complete": False, "candidate_count": len(catalog), "requalified_count": report["requalified_count"],
               "pit_overlap_calendar_days": overlap_days, "matched_control_status": matched["status"],
               "statistical_test_status": statistics["status"], "strategies": [{"strategy_id": r["strategy_id"],
                 "research_state": r["research_state"], "deployment_state": r["deployment_state"],
                 "qualified_closed_trades": r["sample_counts"]["fully_qualified_closed_trades"]} for r in results]}
    save(folder, "research_phase9_summary.json", summary)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--history", required=True)
    ap.add_argument("--cutoff", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    start = time.perf_counter()
    tracemalloc.start()
    result = run(args.md, args.history, args.cutoff, args.out)
    _, peak = tracemalloc.get_traced_memory()
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except ImportError:
        rss = None  # Windows local run; CI records Linux process RSS.
    folder = Path(args.out)
    mult = json.loads((folder / "research_multiple_testing.json").read_text())
    matched = json.loads((folder / "research_matched_controls.json").read_text())
    names = ["research_strategy_trial_census.json", "research_strategy_adjudication.json",
             "research_multiple_testing.json", "research_matched_controls.json", "research_phase9_summary.json",
             "research_phase9_registration_plan.json"]
    save(Path(args.out), "research_phase9_compute.json", {"wall_seconds": time.perf_counter() - start,
         "python_peak_bytes": peak, "process_peak_rss_bytes": rss, "bootstrap_replications_planned": 5000,
         "bootstrap_replications_executed": mult["family_tests"].get("replications", 0),
         "cscv_splits_executed": mult["pbo"].get("combinations", 0),
         "control_matches": sum(m["control_count"] for rows in matched["strategies"].values() for m in rows),
         "candidate_count": result["candidate_count"], "known_parameter_trials": result["known_historical_trials"],
         "artifact_bytes": sum((folder / name).stat().st_size for name in names)})
    def ref(name):
        try:
            return census.git("rev-parse", name).strip()
        except Exception:
            return None
    save(folder, "research_phase9_run_provenance.json", {"head": ref("HEAD"), "tree": ref("HEAD^{tree}"),
         "market_data_commit": ref("origin/market-data"), "history_branch_sha": ref("origin/v8-history"),
         "history_verify": H.verify(H.DirStore(args.history)), "cutoff": args.cutoff})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
