"""Helpers shared by the engine audits: contract ids, the identity and liquidity reasons, candle-miss reasons."""
from __future__ import annotations

from . import identity as ID
from . import liquidity as LQ
from . import taxonomy as T
from .trace import TRACE


def contract_ids(coin):
    """The venue contracts the universe kept for a coin (venue:raw_symbol)."""
    return [f"{d}:{v.get('sym')}" for d, v in sorted(((coin or {}).get("venues") or {}).items())]


def identity_of(t, trace=TRACE):
    """The v8.identity decision for ticker t in this process's last universe, or None."""
    res = getattr(trace, "ident", None)
    return res.asset(t) if res is not None else None


def exposure_summary(info):
    """A compact, readable account of a ticker's exposures for a ledger record."""
    out = []
    crypto = (info or {}).get("state", ID.VERIFIED_CRYPTO) == ID.VERIFIED_CRYPTO
    for x in (info or {}).get("exposures") or []:
        y = {"id": x["id"], "class": x["class"], "reason": x["reason"], "price": x["anchor_price"] or
             (x["price_range"] or [None])[0], "contracts": x["members"],
             "admitted": bool(x["admitted"] or (x["attached"] and crypto))}
        if x.get("wrapper"):          # v8 Phase 5: the exposure's wrapper labels, never its class
            y["wrapper"] = x["wrapper"]
        out.append(y)
    return out


def wrapper_trace(info, o):
    """v8 Phase 5: adds the wrapper path (and its effect: none) and any exposure check that did not run to a ledger
    record, so the Decision Trace shows the wrapper and the economic evidence apart."""
    if (info or {}).get("wrapper_evidence"):
        o["wrapper"] = [[s, w, ID.WRAPPER_ONLY] for s, _, w, _ in info["wrapper_evidence"]]
    bad = [c for c in (info or {}).get("exposure_checks") or [] if c[2] != ID.XCHECK_OK]
    if bad:
        o["exposure_checks"] = bad
    return o


def excluded_code(coin, trace=TRACE):
    """(code, observed) for a coin the identity gate keeps out of the crypto engines: TRADFI_CLASSIFIED,
    TRADFI_EXPOSURE_EXCLUDED or AMBIGUOUS_EXPOSURE (tradfi=True), with the exposures that decided it; or, since v8
    Phase 3, IDENTITY_UNVERIFIED (in the universe, not tradfi, no positive identity evidence) with the evidence path
    and what would resolve it."""
    t = (coin or {}).get("t")
    info = identity_of(t, trace)
    if (coin or {}).get("tradfi"):
        if info is None:          # no identity trace (should not happen): name it, never guess
            return "AUDIT_UNCLASSIFIED", {"why": "no v8.identity decision recorded for this coin"}
        code = info["decision"]
        if code not in (ID.D_TRADFI, ID.D_TRADFI_EXPOSURE, ID.D_AMBIGUOUS):
            return "AUDIT_UNCLASSIFIED", {"why": f"coin excluded but identity decided {code}"}
        o = {"exposures": exposure_summary(info), "name": (coin or {}).get("name")}
        if info.get("ticker_list"):
            o["ticker_list"] = info["ticker_list"]
        if info.get("state"):
            o["state"] = info["state"]
        return code, wrapper_trace(info, o)
    state = (coin or {}).get("identity")
    o = {"state": state, "discovery": True, "execution_identity": False}
    if state is None:
        o["why"] = "the coin record carries no identity (built outside v8.identity): no execution authority"
    elif state != ID.UNVERIFIED:
        return "AUDIT_UNCLASSIFIED", {"why": f"coin not tradfi and not execution-eligible, identity {state}"}
    elif info is not None and info.get("state") == ID.UNVERIFIED:
        o.update(name=(coin or {}).get("name"), exposures=exposure_summary(info), evidence=info.get("evidence") or None,
                 links=info.get("links"), promotion=info.get("promotion"))
        wrapper_trace(info, o)
    return "IDENTITY_UNVERIFIED", o


def excluded_health(code):
    """Data health of an identity exclusion: conflicting evidence, missing evidence, or a settled classification."""
    return {"AMBIGUOUS_EXPOSURE": T.CONFLICTED, "IDENTITY_UNVERIFIED": T.MISSING}.get(code, T.HEALTHY)


def note_identity_steps(L, tickers, trace=TRACE):
    """Adds the identity steps to the final record of every admitted coin (call after the engine loop):
    CRYPTO_EXPOSURE_SELECTED when its ticker also names an excluded tradfi or ambiguous exposure, and (v8 Phase 3)
    UNVERIFIED_EXPOSURE_KEPT_OUT when it also has a price-separated exposure without identity evidence."""
    for t in tickers:
        info = identity_of(t, trace)
        if info and info["decision"] == ID.D_SELECTED:
            L.note(t, "CRYPTO_EXPOSURE_SELECTED")
        if info and info.get("state") == ID.VERIFIED_CRYPTO and info.get("excluded_unverified"):
            L.note(t, "UNVERIFIED_EXPOSURE_KEPT_OUT")


def liquidity_final(L, t, coin, stage, min_vol, trade_dexes, k=None):
    """The final record of a coin the execution-liquidity gate (v8.liquidity.passes) leaves out."""
    e = LQ.evaluate(coin, trade_dexes)
    if e["state"] == LQ.KNOWN:
        return L.final(t, "DEX_VOLUME_BELOW_LEGACY_MIN", stage, o={"trade_vol": e["value"], "basis": e["basis"]},
                       th={"min": min_vol}, k=k)
    if e["state"] == LQ.NOT_ON_TRADE_DEX:
        return L.final(t, "NOT_ON_TRADE_DEX", stage, o={"venues": e["venues"]}, th={"min": min_vol}, k=k)
    return L.final(t, "DEX_VOLUME_MISSING", stage, o={"trade_vol": None, "basis": "MISSING", "venues": e["venues"]},
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
