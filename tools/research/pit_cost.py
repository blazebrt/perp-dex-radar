"""Point-in-time trading costs for research (v8 Phase 8): fees, slippage and funding as they were knowable then.

    Historical research may use only information that was actually knowable at that historical time.

The legacy research (qdata.Panel.slip, pk_trades.COST) charges every past trade the slippage of TODAY's trade-DEX
volume (or a fixed 0.05%) and fills funding it never observed with an assumed 0.01% every 8 hours. Here:

Slippage  time-varying [time, coin]: the tier (same tiers as the scanner: $1M+ a day on your trade DEXs 0.05%,
          $200k-$1M 0.1%, below $200k 0.2%) of the execution liquidity the v8 history recorded at or before that
          time and no older than v8.pit.LIQUIDITY_MAX_STALENESS_S. No such record, or a MISSING volume, is
          LIQUIDITY_HISTORY_UNKNOWN: NaN, never a tier. A trade's entry pays the slippage known at its entry and
          its exit the slippage known at its exit; today's volume never changes a past trade's cost.
Funding   per hour: OBSERVED (a settlement was recorded), OBSERVED_ZERO (recorded at 0), NOT_DUE (inside the
          recorded series, between settlements) or MISSING (before the first or after the last settlement, inside a
          gap longer than the venue's cycle allows, or no funding series at all). Only observed settlements count.
          MISSING is never filled with 0.01% per 8 hours; ASSUMED_SCENARIO does that, only in a scenario.
Fees      one governed schedule (FEE_SCHEDULE) with its limitation stated.

A cost is authoritative only when every input of it was known: a trade with unknown liquidity at entry or exit, or
a funding gap while it was held, is excluded from the authoritative aggregate (kept, with its reasons)."""
from __future__ import annotations

import csv
import gzip
import os

import numpy as np

VERSION = "v8.pit-cost/1"
FEE_SCHEDULE = {
    "version": "v8.fees/1", "taker": 0.00045, "maker": 0.00015,
    "basis": "Hyperliquid base tier (taker 0.045%, maker 0.015%), the schedule the research has always used "
             "(qsim.FEE_T / FEE_M)",
    "limitation": "One schedule for every venue and every date: venue-specific fees, volume tiers, discounts and "
                  "their changes over time are not modelled. It is a governed constant, not an observation."}
SLIP_TIERS = ((1_000_000.0, 0.0005), (200_000.0, 0.001), (0.0, 0.002))      # the scanner's tiers (unchanged)
SCENARIO_FUNDING_8H = 0.0001                                                 # ASSUMED_SCENARIO only
F_NOT_DUE, F_OBSERVED, F_OBSERVED_ZERO, F_MISSING = 0, 1, 2, 3
FUNDING_STATES = {F_NOT_DUE: "NOT_DUE", F_OBSERVED: "OBSERVED", F_OBSERVED_ZERO: "OBSERVED_ZERO",
                  F_MISSING: "MISSING"}
L_KNOWN, L_UNKNOWN, L_MISSING, L_NOT_ON_TRADE_DEX = 0, 1, 2, 3
LIQUIDITY_STATES = {L_KNOWN: "KNOWN", L_UNKNOWN: "LIQUIDITY_HISTORY_UNKNOWN", L_MISSING: "MISSING",
                    L_NOT_ON_TRADE_DEX: "NOT_ON_TRADE_DEX"}
GAP_TOLERANCE = 1.5          # a settlement later than 1.5 cycles after the previous one leaves a gap


def tier(vol):
    """Slippage per market order for one known 24h trade-DEX volume (the scanner's tiers)."""
    for lo, s in SLIP_TIERS:
        if vol >= lo:
            return s
    return SLIP_TIERS[-1][1]


def tiers(vol):
    v = np.asarray(vol, dtype=float)
    out = np.where(v >= 1e6, 0.0005, np.where(v >= 2e5, 0.001, 0.002))
    return np.where(np.isfinite(v), out, np.nan)


# --------------------------------------------------------------------------- liquidity / slippage [time, coin]
def liquidity_panel(hist, times, coins):
    """(vol [T,N] NaN unless KNOWN, state [T,N] int8, slip [T,N] NaN unless KNOWN) from a v8.pit.History for the
    given unix times (each the moment a cost is paid) and coin tickers."""
    times = np.asarray(times, dtype=np.int64)
    T, N = len(times), len(coins)
    vol = np.full((T, N), np.nan)
    state = np.full((T, N), L_UNKNOWN, dtype=np.int8)
    if hist is not None and hist.ok:
        for j, c in enumerate(coins):
            ts, vs = hist._liq.get(c, ((), ()))
            if not ts:
                continue
            ts_a = np.asarray(ts, dtype=np.int64)
            k = np.searchsorted(ts_a, times, side="right") - 1
            ok = k >= 0
            kk = np.where(ok, k, 0)
            fresh = ok & (times - ts_a[kk] <= hist.liq_max_staleness_s)
            st = np.array([s for s, _ in vs], dtype=object)
            val = np.array([np.nan if v is None else float(v) for _, v in vs])
            sel_st, sel_v = st[kk], val[kk]
            known = fresh & (sel_st == "KNOWN") & np.isfinite(sel_v)
            vol[known, j] = sel_v[known]
            state[known, j] = L_KNOWN
            state[fresh & (sel_st == "MISSING"), j] = L_MISSING
            state[fresh & (sel_st == "NOT_ON_TRADE_DEX"), j] = L_NOT_ON_TRADE_DEX
    return vol, state, tiers(vol)


def legacy_slip(trade_vol):
    """The legacy cost input: one slippage per coin from today's volume (qdata.Panel.slip)."""
    tv = np.asarray(trade_vol, dtype=float)
    return np.where(tv >= 1e6, 0.0005, np.where(tv >= 2e5, 0.001, 0.002))


# --------------------------------------------------------------------------- funding [hour, coin]
def _read(path):
    with gzip.open(path, "rt") as fh:
        r = csv.reader(fh)
        head = next(r)
        return head, [row for row in r]


def funding_series(md, coin):
    """(source, [(t, rate, cycle_h)]) - the same source the legacy panel reads (MEXC first, else Hyperliquid)."""
    p = os.path.join(md, "fund_mexc", f"{coin}.csv.gz")
    if os.path.exists(p):
        head, rows = _read(p)
        ci = head.index("cycle_h") if "cycle_h" in head else None
        out = []
        for r in rows:
            if r[1] == "":
                continue
            cyc = float(r[ci]) if ci is not None and r[ci] not in ("", None) else 8.0
            out.append((int(r[0]), float(r[1]), cyc))
        return "mexc", sorted(out)
    p = os.path.join(md, "fund_hl", f"{coin}.csv.gz")
    if os.path.exists(p):
        _, rows = _read(p)
        return "hl", sorted((int(r[0]), float(r[1]), 1.0) for r in rows if r[1] != "")
    return None, []


def funding_panel_from_series(t, series, bar=3600):
    """(rate [T], state [T]) for one coin on the time grid t (bar starts) from its settlements [(t, rate, cycle_h)].

    A bar is MISSING when a settlement was due inside it and none was recorded: before the first settlement, after
    the last settlement's cycle ran out, and inside a gap (the next settlement came more than GAP_TOLERANCE cycles
    after the previous one: every bar from the first missed due time up to the next recorded settlement). A bar
    with a recorded settlement is OBSERVED (OBSERVED_ZERO at a rate of 0) unless a due time inside it was missed."""
    t = np.asarray(t, dtype=np.int64)
    T = len(t)
    rate = np.zeros(T)
    state = np.full(T, F_MISSING, dtype=np.int8)
    if not series or T == 0:
        return rate, state
    first, last_t, last_cyc = series[0][0], series[-1][0], series[-1][2]
    covered = (t + bar > first) & (t < last_t + int(round(last_cyc * 3600)))
    state[covered] = F_NOT_DUE
    for (a, _, cyc), (b, _, _) in zip(series, series[1:]):
        due = a + int(round(cyc * 3600))
        if b - a > GAP_TOLERANCE * cyc * 3600:
            state[(t + bar > due) & (t < b)] = F_MISSING
    for ts, r, _ in series:
        i = (ts - int(t[0])) // bar
        if 0 <= i < T:
            rate[i] += r
            if state[i] != F_MISSING:
                state[i] = F_OBSERVED if (r != 0 or state[i] == F_OBSERVED) else F_OBSERVED_ZERO
    return rate, state


def funding_panel(md, t, coins, bar=3600, cutoff=None):
    """(rate [T,N], state [T,N], source per coin) from the market-data funding files: observed settlements only
    (none after `cutoff`)."""
    T, N = len(t), len(coins)
    rate = np.zeros((T, N))
    state = np.full((T, N), F_MISSING, dtype=np.int8)
    src = []
    for j, c in enumerate(coins):
        s, ser = funding_series(md, c)
        if cutoff is not None:
            ser = [x for x in ser if x[0] <= cutoff]
        src.append(s or "none")
        rate[:, j], state[:, j] = funding_panel_from_series(t, ser, bar)
    return rate, state, src


def scenario_funding(t, state, bar=3600):
    """ASSUMED_SCENARIO: 0.01% per 8 hours at every 8-hour boundary that is MISSING (scenario only, never
    authority)."""
    base = (np.asarray(t, dtype=np.int64) % (8 * 3600)) == 0
    return np.where((state == F_MISSING) & base[:, None], SCENARIO_FUNDING_8H, 0.0)


# --------------------------------------------------------------------------- per-trade cost and qualification
def trade_costs(i_entry, i_exit, j, d, target_exit, slip_pt, fund_rate, fund_state, scen_fund=None,
                fee=FEE_SCHEDULE):
    """Per-trade costs as fractions of notional, vectorised over trades.

    i_entry, i_exit: bar indexes of the entry (open) and of the exit bar; j: coin column; d: +1 long / -1 short;
    target_exit: True where the exit was a take-profit limit (maker fee, no exit slippage).
    slip_pt [T,N]: point-in-time slippage (NaN = unknown). Funding counts bars i_entry+1 .. i_exit (as qsim).
    Returns a dict of arrays: fee, slip_entry, slip_exit, slippage, funding, cost, liquidity_known,
    funding_known, funding_missing_bars, scenario_funding."""
    i_entry, i_exit, j = (np.asarray(x, dtype=np.int64) for x in (i_entry, i_exit, j))
    d = np.asarray(d, dtype=float)
    target_exit = np.asarray(target_exit, dtype=bool)
    se = slip_pt[i_entry, j]
    sx = np.where(target_exit, 0.0, slip_pt[i_exit, j])
    fee_ = fee["taker"] + np.where(target_exit, fee["maker"], fee["taker"])
    n = len(i_entry)
    fsum = np.zeros(n)
    miss = np.zeros(n, dtype=np.int64)
    ssum = np.zeros(n)
    cr = np.cumsum(np.vstack([np.zeros((1, fund_rate.shape[1])), fund_rate]), axis=0)
    cm = np.cumsum(np.vstack([np.zeros((1, fund_state.shape[1]), dtype=np.int64),
                              (fund_state == F_MISSING).astype(np.int64)]), axis=0)
    a, b = i_entry + 1, i_exit + 1                       # bars a .. i_exit inclusive
    b = np.maximum(a, b)
    fsum = cr[b, j] - cr[a, j]
    miss = cm[b, j] - cm[a, j]
    if scen_fund is not None:
        cs = np.cumsum(np.vstack([np.zeros((1, scen_fund.shape[1])), scen_fund]), axis=0)
        ssum = cs[b, j] - cs[a, j]
    liq_known = np.isfinite(se) & np.isfinite(sx)
    slip = se + sx
    funding = d * fsum
    return {"fee": fee_, "slip_entry": se, "slip_exit": sx, "slippage": slip, "funding": funding,
            "cost": fee_ + slip + funding, "liquidity_known": liq_known, "funding_known": miss == 0,
            "funding_missing_bars": miss, "scenario_funding": d * (fsum + ssum)}
