# v8: observable decisions (Phase 1), universe identity (Phase 2), identity coverage (Phase 3), candidate identity evidence (Phase 4), economic exposure (Phase 5), exposure-local ticker authority (Phase 6), full-universe discovery (Phase 7), point-in-time history and research (Phase 8)

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
| Candidate identity evidence (Phase 4) | Which venue fields could be positive crypto evidence: a census and qualification gate over the retained and live scans (none qualified; no identity change), and observed candidate evidence recorded in every audit apart from authoritative evidence | [phase4-positive-crypto-evidence.md](phase4-positive-crypto-evidence.md) |
| Economic exposure (Phase 5) | The identity follows the economic exposure, not the instrument wrapper (`v8.identity/3`): Extended's "Crypto" category is wrapper evidence only, Lighter's documented token-list asset type RWA is tradfi evidence, a failed exposure check never makes a market crypto, and the audit keeps wrapper and economic evidence apart with a before/after against the previous version | [phase5-economic-exposure.md](phase5-economic-exposure.md) |
| Exposure-local ticker authority (Phase 6) | The known-crypto list is ticker-level knowledge, bound to at most one price-coherent exposure of its ticker (`v8.identity/4`): one candidate left after deterministic evidence binds (`TICKER_KNOWN_CRYPTO_BOUND`), several stay `UNVERIFIED` (`TICKER_CRYPTO_EXPOSURE_UNBOUND`), nothing is chosen by volume or venue count; every binding is in the audit (`ticker_authority`, Decision Trace, counts with unaccounted 0) | [phase6-exposure-local-crypto-authority.md](phase6-exposure-local-crypto-authority.md) |
| Full-universe discovery (Phase 7) | Discovery sees everything, execution remains selective: every active perpetual of every healthy venue gets one discovery record (`data/v8/discovery.json`, `v8.discovery/1`) with identity, light market structure, execution liquidity as its own field, research flags, a lane and a nine-step Decision Trace; deep research stays the radar's bounded stage 2 and every other asset says why; a shadow deep-research queue is compared with it and has no authority; the quant audit records an open position below liquidity as an existing position to manage | [phase7-full-universe-discovery.md](phase7-full-universe-discovery.md) |
| Point-in-time history and research (Phase 8) | Historical research may use only what was knowable then: every production scan appends one observation (perpetuals, asset identity, venue health, liquidity every ~4 hours) to the append-only, hash-chained `v8-history` branch (`v8.history/1`, never force-pushed, `HISTORY_CAPTURE_DEGRADED` on failure, backfilled only from archived scan artifacts); a research-only point-in-time view (`v8.pit/1`: KNOWN_ACTIVE / KNOWN_INACTIVE / UNKNOWN, listing intervals, liquidity then); time-varying slippage and observed funding for research, every trade qualified, legacy results labelled `LEGACY_SURVIVORSHIP_UNQUALIFIED` (`research_pit.json`); an append-only shadow experiment ledger with no authority | [phase8-point-in-time-research.md](phase8-point-in-time-research.md) |
| Strategy authority (Phase 9) | Deployment follows the reviewed `v8/quant_strategy_policy.json`; research adjudicates all 24 candidates with a predeclared gate, trial census, matched controls and multiple testing, and can never promote by itself; TSMOM, TREND_EMA and XSMOM are legacy holdovers with insufficient evidence | [phase9-strategy-authority.md](phase9-strategy-authority.md) |
| Portfolio and risk realism (Phase 10) | One governed portfolio-risk authority (`v8.portfolio-risk/1`, policy `v8.portfolio-risk-policy/1`): trade-level, gross/net, concentration, point-in-time dependence, liquidity, funding, six stress scenarios, four fail-closed states, what-if and an INPUT -> RULE -> RESULT -> EFFECT trace; the whole open book counts, actionable and identity-blocked; every limit is a reviewed initial policy (`POLICY_REVIEWED_INITIAL_V1`), never an empirical claim; audit-only (`v8.audit/9`) | [phase10-portfolio-risk.md](phase10-portfolio-risk.md) |

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
  Every difference must be listed in the phase's manifest, and every listed difference must occur. Since Phase 8 the
  manifest is `tests/fixtures/v8/phase8_1_expected_deltas.json` (base: production main f142bb1, Phase 8 merged;
  head golden `legacy_parity_golden_phase8_1.json`), which lists no delta at all: the Phase 8 post-merge hotfix is
  history- and research-only. Phase 8's manifest (`phase8_expected_deltas.json`, base 1609e2c) lists no delta either.
  Phase 7's manifest (`phase7_expected_deltas.json`, base 61960d9, no delta either) is kept for the record. Phase 6's manifest
  (`phase6_expected_deltas.json`, base f7aa7f6: FAKE07's known-crypto authority can no longer be bound to a single
  exposure) and the earlier manifests (`phase3_expected_deltas.json`, `phase3_closure_expected_deltas.json`,
  `phase4_expected_deltas.json`, `phase5_expected_deltas.json`) are kept for the record.
* Only files under `data/v8/` are excluded; wall-clock durations (`duration_s`) are dropped and error notes are
  sorted before hashing (they are collected by parallel threads, in no fixed order).

## Running it locally

```
python -m unittest discover -s tests                     # everything, about 40 seconds
python tools/v8/legacy_parity.py --out /tmp/parity --check tests/fixtures/v8/legacy_parity_golden_phase8_1.json
git worktree add --detach /tmp/base f142bb11959d7f4714c33945258c326434e7c8c6
python tools/v8/delta_parity.py --base-root /tmp/base --manifest tests/fixtures/v8/phase8_1_expected_deltas.json --work /tmp/delta
python tools/v8/ledger_guard.py                          # the shadow ledger is append-only and valid (Phase 8)
python -m v8.history verify --dir <export of v8-history> # the history chain (Phase 8)
python -m v8.history project audit_latest.json.gz --days 3   # measured storage projection (Phase 8)
python -m v8.snapshot --out /tmp/parity --keep-parts     # assemble a snapshot from the parity run
python tools/v8/identity_report.py /tmp/parity/data/v8/audit_latest.json   # identity states, inventory, collisions
python tools/v8/rescore_identity.py research_snapshot.json.gz   # re-resolve an earlier scan's market lists
python tools/v8/candidate_census.py a.json b.json.gz --json census.json   # candidate fields and the Phase 4 gate
python tools/v8/exposure_safety.py a.json b.json.gz --outputs site/data --json es.json   # Phase 5 authority inventory and models
python tools/v8/ticker_binding.py a.json b.json.gz --outputs journal_data --json tb.json   # Phase 6 known-crypto census and binding models
```
