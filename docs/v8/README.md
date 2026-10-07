# v8: observable decisions (Phase 1) and universe identity (Phase 2)

Phase 1 made the existing engines **observable** without changing what they decide. Phase 2 corrects, in a narrow
and approved scope, **which markets form the coin universe** and **what a missing 24h volume means** - see
[phase2-universe-identity.md](phase2-universe-identity.md). No strategy, threshold, score, stop, target, top-N limit,
history requirement, paper-trade rule or data source changed in either phase; Phase 2's output differences from the
Phase 1 base are proven to be exactly the approved ones (see [Behaviour parity](#behaviour-parity)).

What is new:

| Piece | What it answers | Where |
|---|---|---|
| Contract registry | Which markets did the eight DEXs list this scan, including the ones the legacy universe drops, and what happened to each? | [contract-identity.md](contract-identity.md) |
| Disposition ledger | For every coin and every engine: surfaced, watched, rejected, not executable, insufficient data or model-ineligible, and exactly why | [disposition-taxonomy.md](disposition-taxonomy.md) |
| Data health | Was a value observed, observed as zero, missing (and silently used as 0), or a default? Is a record HEALTHY, STALE, MISSING or CONFLICTED? | [data-health.md](data-health.md) |
| Provenance and snapshot | Which code, configuration and inputs produced this scan; a versioned, deterministic audit file per scan | [provenance-and-snapshot.md](provenance-and-snapshot.md) |
| Blocking CI | Tests, parity, simulator and no-edge checks that fail closed | [ci.md](ci.md) |
| Known legacy behaviour | What the audit shows that is still wrong and was deliberately left alone | [known-legacy-behavior.md](known-legacy-behavior.md) |
| Phase 0 recommendations | NON-AUTHORITATIVE notes for later phases; nothing reads them at runtime | [phase0-requalification.md](phase0-requalification.md) |
| Universe identity (Phase 2) | Which markets are one coin, crypto or not, decided per contract and per price-coherent exposure; missing volume is not $0 | [phase2-universe-identity.md](phase2-universe-identity.md) |

## How it runs

1. Each engine process (scanner, smart money, quant desk, coin picks) runs exactly as before. One-line hooks hand
   values the engine already has to a recorder (`v8/trace.py`); the recorder never raises and nothing reads from it
   during the run.
2. After an engine has written its own files, it calls its audit (`v8/audit_*.py`), wrapped so that any audit
   error is recorded in the audit file and logged, never raised. The audit writes `data/v8/parts/<engine>.json`.
3. After the dashboard step, `python -m v8.snapshot --out site` assembles `data/v8/audit_latest.json` (and a gzip
   copy and the first-seen map), hashes the legacy files, and appends the gzip copy to a 14-day Actions artifact.

The snapshot is published with the site at `data/v8/audit_latest.json`. There is no v8 page yet.

Since Phase 2, two v8 modules **decide** instead of observing: `v8/identity.py` builds the coin universe that
`scanner.build_universe()` returns to the scanner, the quant desk and the coin picks, and `v8/liquidity.py` is the
liquidity evaluation behind every $1M gate. They are imported unconditionally: without them the scan does not run.

## Behaviour parity

`tools/v8/legacy_parity.py` runs the whole pipeline offline - scanner, smart money twice, quant desk, coin picks,
dashboard, each in its own process like the Scan workflow - on a fixed fake market that also serves all eight DEX
market lists with every edge case the legacy universe filters (builder markets, delisted and inactive contracts,
tradfi ticker collisions, duplicates, price conflicts, missing and zero volume, small, thin and newly listed coins,
coins without candles, a price-scale conflict). Time is frozen and every outbound request is answered by the fake
or refused, so two runs of the same code produce identical files.

* `tests/fixtures/v8/legacy_parity_golden.json` holds the digests of all 20 legacy output files produced by the
  phase base (main 15a3794, Phase 1) on the fixture; `legacy_parity_golden_phase2.json` those of this branch.
  `tests/test_v8_audit.py` and CI compare every run with the branch's own golden file (no drift).
* `tools/v8/delta_parity.py` (CI, every run) proves the difference between the two: it rebuilds the base on the same
  runner, checks it reproduces its golden file, then compares the base's and this branch's universes and, with a
  counterfactual run (the base's code fed this branch's universe), the engines' outputs. Every difference must be
  listed in `tests/fixtures/v8/phase2_expected_deltas.json`, and every listed difference must occur.
* Only files under `data/v8/` are excluded; wall-clock durations (`duration_s`) are dropped and error notes are
  sorted before hashing (they are collected by parallel threads, in no fixed order).

## Running it locally

```
python -m unittest discover -s tests                     # everything, about 40 seconds
python tools/v8/legacy_parity.py --out /tmp/parity --check tests/fixtures/v8/legacy_parity_golden_phase2.json
git worktree add --detach /tmp/base 15a37944bc73ae531ea33998b899a562e51361ad
python tools/v8/delta_parity.py --base-root /tmp/base --manifest tests/fixtures/v8/phase2_expected_deltas.json --work /tmp/delta
python -m v8.snapshot --out /tmp/parity --keep-parts     # assemble a snapshot from the parity run
python tools/v8/identity_report.py /tmp/parity/data/v8/audit_latest.json   # the collision matrix
```
