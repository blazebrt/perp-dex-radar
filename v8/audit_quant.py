"""End-of-run audit of quant.run(): the quant desk's disposition for every coin of its universe.

The run's own values are passed in. To say why an eligible coin has no signal, the audit evaluates each strategy
at the latest closed bar with quant.py's own functions (eligible, trend_feats, sig_trend_ema, daily_feats,
sig_tsmom, xs_scores, _stop); the results are only written to the audit part."""
from __future__ import annotations

from . import common as C
from . import ledger as LG
from . import parts
from . import taxonomy as T
from .trace import TRACE


def _why_not_trend(q, tf, i):
    """'stop' when TREND_EMA crossed with ADX above its minimum but the stop is too wide, else None."""
    p = q.STRATS["TREND_EMA"]["params"]
    ef, es, a, at, c = tf["ef"], tf["es"], tf["adx"], tf["atr"], tf["c"]
    if i < 1 or None in (ef[i], es[i], ef[i - 1], es[i - 1], a[i], at[i]) or a[i] <= p["adx_min"]:
        return None
    d = 1 if (ef[i] > es[i] and ef[i - 1] <= es[i - 1]) else -1 if (ef[i] < es[i] and ef[i - 1] >= es[i - 1]) else 0
    if d and q._stop(c[i], at[i], p["stop_k"]) is None:
        return p["stop_k"] * at[i] / c[i]
    return None


def _why_not_tsmom(q, f, k):
    p = q.STRATS["TSMOM"]["params"]
    r1, r2, e, c = f["r_long"][k], f["r_short"][k], f["ema"][k], f["c"][k]
    if None in (r1, r2, e):
        return None
    d = 1 if (r1 > 0 and r2 > 0 and c > e) else -1 if (r1 < 0 and r2 < 0 and c < e) else 0
    if d and q._stop(c, f["atr"][k], p["stop_k"]) is None and f["atr"][k] is not None:
        return p["stop_k"] * f["atr"][k] / c
    return None


def quant_part(now, universe, coins, got, data, daily, lastd, new, open_trades):
    import quant as q
    import scanner as sc
    cfg = q.CFG
    L = LG.Ledger("quant")
    L.expect(sorted(universe))
    chosen = {c["t"] for c in coins}
    new_by = {}
    for tr in new:
        new_by.setdefault(tr["c"], []).append([tr["s"], tr["d"]])
    open_by = {}
    for tr in open_trades:
        open_by.setdefault(tr["c"], []).append([tr["s"], tr["d"], tr.get("t_in")])
    # the latest closed day, evaluated like quant.run() does for TSMOM and XSMOM
    feats, xs = {}, {}
    if lastd is not None:
        for t, cd in daily.items():
            k = next((j for j in range(len(cd) - 1, -1, -1) if cd[j]["t"] == lastd), None)
            if k is None:
                continue
            c4 = data[t]["c4"]
            i4 = next((j for j in range(len(c4) - 1, -1, -1) if c4[j]["t"] == lastd + q.DAY - q.B4), None)
            if i4 is None or not q.eligible(c4, i4, lastd):
                continue
            f = q.daily_feats(cd[: k + 1])
            feats[t] = f
            if f["r_x"][-1] is not None and f["vol"][-1]:
                xs[t] = f["r_x"][-1] / f["vol"][-1]
    xs_dir = q.xs_scores(xs)
    xs_rank = {t: i + 1 for i, (t, _) in enumerate(sorted(xs.items(), key=lambda kv: -kv[1]))}
    top = q.STRATS["XSMOM"]["params"]["top"]
    for t in sorted(universe):
        c = universe[t]
        k = C.contract_ids(c)
        if c.get("tradfi"):
            code, o = C.excluded_code(c)
            L.final(t, code, "universe", o=o, k=k, h=T.CONFLICTED if code == "AMBIGUOUS_EXPOSURE" else T.HEALTHY)
            continue
        if t not in chosen:
            C.liquidity_final(L, t, c, "universe", cfg["min_dex_vol"], sc.CFG["trade_dexes"], k=k)
            continue
        g = got.get(t)
        if not g:
            code, h, o = C.candle_miss(TRACE.candles.get((t, "4h")), "INSUFFICIENT_4H_HISTORY")
            L.final(t, code, "candles_4h", o=o, th={"min_bars_4h": 60}, h=h, k=k)
            continue
        if t not in data:
            n = sum(1 for x in g["candles"] if x["t"] + q.B4 <= now)
            L.final(t, "INSUFFICIENT_4H_HISTORY", "candles_4h", o={"closed_bars": n, "src": g["src"]},
                    th={"min_bars_4h": 60}, h=T.MISSING, src=g["src"], k=k)
            continue
        src = data[t]["src"]
        if t in new_by:
            L.final(t, "QUANT_NEW_SIGNAL", "publish", o={"signals": new_by[t]}, src=src, k=k, x=["PAPER_OPENED"])
            continue
        if t in open_by:
            L.final(t, "QUANT_POSITION_OPEN", "publish", o={"open": open_by[t]}, src=src, k=k)
            continue
        c4 = data[t]["c4"]
        i4 = None
        if lastd is not None:
            i4 = next((j for j in range(len(c4) - 1, -1, -1) if c4[j]["t"] == lastd + q.DAY - q.B4), None)
        i = i4 if i4 is not None else len(c4) - 1
        span_d = (c4[i]["t"] - c4[0]["t"]) / q.DAY
        if c4[i]["t"] - c4[0]["t"] < cfg["min_days"] * q.DAY - q.B4:
            L.final(t, "INSUFFICIENT_30D_HISTORY", "eligibility", o={"days": round(span_d, 2)},
                    th={"min_days": cfg["min_days"]}, h=T.MISSING, src=src, k=k)
            continue
        w = [x["qv"] for x in c4[max(0, i - 41): i + 1]]
        ref = sum(w) / len(w) * 6 if w else 0.0
        if not (len(w) >= 6 and ref >= cfg["min_ref_vol"]):
            L.final(t, "REF_VOLUME_BELOW_LEGACY_MIN", "eligibility", o={"ref_vol_day": ref},
                    th={"min_ref_vol": cfg["min_ref_vol"]}, src=src, k=k)
            continue
        # eligible, no trade: the state of each strategy at the latest closed bar
        state, wide = {}, {}
        j = len(c4) - 1
        if q.eligible(c4, j, c4[j]["t"]):
            tf = q.trend_feats(c4)
            s = q.sig_trend_ema(tf, j)
            if s:
                state["TREND_EMA"] = s[0]
            else:
                w_ = _why_not_trend(q, tf, j)
                if w_ is not None:
                    wide["TREND_EMA"] = w_
        f = feats.get(t)
        if f:
            kk = len(f["c"]) - 1
            s = q.sig_tsmom(f, kk)
            if s:
                state["TSMOM"] = s[0]
            else:
                w_ = _why_not_tsmom(q, f, kk)
                if w_ is not None:
                    wide["TSMOM"] = w_
            if t in xs_dir:
                p = q.STRATS["XSMOM"]["params"]
                if q._stop(f["c"][-1], f["atr"][-1], p["stop_k"]):
                    state["XSMOM"] = xs_dir[t]
                elif f["atr"][-1] is not None:
                    wide["XSMOM"] = p["stop_k"] * f["atr"][-1] / f["c"][-1]
        o = {"xsmom_rank": [xs_rank.get(t), len(xs), top]} if t in xs_rank else {}
        if state:
            L.final(t, "QUANT_SIGNAL_NOT_ACTED", "paper", o=dict(o, state=state), src=src, k=k)
        elif wide:
            L.final(t, "STOP_TOO_WIDE", "plan", o=dict(o, stop_pct=wide), th={"max_stop": cfg["max_stop"]}, src=src,
                    k=k)
        else:
            L.final(t, "NO_STRATEGY_SIGNAL", "signal", o=o or None, src=src, k=k)
    C.note_identity_steps(L, sorted(universe))
    part = L.to_part()
    published = set(new_by) | set(open_by)
    led = {r["a"] for r in L.records.values() if r["d"] == T.SURFACED}
    if published & set(universe) != led:
        L.problem("published quant signals/positions differ from the ledger's SURFACED")
        part["problems"] = L.problems
    part["stages"] = {"universe": len(universe), "liquid_crypto": len(chosen), "with_4h": len(data),
                      "eligible_latest_day": len(feats), "xsmom_ranked": len(xs), "new_signals": len(new),
                      "open": len(open_trades), "latest_day": lastd}
    return part


def audit(out_dir, now, **kw):
    parts.safe_audit("quant", out_dir, quant_part, ts=now, now=now, **kw)
