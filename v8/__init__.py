"""v8 layer: contract registry, disposition ledger, data health and run provenance (Phase 1); universe identity and
liquidity semantics (Phase 2).

Two modules DECIDE (Phase 2): `identity` builds the coin universe the engines read (which markets are one coin,
crypto or not) and `liquidity` is the shared execution-liquidity evaluation behind every $1M gate. Everything else
OBSERVES the legacy engines (scanner.py, quant.py, picks.py, smart.py): it never feeds a value back into them, and
every audit entry point swallows its own errors so an audit problem can never stop or change a scan.

Modules
    identity    contract-first classification, price-coherent exposures, the legacy coin records (decides)
    liquidity   KNOWN / MISSING / NOT_ON_TRADE_DEX and the execution-liquidity gate (decides)
    taxonomy    dispositions, data-health states and the stable reason codes
    health      how a value was observed (observed, observed zero, missing treated as zero, assumed default)
    trace       a thread-safe recorder the legacy code reports into with one-line hooks
    registry    every contract the eight DEX market lists returned, keyed venue:raw_symbol
    ledger      one final disposition per asset per engine, with coverage accounting
    provenance  scan id, git commit, deterministic config hashes, file hashes
    parts       the per-engine audit part each engine process writes (data/v8/parts/<engine>.json)
    audit_*     the end-of-run audit of each engine (reads the run's own values, recomputes nothing it decides)
    snapshot    assembles the versioned audit snapshot (data/v8/audit_latest.json) after all engines ran
"""

SCHEMA = "v8.audit/2"
ENGINE_VERSION = "v8-phase2.0"
