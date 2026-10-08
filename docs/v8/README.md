# v8: observable decisions (Phase 1), universe identity (Phase 2), identity coverage (Phase 3)

Phase 1 made the existing engines **observable** without changing what they decide. Phase 2 corrects, in a narrow
and approved scope, **which markets form the coin universe** and **what a missing 24h volume means** - see
[phase2-universe-identity.md](phase2-universe-identity.md). Phase 3 retires "no evidence means crypto": every coin
has one of four identity states, every coin stays visible (discovery), and only `VERIFIED_CRYPTO` coins may reach a
crypto engine (execution identity) - see [phase3-identity-coverage.md](phase3-identity-coverage.md). No strategy,
threshold, score, stop, target, top-N limit, history requirement, liquidity gate, paper-trade rule or data source
changed in any phase; each phase's output differences from its base are proven to be exactly the approved ones (see
[Behaviour parity](#behaviour-parity)).

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
| Identity coverage (Phase 3) | Four identity states; unknown coins stay visible but never reach an engine or become a signal (smart money included, through the scanner's same-scan identity authority); venue-symbol parsing; identity transitions per scan | [phase3-identity-coverage.md](phase3-identity-coverage.md) |
| Production-evidence closure (Phase 3) | A quant position on a coin without crypto identity now is never actionable (published apart as blocked); quant and live radar trades count as forward evidence only with entry-time identity proof; legacy trades are kept and reported apart | [phase3-production-evidence-closure.md](phase3-production-evidence-closure.md) |

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

* `tests/fixtures/v8/legacy_parity_golden_phase3_base.json` holds the digests of all 20 legacy output files produced
  by the phase base (main 82f8d35, Phase 2) on the fixture; `legacy_parity_golden_phase3.json` those of this branch.
  `tests/test_v8_audit.py` and CI compare every run with the branch's own golden file (no drift). (Phase 2's
  `legacy_parity_golden.json`, `legacy_parity_golden_phase2.json` and `phase2_expected_deltas.json` are kept for
  the record; they belong to the Phase 2 fixture and are no longer checked.)
* `tools/v8/delta_parity.py` (CI, every run) proves the difference between the two: it rebuilds the base on the same
  runner, checks it reproduces its golden file, then compares the base's and this branch's universes (coin fields,
  the derived `execution_identity`, every identity state) and, with a counterfactual run (the base's code fed this
  branch's universe, coins without execution identity excluded the base code's own way), the engines' outputs.
  Every difference must be listed in `tests/fixtures/v8/phase3_expected_deltas.json`, and every listed difference
  must occur.
* Only files under `data/v8/` are excluded; wall-clock durations (`duration_s`) are dropped and error notes are
  sorted before hashing (they are collected by parallel threads, in no fixed order).

## Running it locally

```
python -m unittest discover -s tests                     # everything, about 40 seconds
python tools/v8/legacy_parity.py --out /tmp/parity --check tests/fixtures/v8/legacy_parity_golden_phase3.json
git worktree add --detach /tmp/base 82f8d35a80e561384f2e8be0e1399dd4e5adb99b
python tools/v8/delta_parity.py --base-root /tmp/base --manifest tests/fixtures/v8/phase3_expected_deltas.json --work /tmp/delta
python -m v8.snapshot --out /tmp/parity --keep-parts     # assemble a snapshot from the parity run
python tools/v8/identity_report.py /tmp/parity/data/v8/audit_latest.json   # identity states, inventory, collisions
python tools/v8/rescore_identity.py research_snapshot.json.gz   # re-resolve an earlier scan's market lists
```
