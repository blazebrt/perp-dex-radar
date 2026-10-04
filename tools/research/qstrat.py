"""Strategy library: long and short signals on closed bars. Every signal is known at the close of
its bar (hourly index i) and is entered at the open of bar i+1."""
from __future__ import annotations

import numpy as np

import qind as I
from qdata import resample

MIN_STOP = 0.015
MAX_STOP = 0.20


class Feat:
    """Features on the hourly panel and on 4h / daily bars (mapped to the hour they become known)."""

    def __init__(self, p, min_days=30, min_vol_usd=5e6):
        self.p = p
        bh = p.bar_h
        self.bar_h = bh
        h, l, c, v = p.h, p.l, p.c, p.v
        self.atr1 = I.atr(h, l, c, 14)
        self.atr1_24 = I.atr(h, l, c, 24)
        # eligibility: 30 days of history and $5M+ a day traded on the reference exchange
        alive = ~np.isnan(c)
        age = np.cumsum(alive, axis=0)
        per_day = 24 // bh
        vol24 = I.df(np.nan_to_num(v)).rolling(per_day * 7, min_periods=per_day).mean().to_numpy() * per_day
        self.vol24 = vol24
        self.elig = alive & (age >= per_day * min_days) & (vol24 >= min_vol_usd)
        # 4h and daily bars
        self.b4 = self._bars(4 // bh)
        self.bd = self._bars(24 // bh)

    def _bars(self, k):
        t, o, h, l, c, v, end = resample(self.p, k)
        b = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v, "end": end, "hours": k * self.bar_h}
        b["atr"] = I.atr(h, l, c, 14)
        return b


def _stop_from_atr(price, atr, k, floor=MIN_STOP):
    with np.errstate(all="ignore"):
        return np.fmax(floor, k * atr / price)


def _emit(out, i, j, d, stop, target, trail, be, hold):
    ok = (stop > 0) & (stop <= MAX_STOP) & np.isfinite(stop)
    for key, val in (("i", i), ("j", j), ("d", d), ("stop", stop), ("target", target), ("trail", trail),
                     ("be", be), ("hold", hold)):
        out.setdefault(key, []).append(np.broadcast_to(val, i.shape)[ok] if np.ndim(val) else
                                       np.full(int(ok.sum()), val))


def _pack(out):
    if not out:
        return {k: np.array([]) for k in ("i", "j", "d", "stop", "target", "trail", "be", "hold")}
    return {k: np.concatenate(v) for k, v in out.items()}


def _on_bars(F, b, cond_long, cond_short, stop_k, trail_k, hold_h, target=0.0, be=0.0, sides="both",
             stop_override=None):
    """Turn bar-level conditions [K, N] into hourly signals at each bar's last hour."""
    out = {}
    end = b["end"]
    with np.errstate(all="ignore"):
        price = b["c"]
        stop = stop_override if stop_override is not None else _stop_from_atr(price, b["atr"], stop_k)
        trail = trail_k * b["atr"] / price if trail_k else np.zeros_like(price)
    elig_b = F.elig[end]
    for d, cond in ((1, cond_long), (-1, cond_short)):
        if cond is None or (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        k, j = np.where(cond & elig_b)
        if len(k) == 0:
            continue
        i = end[k]
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[k, j], target, trail[k, j], be,
              max(1, hold_h // F.bar_h))
    s = _pack(out)
    s["i"] = s["i"].astype(np.int64)
    s["j"] = s["j"].astype(np.int64)
    s["hold"] = s["hold"].astype(np.int64)
    return s


# ---------------------------------------------------------------------------- strategies
def trend_donchian(F, n=55, tf=4, stop_k=2.0, trail_k=3.0, hold_days=30, sides="both"):
    """Breakout of the n-bar high (long) or low (short) on 4h bars; ATR trailing stop; let winners run."""
    b = F.b4 if tf == 4 else F.bd
    h, l, c = b["h"], b["l"], b["c"]
    hi = I.shift(I.rmax(h, n))
    lo = I.shift(I.rmin(l, n))
    with np.errstate(all="ignore"):
        up = (c > hi) & (I.shift(c) <= I.shift(hi))
        dn = (c < lo) & (I.shift(c) >= I.shift(lo))
    return _on_bars(F, b, up, dn, stop_k, trail_k, hold_days * 24, sides=sides)


def trend_ema(F, fast=20, slow=100, tf=4, adx_min=20, stop_k=2.5, trail_k=3.0, hold_days=30, sides="both"):
    """EMA cross on 4h bars with a trend-strength (ADX) filter; ATR trailing stop."""
    b = F.b4 if tf == 4 else F.bd
    c = b["c"]
    ef, es = I.ema(c, fast), I.ema(c, slow)
    a, pdi, ndi = I.adx(b["h"], b["l"], c, 14)
    with np.errstate(all="ignore"):
        up = (ef > es) & (I.shift(ef) <= I.shift(es)) & (a > adx_min)
        dn = (ef < es) & (I.shift(ef) >= I.shift(es)) & (a > adx_min)
    return _on_bars(F, b, up, dn, stop_k, trail_k, hold_days * 24, sides=sides)


def tsmom(F, look=30, short_look=7, stop_k=3.0, trail_k=3.0, hold_days=21, sides="both"):
    """Time-series momentum on daily bars: 30-day and 7-day returns and the 50-day EMA agree."""
    b = F.bd
    c = b["c"]
    r1, r2 = I.ret(c, look), I.ret(c, short_look)
    e = I.ema(c, 50)
    with np.errstate(all="ignore"):
        up = (r1 > 0) & (r2 > 0) & (c > e)
        dn = (r1 < 0) & (r2 < 0) & (c < e)
    return _on_bars(F, b, up, dn, stop_k, trail_k, hold_days * 24, sides=sides)


def xs_momentum(F, look=7, hold_days=3, top=5, stop_k=2.5, sides="both", vol_adj=True):
    """Cross-sectional momentum on daily bars: long the strongest `top` coins, short the weakest."""
    b = F.bd
    c = b["c"]
    r = I.ret(c, look)
    if vol_adj:
        dr = I.ret(c, 1)
        vol = I.rstd(dr, 30, minp=20)
        with np.errstate(all="ignore"):
            r = r / vol
    elig = F.elig[b["end"]]
    r = np.where(elig, r, np.nan)
    rank_hi = I.df(r).rank(axis=1, ascending=False).to_numpy()
    rank_lo = I.df(r).rank(axis=1, ascending=True).to_numpy()
    up = rank_hi <= top
    dn = rank_lo <= top
    return _on_bars(F, b, up, dn, stop_k, 0.0, hold_days * 24, sides=sides)


def xs_reversal(F, look=1, hold_days=1, top=5, stop_k=2.5, sides="both"):
    """Cross-sectional short-term reversal: long the biggest 1-day losers, short the biggest winners."""
    b = F.bd
    r = I.ret(b["c"], look)
    elig = F.elig[b["end"]]
    r = np.where(elig, r, np.nan)
    up = I.df(r).rank(axis=1, ascending=True).to_numpy() <= top
    dn = I.df(r).rank(axis=1, ascending=False).to_numpy() <= top
    return _on_bars(F, b, up, dn, stop_k, 0.0, hold_days * 24, sides=sides)


def squeeze_breakout(F, tf=4, pct=0.10, look=180, vol_mult=1.5, stop_k=2.0, trail_k=2.5, hold_days=10,
                     sides="both"):
    """Bollinger bands at their narrowest in `look` bars, then a close outside the band with volume."""
    b = F.b4 if tf == 4 else F.bd
    c, v = b["c"], b["v"]
    w, upper, lower = I.boll_width(c, 20, 2.0)
    wr = I.pct_rank(w, look, minp=look // 2)
    va = I.sma(v, 20)
    with np.errstate(all="ignore"):
        tight = I.shift(wr) <= pct
        up = tight & (c > upper) & (v > vol_mult * I.shift(va))
        dn = tight & (c < lower) & (v > vol_mult * I.shift(va))
    return _on_bars(F, b, up, dn, stop_k, trail_k, hold_days * 24, sides=sides)


def liq_flush(F, z=3.0, vol_mult=3.0, target=1.5, hold_h=12, sides="both"):
    """A one-hour crash (or spike) of z ATRs on heavy volume: forced selling (buying) that tends to
    snap back. Enter against it at the next open; stop beyond the extreme."""
    p = F.p
    o, h, l, c, v = p.o, p.h, p.l, p.c, p.v
    a = I.shift(F.atr1_24)
    va = I.shift(I.sma(v, 24 * 7, minp=48))
    out = {}
    with np.errstate(all="ignore"):
        body = (c - o) / a
        heavy = v > vol_mult * va
        dn_bar = (body < -z) & heavy & F.elig
        up_bar = (body > z) & heavy & F.elig
        stop_long = np.fmax(MIN_STOP, (c - (l - 0.25 * a)) / c)
        stop_short = np.fmax(MIN_STOP, ((h + 0.25 * a) - c) / c)
    for d, cond, stop in ((1, dn_bar, stop_long), (-1, up_bar, stop_short)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], target, 0.0, 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def pullback(F, rsi_lo=35, rsi_up=40, target=2.5, be=1.0, hold_h=72, swing=12, sides="both"):
    """Trend on 4h (EMA50 vs EMA200, price beyond EMA50), entry on a 1h RSI pullback that turns back."""
    p, b = F.p, F.b4
    e50, e200 = I.ema(b["c"], 50), I.ema(b["c"], 200)
    with np.errstate(all="ignore"):
        up4 = (e50 > e200) & (b["c"] > e50)
        dn4 = (e50 < e200) & (b["c"] < e50)
    # map the last closed 4h state to every hour
    up_h = np.zeros((p.T, p.N), dtype=bool)
    dn_h = np.zeros((p.T, p.N), dtype=bool)
    end = b["end"]
    for k in range(len(end) - 1):
        up_h[end[k]:end[k + 1]] = up4[k]
        dn_h[end[k]:end[k + 1]] = dn4[k]
    up_h[end[-1]:] = up4[-1]
    dn_h[end[-1]:] = dn4[-1]
    r = I.rsi(p.c, 14)
    a = F.atr1
    lo_sw = I.rmin(p.l, swing)
    hi_sw = I.rmax(p.h, swing)
    was_lo = I.rmin(r, 6) < rsi_lo
    was_hi = I.rmax(r, 6) > 100 - rsi_lo
    out = {}
    with np.errstate(all="ignore"):
        long_c = up_h & was_lo & (r > rsi_up) & (I.shift(r) <= rsi_up) & F.elig
        short_c = dn_h & was_hi & (r < 100 - rsi_up) & (I.shift(r) >= 100 - rsi_up) & F.elig
        stop_long = np.fmax(MIN_STOP, (p.c - (lo_sw - 0.25 * a)) / p.c)
        stop_short = np.fmax(MIN_STOP, ((hi_sw + 0.25 * a) - p.c) / p.c)
    for d, cond, stop in ((1, long_c, stop_long), (-1, short_c, stop_short)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], target, 0.0, be, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def failed_breakout(F, look=48, wick=0.5, target=2.0, hold_h=24, sides="both"):
    """A new 48-hour high that closes back below the old high with a long upper wick (stop hunt): short.
    Mirror at lows: long."""
    p = F.p
    o, h, l, c = p.o, p.h, p.l, p.c
    a = F.atr1
    ph = I.shift(I.rmax(h, look))
    pl = I.shift(I.rmin(l, look))
    rng = h - l
    out = {}
    with np.errstate(all="ignore"):
        upper_wick = (h - np.fmax(o, c)) / rng
        lower_wick = (np.fmin(o, c) - l) / rng
        short_c = (h > ph) & (c < ph) & (upper_wick > wick) & F.elig
        long_c = (l < pl) & (c > pl) & (lower_wick > wick) & F.elig
        stop_short = np.fmax(MIN_STOP, ((h + 0.25 * a) - c) / c)
        stop_long = np.fmax(MIN_STOP, (c - (l - 0.25 * a)) / c)
    for d, cond, stop in ((1, long_c, stop_long), (-1, short_c, stop_short)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], target, 0.0, 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def volume_spike(F, vol_mult=5.0, body_atr=2.0, close_pos=0.8, stop_k=1.5, trail_k=2.0, hold_h=12, sides="both"):
    """An hour with 5x normal volume and a big body closing near its extreme: follow it."""
    p = F.p
    o, h, l, c, v = p.o, p.h, p.l, p.c, p.v
    a = I.shift(F.atr1_24)
    va = I.shift(I.sma(v, 24 * 7, minp=48))
    out = {}
    with np.errstate(all="ignore"):
        pos = (c - l) / (h - l)
        big = (np.abs(c - o) > body_atr * a) & (v > vol_mult * va) & F.elig
        long_c = big & (c > o) & (pos >= close_pos)
        short_c = big & (c < o) & (pos <= 1 - close_pos)
        stop = np.fmax(MIN_STOP, stop_k * a / c)
        trail = trail_k * a / c
    for d, cond in ((1, long_c), (-1, short_c)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], 0.0, trail[i, j], 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def btc_lead(F, btc_move=0.015, lag=0.3, beta_h=24 * 30, hold_h=6, stop_k=2.0, sides="both"):
    """BTC makes a big 1-hour move; alts that have not followed yet (relative to their beta) catch up."""
    p = F.p
    r = I.ret(p.c, 1)
    rb = r[:, 0:1]
    # rolling beta of each coin to BTC (hourly returns, 30 days), known up to the previous hour
    rb_f = np.repeat(rb, p.N, axis=1)
    cov = I.df(r * rb_f).rolling(beta_h, min_periods=beta_h // 2).mean().to_numpy() - \
        I.sma(r, beta_h, minp=beta_h // 2) * I.sma(rb_f, beta_h, minp=beta_h // 2)
    var = I.rstd(rb_f, beta_h, minp=beta_h // 2) ** 2
    with np.errstate(all="ignore"):
        beta = I.shift(cov / var)
        exp_r = beta * rb
        a = F.atr1
        stop = np.fmax(MIN_STOP, stop_k * a / p.c)
        long_c = (rb > btc_move) & (r < lag * exp_r) & (beta > 0.5) & F.elig
        short_c = (rb < -btc_move) & (r > lag * exp_r) & (beta > 0.5) & F.elig
    long_c[:, 0] = False
    short_c[:, 0] = False
    out = {}
    for d, cond in ((1, long_c), (-1, short_c)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], 0.0, 0.0, 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def rs_breakout(F, look=30, top=0.2, brk=10, stop_k=2.0, trail_k=3.0, hold_days=14, sides="both"):
    """Leaders (strongest 30-day return vs BTC) breaking a 10-bar high while BTC's 4h trend is up: long.
    Laggards breaking a 10-bar low while BTC's trend is down: short."""
    b = F.b4
    c = b["c"]
    look_b = look * 6
    rs = I.ret(c, look_b) - I.ret(c[:, 0:1], look_b)
    elig = F.elig[b["end"]]
    rs = np.where(elig, rs, np.nan)
    rk = I.df(rs).rank(axis=1, pct=True).to_numpy()
    e50, e200 = I.ema(c[:, 0:1], 50), I.ema(c[:, 0:1], 200)
    hi = I.shift(I.rmax(b["h"], brk))
    lo = I.shift(I.rmin(b["l"], brk))
    with np.errstate(all="ignore"):
        btc_up = (e50 > e200) & (c[:, 0:1] > e50)
        btc_dn = (e50 < e200) & (c[:, 0:1] < e50)
        up = (rk >= 1 - top) & (c > hi) & btc_up
        dn = (rk <= top) & (c < lo) & btc_dn
    up[:, 0] = False
    dn[:, 0] = False
    return _on_bars(F, b, up, dn, stop_k, trail_k, hold_days * 24, sides=sides)


def funding_fade(F, hi=0.0004, lo=-0.0002, hold_h=48, stop_k=2.0, trail_k=0.0, sides="both"):
    """Crowded trades: very positive funding (longs pay a lot) while price stalls under its 1h EMA20 -> short;
    very negative funding while price holds above it -> long (squeeze). Checked right after each settlement."""
    p = F.p
    f = p.fund.copy()
    settle = f != 0
    last = np.where(settle, f, np.nan)
    last = I.ffill(last)
    e20 = I.ema(p.c, 20)
    a = F.atr1_24
    with np.errstate(all="ignore"):
        just = settle  # the hour a funding payment settles
        short_c = just & (last >= hi) & (p.c < e20) & F.elig
        long_c = just & (last <= lo) & (p.c > e20) & F.elig
        stop = np.fmax(MIN_STOP, stop_k * 4 * a / p.c)  # about 2 x the 4h ATR
        trail = trail_k * 4 * a / p.c if trail_k else np.zeros_like(p.c)
    out = {}
    for d, cond in ((1, long_c), (-1, short_c)):
        if (sides == "long" and d < 0) or (sides == "short" and d > 0):
            continue
        i, j = np.where(cond)
        _emit(out, i, j, np.full(len(i), d, dtype=float), stop[i, j], 0.0, trail[i, j], 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


def funding_carry(F, top=5, hold_h=24, stop_k=3.0, sides="both"):
    """Cross-sectional carry: at each settlement short the coins with the highest funding (they pay you)
    and long the coins with the most negative funding."""
    p = F.p
    f = p.fund
    settle = (f != 0).sum(axis=1) > p.N // 3
    rows = np.where(settle)[0]
    a = F.atr1_24
    out = {}
    for i in rows:
        fr = np.where(F.elig[i] & (f[i] != 0), f[i], np.nan)
        if np.isfinite(fr).sum() < 2 * top + 5:
            continue
        order = np.argsort(np.where(np.isfinite(fr), fr, np.inf))
        lows = [j for j in order[:top] if np.isfinite(fr[j]) and fr[j] < 0]
        order_hi = np.argsort(np.where(np.isfinite(fr), -fr, np.inf))
        highs = [j for j in order_hi[:top] if np.isfinite(fr[j]) and fr[j] > 0.0001]
        for d, js in ((1, lows), (-1, highs)):
            if not js or (sides == "long" and d < 0) or (sides == "short" and d > 0):
                continue
            js = np.array(js)
            ii = np.full(len(js), i)
            with np.errstate(all="ignore"):
                stop = np.fmax(MIN_STOP, stop_k * 4 * a[i, js] / p.c[i, js])
            _emit(out, ii, js, np.full(len(js), d, dtype=float), stop, 0.0, 0.0, 0.0, hold_h)
    s = _pack(out)
    for k in ("i", "j", "hold"):
        s[k] = s[k].astype(np.int64)
    return s


LIBRARY = {
    "TREND_DC55": (trend_donchian, {"n": 55}),
    "TREND_DC20": (trend_donchian, {"n": 20}),
    "TREND_EMA": (trend_ema, {}),
    "TSMOM": (tsmom, {}),
    "XSMOM_7D": (xs_momentum, {"look": 7, "hold_days": 3}),
    "XSMOM_14D": (xs_momentum, {"look": 14, "hold_days": 7}),
    "XSREV_1D": (xs_reversal, {}),
    "SQZ_4H": (squeeze_breakout, {}),
    "LIQ_FLUSH": (liq_flush, {}),
    "PULLBACK": (pullback, {}),
    "FAIL_BRK": (failed_breakout, {}),
    "VOL_SPIKE": (volume_spike, {}),
    "BTC_LEAD": (btc_lead, {}),
    "RS_BRK": (rs_breakout, {}),
    "FUND_FADE": (funding_fade, {}),
    "FUND_CARRY": (funding_carry, {}),
}
