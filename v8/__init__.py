"""v8 observability layer (Phase 1): contract registry, disposition ledger, data health and run provenance.

Everything in this package OBSERVES the legacy engines (scanner.py, quant.py, picks.py, smart.py). It never feeds
a value back into them: no threshold, ranking, pick, signal or paper trade depends on anything computed here, and
every entry point swallows its own errors so an audit problem can never stop or change a scan.

Modules
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

SCHEMA = "v8.audit/1"
ENGINE_VERSION = "v8-phase1.0"
