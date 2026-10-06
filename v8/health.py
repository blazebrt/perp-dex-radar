"""Data-health states and how each value was observed.

A value is one of
    OBSERVED              the venue sent a number (non-zero)
    OBSERVED_ZERO         the venue sent exactly 0
    MISSING               the venue sent nothing (field absent, null, unparsable)
    MISSING_LEGACY_ZERO   missing, and the legacy engine uses 0 in its place (e.g. `liq_of(c) or 0`)
    ASSUMED_DEFAULT       missing, and the legacy engine uses a configured default (e.g. fund_default)

A record (contract, candle set, engine input) is HEALTHY, STALE, MISSING or CONFLICTED. These states are
observations only: Phase 1 never feeds them back into any engine."""
from __future__ import annotations

from .taxonomy import CONFLICTED, HEALTHY, MISSING, STALE

OBSERVED, OBSERVED_ZERO, MISSING_VALUE = "OBSERVED", "OBSERVED_ZERO", "MISSING"
MISSING_LEGACY_ZERO, ASSUMED_DEFAULT = "MISSING_LEGACY_ZERO", "ASSUMED_DEFAULT"
NOT_ON_TRADE_DEX = "NOT_ON_TRADE_DEX"

_RANK = {HEALTHY: 0, STALE: 1, MISSING: 2, CONFLICTED: 3}
STALE_AFTER_S = 900          # a venue timestamp older than this at receipt marks the record stale


def basis(value):
    """How a raw value was observed: OBSERVED, OBSERVED_ZERO or MISSING."""
    if value is None:
        return MISSING_VALUE
    try:
        f = float(value)
    except (TypeError, ValueError):
        return MISSING_VALUE
    if f != f:  # NaN
        return MISSING_VALUE
    return OBSERVED_ZERO if f == 0 else OBSERVED


def worst(states):
    """The worst of several health states (CONFLICTED > MISSING > STALE > HEALTHY); HEALTHY for none."""
    out = HEALTHY
    for s in states:
        if s and _RANK.get(s, 0) > _RANK[out]:
            out = s
    return out


def contract_state(price_basis, vol_basis, conflicted=False, source_ts=None, receive_ts=None):
    """Health of one raw contract record."""
    if conflicted:
        return CONFLICTED
    if price_basis == MISSING_VALUE or vol_basis == MISSING_VALUE:
        return MISSING
    if source_ts is not None and receive_ts is not None and receive_ts - source_ts > STALE_AFTER_S:
        return STALE
    return HEALTHY


def liquidity(coin, in_my_dexes):
    """(basis, value) of the legacy liquidity of a universe coin, as `liq_of(coin) or 0` sees it.

    The legacy coin keeps only truthy volumes (`if v.get("vol")`), so an observed 0 and a missing value both end up
    as trade_vol None and then 0. This tells the two apart from the venue rows the coin still carries."""
    venues = (coin or {}).get("venues") or {}
    mine = [v for d, v in venues.items() if in_my_dexes(d)]
    vols = [v.get("vol") for v in mine]
    good = [x for x in vols if basis(x) == OBSERVED]
    if good:
        return OBSERVED, max(good)
    if not venues:
        return MISSING_LEGACY_ZERO, None
    if not mine:
        return NOT_ON_TRADE_DEX, None
    if any(basis(x) == OBSERVED_ZERO for x in vols):
        return OBSERVED_ZERO, 0.0
    return MISSING_LEGACY_ZERO, None


def funding(coin):
    """(basis, value) of the coin's average DEX funding per 8h as legacy paper costs use it: OBSERVED when any
    venue sent funding, else ASSUMED_DEFAULT (scanner CFG fund_default)."""
    fs = [v.get("funding8h") for v in ((coin or {}).get("venues") or {}).values() if v.get("funding8h") is not None]
    if fs:
        return OBSERVED, sum(fs) / len(fs)
    return ASSUMED_DEFAULT, None
