"""End-of-run audit of picks.run(): the swing engine's and the day-trade engine's disposition for every coin of
the coin-picks universe. Reads the run's own values; recomputes nothing that decides a score or a list."""
from __future__ import annotations

from . import common as C
from . import ledger as LG
from . import parts
from . import taxonomy as T
from .trace import TRACE


def _listed(out):
    got = {}
    for side in ("all", "long", "short"):
        for i, r in enumerate(out.get(side) or []):
            got.setdefault(r["coin"], [])
            got[r["coin"]].append(f"{side}#{i + 1}")
    return got


def _score_final(L, t, rec, listed, cfg, kind, k, src, steps):
    ready, surf, watch = ("SWING_READY", "SWING_SETTING_UP", None) if kind == "swing" else \
        ("DAY_READY", "DAY_SETTING_UP", None)
    o = {"score": rec["score"], "side": rec["side"]}
    th = {"ready": cfg["ready"], "watch": cfg["watch"], "top_n": cfg["top_n"]}
    if t in listed:
        o["lists"] = listed[t]
        if rec["score"] >= cfg["ready"]:
            return L.final(t, ready, "publish", o=o, th=th, src=src, k=k, x=steps)
        if rec["score"] >= cfg["watch"]:
            return L.final(t, surf, "publish", o=o, th=th, src=src, k=k, x=steps)
        return L.final(t, "LISTED_BELOW_WATCH", "publish", o=o, th=th, src=src, k=k, x=steps)
    if rec["score"] >= cfg["watch"]:
        return L.final(t, "OUTPUT_TOP_N_CUTOFF", "publish", o=o, th=th, src=src, k=k, x=steps)
    return L.final(t, "SCORE_BELOW_THRESHOLD", "publish", o=o, th=th, src=src, k=k, x=steps)


def picks_parts(now, universe, coins, got, data, last_day, swing, by_liq, day_set, c1s, sw_recs, day_recs, swing_out,
                day_out, new):
    import picks as P
    import scanner as sc
    cfg = P.CFG
    S, D = LG.Ledger("swing"), LG.Ledger("day")
    S.expect(sorted(universe))
    D.expect(sorted(universe))
    chosen = {c["t"] for c in coins}
    sw_by = {r["coin"]: r for r in sw_recs}
    day_by = {r["coin"]: r for r in day_recs}
    sw_list, day_list = _listed(swing_out), _listed(day_out)
    new_sw = {tr["c"] for tr in new if tr["kind"] == "swing"}
    new_day = {tr["c"] for tr in new if tr["kind"] == "day"}
    liq_rank = {t: i + 1 for i, t in enumerate(by_liq)}

    def both(t, code, stage, **kw):
        S.final(t, code, stage, **kw)
        D.final(t, code, stage, **kw)

    for t in sorted(universe):
        c = universe[t]
        k = C.contract_ids(c)
        if c.get("tradfi"):
            code, o = C.tradfi_code(c)
            both(t, code, "universe", o=o, k=k)
            continue
        if t not in chosen:
            C.liquidity_final(S, t, c, "universe", cfg["min_dex_vol"], sc.in_my_dexes, k=k)
            C.liquidity_final(D, t, c, "universe", cfg["min_dex_vol"], sc.in_my_dexes, k=k)
            continue
        g = got.get(t)
        if not g:
            code, h, o = C.candle_miss(TRACE.candles.get((t, "4h")), "INSUFFICIENT_4H_HISTORY")
            both(t, code, "candles_4h", o=o, th={"min_bars_4h": 60}, h=h, k=k)
            continue
        if t not in data:
            n = sum(1 for x in g["candles"] if x["t"] + P.B4 <= now)
            both(t, "INSUFFICIENT_4H_HISTORY", "candles_4h", o={"closed_bars": n, "src": g["src"]},
                 th={"min_bars_4h": 60}, h=T.MISSING, src=g["src"], k=k)
            continue
        src = data[t]["src"]
        if t not in swing:
            cd = data[t]["cd"]
            if not cd or cd[-1]["t"] != last_day:
                both(t, "LAST_DAY_NOT_SYNCED", "swing_inputs", o={"last_day": cd[-1]["t"] if cd else None},
                     th={"scan_last_day": last_day}, h=T.STALE if cd else T.MISSING, src=src, k=k)
            elif cd[-1]["qv"] < cfg["min_ref_vol"]:
                both(t, "REF_VOLUME_BELOW_LEGACY_MIN", "swing_inputs", o={"last_day_ref_vol": cd[-1]["qv"]},
                     th={"min_ref_vol": cfg["min_ref_vol"]}, src=src, k=k)
            elif len(cd) < cfg["min_days"]:
                both(t, "INSUFFICIENT_90D_HISTORY", "swing_inputs", o={"daily_candles": len(cd)},
                     th={"min_days": cfg["min_days"]}, h=T.MISSING, src=src, k=k)
            else:
                both(t, "SWING_INPUTS_UNAVAILABLE", "swing_inputs", o={"daily_candles": len(cd)}, h=T.MISSING,
                     src=src, k=k)
            continue
        rec = sw_by.get(t)
        if rec is None:
            S.problem(f"{t}: swing checks ran but no swing record")
            both(t, "AUDIT_UNCLASSIFIED", "swing", src=src, k=k)
            continue
        st = ["PAPER_OPENED"] if t in new_sw else []
        _score_final(S, t, rec, sw_list, cfg, "swing", k, src, st)
        # the day-trade engine starts from the swing set
        if t not in day_set:
            D.final(t, "DAY_CANDIDATE_NOT_SELECTED", "day_candidates",
                    o={"liquid_rank": liq_rank.get(t), "swing_score": max(swing[t]["long"], swing[t]["short"])},
                    th={"top_liquid": cfg["day_coins"], "or_swing_min": 60}, src=src, k=k)
            continue
        drec = day_by.get(t)
        if drec is None:
            c1 = c1s.get(t)
            D.final(t, "NO_HOURLY_CANDLES", "candles_1h", o={"closed_1h": len(c1) if c1 else 0},
                    th={"min_1h": 170}, h=T.MISSING, src=src, k=k)
            continue
        _score_final(D, t, drec, day_list, cfg, "day", k, src, ["PAPER_OPENED"] if t in new_day else [])
    out = {}
    for L, lists in ((S, swing_out), (D, day_out)):
        part = L.to_part()
        shown = set(_listed(lists))
        led = {r["a"] for r in L.records.values() if r["c"] in ("SWING_READY", "SWING_SETTING_UP", "DAY_READY",
                                                                "DAY_SETTING_UP", "LISTED_BELOW_WATCH")}
        if shown & set(universe) != led:
            L.problem("published lists differ from the ledger's listed records")
            part["problems"] = L.problems
        out[L.engine] = part
    out["swing"]["stages"] = {"universe": len(universe), "liquid_crypto": len(chosen), "with_4h": len(data),
                              "swing_checked": len(swing), "listed": len(sw_list), "paper_new": len(new_sw),
                              "last_day": last_day}
    out["day"]["stages"] = {"day_candidates": len(day_set), "day_scored": len(day_recs), "listed": len(day_list),
                            "paper_new": len(new_day)}
    return out


def audit(out_dir, now, **kw):
    """Called once at the end of picks.run(). Writes data/v8/parts/swing.json and day.json. Never raises."""
    holder = {}

    def run_both(**inputs):
        holder.update(picks_parts(**inputs))
        return holder["swing"]

    parts.safe_audit("swing", out_dir, run_both, ts=now, now=now, **kw)

    def day():
        if "day" not in holder:
            raise RuntimeError("the swing audit failed, so the day-trade audit has no input")
        return holder["day"]

    parts.safe_audit("day", out_dir, day, ts=now)
