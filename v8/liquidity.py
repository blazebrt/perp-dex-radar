"""Execution liquidity of a universe coin (v8 Phase 2): one shared evaluation, three states.

    KNOWN              at least one of your trade DEXs reported a 24h volume (an observed 0 is a known 0)
    MISSING            the coin trades on your trade DEXs, but none of them reported a volume
    NOT_ON_TRADE_DEX   the coin is not listed on any of your trade DEXs

The legacy engines gated on `(liq_of(coin) or 0) >= min`, which turned a missing volume into an observed $0.
passes() gives the same yes/no for every coin - a missing volume still cannot pass the gate: missing evidence is not
evidence of execution liquidity - but the reason is now named (v8.common.liquidity_final): KNOWN below the minimum
is NOT_EXECUTABLE / DEX_VOLUME_BELOW_LEGACY_MIN, MISSING is INSUFFICIENT_DATA / DEX_VOLUME_MISSING, and
NOT_ON_TRADE_DEX stays its own reason.

sort_value() is the only place a missing volume becomes 0: an internal, deterministic sort fallback. Stored and
published values keep None (see stored())."""
from __future__ import annotations

import math

VERSION = "v8.liquidity/1"
KNOWN, MISSING, NOT_ON_TRADE_DEX = "KNOWN", "MISSING", "NOT_ON_TRADE_DEX"
OBSERVED, OBSERVED_ZERO = "OBSERVED", "OBSERVED_ZERO"


def _observed(x):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def evaluate(coin, trade_dexes=()):
    """{"state", "value", "basis", "venues"} for one universe coin.

    trade_dexes: the DEXs you trade (scanner CFG["trade_dexes"]); empty means every DEX counts. The value is the
    coin's own trade_vol (best_vol when every DEX counts) - exactly what scanner.liq_of() returns, the largest 24h
    volume reported on those DEXs, an observed 0 included (v8.identity). None means no such venue reported one:
    NOT_ON_TRADE_DEX when the coin has venues but none on your trade DEXs, else MISSING."""
    coin = coin or {}
    venues = coin.get("venues") or {}
    mine = sorted(d for d in venues if not trade_dexes or d in trade_dexes)
    value = _observed(coin.get("trade_vol") if trade_dexes else coin.get("best_vol"))
    if value is not None:
        return {"state": KNOWN, "value": value, "basis": OBSERVED if value != 0 else OBSERVED_ZERO, "venues": mine}
    if venues and not mine:
        return {"state": NOT_ON_TRADE_DEX, "value": None, "basis": None, "venues": sorted(venues)}
    return {"state": MISSING, "value": None, "basis": "MISSING", "venues": mine}


def passes(coin, min_vol, trade_dexes=()):
    """The execution-liquidity gate: KNOWN and at least min_vol. MISSING and NOT_ON_TRADE_DEX never pass."""
    e = evaluate(coin, trade_dexes)
    return e["state"] == KNOWN and e["value"] >= min_vol


def sort_value(coin, trade_dexes=()):
    """A number to rank coins by liquidity: the KNOWN value, else 0.0. Internal ordering only, never stored."""
    e = evaluate(coin, trade_dexes)
    return e["value"] if e["state"] == KNOWN else 0.0


def stored(x):
    """A volume for publishing: rounded, or None when it is missing (never 0 in place of a missing value)."""
    return round(x) if x is not None else None
