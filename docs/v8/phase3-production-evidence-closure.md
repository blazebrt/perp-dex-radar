# v8 Phase 3 production-evidence closure: legacy quant and radar evidence

Phase 3 ([phase3-identity-coverage.md](phase3-identity-coverage.md)) gave only `VERIFIED_CRYPTO` coins execution
authority and gave smart-money paper trades entry-time identity proof. The first production scan of merged Phase 3
(run 37822641991, main `f8648fe`) showed two gaps that the same rule had not yet reached:

1. **Quant positions.** The quant journal still held `NIGHT-XSMOM-1791072000`, an XSMOM long opened on 2026-10-04 by
   pre-Phase-3 code. NIGHT is `UNVERIFIED` now. `quant.json` republished it under `open`, the dashboard adds every
   `open` position as a proven quant signal, and the Analyzer turned it into a Proven LONG. Quant's live record also
   counted every closed trade, with or without proof.
2. **Radar journal.** Live radar paper trades written before Phase 3 (including trades on coins now `UNVERIFIED`)
   fed the tournament, live edge against random twins, lessons, cool-downs, tuning and the published live-picks
   record.

This closure fixes both, for every coin and every legacy trade (nothing is special-cased), without changing any
strategy, threshold, gate, stop, target, hold, twin methodology or backtest.

## Two separate questions

`v8/evidence.py` keeps them apart:

| Question | Answered by | When | Rule |
|---|---|---|---|
| May this open position be an actionable signal **now**? | current identity | every scan | only `VERIFIED_CRYPTO` in this scan's universe (`v8.identity.execution_identity_eligible`, the gate every engine uses); a missing identity or a coin missing from the universe fails closed (`IDENTITY_AUTHORITY_MISSING`) |
| May this trade count as **forward evidence** when it closes? | entry-time proof | once, when it opens | `identity_state_at_entry`, `identity_qualified`, `identity_version`, `identity_scan_id`, `identity_decision`, from the identity of the scan that opens it; never recomputed |

| Trade | Actionable now? | Forward evidence? |
|---|---|---|
| pre-closure trade, coin `VERIFIED_CRYPTO` now (e.g. a legacy BTC position) | yes | no (`LEGACY_NO_IDENTITY_PROOF`) |
| pre-closure trade, coin not verified now (NIGHT) | no (`blocked_open`) | no |
| new trade, coin `VERIFIED_CRYPTO` at entry and now | yes | yes |
| new trade, verified at entry, coin degrades later | no (`blocked_open`) | yes: its entry proof stays true and its close counts |

Nothing is inferred backwards: a legacy trade is never qualified because its coin is verified today, and a qualified
trade is never disqualified because its coin changed later.

## Quant (`quant.py`)

* `mark_legacy` runs right after the journal is loaded: every trade without entry-time proof keeps every value it
  has (entry, stop, trail, hours, funding, returns, R, open/closed state) and gains `identity_qualified: false`,
  `identity_state_at_entry: null`, `identity_unqualified_reason: LEGACY_NO_IDENTITY_PROOF`.
* Every new paper trade is stamped from this scan's universe (`evidence.universe_authority`, the same record the
  scanner publishes as `data/v8/identity_authority.json`).
* Open positions are split by current identity (`split_open`). `quant.json`:
  * `open`: the actionable positions only, each with `identity` (its coin's state now);
  * `blocked_open`: the others, as observations, with the current identity, `identity_reason`, trade id, strategy,
    side, entry, current R (`r_now`), normal exits (`exit_stop`, `exit_time`), the entry proof as written, and `why`.
  The journal keeps every one of them: their paper trades run to their normal stop or time exit, simulated exactly
  as before (the gate never touches the simulation).
* `live` and `live_all` count identity-qualified closed trades only; `legacy_unqualified` reports the others (per
  strategy and all); `evidence` gives the counts: qualified / unqualified, open / closed, proof completeness,
  actionable and blocked positions with their reasons.
* `quant_research.json` (the backtest) is unchanged; hard-coded FINAL/ORDER is unchanged (a later phase).

Defense in depth: `dashboard.py` aggregates a quant position (signals, the quant card) only when its `identity` is
`VERIFIED_CRYPTO`; `analyze.js` `testedSignals()` and `signalCoins()` apply the same rule. For a blocked position the
Analyzer says: *"The quant journal still contains this historical paper position (...), but NIGHT is not currently
verified as crypto (UNVERIFIED), so it is not a trade signal."* An `open` entry without an identity (an older or
altered file) is refused.

## Radar (`scanner.py`)

* After the journal is loaded, every **live** row (`bt=0`) without entry-time proof is marked
  `LEGACY_NO_IDENTITY_PROOF`. Backtest rows (`bt=1`) are never touched.
* Every new live paper trade is stamped from this scan's universe; every new random twin carries **its pair's**
  proof (`stamp_pair`), the id of the trade it benchmarks (`pair`) and its own coin's state at entry. A pair is in
  or out of the evidence as a whole.
* `evidence_pool()` is the only input of every evidence-derived output: backtest rows plus identity-qualified live
  rows, with pair integrity (a live twin whose trade is out is out; a live trade whose twin is out is out). It feeds
  `learn()` (strategy status - the tournament -, statistics, live statistics, live edge against twins, tuned targets
  and stops, lessons, cool-downs), `current_tuning()`, `promotion_check()` and `journal_summary()` (strategy rows,
  mistakes, calibration, gate report, the published live-picks record).
* Legacy rows are **reported, never dropped**: `journal.evidence` (exact counts by class - backtest, qualified live,
  legacy live, pair-excluded live -, strategy trades and twins, open and closed, copies; pair integrity; reasons; the
  coins of legacy rows with their identity in this scan), `journal.legacy_unqualified` (their counts, per-strategy
  statistics and picks record), `journal.counts.legacy_live`, the evidence class as the last item of each trade-table
  row and three new `journal.csv` columns (`evidence`, `identity_at_entry`, `identity_scan_id`).
* The lifetime counters (`life`, "since the journal started") are an unchanged historical tally that already mixes
  backtest seeds and live trades; they grant nothing.

**Consequence in production.** Until new qualified live trades accumulate, every strategy's live record is empty
(`live_n` 0, no live edge). With publication restricted to `passed` strategies (unchanged), nothing that was
unpublished becomes published; a strategy can pass again only on forty or more new, identity-qualified live trades
under the unchanged rules. A status that rested on legacy live rows (rejection included) is recomputed from the
remaining evidence.

**Historical backtest identity correctness remains unresolved.** Backtest rows (radar `bt=1`, `quant_research.json`,
smart research) are measured on today's universe; point-in-time identity, survivorship and the historical universe
are scheduled for a later historical-correctness phase.

## Picks

The coin-picks journal was checked independently against the published copy: no open or closed paper trade on a coin
that is not `VERIFIED_CRYPTO` now. No behavioural change was made to picks.

## Audit

* quant part: `journal` (evidence counts, every blocked position, every unqualified trade with its reason), stage
  `blocked_open`; a blocked coin's final record carries the step `QUANT_POSITION_IDENTITY_BLOCKED`, a coin with an
  open legacy position `QUANT_LEGACY_NO_IDENTITY_PROOF`; a blocked coin recorded as SURFACED is an audit problem.
* radar part: `journal` (the radar evidence breakdown and pair integrity); a coin with an open legacy live trade
  carries the step `RADAR_LEGACY_NO_IDENTITY_PROOF`.
* Both reach `coverage.engines.<engine>.journal` in the snapshot. Dispositions are unchanged, so `unaccounted` stays 0.

## Differential parity

The closure is measured from production main `f8648fe` (tree `bb296e4`), whose fixture golden is the Phase 3 branch
golden: `tests/fixtures/v8/phase3_closure_expected_deltas.json`, head golden
`legacy_parity_golden_closure.json`. Universe, DEX status, notes, identity states and engine decisions may not
change at all. Allowed: entry-time proof on every new quant and live radar trade (manifest kind `each`: exactly
these fields with these values on an exact number of trades), the current identity on quant's actionable positions,
the new evidence keys, the evidence class appended to each trade-table row (kind `append`, exact counts) and the
pinned digests of `analyze.js` and `journal.csv`. The Phase 3 manifest (base `82f8d35`) is kept for the record.

The harness replays the identity decisions with an injected universe (`--universe-from`), so a base that publishes an
identity authority reproduces its own golden from its own dumped universe (step 2).

## Tests

`tests/test_v8_phase3_closure.py` (also in the Scan workflow's pre-publication gate): the production NIGHT case and
every quant combination of legacy / qualified and verified / unverified / missing, dashboard and Analyzer included;
forty legacy radar winners never pass while the same forty trades with proof pass under the unchanged rules; legacy
rows never feed lessons, tuning, cool-downs, live edge or the live-picks record; pairs in or out together; backtest
rows untouched. `tests/test_v8_delta.py` covers the new manifest kinds, each failing closed.
