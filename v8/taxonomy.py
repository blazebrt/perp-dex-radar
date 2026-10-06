"""Dispositions, data-health states and stable reason codes.

A reason code names WHY an engine did not (or did) surface an asset. Codes are stable identifiers: they may be
added, never renamed or reused for another meaning. There is deliberately no generic FILTERED code; an audit that
cannot name the reason records AUDIT_UNCLASSIFIED, which the tests treat as a failure."""
from __future__ import annotations

SURFACED = "SURFACED"                    # published as an actionable item (a pick, a signal, a ready setup)
WATCHED = "WATCHED"                      # published for watching, not as an actionable call
REJECTED = "REJECTED"                    # evaluated by the engine and not surfaced (no setup, blocked, cut)
NOT_EXECUTABLE = "NOT_EXECUTABLE"        # not tradable enough on the DEXs the engine trades (liquidity, venue)
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # the engine could not evaluate it: candles, history or a value missing
MODEL_INELIGIBLE = "MODEL_INELIGIBLE"    # outside what the engine's model covers (tradfi, reference volume)
DISPOSITIONS = (SURFACED, WATCHED, REJECTED, NOT_EXECUTABLE, INSUFFICIENT_DATA, MODEL_INELIGIBLE)

HEALTHY, STALE, MISSING, CONFLICTED = "HEALTHY", "STALE", "MISSING", "CONFLICTED"
HEALTH = (HEALTHY, STALE, MISSING, CONFLICTED)

# code -> (disposition, description). Contract-level legacy states use disposition None (they describe what the
# legacy universe did with one raw contract, not an engine's final word on an asset).
REASONS = {
    # ---- contract level: what the legacy adapters and build_universe() did with a raw market
    "SELECTED": (None, "kept by the legacy adapter and chosen as the asset's market on this venue"),
    "HL_BUILDER_MARKET": (None, "Hyperliquid builder-deployed market (name contains ':'); the adapter skips it"),
    "DELISTED": (None, "the venue marks the market delisted; the adapter skips it"),
    "NOT_PERPETUAL": (None, "not a perpetual contract (dated future, option, spot); the adapter skips it"),
    "NOT_TRADING": (None, "the venue reports the market inactive or not trading; the adapter skips it"),
    "EMPTY_SYMBOL": (None, "the venue sent no usable symbol; the adapter skips it"),
    "DUPLICATE_NOT_SELECTED": (None, "another market of the same canonical asset on this venue had more volume; "
                                     "build_universe() keeps one market per asset and venue"),
    "PRICE_CONFLICT_DROPPED": (None, "price more than 20% away from the asset's main market; build_universe() "
                                     "treats it as a different asset under the same ticker and leaves it out"),
    "ADAPTER_FAILED": (None, "the venue's legacy adapter raised an error this scan, so legacy used none of its "
                             "markets"),
    "AUDIT_ADAPTER_MISMATCH": (None, "the registry's reading of the raw market disagrees with the legacy adapter "
                                     "(an observability defect; legacy output is unaffected)"),
    # ---- shared universe (asset level)
    "TRADFI_CLASSIFIED": (MODEL_INELIGIBLE, "classified tradfi (stock, index, FX, commodity); legacy engines "
                                            "are crypto only"),
    "TRADFI_TICKER_COLLISION": (MODEL_INELIGIBLE, "venues disagree: a tradfi listing shares the ticker of a market "
                                                  "listed as crypto; legacy marks the whole ticker tradfi (a real "
                                                  "crypto coin is excluded when known_crypto is true)"),
    "NO_ACTIVE_PERP_CONTRACT": (NOT_EXECUTABLE, "every contract for this asset was skipped by the legacy "
                                                "adapters (delisted, inactive, builder, non-perpetual)"),
    "PRICE_CONFLICT_ALL_VENUES": (INSUFFICIENT_DATA, "every venue's price was dropped as a price conflict"),
    "VENUE_ADAPTER_FAILED": (INSUFFICIENT_DATA, "listed only on venues whose legacy adapter failed this scan"),
    "FALLBACK_UNIVERSE": (INSUFFICIENT_DATA, "no DEX market list loaded; legacy used its built-in coin list "
                                             "without DEX data"),
    # ---- liquidity on the DEXs you trade (all engines)
    "DEX_VOLUME_BELOW_LEGACY_MIN": (NOT_EXECUTABLE, "24h volume on your trade DEXs below the legacy minimum"),
    "DEX_VOLUME_MISSING_LEGACY_ZERO": (INSUFFICIENT_DATA, "no 24h volume reported on your trade DEXs; legacy "
                                                          "treats the missing value as 0"),
    "NOT_ON_TRADE_DEX": (NOT_EXECUTABLE, "listed only on DEXs outside your trade DEXs; legacy treats its "
                                         "volume as 0"),
    # ---- candles and history
    "NO_SUPPORTED_CANDLES": (INSUFFICIENT_DATA, "no candle source (MEXC, Gate.io, Bitget, Hyperliquid, Aster) "
                                                "returned candles for this asset"),
    "PRICE_SCALE_CONFLICT": (INSUFFICIENT_DATA, "candle prices do not match the DEX price (another asset under "
                                                "the same symbol); the source was skipped"),
    "INSUFFICIENT_1H_HISTORY": (INSUFFICIENT_DATA, "fewer closed 1h candles than the radar's stage 1 needs"),
    "INSUFFICIENT_15M_HISTORY": (INSUFFICIENT_DATA, "fewer closed 15m candles than the radar's deep dive needs"),
    "INSUFFICIENT_4H_HISTORY": (INSUFFICIENT_DATA, "fewer closed 4h candles than the engine needs"),
    "INSUFFICIENT_30D_HISTORY": (INSUFFICIENT_DATA, "less than 30 days of history (quant eligibility)"),
    "INSUFFICIENT_90D_HISTORY": (INSUFFICIENT_DATA, "less than 90 daily candles (swing checks)"),
    "LAST_DAY_NOT_SYNCED": (INSUFFICIENT_DATA, "the asset's last complete day is older than the scan's last "
                                               "day (stale candles)"),
    "SWING_INPUTS_UNAVAILABLE": (INSUFFICIENT_DATA, "a swing input (range, RSI, squeeze, ATR) could not be "
                                                    "computed"),
    "NO_HOURLY_CANDLES": (INSUFFICIENT_DATA, "not enough closed hourly candles for the day-trade checks"),
    "REF_VOLUME_BELOW_LEGACY_MIN": (MODEL_INELIGIBLE, "reference (CEX candle) volume below the legacy minimum"),
    # ---- radar (scanner.py)
    "RADAR_STAGE2_NOT_SELECTED": (REJECTED, "liquid, but outside the stage-1 top N and not an extra"),
    "NO_STRATEGY_SIGNAL": (REJECTED, "evaluated; no strategy fired on the latest closed candles"),
    "STOP_TOO_WIDE": (REJECTED, "a strategy fired but its stop is wider than the maximum risk allowed"),
    "STOP_ABOVE_PRICE": (REJECTED, "a strategy fired but the price is already at or below the stop"),
    "PAST_TARGET": (REJECTED, "a strategy fired but the price is already past the first target"),
    "VARIANT_FILTER_NOT_MET": (REJECTED, "a strategy variant fired but its own filter did not pass"),
    "MARKET_GATE_BLOCKED": (REJECTED, "signals blocked by the market gate"),
    "STRATEGY_NOT_PASSED": (REJECTED, "signals come from strategies that have not passed their test; paper "
                                      "only"),
    "VARIANT_FORWARD_TEST": (REJECTED, "signal from a new variant in its live test; paper only"),
    "ADJUSTMENT_BLOCKED": (REJECTED, "a learned adjustment blocked the signal"),
    "SCORE_BELOW_THRESHOLD": (REJECTED, "score below the publishing threshold and not in the watch slots"),
    "OUTPUT_TOP_N_CUTOFF": (REJECTED, "qualified, but cut by the number of published slots"),
    "RADAR_PICK": (SURFACED, "published as a radar pick"),
    "RADAR_WATCH": (WATCHED, "published on the radar watch list"),
    # ---- quant (quant.py)
    "QUANT_NEW_SIGNAL": (SURFACED, "new quant signal this scan (paper trade opened)"),
    "QUANT_POSITION_OPEN": (SURFACED, "an open quant position is published"),
    "QUANT_SIGNAL_NOT_ACTED": (REJECTED, "a strategy is in signal state but no trade was opened: the bar was "
                                         "processed in an earlier scan (quant acts on new bars only) or the "
                                         "strategy's last trade on this coin is too recent"),
    # ---- coin picks (picks.py), swing and day engines
    "SWING_READY": (SURFACED, "listed with a Ready or Strong swing score"),
    "SWING_SETTING_UP": (WATCHED, "listed with a Setting-up swing score"),
    "DAY_READY": (SURFACED, "listed with Good or Best day-trade conditions"),
    "DAY_SETTING_UP": (WATCHED, "listed with Setting-up day-trade conditions"),
    "LISTED_BELOW_WATCH": (REJECTED, "listed in a top list, but with a Weak score"),
    "DAY_CANDIDATE_NOT_SELECTED": (REJECTED, "not among the most liquid coins and swing score below 60"),
    # ---- smart money (smart.py)
    "SMART_CROWD_SIGNAL": (SURFACED, "proven traders crowd into the tested side: a smart-money signal"),
    "SMART_CROWD_INFO": (WATCHED, "proven traders crowd into the untested side: information only"),
    "SMART_NO_CROWD": (REJECTED, "held by proven traders, no crowd of new entries under the rule"),
    "SMART_POSITIONS_BELOW_MIN": (REJECTED, "proven traders hold it only in positions below the minimum size"),
    "SMART_NOT_HELD": (REJECTED, "listed on Hyperliquid, not held by any proven trader read this scan"),
    "SMART_VENUE_NOT_COVERED": (MODEL_INELIGIBLE, "not listed on Hyperliquid; the smart-money engine reads "
                                                  "Hyperliquid accounts only"),
    # ---- audit itself
    "AUDIT_UNCLASSIFIED": (INSUFFICIENT_DATA, "the audit could not classify this asset (an audit defect)"),
}

# step codes recorded next to a final disposition (they never are the final disposition themselves)
STEPS = {
    "PAPER_LIMIT_REACHED": "a paper trade was not opened: the open-trade limit was reached",
    "PAPER_BUSY": "a paper trade was not opened: one is already open on this coin",
    "PAPER_NO_PRICE": "a paper trade was not opened: no live price for the coin",
    "PAPER_BELOW_MIN_SCORE": "listed, below the paper-trade score minimum",
    "PAPER_OPENED": "a paper trade was opened this scan",
    "FUNDING_ASSUMED_DEFAULT": "no DEX funding observed; legacy paper costs assume the default funding rate",
    "FUNDING_MISSING_AS_ZERO": "no funding settlement found; legacy quant paper costs count it as 0",
    "NOT_IN_PUBLISHED_LIST": "kept out of the published list by its length limit",
    "PLAN_REJECTED": "a strategy fired but its trade plan was rejected (see the plan list)",
    "EXTRA_DEEP_DIVE": "deep-dived as a stage-2 extra (smart money long or dip in an uptrend)",
}

# trader-level outcomes of the smart-money engine (aggregate counts, not asset dispositions)
TRADER_REASONS = {
    "TRADER_SELECTED": "proven trader, read this scan",
    "TRADER_UNREADABLE": "proven trader whose account state could not be read",
    "TRADER_BAD_ADDRESS": "leaderboard row without a usable address",
    "TRADER_ACCOUNT_BELOW_MIN": "account value below the minimum",
    "TRADER_PNL_BELOW_MIN": "all-time profit below the minimum",
    "TRADER_MONTH_LOSS": "lost more than the allowed share of the account this month",
    "TRADER_MARKET_MAKER_OR_INACTIVE": "30-day volume like a market maker's, or no volume at all",
    "TRADER_BEYOND_MAX": "proven, but beyond the maximum number of traders read",
}


def disposition_of(code):
    """The disposition a reason code implies (None for contract-level states). Unknown codes raise KeyError."""
    return REASONS[code][0]


def describe(code):
    return REASONS[code][1] if code in REASONS else STEPS.get(code, code)


def check_code(code):
    if code not in REASONS:
        raise KeyError(f"unknown v8 reason code {code!r}")
    return code
