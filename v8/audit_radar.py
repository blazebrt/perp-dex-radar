"""End-of-run audit of scanner.run(): the contract registry, the shared-universe exclusions and the radar's
disposition for every coin of its universe.

It reads the run's own values (passed in explicitly) and the trace; it decides nothing. The only recomputation is
explain_plan(), which re-derives WHY build_plan() returned None for a strategy that fired (build_plan only returns
None), from the same inputs; tests/test_v8_audit.py checks it against build_plan() on random inputs."""
from __future__ import annotations

from . import common as C
from . import health as H
from . import ledger as LG
from . import parts
from . import registry as R
from . import taxonomy as T
from .trace import TRACE


def explain_plan(info, cfg):
    """Why build_plan() rejected a fired strategy: STOP_TOO_WIDE, STOP_ABOVE_PRICE, PAST_TARGET, or None when the
    inputs would give a plan (an audit inconsistency). Mirrors scanner.build_plan() step by step."""
    A = info["atr"]
    last = info["last"] if info.get("px") is None else info["px"]
    lo, hi, stop, trig = info["lv"]
    if hi < lo:
        lo, hi = hi, lo
    mid = (lo + hi) / 2
    smin, smax = info.get("stop_atr") or (0.9, 3.5)
    floor = mid * max(0.003, cfg["min_stop_pct"])
    min_risk = max(smin * A, floor)
    if mid - stop < min_risk:
        stop = mid - min_risk
    if mid - stop > max(smax * A, min_risk):
        stop = mid - max(smax * A, min_risk)
    sk = info.get("sk")
    if sk and sk != 1.0:
        stop = mid - (mid - stop) * sk
        if mid - stop < floor:
            stop = mid - floor
    risk = (mid - stop) / mid if mid > 0 else 1.0
    max_risk = info.get("max_risk") or cfg["max_risk"]
    if stop <= 0 or risk > max_risk:
        return "STOP_TOO_WIDE", {"risk": risk}, {"max_risk": max_risk}
    if last <= stop:
        return "STOP_ABOVE_PRICE", {"price": last, "stop": stop}, None
    R_ = mid - stop
    tp1 = mid + R_ * info["tp_r"][0]
    if not (trig is not None and info["last"] < trig) and not (lo <= last <= hi) and last > hi and last >= tp1:
        return "PAST_TARGET", {"price": last, "tp1": tp1}, None
    return None, None, None


def universe_part(coins, dex_status, dex_ok, scan_t):
    reg = R.build(TRACE, coins, dex_status, dex_ok, scan_t)
    L = LG.Ledger("universe")
    L.expect(sorted(reg["assets"]))
    by_id = {c["id"]: c for c in reg["contracts"]}
    passed = []
    for t, a in sorted(reg["assets"].items()):
        if a["legacy"] in ("CRYPTO", "TRADFI"):
            passed.append(t)
            continue
        code = a["legacy"]  # NO_ACTIVE_PERP_CONTRACT, PRICE_CONFLICT_ALL_VENUES or VENUE_ADAPTER_FAILED
        skips = {cid: by_id[cid]["legacy"] for cid in a["contracts"] if cid in by_id}
        L.final(t, code, "universe", o={"contracts": skips},
                h={"PRICE_CONFLICT_ALL_VENUES": T.CONFLICTED, "VENUE_ADAPTER_FAILED": T.MISSING}.get(code, T.HEALTHY),
                k=a["contracts"])
    part = L.to_part()
    cov = part["coverage"]
    # assets that passed the universe stage are accounted for by the radar part, not here
    cov["passed_to_engines"] = len(passed)
    cov["unaccounted"] = len([t for t in L.input if t not in L.records and t not in set(passed)])
    cov["unaccounted_assets"] = [t for t in L.input if t not in L.records and t not in set(passed)][:50]
    part["registry"] = reg
    part["registry_counts"] = R.counts(reg)
    part["passed"] = passed
    part["fallback"] = not dex_ok
    return part


def radar_part(scan_t, coins, dex_ok, crypto, res1, s1, ranked, cands, extras, res2, A, sigs, best, pick_sigs,
               watch_sigs, gate):
    import scanner as sc
    cfg = sc.CFG
    L = LG.Ledger("radar")
    L.expect(sorted(coins))

    def liquid(t):
        return (not dex_ok) or (sc.liq_of(crypto[t]) or 0) >= cfg["min_dex_vol"]

    liq_rank = {t: i + 1 for i, t in enumerate(t for t in ranked if liquid(t))}
    stage2, extra = set(cands), set(extras)
    picked = {x["t"]: i + 1 for i, x in enumerate(pick_sigs)}
    watched = {x["t"]: i + 1 for i, x in enumerate(watch_sigs)}
    by_coin = {}
    for x in sigs:
        by_coin.setdefault(x["t"], []).append(x)
    a_coin = {id(a): t for t, a in A.items()}
    plans, filt = {}, {}
    for aid, sid, info in TRACE.plans:
        t = a_coin.get(aid)
        if t is not None:
            plans.setdefault(t, []).append((sid, info))
    for aid, sid in TRACE.filters:
        t = a_coin.get(aid)
        if t is not None:
            filt.setdefault(t, []).append(sid)
    for t in sorted(coins):
        c = coins[t]
        k = C.contract_ids(c)
        if c.get("tradfi"):
            code, o = C.tradfi_code(c)
            L.final(t, code, "universe", o=o, k=k)
            continue
        steps = []
        fb, _ = H.funding(c)
        if fb == H.ASSUMED_DEFAULT:
            steps.append("FUNDING_ASSUMED_DEFAULT")
        if t not in s1:
            r = res1.get(t)
            if r is None:
                code, h, o = C.candle_miss(TRACE.candles.get((t, "1h")), "INSUFFICIENT_1H_HISTORY")
            else:
                n = len(sc.closed_part(r["candles"], 3600, scan_t))
                code, h, o = "INSUFFICIENT_1H_HISTORY", T.MISSING, {"closed_bars": n, "src": r.get("src")}
            L.final(t, code, "stage1", o=o, th={"min_closed_1h": 30}, h=h, k=k)
            continue
        src = s1[t].get("src")
        if t in extra:
            steps.append("EXTRA_DEEP_DIVE")
        ss = by_coin.get(t)
        if ss:
            if t in best:
                x = best[t]
                o = {"score": x["final"], "sid": x["s"]["sid"], "signals": len(ss)}
                if t in picked:
                    L.final(t, "RADAR_PICK", "publish", o=dict(o, rank=picked[t]), th={"min": cfg["min_pick_score"]},
                            src=src, k=k, x=steps)
                elif t in watched:
                    L.final(t, "RADAR_WATCH", "publish", o=dict(o, slot=watched[t]), th={"watch_n": cfg["watch_n"]},
                            src=src, k=k, x=steps)
                elif x["final"] >= cfg["min_pick_score"]:
                    L.final(t, "OUTPUT_TOP_N_CUTOFF", "publish", o=o, th={"top_n": cfg["top_n"]}, src=src, k=k,
                            x=steps)
                else:
                    L.final(t, "SCORE_BELOW_THRESHOLD", "publish", o=o,
                            th={"min": cfg["min_pick_score"], "watch_n": cfg["watch_n"]}, src=src, k=k, x=steps)
            else:
                top = max(ss, key=lambda y: y["final"])
                blk = str(top["block"] or "")
                if gate and blk == f"Market gate: {gate}":
                    code = "MARKET_GATE_BLOCKED"
                elif blk == "new variant in its live test: paper-traded only":
                    code = "VARIANT_FORWARD_TEST"
                elif blk.endswith(": paper-traded only"):
                    code = "STRATEGY_NOT_PASSED"
                else:
                    code = "ADJUSTMENT_BLOCKED"
                L.final(t, code, "block", o={"signals": len(ss), "best": [top["s"]["sid"], top["final"]], "block": blk},
                        th={"publish": list(cfg["publish"])}, src=src, k=k, x=steps)
            continue
        if t not in stage2:
            if not liquid(t):
                C.liquidity_final(L, t, c, "stage2", cfg["min_dex_vol"], sc.in_my_dexes, k=k)
            else:
                L.final(t, "RADAR_STAGE2_NOT_SELECTED", "stage2",
                        o={"liquid_rank": liq_rank.get(t), "stage1_score": s1[t]["score"]},
                        th={"top_n": cfg["stage2_n"], "extras": cfg["stage2_extra"]}, src=src, k=k)
            for s in steps:
                L.note(t, s)
            continue
        if t not in A:
            r = res2.get(t)
            if r is None:
                code, h, o = C.candle_miss(TRACE.candles.get((t, "15m")), "INSUFFICIENT_15M_HISTORY")
            else:
                n = len(sc.closed_part(r["candles"], 900, scan_t))
                code, h, o = "INSUFFICIENT_15M_HISTORY", T.MISSING, {"closed_bars": n, "src": r.get("src")}
            L.final(t, code, "deep_dive", o=o, th={"min_closed_15m": 60}, h=h, src=src, k=k, x=steps)
            continue
        pr = plans.get(t)
        if pr:
            why = []
            for sid, info in pr:
                code, o_, th_ = explain_plan(info, cfg)
                if code is None:
                    L.problem(f"{t} {sid}: build_plan rejected a plan explain_plan would accept")
                    code = "AUDIT_UNCLASSIFIED"
                why.append([sid, code, o_, th_])
            first = why[0]
            L.final(t, first[1], "plan", o={"plans": [[w[0], w[1], w[2]] for w in why]}, th=first[3], src=src, k=k,
                    x=steps + ["PLAN_REJECTED"])
        elif filt.get(t):
            L.final(t, "VARIANT_FILTER_NOT_MET", "signal", o={"variants": filt[t]}, src=src, k=k, x=steps)
        else:
            L.final(t, "NO_STRATEGY_SIGNAL", "signal", o={"setups_checked": "all active 15m strategies"}, src=src,
                    k=k, x=steps)
    part = L.to_part()
    # consistency: what was published must be what the ledger says was surfaced or watched
    led_s = {r["a"] for r in L.records.values() if r["d"] == T.SURFACED}
    led_w = {r["a"] for r in L.records.values() if r["d"] == T.WATCHED}
    if led_s != set(picked) or led_w != set(watched):
        L.problem("published picks/watch differ from the ledger's SURFACED/WATCHED")
        part["problems"] = L.problems
    part["stages"] = {"universe": len(coins), "crypto": len(crypto), "stage1_charted": len(s1),
                      "stage2_selected": len(stage2) - len(extra), "stage2_extras": len(extra), "deep_dives": len(A),
                      "signals": len(sigs), "signal_coins": len(by_coin), "publishable": len(best),
                      "picks": len(pick_sigs), "watch": len(watch_sigs), "plan_rejections": len(TRACE.plans),
                      "market_gate": gate}
    return part


def audit(out_dir, scan_t, coins, dex_status, dex_ok, crypto, res1, s1, ranked, cands, extras, res2, A, sigs, best,
          pick_sigs, watch_sigs, gate):
    """Called once at the end of scanner.run(). Writes data/v8/parts/universe.json and radar.json. Never raises."""
    parts.safe_audit("universe", out_dir, universe_part, ts=scan_t, coins=coins, dex_status=dex_status,
                     dex_ok=dex_ok, scan_t=scan_t)
    parts.safe_audit("radar", out_dir, radar_part, ts=scan_t, scan_t=scan_t, coins=coins, dex_ok=dex_ok,
                     crypto=crypto, res1=res1, s1=s1, ranked=ranked, cands=cands, extras=extras, res2=res2, A=A,
                     sigs=sigs, best=best, pick_sigs=pick_sigs, watch_sigs=watch_sigs, gate=gate)
