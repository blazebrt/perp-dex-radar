# Shadow experiment ledger (v8.shadow-ledger/1)

Pre-registration of shadow research experiments (v8 Phase 8). Append-only: files here are only ever added
(`tools/v8/ledger_guard.py` fails CI on any modification, deletion or rename). One canonical JSON record per file,
`<seq>-<kind>-<id>.json`, chained by `prev_hash`. No record has trade authority (`authority: NONE`), and there is no
FINAL, LIVE or PROMOTED status. Changed parameters need a new experiment id; a status change is a new `STATUS` record.
Validate with `python tools/v8/ledger_guard.py`. See `docs/v8/phase8-point-in-time-research.md`.
