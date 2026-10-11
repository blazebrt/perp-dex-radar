"""Full-universe discovery (v8 Phase 7): every active perp of every healthy venue is visible to discovery.

    Discovery sees everything. Execution remains selective.

One record per canonical asset, at three levels:

    Level 0  registry        every contract the eight market lists returned (v8.registry, unchanged)
    Level 1  light discovery every asset with an active perpetual on a venue whose market list loaded: identity,
                             exposures, contracts, venues, price and its cross-venue dispersion, volume, execution
                             liquidity, open interest, funding, first seen, listing age, research flags. Built only from
                             the market lists the scan already fetched and the ledgers the engines already wrote: zero
                             extra network requests
    Level 2  deep research   the legacy radar's bounded stage 2 (the stage-1 top 40 that pass execution liquidity, plus
                             16 extras), unchanged; every asset outside it says why it was not deep-researched

Visibility is never gated. Identity, liquidity, history and the output Top-N decide what an engine may do with an asset,
never whether discovery sees it. Execution liquidity is its own field {state, observed_value, threshold, passes}; a
missing value stays null (never 0).

Research flags, research priority points, priority lanes and the shadow deep-research queue are observational. They
order what a person might look at next; they are not signals, not scores of expected return, and have no trade
authority. No engine reads this module, and nothing here changes a strategy, threshold, gate, ranking or published file.

scan_part() runs inside the scanner process, at the end of scanner.run() (through v8.audit_radar.audit): it keeps the coin
records and the radar's stage-1 / stage-2 membership, which the snapshot cannot rebuild. build() runs at snapshot time
and joins that part with the registry, the first-seen history and every engine's ledger into data/v8/discovery.json
(schema v8.discovery/1) and the audit snapshot's `discovery` section."""
from __future__ import annotations

import os

from . import identity as ID
from . import liquidity as LQ
from . import taxonomy as T

VERSION = "v8.discovery/1"
FILE = os.path.join("data", "v8", "discovery.json")
ENGINES = ("radar", "quant", "swing", "day", "smart")

# ---- discovery stages: how far down the hierarchical scan an asset went this scan (the furthest one is its stage)
DISCOVERED, LIGHT_ONLY, CHARTED_1H = "DISCOVERED", "LIGHT_ONLY", "CHARTED_1H"
DEEP_RESEARCH, STRATEGY_EVALUATED, EXECUTION_BLOCKED = "DEEP_RESEARCH", "STRATEGY_EVALUATED", "EXECUTION_BLOCKED"
SURFACED, WATCHED = "SURFACED", "WATCHED"
STAGES = {
    DISCOVERED: "in discovery from the registry, without a coin record to build market structure from (the fallback "
                "universe, or every venue's price dropped as a conflict)",
    LIGHT_ONLY: "light discovery record only (identity, venues, price, volume, liquidity, open interest, funding, "
                "flags): not charted by the radar",
    CHARTED_1H: "charted on 1h candles by the radar's stage 1; not deep-researched",
    DEEP_RESEARCH: "selected for the radar's 15m deep dive, which could not run (not enough 15m history)",
    STRATEGY_EVALUATED: "deep-researched: every active 15m strategy was evaluated; nothing published",
    EXECUTION_BLOCKED: "a strategy fired and a publishing gate (strategy test, adjustment, market gate, forward test) "
                       "blocked it",
    SURFACED: "published as a radar pick",
    WATCHED: "published on the radar watch list",
}
STAGE_ORDER = (DISCOVERED, LIGHT_ONLY, CHARTED_1H, DEEP_RESEARCH, STRATEGY_EVALUATED, EXECUTION_BLOCKED, SURFACED,
               WATCHED)

# ---- venue states (the denominator: active perpetuals of every venue whose market list loaded)
VENUE_OK, VENUE_UNAVAILABLE = "OK", "VENUE_UNAVAILABLE"
NO_MARKETS, ZERO_ACTIVE_MARKETS = "NO_MARKETS", "ZERO_ACTIVE_MARKETS"
VENUE_STATES = {
    VENUE_OK: "the market list loaded and has active perpetuals: every one is in discovery",
    VENUE_UNAVAILABLE: "the market list did not load this scan (DATA_DEGRADED, VENUE_MARKET_LIST_UNAVAILABLE): none of "
                       "its markets can be in discovery; they are not counted in the denominator",
    NO_MARKETS: "the market list loaded and returned no market at all",
    ZERO_ACTIVE_MARKETS: "the market list loaded; none of its markets is an active perpetual (delisted, inactive, "
                         "dated, options)",
}
DATA_DEGRADED, HEALTHY = "DATA_DEGRADED", "HEALTHY"
VENUE_MARKET_LIST_UNAVAILABLE = "VENUE_MARKET_LIST_UNAVAILABLE"
REGISTRY_PAYLOAD_UNREADABLE = "REGISTRY_PAYLOAD_UNREADABLE"
# active perpetuals the legacy adapters skip as unusable or unsupported (contract states of v8.registry): counted, by
# reason, outside the denominator
UNSUPPORTED_STATES = ("EMPTY_SYMBOL", "HL_BUILDER_MARKET", "DELISTED", "NOT_PERPETUAL", "NOT_TRADING")
# registry assets outside discovery (no active perpetual on a healthy venue)
REGISTRY_ONLY = {
    "NO_ACTIVE_PERP_CONTRACT": "every contract of the asset is delisted, inactive, a builder market or not a perpetual",
    "VENUE_ADAPTER_FAILED": "listed only on venues whose market list failed this scan (DATA_DEGRADED)",
}

# ---- research flags: observational, zero trade authority. points order the shadow queue and the lanes' lists only
THRESHOLDS = {"new_listing_days": 7, "funding_extreme_8h": 0.001, "funding_disagreement_8h": 0.0005,
              "price_dispersion": 0.02, "oi_to_volume": 2.0, "stage1_extreme_r24": 0.15}
FLAGS = {
    "NEW_LISTING": (3, "first seen after tracking started, within the last 7 days (from the first-seen history only: a "
                       "market older than the history is never called new)"),
    "FUNDING_EXTREME": (2, "median funding of its venues at least 0.1% per 8h, either sign (as each venue reports it, "
                           "8h-equivalent)"),
    "FUNDING_DISAGREEMENT": (1, "its venues' funding rates are at least 0.05% per 8h apart (venues settle on different "
                                "intervals; observed as reported)"),
    "PRICE_DISPERSION": (2, "the markets of its admitted exposure are at least 2% apart in price per coin"),
    "SINGLE_VENUE": (0, "one venue lists it"),
    "MULTI_VENUE": (1, "two or more venues list it"),
    "OI_HIGH_RELATIVE_TO_VOLUME": (1, "open interest at least 2x its 24h volume across its venues"),
    "THIN_LIQUIDITY": (0, "execution liquidity is known and below the $1M legacy minimum"),
    "LIQUIDITY_MISSING": (0, "listed on your trade DEXs, none reported a 24h volume"),
    "IDENTITY_UNVERIFIED": (1, "no verified identity (UNVERIFIED or AMBIGUOUS): discovery yes, crypto execution no"),
    "ECONOMIC_EXPOSURE_CONFLICT": (2, "its contracts' economic evidence disagrees (a ticker collision or conflicting "
                                      "contract evidence)"),
    "EXPOSURE_METADATA_DEGRADED": (1, "an economic-exposure check of one of its markets did not run cleanly"),
    "STAGE1_EXTREME": (2, "charted at stage 1 with a 24h move of at least 15%, either direction"),
}
STRUCTURAL = ("FUNDING_EXTREME", "FUNDING_DISAGREEMENT", "PRICE_DISPERSION", "OI_HIGH_RELATIVE_TO_VOLUME",
              "STAGE1_EXTREME")
CORE, EMERGING, STRUCTURAL_ANOMALY = "CORE", "EMERGING", "STRUCTURAL_ANOMALY"
IDENTITY_RESEARCH, NON_CRYPTO = "IDENTITY_RESEARCH", "NON_CRYPTO"
LANES = {
    CORE: "verified crypto that passes execution liquidity, no structural flag",
    EMERGING: "verified crypto that is new or below execution liquidity (thin, missing, not on a trade DEX)",
    STRUCTURAL_ANOMALY: "verified crypto that passes execution liquidity and carries a structural flag (funding, price "
                        "dispersion, open interest, stage-1 move)",
    IDENTITY_RESEARCH: "no verified identity (UNVERIFIED, AMBIGUOUS): the identity is what needs research",
    NON_CRYPTO: "verified tradfi (stocks, indices, FX, commodities): visible, outside the crypto engines",
}
AUTHORITY = "NONE"      # what a flag, a lane, a priority or the shadow queue may decide

# ---- why an asset was or was not deep-researched (Level 2)
DEEP_COMPLETED = "DEEP_COMPLETED"
DEEP_HISTORY_INSUFFICIENT = "DEEP_HISTORY_INSUFFICIENT"
DEEP_BUDGET_NOT_SELECTED = "DEEP_BUDGET_NOT_SELECTED"
EXECUTION_LIQUIDITY_BELOW_MIN = "EXECUTION_LIQUIDITY_BELOW_MIN"
EXECUTION_LIQUIDITY_UNKNOWN = "EXECUTION_LIQUIDITY_UNKNOWN"
NOT_ON_TRADE_DEX = "NOT_ON_TRADE_DEX"
INSUFFICIENT_1H_DATA = "INSUFFICIENT_1H_DATA"
IDENTITY_NOT_CRYPTO = "IDENTITY_NOT_CRYPTO"
NO_COIN_RECORD = "NO_COIN_RECORD"
DEEP_REASONS = {
    DEEP_COMPLETED: "deep-researched (15m deep dive ran; every active strategy evaluated)",
    DEEP_HISTORY_INSUFFICIENT: "selected for the deep dive; its 15m history was too short or missing",
    DEEP_BUDGET_NOT_SELECTED: "passes execution liquidity, charted, outside the stage-1 top 40 and not an extra",
    EXECUTION_LIQUIDITY_BELOW_MIN: "charted; 24h volume on your trade DEXs known and below the $1M legacy minimum",
    EXECUTION_LIQUIDITY_UNKNOWN: "charted; listed on your trade DEXs, none reported a 24h volume",
    NOT_ON_TRADE_DEX: "charted; not listed on any of your trade DEXs",
    INSUFFICIENT_1H_DATA: "verified crypto without enough 1h candles for stage 1",
    IDENTITY_NOT_CRYPTO: "no crypto execution identity (tradfi, ambiguous, unverified): the radar charts verified "
                         "crypto only",
    NO_COIN_RECORD: "no coin record (every venue's price dropped as a conflict): nothing to chart",
}
_LIQ_REASON = {"DEX_VOLUME_BELOW_LEGACY_MIN": EXECUTION_LIQUIDITY_BELOW_MIN,
               "DEX_VOLUME_MISSING": EXECUTION_LIQUIDITY_UNKNOWN, "NOT_ON_TRADE_DEX": NOT_ON_TRADE_DEX}
_BLOCK_CODES = ("ADJUSTMENT_BLOCKED", "STRATEGY_NOT_PASSED", "MARKET_GATE_BLOCKED", "VARIANT_FORWARD_TEST")


def _r(x, nd=6):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return float(f"{f:.{nd}g}")


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


# --------------------------------------------------------------------------- scan side (inside scanner.run)
def scan_part(scan_t, coins, dex_status, dex_ok, crypto, res1, s1, ranked, cands, extras, res2, A):
    """What only the scanner process knows: every coin record's reference price, volumes and execution liquidity, and
    the radar's stage-1 / stage-2 membership. Reads the run's own values; decides nothing; no request."""
    import scanner as sc
    td = sc.CFG["trade_dexes"]
    extra, deep = set(extras), set(cands)
    rank = {t: i + 1 for i, t in enumerate(ranked)}
    out = {}
    for t, c in sorted((coins or {}).items()):
        e = LQ.evaluate(c, td)
        rec = {"identity": c.get("identity"), "tradfi": bool(c.get("tradfi")), "name": c.get("name"),
               "ref_price": _r(c.get("ref_price"), 8), "best_vol": LQ.stored(c.get("best_vol")),
               "tot_vol": LQ.stored(c.get("tot_vol")), "trade_vol": LQ.stored(c.get("trade_vol")),
               "venues": sorted((c.get("venues") or {})),
               "liquidity": {"state": e["state"], "value": LQ.stored(e["value"]), "basis": e["basis"]},
               "crypto": t in crypto}
        if t in crypto:
            h = {"requested": True, "returned": (res1 or {}).get(t) is not None, "charted": t in s1}
            if t in s1:
                m = s1[t]
                h.update(src=m.get("src"), score=_r(m.get("score"), 5), r24=_r(m.get("r24"), 5),
                         r3=_r(m.get("r3"), 5), trend=_r(m.get("trend"), 5), rank=rank.get(t))
            rec["h1"] = h
        if t in deep:
            rec["deep"] = {"selected": True, "via": "EXTRA" if t in extra else "TOP_N", "completed": t in (A or {})}
        out[t] = rec
    return {"coins": out, "dex_ok": bool(dex_ok),
            "dex_status": {d: {"ok": bool((s or {}).get("ok")), "markets": (s or {}).get("markets")}
                           for d, s in sorted((dex_status or {}).items())},
            "config": {"stage2_n": sc.CFG["stage2_n"], "stage2_extra": sc.CFG["stage2_extra"],
                       "min_dex_vol": sc.CFG["min_dex_vol"], "trade_dexes": list(td)},
            "stages": {"universe": len(coins or {}), "crypto": len(crypto or {}), "h1_requested": len(crypto or {}),
                       "h1_returned": sum(1 for t in (crypto or {}) if (res1 or {}).get(t) is not None),
                       "charted_1h": len(s1 or {}), "deep_selected": len(deep), "deep_top_n": len(deep - extra),
                       "deep_extras": len(extra), "deep_completed": len(A or {})},
            # the radar's own candle requests this scan; discovery adds none
            "requests": {"stage1_1h": len(crypto or {}), "stage2_15m": len(deep), "discovery_extra": 0}}


# --------------------------------------------------------------------------- snapshot side
def supported(c):
    """An active perpetual a supported market adapter reads (not skipped as unusable: an empty symbol, a Hyperliquid
    builder-deployed market). Skipped ones are counted apart, by reason, never silently dropped."""
    return c.get("type") == "perp" and bool(c.get("active")) and c.get("legacy") not in UNSUPPORTED_STATES \
        and c.get("legacy") != "ADAPTER_FAILED"


def venue_table(reg):
    """Every venue's state this scan, and its active perpetuals (the denominator counts OK venues only)."""
    out = {}
    cs = reg.get("contracts") or []
    for v, vi in sorted((reg.get("venues") or {}).items()):
        act = [c for c in cs if c["venue"] == v and supported(c)]
        if not vi.get("ok"):
            st, h, why = VENUE_UNAVAILABLE, DATA_DEGRADED, VENUE_MARKET_LIST_UNAVAILABLE
        elif vi.get("error"):
            st, h, why = VENUE_UNAVAILABLE, DATA_DEGRADED, REGISTRY_PAYLOAD_UNREADABLE
        elif not vi.get("raw"):
            st, h, why = NO_MARKETS, HEALTHY, None
        elif not act:
            st, h, why = ZERO_ACTIVE_MARKETS, HEALTHY, None
        else:
            st, h, why = VENUE_OK, HEALTHY, None
        uns = [c for c in cs if c["venue"] == v and c.get("type") == "perp" and c.get("active")
               and c.get("legacy") in UNSUPPORTED_STATES]
        out[v] = {"state": st, "health": h, "reason": why, "raw_markets": vi.get("raw", 0),
                  "active_perps": len(act) if st == VENUE_OK else 0,
                  "active_perps_unsupported": _count(c.get("legacy") for c in uns),
                  "active_perps_not_in_denominator": len(act) if st != VENUE_OK else 0,
                  "assets": len({c["asset"] for c in act}) if st == VENUE_OK else 0}
    return out


def _flags(rec, coin, liq, min_vol, charted_r24):
    fl = []
    th = THRESHOLDS
    if (rec["listing_age"] or {}).get("state") == "KNOWN" and rec["listing_age"]["days"] <= th["new_listing_days"]:
        fl.append("NEW_LISTING")
    f = rec["funding"]
    if f["median_8h"] is not None and abs(f["median_8h"]) >= th["funding_extreme_8h"]:
        fl.append("FUNDING_EXTREME")
    if f["spread_8h"] is not None and f["venues_reporting"] >= 2 and f["spread_8h"] >= th["funding_disagreement_8h"]:
        fl.append("FUNDING_DISAGREEMENT")
    d = rec["cross_venue_price_dispersion"]
    if d is not None and d >= th["price_dispersion"]:
        fl.append("PRICE_DISPERSION")
    if len(rec["record_venues"]) == 1:
        fl.append("SINGLE_VENUE")
    elif len(rec["record_venues"]) >= 2:
        fl.append("MULTI_VENUE")
    oi, vol = rec["open_interest"]["value"], rec["total_volume"]
    if oi is not None and vol and oi / vol >= th["oi_to_volume"]:
        fl.append("OI_HIGH_RELATIVE_TO_VOLUME")
    if liq["state"] == LQ.KNOWN and liq["observed_value"] is not None and liq["observed_value"] < min_vol:
        fl.append("THIN_LIQUIDITY")
    if liq["state"] == LQ.MISSING:
        fl.append("LIQUIDITY_MISSING")
    if rec["identity"] in (ID.UNVERIFIED, ID.AMBIGUOUS) or rec["identity"] is None:
        fl.append("IDENTITY_UNVERIFIED")
    if rec["_conflict"]:
        fl.append("ECONOMIC_EXPOSURE_CONFLICT")
    if rec["exposure_check_state"] == "DEGRADED":
        fl.append("EXPOSURE_METADATA_DEGRADED")
    if charted_r24 is not None and abs(charted_r24) >= th["stage1_extreme_r24"]:
        fl.append("STAGE1_EXTREME")
    return [x for x in FLAGS if x in fl]


def _lane(identity, eligible, liq_passes, flags):
    if identity == ID.VERIFIED_TRADFI:
        return NON_CRYPTO
    if not eligible:
        return IDENTITY_RESEARCH
    if "NEW_LISTING" in flags or not liq_passes:
        return EMERGING
    if any(f in flags for f in STRUCTURAL):
        return STRUCTURAL_ANOMALY
    return CORE


def _stage(rr, ur):
    """(discovery stage, path) from the asset's radar or universe ledger record."""
    if rr is None:
        return DISCOVERED, [DISCOVERED]
    st, code = rr["st"], rr["c"]
    if st in ("universe", "stage1"):
        return LIGHT_ONLY, [DISCOVERED, LIGHT_ONLY]
    if st == "stage2":
        return CHARTED_1H, [DISCOVERED, CHARTED_1H]
    if st == "deep_dive":
        return DEEP_RESEARCH, [DISCOVERED, CHARTED_1H, DEEP_RESEARCH]
    base = [DISCOVERED, CHARTED_1H, DEEP_RESEARCH, STRATEGY_EVALUATED]
    if st == "block" or code in _BLOCK_CODES:
        return EXECUTION_BLOCKED, base + [EXECUTION_BLOCKED]
    if code == "RADAR_PICK":
        return SURFACED, base + [SURFACED]
    if code == "RADAR_WATCH":
        return WATCHED, base + [WATCHED]
    return STRATEGY_EVALUATED, base


def _deep(rr, coin, eligible, liq):
    """deep_research_state from the radar ledger (the authority on what happened) and the scan part (how)."""
    d = (coin or {}).get("deep") or {}
    h1 = (coin or {}).get("h1") or {}
    via = d.get("via") or ("EXTRA" if rr is not None and "EXTRA_DEEP_DIVE" in (rr.get("x") or []) else None)
    out = {"selected": False, "via": None, "completed": False, "reason": None, "stage1_rank": h1.get("rank"),
           "stage1_score": h1.get("score")}
    if rr is None:
        out["reason"] = NO_COIN_RECORD
        return out
    st, code = rr["st"], rr["c"]
    if st == "universe":
        out["reason"] = IDENTITY_NOT_CRYPTO
    elif st == "stage1":
        out["reason"] = INSUFFICIENT_1H_DATA
        out["detail"] = code
    elif st == "stage2":
        if code == "RADAR_STAGE2_NOT_SELECTED":
            out["reason"] = DEEP_BUDGET_NOT_SELECTED
            out["liquid_rank"] = (rr.get("o") or {}).get("liquid_rank")
        else:
            out["reason"] = _LIQ_REASON.get(code, code)
            out["detail"] = code
    elif st == "deep_dive":
        out.update(selected=True, via=via or "TOP_N", reason=DEEP_HISTORY_INSUFFICIENT, detail=code)
    else:
        out.update(selected=True, via=via or "TOP_N", completed=True, reason=DEEP_COMPLETED)
    return out


TRACE_RULES = {     # the rule of each Decision Trace step (each record names it; the text is here once)
    "Discovery": "every active perpetual of every venue whose market list loaded enters discovery",
    "Data quality": "values kept as observed; a missing value stays null, never 0",
    "Identity": f"{ID.VERSION}, unchanged: only VERIFIED_CRYPTO has crypto execution identity",
    "Light market structure": "read from the market lists this scan already fetched; no extra request",
    "Research-priority flags": "observational flags (provenance.thresholds); points order research attention only",
    "Chart coverage": "the radar charts VERIFIED_CRYPTO on 1h candles (stage 1, unchanged)",
    "Deep-selection result": "stage 2: top 40 passing execution liquidity by stage-1 score, plus 16 extras (unchanged)",
    "Execution gate": "a new entry needs crypto execution identity and a known 24h trade-DEX volume >= the legacy "
                      "minimum (unchanged)",
    "Final discovery disposition": "the radar's (or universe's) final ledger record, existing vocabulary",
}


def _trace(rec, n_contracts, venues_down):
    """The asset's Decision Trace: [step, input, rule, result, effect] per step (rule texts in TRACE_RULES)."""
    liq, ex, dp = rec["execution_liquidity"], rec["execution_state"], rec["deep_research_state"]
    lq = f"{liq['state']} {liq['observed_value']}" if liq["observed_value"] is not None else liq["state"]
    charted = rec["discovery_stage"] not in (DISCOVERED, LIGHT_ONLY)
    fin = rec["final_disposition"] or {}
    h = " ".join(f"{k} {v}" for k, v in rec["_health"].items()) if isinstance(rec["_health"], dict) else rec["_health"]
    steps = [
        ["Discovery", f"{n_contracts} active perp(s): {' '.join(rec['venues']) or 'no venue'}", DISCOVERED,
         "visible whatever its identity, liquidity or history"],
        ["Data quality", f"contracts {h}; venues down: {' '.join(venues_down) or 'none'}", rec["data_quality"],
         "none on visibility"],
        ["Identity", f"{rec['identity']} / {rec['identity_reason']} / {rec['identity_authority']}",
         rec["identity"] or "NO_IDENTITY", "execution identity " + ("yes" if ex["identity_ok"] else "no")],
        ["Light market structure", f"px {rec['price']} {rec['price_basis']}; vol {rec['best_volume']}; "
                                   f"oi {rec['open_interest']['value']}; fund8h {rec['funding']['median_8h']}",
         lq, "light record"],
        ["Research-priority flags", " ".join(rec["anomaly_flags"]) or "none",
         f"{rec['research_priority']['points']} pt, {rec['priority_lane']}", "no trade authority"],
        ["Chart coverage", "verified crypto" if rec["identity"] == ID.VERIFIED_CRYPTO else "not verified crypto",
         CHARTED_1H if charted else "NOT_CHARTED", "1h metrics" if charted else "light record only"],
        ["Deep-selection result", f"rank {dp.get('stage1_rank')}; liquidity {liq['state']}", dp["reason"],
         (f"deep-researched ({dp['via']})" if dp["selected"] else "not deep-researched")],
        ["Execution gate", f"{rec['identity']}; {lq} vs {liq['threshold']}", ex["state"],
         "new entry allowed" if ex["new_entry_executable"] else "no new entry: " + " ".join(ex["reasons"])],
        ["Final discovery disposition", f"{fin.get('engine')} {fin.get('code')}", fin.get("disposition") or "NONE",
         f"stage {rec['discovery_stage']}"],
    ]
    return [[s[0], s[1], s[0], s[2], s[3]] for s in steps]      # rule: the step's entry in TRACE_RULES


def build(reg, scan, dispositions, header, tracking, ts):
    """(document, summary): data/v8/discovery.json and the audit snapshot's discovery section.

    reg: the scan's registry (contracts with first_seen); scan: the scanner's discovery part (None when missing);
    dispositions: engine -> ledger records; header: the scan's provenance header; tracking: {"since", "source"} of the
    first-seen history; ts: the scan time. Deterministic for the same inputs."""
    reg = reg or {}
    scan = scan or {}
    coins = scan.get("coins") or {}
    cfg = scan.get("config") or {}
    min_vol = cfg.get("min_dex_vol", 1_000_000)
    dex_ok = scan.get("dex_ok", not reg.get("fallback"))
    fallback = bool(reg.get("fallback")) or not dex_ok
    contracts = reg.get("contracts") or []
    assets = reg.get("assets") or {}
    venues = venue_table(reg)
    down = sorted(v for v, x in venues.items() if x["state"] == VENUE_UNAVAILABLE)
    ok_venues = {v for v, x in venues.items() if x["state"] == VENUE_OK}
    denom = [c for c in contracts if c["venue"] in ok_venues and supported(c)]
    by_asset = {}
    for c in denom:
        by_asset.setdefault(c["asset"], []).append(c)
    recs = {e: {r["a"]: r for r in (dispositions or {}).get(e) or []} for e in ("universe",) + ENGINES}
    since = (tracking or {}).get("since")
    names = sorted(set(by_asset) | set(coins))
    records, problems = [], []
    for t in names:
        a = assets.get(t) or {}
        ib = a.get("identity") or {}
        coin = coins.get(t)
        cs = by_asset.get(t, [])
        sel = [c for c in cs if c.get("legacy") == "SELECTED"] or cs
        identity = (coin or {}).get("identity") if coin else ib.get("state")
        identity = identity or ib.get("state")
        tradfi = bool((coin or {}).get("tradfi")) if coin else identity == ID.VERIFIED_TRADFI
        eligible = identity == ID.VERIFIED_CRYPTO and not tradfi
        # price: the coin record's reference (anchored on its most traded venue), else the contracts' median
        npx = [(c.get("npx") if c.get("npx") is not None else (c["price"] / (c.get("mult") or 1.0)))
               for c in sel if c.get("price")]
        if coin and coin.get("ref_price") is not None:
            price, pbasis = coin["ref_price"], "COIN_REFERENCE"
        elif npx:
            price, pbasis = _r(_median(npx), 8), "CONTRACT_MEDIAN"
        else:
            price, pbasis = None, "MISSING"
        disp = _r((max(npx) - min(npx)) / _median(npx), 5) if len(npx) >= 2 and _median(npx) else None
        vols = [c["vol"] for c in sel if c.get("vol") is not None]
        oi = [c["oi"] for c in sel if c.get("oi") is not None]
        fd = [c["fund8h"] for c in sel if c.get("fund8h") is not None]
        first = min((c["first_seen"] for c in cs if c.get("first_seen") is not None), default=None)
        if first is None:
            age = {"state": "UNKNOWN", "days": None, "basis": "NO_HISTORY"}
        elif since is None or first <= since:
            age = {"state": "UNKNOWN", "days": None, "basis": "BEFORE_TRACKING_START",
                   "at_least_days": _r((ts - since) / 86400, 4) if since is not None and ts else None}
        else:
            age = {"state": "KNOWN", "days": _r((ts - first) / 86400, 4), "basis": "FIRST_SEEN_AFTER_TRACKING_START"}
        if coin:
            lq = coin.get("liquidity") or {}
            lstate, lval = lq.get("state"), lq.get("value")
        else:
            lstate, lval = NO_COIN_RECORD, None
        passes = lstate == LQ.KNOWN and lval is not None and lval >= min_vol
        checks = ib.get("exposure_checks") or []
        xstate = "NOT_APPLICABLE" if not checks else "OK" if all(x[2] == ID.XCHECK_OK for x in checks) else "DEGRADED"
        exps = ib.get("exposures") or []
        conflict = bool(a.get("collision")) or any(x.get("reason") == "CONFLICTING_CONTRACT_EVIDENCE" for x in exps)
        health = {}
        for c in cs:
            health[c.get("health")] = health.get(c.get("health"), 0) + 1
        rr, ur = recs["radar"].get(t), recs["universe"].get(t)
        stage, path = _stage(rr, ur)
        fin = rr or ur
        rec = {
            "asset": t, "name": (coin or {}).get("name"),
            "identity": identity, "identity_reason": ib.get("reason"), "identity_authority": ib.get("authority"),
            "identity_decision": ib.get("decision"),
            "exposures": [{"id": x.get("id"), "class": x.get("class"), "reason": x.get("reason"),
                           "anchor_price": x.get("anchor_price"), "contracts": len(x.get("members") or []),
                           "in_record": bool(x.get("admitted") or x.get("attached") or x.get("recorded"))}
                          for x in exps],
            "contracts": [[c["id"], c.get("legacy")] for c in cs],
            "venues": sorted({c["venue"] for c in cs}),
            "record_venues": sorted({c["venue"] for c in sel}) if cs else list((coin or {}).get("venues") or []),
            "price": price, "price_basis": pbasis, "cross_venue_price_dispersion": disp,
            "best_volume": (coin or {}).get("best_vol") if coin else (LQ.stored(max(vols)) if vols else None),
            "trade_volume": (coin or {}).get("trade_vol") if coin else None,
            "total_volume": (coin or {}).get("tot_vol") if coin else (LQ.stored(sum(vols)) if vols else None),
            "liquidity_state": lstate, "liquidity_value": lval,
            "execution_liquidity": {"state": lstate, "observed_value": lval, "threshold": min_vol, "passes": passes,
                                    **({"legacy_gate": "BYPASSED_FALLBACK_UNIVERSE"} if fallback else {})},
            "open_interest": {"value": LQ.stored(sum(oi)) if oi else None, "venues_reporting": len(oi),
                              "venues": len(sel), "basis": ("MISSING" if not oi else "OBSERVED_SUM" if len(oi) == len(sel)
                                                            else "PARTIAL_SUM")},
            "funding": {"median_8h": _r(_median(fd), 6), "min_8h": _r(min(fd), 6) if fd else None,
                        "max_8h": _r(max(fd), 6) if fd else None,
                        "spread_8h": _r(max(fd) - min(fd), 6) if len(fd) >= 2 else None, "venues_reporting": len(fd),
                        "basis": "VENUE_REPORTED_8H_EQUIVALENT" if fd else "MISSING"},
            "first_seen": first, "listing_age": age,
            "wrapper_evidence": ib.get("wrapper_evidence") or [], "economic_evidence": ib.get("evidence") or [],
            "exposure_check_state": xstate,
            "data_quality": DATA_DEGRADED if (any(h != T.HEALTHY for h in health) or not cs) else HEALTHY,
            "_health": dict(sorted(health.items())) or "no contract", "_conflict": conflict,
        }
        r24 = ((coin or {}).get("h1") or {}).get("r24")
        rec["anomaly_flags"] = _flags(rec, coin, rec["execution_liquidity"], min_vol, r24)
        rec["research_priority"] = {"points": sum(FLAGS[f][0] for f in rec["anomaly_flags"]), "authority": AUTHORITY}
        rec["priority_lane"] = _lane(identity, eligible, passes, rec["anomaly_flags"])
        rec["discovery_stage"], rec["stage_path"] = stage, path
        rec["deep_research_state"] = _deep(rr, coin, eligible, rec["execution_liquidity"])
        reasons = [] if eligible else [IDENTITY_NOT_CRYPTO]
        if not passes:
            reasons.append({LQ.KNOWN: EXECUTION_LIQUIDITY_BELOW_MIN, LQ.MISSING: EXECUTION_LIQUIDITY_UNKNOWN,
                            LQ.NOT_ON_TRADE_DEX: NOT_ON_TRADE_DEX}.get(lstate, NO_COIN_RECORD))
        # the scan part and the radar ledger must tell the same story
        dsel, h1c = ((coin or {}).get("deep") or {}), ((coin or {}).get("h1") or {})
        if coin is not None and bool(dsel.get("selected")) != rec["deep_research_state"]["selected"]:
            problems.append(f"{t}: deep selection in the scan part and the radar ledger disagree")
        if coin is not None and bool(h1c.get("charted")) != (stage not in (DISCOVERED, LIGHT_ONLY)):
            problems.append(f"{t}: 1h charting in the scan part and the radar ledger disagree")
        eng = {e: [recs[e][t]["d"], recs[e][t]["c"]] for e in ENGINES if t in recs[e]}
        rec["execution_state"] = {"state": "GATES_PASSED" if eligible and passes else "GATES_BLOCKED",
                                  "identity_ok": eligible, "liquidity_ok": passes,
                                  "new_entry_executable": bool(eligible and passes), "reasons": reasons,
                                  "engines": eng, "surfaced_by": sorted(e for e, v in eng.items() if v[0] == T.SURFACED)}
        rec["final_disposition"] = ({"engine": "radar" if rr is not None else "universe", "code": fin["c"],
                                     "disposition": fin["d"], "stage": fin["st"]} if fin is not None else None)
        if fin is None:
            problems.append(f"{t}: no radar or universe ledger record")
        rec["decision_trace"] = _trace(rec, len(cs), down)
        del rec["_health"], rec["_conflict"]
        records.append(rec)
    disc = {r["asset"] for r in records}
    reg_only = []
    for t, a in sorted(assets.items()):
        if t not in disc:
            reg_only.append({"asset": t, "reason": a.get("legacy"), "contracts": len(a.get("contracts") or []),
                             "venues": a.get("venues") or []})
    doc = {"schema": VERSION, "provenance": _provenance(reg, header, ts, venues, records, fallback, tracking, denom,
                                                        reg_only, cfg),
           "venues": venues, "assets": records, "registry_only": reg_only,
           "vocabulary": {"stages": STAGES, "venue_states": VENUE_STATES, "flags": {k: v[1] for k, v in FLAGS.items()},
                          "flag_points": {k: v[0] for k, v in FLAGS.items()}, "lanes": LANES,
                          "deep_reasons": DEEP_REASONS, "registry_only": REGISTRY_ONLY,
                          "unsupported_contract_states": list(UNSUPPORTED_STATES), "trace_rules": TRACE_RULES,
                          "trace_format": ["step", "input", "rule (key of trace_rules)", "result", "effect"]}}
    doc["shadow_queue"], doc["legacy_vs_shadow"] = shadow(records, cfg, scan)
    doc["emerging"] = emerging(records)
    doc["accounting"] = accounting(reg, denom, records, reg_only, problems)
    doc["provenance"]["full_discovery_qualified"] = (not fallback) and doc["accounting"]["unaccounted"] == 0
    return doc, summary(doc, scan)


def _provenance(reg, header, ts, venues, records, fallback, tracking, denom, reg_only, cfg):
    rc_active = sum(1 for c in reg.get("contracts") or [] if c.get("type") == "perp" and c.get("active"))
    down = sorted(v for v, x in venues.items() if x["state"] == VENUE_UNAVAILABLE)
    return {"schema": VERSION, "scan_id": (header or {}).get("scan_id"), "git_sha": (header or {}).get("git_sha"),
            "generated_at": ts, "identity_version": ID.VERSION,
            "identity_config_hash": (header or {}).get("identity_config_hash"),
            "registry_contracts": len(reg.get("contracts") or []), "active_perps": rc_active,
            "active_perps_in_denominator": len(denom), "canonical_assets": len(reg.get("assets") or {}),
            "discovery_assets": len(records), "registry_only_assets": len(reg_only),
            "venues_expected": len(venues), "venues_ok": sum(1 for x in venues.values() if x["state"] == VENUE_OK),
            "venues_failed": len(down), "venues_failed_names": down,
            "venues_without_active_markets": sorted(v for v, x in venues.items()
                                                    if x["state"] in (NO_MARKETS, ZERO_ACTIVE_MARKETS)),
            "fallback_universe": bool(fallback), "full_discovery_qualified": None,
            "coverage_state": "FALLBACK" if fallback else "DEGRADED" if down else "FULL",
            "tracking_since": (tracking or {}).get("since"), "first_seen_source": (tracking or {}).get("source"),
            "thresholds": dict(THRESHOLDS, execution_liquidity_min=cfg.get("min_dex_vol", 1_000_000),
                               deep_slots=(cfg.get("stage2_n") or 0) + (cfg.get("stage2_extra") or 0)),
            "network_requests_added": 0, "authority": AUTHORITY,
            "rule": "Discovery sees everything. Execution remains selective."}


def shadow(records, cfg, scan):
    """The observational shadow deep-research queue: as many slots as the legacy stage 2 (40 + 16), filled from verified
    crypto by research-priority points, then known execution liquidity, then ticker - regardless of the liquidity
    gate. No request is made for it and nothing it holds can be published or traded."""
    slots = (cfg.get("stage2_n") or 40) + (cfg.get("stage2_extra") or 16)
    pool = [r for r in records if r["identity"] == ID.VERIFIED_CRYPTO and r["execution_state"]["identity_ok"]]
    pool.sort(key=lambda r: (-r["research_priority"]["points"], -(r["execution_liquidity"]["observed_value"] or 0.0),
                             r["asset"]))
    q = pool[:slots]
    legacy = sorted(r["asset"] for r in records if r["deep_research_state"]["selected"])
    sq = [r["asset"] for r in q]
    by = {r["asset"]: r for r in records}
    entries = [{"rank": i + 1, "asset": r["asset"], "points": r["research_priority"]["points"],
                "flags": r["anomaly_flags"], "lane": r["priority_lane"],
                "liquidity": [r["execution_liquidity"]["state"], r["execution_liquidity"]["observed_value"]],
                "charted_1h": r["discovery_stage"] not in (DISCOVERED, LIGHT_ONLY),
                "in_legacy_deep": r["deep_research_state"]["selected"]} for i, r in enumerate(q)]
    ov = sorted(set(sq) & set(legacy))
    lo = sorted(set(legacy) - set(sq))
    so = sorted(set(sq) - set(legacy))
    cmp_ = {"legacy_deep": len(legacy), "shadow": len(sq), "overlap": len(ov), "legacy_only": lo,
            "shadow_only": [{"asset": t, "flags": by[t]["anomaly_flags"], "lane": by[t]["priority_lane"],
                             "why_not_legacy_deep": by[t]["deep_research_state"]["reason"],
                             "liquidity": [by[t]["execution_liquidity"]["state"],
                                           by[t]["execution_liquidity"]["observed_value"]]} for t in so],
            "shadow_only_by_reason": _count(by[t]["deep_research_state"]["reason"] for t in so),
            "overlap_assets": ov,
            "resource": {"shadow_requests_made": 0, "legacy_stage2_15m_requests": len(legacy),
                         "shadow_15m_requests_if_it_ran": len(sq),
                         "budget_ratio": _r(len(sq) / len(legacy), 4) if legacy else None,
                         "within_budget": len(sq) <= max(len(legacy), slots)},
            "authority": AUTHORITY}
    return {"slots": slots, "ranking": "research-priority points desc, known execution liquidity desc, ticker",
            "pool": "VERIFIED_CRYPTO with crypto execution identity (liquidity not required)", "entries": entries,
            "authority": AUTHORITY, "trade_authority": False}, cmp_


def emerging(records):
    """Census of what the legacy funnel cannot see well: verified crypto below execution liquidity, on one venue or
    newly listed, outside stage 2; and the unverified ones. Census only: nothing is promoted."""
    def em(r):
        f = r["anomaly_flags"]
        return (not r["deep_research_state"]["selected"]) and (
            not r["execution_liquidity"]["passes"] or "SINGLE_VENUE" in f or "NEW_LISTING" in f)
    v = [r for r in records if r["identity"] == ID.VERIFIED_CRYPTO and em(r)]
    u = [r for r in records if r["identity"] in (ID.UNVERIFIED, ID.AMBIGUOUS) and em(r)]

    def census(rs):
        lq = [r["execution_liquidity"] for r in rs]
        return {"assets": len(rs),
                "below_min": sum(1 for x in lq if x["state"] == LQ.KNOWN and not x["passes"]),
                "liquidity_missing": sum(1 for x in lq if x["state"] == LQ.MISSING),
                "not_on_trade_dex": sum(1 for x in lq if x["state"] == LQ.NOT_ON_TRADE_DEX),
                "single_venue": sum(1 for r in rs if "SINGLE_VENUE" in r["anomaly_flags"]),
                "new_listing": sum(1 for r in rs if "NEW_LISTING" in r["anomaly_flags"]),
                "charted_1h": sum(1 for r in rs if r["discovery_stage"] not in (DISCOVERED, LIGHT_ONLY)),
                "liquidity_buckets": _count(_bucket(x["observed_value"], x["state"]) for x in lq),
                "flags": _count(f for r in rs for f in r["anomaly_flags"]),
                "top_by_points": [[r["asset"], r["research_priority"]["points"], r["anomaly_flags"]]
                                  for r in sorted(rs, key=lambda r: (-r["research_priority"]["points"], r["asset"]))[:25]]}
    return {"verified_crypto": census(v), "unverified": census(u), "trade_promotion": "NONE",
            "rule": "outside stage 2 and (below execution liquidity, or one venue, or newly listed)"}


def _bucket(v, state):
    if v is None:
        return state or "MISSING"
    return ">=5M" if v >= 5e6 else "1M-5M" if v >= 1e6 else "100k-1M" if v >= 1e5 else "<100k"


def _count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: str(kv[0])))


def accounting(reg, denom, records, reg_only, problems):
    """Every contract and asset in exactly one place; every discovery asset in exactly one stage, deep reason, lane."""
    disc = {r["asset"] for r in records}
    in_disc = sum(1 for c in denom if c["asset"] in disc)
    act = [c for c in reg.get("contracts") or [] if c.get("type") == "perp" and c.get("active")]
    dn = {id(c) for c in denom}
    unsup = [c for c in act if c.get("legacy") in UNSUPPORTED_STATES]
    off = [c for c in act if id(c) not in dn and c.get("legacy") not in UNSUPPORTED_STATES]
    n = len(records)
    stages = _count(r["discovery_stage"] for r in records)
    deep = _count(r["deep_research_state"]["reason"] for r in records)
    lanes = _count(r["priority_lane"] for r in records)
    fin = _count((r["final_disposition"] or {}).get("disposition") or "MISSING" for r in records)
    canon = len(reg.get("assets") or {})
    extra_coins = sorted(t for t in disc if t not in (reg.get("assets") or {}))
    un = {"contracts": len(denom) - in_disc,
          "active_perps": len(act) - len(denom) - len(unsup) - len(off),
          "assets": canon - (n - len(extra_coins)) - len(reg_only),
          "stages": n - sum(stages.values()), "deep_reasons": n - sum(deep.values()),
          "lanes": n - sum(lanes.values()), "final_disposition_missing": fin.get("MISSING", 0)}
    return {"registry_contracts": len(reg.get("contracts") or []),
            "active_perps": len(act), "active_perps_in_denominator": len(denom), "active_perps_in_discovery": in_disc,
            "active_perps_unsupported": _count(c.get("legacy") for c in unsup),
            "active_perps_on_unavailable_venues": _count(c["venue"] for c in off),
            "canonical_assets": canon, "discovery_assets": n, "registry_only_assets": len(reg_only),
            "registry_only_by_reason": _count(x["reason"] for x in reg_only),
            "discovery_assets_without_registry_entry": extra_coins,
            "by_stage": stages, "by_deep_reason": deep, "by_lane": lanes, "by_final_disposition": fin,
            "unaccounted_by_scope": un, "unaccounted": sum(un.values()), "problems": problems}


def summary(doc, scan):
    """The audit snapshot's discovery section (the full records stay in data/v8/discovery.json)."""
    rs = doc["assets"]
    pv = doc["provenance"]
    legacy_visible = sum(1 for r in rs if r["discovery_stage"] not in (DISCOVERED, LIGHT_ONLY))
    return {"schema": VERSION, "status": "OK",
            "coverage": {k: pv[k] for k in ("registry_contracts", "active_perps", "active_perps_in_denominator",
                                            "canonical_assets", "discovery_assets", "registry_only_assets",
                                            "fallback_universe", "full_discovery_qualified", "coverage_state",
                                            "venues_expected", "venues_ok", "venues_failed", "venues_failed_names",
                                            "tracking_since", "first_seen_source")},
            "venues": {v: [x["state"], x["active_perps"]] for v, x in doc["venues"].items()},
            "stages": doc["accounting"]["by_stage"],
            "identity_breakdown": _count(r["identity"] or "NONE" for r in rs),
            "liquidity_breakdown": _count(_bucket(r["execution_liquidity"]["observed_value"],
                                                  r["execution_liquidity"]["state"]) for r in rs),
            "execution_gates": _count(r["execution_state"]["state"] for r in rs),
            "priority_lanes": doc["accounting"]["by_lane"],
            "anomaly_flags": _count(f for r in rs for f in r["anomaly_flags"]),
            "deep_research": doc["accounting"]["by_deep_reason"],
            "visibility": {"radar_published_table": legacy_visible, "discovery_only": len(rs) - legacy_visible,
                           "discovery_only_by_identity": _count(r["identity"] or "NONE" for r in rs
                                                                if r["discovery_stage"] in (DISCOVERED, LIGHT_ONLY))},
            "emerging": {k: {kk: vv for kk, vv in v.items() if kk != "top_by_points"}
                         for k, v in doc["emerging"].items() if isinstance(v, dict)},
            "shadow_queue": {"slots": doc["shadow_queue"]["slots"], "filled": len(doc["shadow_queue"]["entries"]),
                             "authority": AUTHORITY},
            "legacy_vs_shadow": {k: (len(v) if isinstance(v, list) else v) for k, v in doc["legacy_vs_shadow"].items()},
            "scan_stages": (scan or {}).get("stages"), "requests": (scan or {}).get("requests"),
            "unaccounted": doc["accounting"]["unaccounted"],
            "unaccounted_by_scope": doc["accounting"]["unaccounted_by_scope"],
            "problems": doc["accounting"]["problems"][:20]}
