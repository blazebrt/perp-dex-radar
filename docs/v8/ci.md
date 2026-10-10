# Blocking CI

## `.github/workflows/ci.yml`

Runs on every pull request to main, every push to main and to `v8/*` branches, and on demand. No step uses
`continue-on-error` and no test command ends in `|| true`: a failing command fails the job.

| Job | Steps |
|---|---|
| Unit tests and legacy parity | all unit tests (`python -m unittest discover -s tests`); the v8 tests on their own (Phase 1 audit, Phase 2 identity, liquidity and delta validator, Phase 3 identity coverage, smart-money identity and journal provenance, Phase 3 closure quant and radar evidence, Phase 4 candidate identity evidence, Phase 5 economic exposure, Phase 6 exposure-local ticker authority); legacy parity against this branch's committed golden digests (`legacy_parity_golden_phase6.json`); differential parity against the phase base commit rebuilt on the same runner (`tools/v8/delta_parity.py`: only the deltas listed in `tests/fixtures/v8/phase6_expected_deltas.json`, all of them, nothing else); every workflow file parses |
| Simulator and no-edge checks | installs numpy and numba; `tools/research/test_qsim.py`; `tools/no_edge_check.py` |

Both jobs are required status checks of `main` (ruleset 24588029, strict). Their names are what the ruleset matches:
do not rename them.

### Differential parity (Phase 2, rotated in Phase 3)

Phase 3 moves the base to main `82f8d35` (Phase 2) with its own manifest (`phase3_expected_deltas.json`, schema
`v8.delta/2`): every coin's identity state is pinned, the derived `execution_identity` field is compared like a coin
field, the counterfactual excludes coins without execution identity the base code's own way, and published lists can
be compared as sets. The Phase 2 manifest is kept for the record and no longer checked.

The Phase 3 production-evidence closure moves the base to production main `f8648fe` (Phase 3 merged) with its own
manifest (`phase3_closure_expected_deltas.json`): no universe, identity, DEX status, note or engine-decision delta
is allowed at all. Two manifest kinds were added for per-trade provenance, both exact: `each` (every matching element
of a list gains exactly the listed fields with the listed values - literal, `one_of`, `id_in` or `twin_pair` - on
exactly `count` elements; any other change of those elements is still an unexpected delta) and `append` (every row
of a list gains one trailing value, counted exactly). The harness replays the identity decisions with an injected
universe, so a base that publishes an identity authority reproduces its own golden from its dumped universe. The
Phase 3 manifest is kept for the record and no longer checked.

Phase 4 moves the base to production main `d011bcb` (the closure merged) with `phase4_expected_deltas.json`: no
universe, identity, DEX status, note, engine-decision, code or file delta at all (Stage A records candidate evidence in
the audit trace only, which the parity harness does not compare). The closure manifest is kept for the record and no
longer checked.

Phase 5 moves the base to production main `3288b15` (Phase 4 merged) with `phase5_expected_deltas.json`. The allowed deltas:

* The economic-exposure identity changes of six fixture coins:
  * EXTONLY and PRLX lose crypto execution identity, because Extended Crypto was their only authority.
  * BYD, HYUNDAIUSD, US10Y and XIAOMI become tradfi through Lighter token-list RWA.
* The two DEX crypto counts and the one price-check note that follow from them.
* The published unverified/tradfi lists.
* The identity version (v2 -> v3) on the entry-time proof of the trades the run opens.

The fixture gains only what the base never reads: Extended `subCategory` and a Lighter token-list response. Where the base row lacks them, the delta validator ignores the new raw adapter fields (`xcheck`, `asset_type`, `asset_categories`), as it does for the Phase 2/3 ones, and it still compares every value both sides carry. The Phase 4 manifest is kept for the record and no longer checked.

Phase 6 moves the base to production main `f7aa7f6` (Phase 5 merged) with `phase6_expected_deltas.json`. The allowed deltas:

* FAKE07, a fixture known-crypto coin with a second market 30% away, loses crypto execution identity: its two
  price-separated exposures are both binding candidates, so the list is bound to neither
  (`TICKER_CRYPTO_EXPOSURE_UNBOUND`).
* The three DEX crypto counts that follow from it.
* The published unverified/tradfi lists (FAKE07 joins `coverage.unverified`).
* The identity version (v3 -> v4) on the entry-time proof of the trades the run opens.

The fixture is unchanged. The Phase 5 manifest is kept for the record and no longer checked; the audit tests still
check the Phase 3, closure and Phase 4 manifests' identity states against this run's contracts replayed under the
`v8.identity/2` rules, and the Phase 5 manifest's against the recorded `previous` (`v8.identity/3`).

Phase 1 required the legacy outputs to be identical to the base. Phase 2 changes them on purpose, so the base check
became a differential one: the base commit named in the manifest must reproduce its own golden digests (also with
its own universe injected, which proves injection changes nothing else); this branch must reproduce its own; the
universe delta between the two (per coin field, venue set, DEX status count and note) must equal the manifest; and
the base's code fed this branch's universe must produce this branch's outputs except for the manifest's code deltas.
A difference outside the manifest, or a manifest entry that does not occur, fails the job.

## Scan workflow gate

`scan.yml` now runs the fast core unit tests (every engine's, the v8 unit tests and, since Phase 2, the identity and
liquidity tests; since Phase 3 also the identity coverage and execution-safety tests, `tests.test_v8_phase3` and
`tests.test_v8_phase3_smart` and `tests.test_v8_phase3_journal`; since the Phase 3 closure also
`tests.test_v8_phase3_closure`: no quant position without crypto identity is actionable, legacy quant trades never
become live evidence, legacy radar trades never grant a pass; since Phase 4 also `tests.test_v8_phase4`: no candidate
venue field is crypto evidence, candidates are traced and never authority; since Phase 5 also `tests.test_v8_phase5`:
a crypto wrapper beside tradfi exposure is never crypto-authorized, a wrapper-only unknown and a failed exposure check
fail closed, the current gates react to an identity downgrade, entry-time proof stays historical; since Phase 6 also
`tests.test_v8_phase6.ScanGateInvariants`: one known-crypto exposure binds, two unresolved price exposures of one
ticker never both receive crypto, a tradfi collision leaves one bindable exposure, a failed exposure check cannot
acquire crypto, a current downgrade blocks actionability, a prior entry proof stays historical; about 30 seconds) right after
Python is set up. If they fail, the job stops there: the scanner does not run and nothing is published. The
downstream resilience of the scan is unchanged: smart money, quant desk and coin picks keep `continue-on-error`
with their "keep the published files" fallbacks, and the v8 snapshot step is also `continue-on-error` because an
observability problem must never stop the pages from being published.

## Research workflow

`research.yml` (non-blocking by design: it runs the engines on live data and saves the results to the `research`
branch) now also runs on `v8/phase-*` branches and saves `research_v8_summary.json`, the gzip snapshot and (Phase 2)
`research_identity.json`, the live collision matrix from `tools/v8/identity_report.py`, so the registry, coverage and
identity decisions of a live run can be read before main changes. Since Phase 3 it also runs the phase base's
scanner, quant desk and coin picks on the same live data, and `research_identity.json` adds the four identity
states, the default-crypto inventory, every unverified asset, the venue field census and every production output
the identity gate removes or adds (the base's outputs are saved as `base_*.json`). Since the Phase 3 closure it
also replays the published quant journal through both versions of `quant.py` and classifies and learns the published
radar journal with both versions, then scans with it (`tools/v8/closure_evidence_report.py`:
`research_quant_evidence.json`, `research_radar_evidence.json`). Since Phase 4 it also runs the candidate census (`research_candidate_census.json`).

Since Phase 5 it also runs the economic-exposure safety report on the same observations (`tools/v8/exposure_safety.py`: `research_exposure_safety.json`). `research_identity.json` gains a Phase 5 section with:

* the wrapper vs economic evidence counts;
* the token-list health and coverage;
* every transition against the previous identity version;
* the controls.

Since Phase 6 it also runs the known-crypto ticker binding report on the same observations, with the production
journal (the journal-data branch) for open positions (`tools/v8/ticker_binding.py`: `research_ticker_binding.json`,
whose `v4_check` compares an independent model-2 projection with this checkout's `v8.identity/4`), and
`research_identity.json` gains a Phase 6 section with:

* the ticker_authority counts (unaccounted 0);
* every known-crypto ticker with several priced exposures, with its bindable exposures and result;
* every unbound or check-blocked ticker;
* the controls' bindings and the known-crypto list audit.

The phase base it runs beside the head is the Phase 6 manifest's base (production main `f7aa7f6`).
