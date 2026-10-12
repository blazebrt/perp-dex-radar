"""v8 layer: contract registry, disposition ledger, data health and run provenance (Phase 1); universe identity and
liquidity semantics (Phase 2); four identity states and the identity execution gate (Phase 3); observed candidate
identity evidence, kept apart from authoritative evidence (Phase 4); wrapper evidence kept apart from economic-exposure
evidence, venue exposure checks and the before/after against the previous identity version (Phase 5); the known-crypto
list bound to at most one price-coherent exposure per ticker, with its binding trace (Phase 6); full-universe discovery:
every active perpetual of every healthy venue in one discovery record per asset, deep research still bounded, research
flags and a shadow queue without trade authority (Phase 7); an append-only point-in-time history of every scan and a
research-only point-in-time view of it, with time-varying costs and a shadow experiment ledger (Phase 8).

Two modules DECIDE (Phase 2): `identity` builds the coin universe the engines read (which markets are one coin,
crypto or not) and `liquidity` is the shared execution-liquidity evaluation behind every $1M gate. Everything else
OBSERVES the legacy engines (scanner.py, quant.py, picks.py, smart.py): it never feeds a value back into them, and
every audit entry point swallows its own errors so an audit problem can never stop or change a scan.

Modules
    identity    contract-first classification, price-coherent exposures, the four identity states, the legacy coin
                records and the execution identity gate every crypto engine applies (decides)
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
    discovery   full-universe discovery (data/v8/discovery.json, v8.discovery/1): observes, never decides (Phase 7)
    history     append-only point-in-time history on the v8-history branch (v8.history/2 after /1), written by Scan
                workflow after the snapshot; a failure is HISTORY_CAPTURE_DEGRADED and never stops a scan (Phase 8)
    pit         research-only point-in-time queries over the history (universe_at, liquidity_at, intervals); no
                live engine imports it (Phase 8)
    shadow_ledger  the append-only shadow experiment ledger (research/shadow-ledger/, v8.shadow-ledger/1); no
                record has trade authority (Phase 8)
"""

SCHEMA = "v8.audit/7"
ENGINE_VERSION = "v8-phase8.1"
