"""Helpers shared by the engine audits: contract ids, the tradfi and liquidity reasons, candle-miss reasons."""
from __future__ import annotations

from . import health as H
from . import taxonomy as T
from .trace import TRACE


def contract_ids(coin):
    """The venue contracts the legacy universe kept for a coin (venue:raw_symbol)."""
    return [f"{d}:{v.get('sym')}" for d, v in sorted(((coin or {}).get("venues") or {}).items())]


def tradfi_code(coin, trace=TRACE):
    """TRADFI_TICKER_COLLISION when the venues disagree (one lists the ticker as crypto), else TRADFI_CLASSIFIED.

    The legacy universe ORs the tradfi flag over every adapter row of the ticker - duplicates and markets later
    dropped as price conflicts included - so the observed value names the rows that carried the flag."""
    venues = (coin or {}).get("venues") or {}
    flags = {d: bool(v.get("tradfi")) for d, v in venues.items()}
    code = "TRADFI_TICKER_COLLISION" if any(not f for f in flags.values()) else "TRADFI_CLASSIFIED"
    t = (coin or {}).get("t")
    o = {"venue_tradfi": dict(sorted(flags.items())), "name": (coin or {}).get("name")}
    try:
        import scanner as sc
        o["known_crypto"] = t in sc.KNOWN_CRYPTO     # True: a listed crypto coin is the one being excluded
    except Exception:  # noqa: BLE001
        pass
    rows = getattr(trace, "rows", None) or {}
    flagged = sorted(f"{d}:{r.get('sym')}" for d, rs in rows.items() for r in (rs or [])
                     if r.get("t") == t and r.get("tradfi"))
    if flagged:
        o["tradfi_rows"] = flagged
    return code, o


def liquidity_final(L, t, coin, stage, min_vol, in_my_dexes, k=None):
    """The final record of a coin the legacy `(liq_of(c) or 0) >= min` check leaves out."""
    b, v = H.liquidity(coin, in_my_dexes)
    if b == H.OBSERVED:
        return L.final(t, "DEX_VOLUME_BELOW_LEGACY_MIN", stage, o={"trade_vol": v, "basis": b}, th={"min": min_vol},
                       k=k)
    if b == H.OBSERVED_ZERO:
        return L.final(t, "DEX_VOLUME_BELOW_LEGACY_MIN", stage, o={"trade_vol": 0.0, "basis": b},
                       th={"min": min_vol}, k=k)
    if b == H.NOT_ON_TRADE_DEX:
        return L.final(t, "NOT_ON_TRADE_DEX", stage, o={"venues": sorted(((coin or {}).get("venues") or {}))},
                       th={"min": min_vol}, k=k)
    return L.final(t, "DEX_VOLUME_MISSING_LEGACY_ZERO", stage, o={"trade_vol": None, "basis": b,
                                                                   "legacy_used": 0.0},
                   th={"min": min_vol}, h=T.MISSING, k=k)


def candle_miss(tried, short_code):
    """(code, health, observed) for a candle request that returned nothing usable.

    tried: [(source, outcome), ...] from the trace, outcome one of 'breaker', 'no_venue', 'error', 'short:<n>',
    'scale'. A scale mismatch wins (another asset under the symbol), then too-short history, else no source."""
    tried = tried or []
    if any(o == "scale" for _, o in tried):
        return "PRICE_SCALE_CONFLICT", T.CONFLICTED, {"tried": [f"{s}:{o}" for s, o in tried]}
    shorts = [(s, int(o.split(":")[1])) for s, o in tried if str(o).startswith("short:") and o != "short:0"]
    if shorts:
        best = max(shorts, key=lambda x: x[1])
        return short_code, T.MISSING, {"bars": best[1], "src": best[0], "tried": [f"{s}:{o}" for s, o in tried]}
    return "NO_SUPPORTED_CANDLES", T.MISSING, {"tried": [f"{s}:{o}" for s, o in tried] or None}
