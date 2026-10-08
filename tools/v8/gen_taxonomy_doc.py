"""Regenerates docs/v8/disposition-taxonomy.md from v8/taxonomy.py (the tables of codes).

    python tools/v8/gen_taxonomy_doc.py

tests/test_v8_units.py fails when the document and the module list different codes."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)

from v8 import taxonomy as T  # noqa: E402

HEAD = "# Disposition taxonomy (v8 Phase 1, extended in Phases 2 and 3)\n\nEvery asset an engine receives ends with exactly **one final disposition** in that engine's ledger, with a\nstable **reason code**, the observed input, the rule it was compared with, the data health of the inputs and the\nvenue contracts involved. Codes are stable identifiers: new ones may be added, existing ones are never renamed\nor reused. There is deliberately no generic `FILTERED` code; an audit that cannot name a reason writes\n`AUDIT_UNCLASSIFIED`, and the tests fail on it.\n\nSource of truth: `v8/taxonomy.py`. `tests/test_v8_units.py` checks that every code below is in that module and\nthe other way round. Phase 2 added the identity and missing-volume codes and retired two codes (marked\n[retired in v8 Phase 2]: kept for older snapshots, never emitted again, never reused). Phase 3 added the four\nidentity states and `IDENTITY_UNVERIFIED`, and retired the exposure reason `DEFAULT_CRYPTO`.\n\n## Final dispositions\n\n| Disposition | Meaning |\n|---|---|\n| `SURFACED` | published as an actionable item: a radar pick, a new or open quant position, a Ready/Strong swing or Good/Best day-trade listing, a smart-money signal |\n| `WATCHED` | published for watching, not as an actionable call: radar watch list, Setting-up listings, smart-money information-only crowds |\n| `REJECTED` | evaluated by the engine and not surfaced: no setup, blocked, below a score, cut by the number of published slots |\n| `NOT_EXECUTABLE` | not tradable enough on the DEXs the engine trades: volume below the legacy minimum, not on a trade DEX, no active perp contract |\n| `INSUFFICIENT_DATA` | the engine could not evaluate it: candles, history, a 24h volume or a crypto identity missing or conflicting |\n| `MODEL_INELIGIBLE` | outside what the engine's model covers: tradfi exposures, reference volume below the minimum, smart money outside Hyperliquid |\n\n## Engines\n\n| Engine | Input (every asset gets one record) | Written by |\n|---|---|---|\n| `universe` | registry assets the legacy universe never kept (all contracts skipped, every venue dropped as a price conflict, or only on venues whose adapter failed) | scanner.py |\n| `radar` | every coin of the scanner's legacy universe, tradfi and identity-unverified included | scanner.py |\n| `quant` | every coin of the quant desk's own universe | quant.py |\n| `swing` | every coin of the coin-picks universe (swing scores) | picks.py |\n| `day` | every coin of the coin-picks universe (day-trade scores) | picks.py |\n| `smart` | every coin proven traders hold, plus (at snapshot time) every other registry asset | smart.py, snapshot |\n\n"

TAIL = '\n\n| Filter | Code(s) |\n|---|---|\n| Adapter skips: builder markets, delisted, inactive, non-perpetual, empty symbol | contract states `HL_BUILDER_MARKET`, `DELISTED`, `NOT_TRADING`, `NOT_PERPETUAL`, `EMPTY_SYMBOL`; asset `NO_ACTIVE_PERP_CONTRACT` |\n| One market per asset and venue (highest volume kept) | contract state `DUPLICATE_NOT_SELECTED` |\n| Price more than 20% from the main market | contract state `PRICE_CONFLICT_DROPPED` (CONFLICTED); asset `PRICE_CONFLICT_ALL_VENUES` |\n| Universe identity (Phase 2, v8.identity): contract evidence, price-coherent exposures, tradfi lists | `TRADFI_CLASSIFIED`, `TRADFI_EXPOSURE_EXCLUDED`, `AMBIGUOUS_EXPOSURE`; contract state `EXPOSURE_NOT_ADMITTED`; step `CRYPTO_EXPOSURE_SELECTED` (Phase 1: `TRADFI_TICKER_COLLISION`, retired) |\n| Identity execution gate (Phase 3, v8.identity): only VERIFIED_CRYPTO reaches a crypto engine | `IDENTITY_UNVERIFIED`; contract state `UNVERIFIED_EXPOSURE_NOT_ADMITTED`; step `UNVERIFIED_EXPOSURE_KEPT_OUT` |\n| No DEX market list at all (built-in coin list) | manifest `fallback_universe`, `FALLBACK_UNIVERSE` event |\n| $1M 24h volume on your trade DEXs (radar stage 2, quant, picks; v8.liquidity since Phase 2) | `DEX_VOLUME_BELOW_LEGACY_MIN` (observed, an observed 0 included), `DEX_VOLUME_MISSING` (no volume reported), `NOT_ON_TRADE_DEX` (Phase 1: `DEX_VOLUME_MISSING_LEGACY_ZERO`, retired) |\n| Candle source chain and price-scale check | `NO_SUPPORTED_CANDLES`, `PRICE_SCALE_CONFLICT` |\n| Radar stage 1: 30 closed 1h candles | `INSUFFICIENT_1H_HISTORY` |\n| Radar stage 2: top 40 liquid plus 16 extras | `RADAR_STAGE2_NOT_SELECTED`, step `EXTRA_DEEP_DIVE` |\n| Radar deep dive: 60 closed 15m candles | `INSUFFICIENT_15M_HISTORY` |\n| Strategy fired, plan rejected (stop too wide, below stop, past TP1) | `STOP_TOO_WIDE`, `STOP_ABOVE_PRICE`, `PAST_TARGET`, step `PLAN_REJECTED` |\n| Variant filters | `VARIANT_FILTER_NOT_MET` |\n| Market gate, strategy status, forward test, learned adjustments | `MARKET_GATE_BLOCKED`, `STRATEGY_NOT_PASSED`, `VARIANT_FORWARD_TEST`, `ADJUSTMENT_BLOCKED` |\n| Minimum pick score, top 10, 8 watch slots | `SCORE_BELOW_THRESHOLD`, `OUTPUT_TOP_N_CUTOFF`, `RADAR_PICK`, `RADAR_WATCH` |\n| Quant: 4h candles, 30 days, $5M reference volume, stop above 20%, XSMOM rank, new bars only | `INSUFFICIENT_4H_HISTORY`, `INSUFFICIENT_30D_HISTORY`, `REF_VOLUME_BELOW_LEGACY_MIN`, `STOP_TOO_WIDE`, `NO_STRATEGY_SIGNAL` (with the XSMOM rank), `QUANT_SIGNAL_NOT_ACTED`, `QUANT_NEW_SIGNAL`, `QUANT_POSITION_OPEN` |\n| Picks: last-day sync, $5M last-day volume, 90 daily candles, swing inputs | `LAST_DAY_NOT_SYNCED` (STALE), `REF_VOLUME_BELOW_LEGACY_MIN`, `INSUFFICIENT_90D_HISTORY`, `SWING_INPUTS_UNAVAILABLE` |\n| Picks: day candidates (top 50 liquid or swing 60+), hourly candles, top-10 lists, labels | `DAY_CANDIDATE_NOT_SELECTED`, `NO_HOURLY_CANDLES`, `SWING_READY`, `SWING_SETTING_UP`, `DAY_READY`, `DAY_SETTING_UP`, `LISTED_BELOW_WATCH`, `OUTPUT_TOP_N_CUTOFF`, `SCORE_BELOW_THRESHOLD` |\n| Picks paper trades (80+ swing, 85+ day) | step `PAPER_OPENED` |\n| Smart: trader eligibility, $10k position minimum, entry rule, 60 published rows, 12 open paper trades | trader outcomes above, `SMART_POSITIONS_BELOW_MIN`, `SMART_CROWD_SIGNAL`, `SMART_CROWD_INFO`, `SMART_NO_CROWD`, steps `NOT_IN_PUBLISHED_LIST`, `PAPER_LIMIT_REACHED`, `PAPER_BUSY`, `PAPER_NO_PRICE`, `PAPER_OPENED` |\n'


def render():
    out = [HEAD.rstrip("\n"), "", "## Reason codes", "",
           "Contract states (disposition column empty) describe what the legacy universe did with one raw market; they",
           "appear in the registry, never as an asset's final disposition.", "",
           "| Code | Disposition | Meaning |", "|---|---|---|"]
    for k, (d, t) in T.REASONS.items():
        out.append(f"| `{k}` | {('`' + d + '`') if d else ''} | {t} |")
    out += ["", "## Step codes", "", "Noted on a record next to its final disposition (field `x`); never a final "
            "disposition themselves.", "", "| Code | Meaning |", "|---|---|"]
    out += [f"| `{k}` | {t} |" for k, t in T.STEPS.items()]
    out += ["", "## Identity states (v8 Phase 3)", "", "Every asset with an active perp has exactly one state "
            "(registry `assets[t].identity.state`, coin record `identity`). Only `VERIFIED_CRYPTO` has crypto "
            "execution identity; every state is discovery-visible.", "", "| State | Meaning |", "|---|---|"]
    out += [f"| `{k}` | {t} |" for k, t in T.IDENTITY_STATES.items()]
    out += ["", "Retired identity reasons (older snapshots only):", "", "| Reason | Replaced by |", "|---|---|"]
    out += [f"| `{k}` | {t} |" for k, t in T.RETIRED_IDENTITY_REASONS.items()]
    out += ["", "## Smart-money trader outcomes", "", "Counts per scan in the smart part (`traders.by_reason`), one per "
            "leaderboard row.", "", "| Code | Meaning |", "|---|---|"]
    out += [f"| `{k}` | {t} |" for k, t in T.TRADER_REASONS.items()]
    out += ["", "## Where each legacy filter is recorded" + TAIL.rstrip("\n")]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    with open(os.path.join(ROOT, "docs", "v8", "disposition-taxonomy.md"), "w") as fh:
        fh.write(render())
