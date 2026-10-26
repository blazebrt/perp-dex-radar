# v9 handover: from a governed desk with no trades to a data-driven desk that earns its trades

The owner's brief (2026-10-14) asked for four things:

- The v8 desk's interface is clean, but its data use, signal quality and evaluation methods are worse than the
  legacy product's.
- It recommends no trades at all.
- Rebuild it from the legacy product using every free crypto data source, with a data-driven decision engine. It
  should be "world class", the kind of tool someone would pay $1,000 for.
- Leave a plan so that later sessions do not get lost.

Work autonomously, and ask the owner only when a login is needed.

This file is that plan. Keep it current.

## 0. How to resume

1. Read `CLAUDE.md`. It covers environment facts, the results branches and the rules.
2. v9 is merged into `main` (PR #28, merge commit `f58c058`), so start from `main` and work on a new `v9/...`
   branch with a draft PR. #25, #26 and #27 are closed as merged through #28. PR #24 (the v8 desk) was merged on
   2026-10-14. The local clone fetches `v9/*` branches; results branches still need an explicit refspec.
3. Read the latest evidence. Fetch each results branch with an explicit refspec (see `CLAUDE.md`), then:
   - `git show origin/evidence-results:REPORT.md` (phase A/B: the legacy strategies);
   - `git show origin/evidence-d1-results:REPORT_D1.md` and `origin/evidence-d2-results:REPORT_D2.md` (phase D);
   - `research/v9/evidence_runs.jsonl` (every run, hash-chained).
4. Pick the first unchecked item in section 6 that is not blocked, and work on it.

## 1. Where things stand

| Area | State | Where |
|---|---|---|
| Release | **v9 is merged into `main`** (PR #28, merge commit `f58c058`, 2026-10-15, at the owner's request), carrying #25, #26 and #27; those three are closed. The first production Scan on `main` published the v9 desk and the first market-history record. | PR #28 |
| v8 desk (Today, Analyzer, Funding, Portfolio, Research) | **Merged into main** (PR #24, 2026-10-14, with the owner's accuracy fixes). | `today.html`, `desk.js`, `desk.css` |
| Data-source survey | **Done.** 102 sources probed from the Actions runner; 81 answer. | `docs/v9/data-sources.md`, branch `probe-results` |
| Known-trial replay (A4) | **A4.1â€“A4.3 complete (verified 2026-10-16), draft PR #30.** All 192 four-hour/daily definitions replayed on the pinned archive; 2,670,894 trades independently reconciled across 2,346 daily rows. Seven hourly columns remain missing. A4.4 assembly/reporting is complete (2026-10-21): the retained artifact in `research/v9/family_assembly/` preserves all 466,854 cells and every column metadata record, independently verified. The complete-return objective remains open. All seven hourly net series remain unavailable; no promotion follows. | `tools/v9/census_plan.py`, `research/v9/census_replay_plan.json` |
| Hourly liquid-universe archive (A5) | **A5.1 and conditional A5.2 complete (2026-10-19), draft PR #30.** The original archive remains rejected. A separate 690-segment quality-restricted archive is published at `0859e683910a7eea7ef446b27cf9773f33d9e9f8`; all 1,386 retained files match the independently verified candidate. It retains 13,862,226 rows, reconstructs 264 hours, quarantines 112, preserves 7,026 original missing hours and 663 zero-trade hours, and blocks new entries on 70/2,345 days. Acceptance is conditional on retrospective-quality disclosure and registered gap-aware execution. A5.3 execution contract and uncertainty-preserving kernel are implemented; batch position accounting and feature-readiness boundaries are implemented; session-reset indicator/signal integration is implemented for six definitions with eight synthetic checks; Funding parsing now explicitly preserves unknown coverage; FUND_CARRY will be recorded unavailable without changing its definition. The bound archive replay driver is implemented and synthetically tested; Durable replay workflow and evidence-recording support are implemented; all 1,082 full regression tests pass. First market replay completed in Actions run `39464874726`, result `84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e` from `491ca15b235a1f635cc5f858115d03162d8e1a5d`. Artifact accounting, all 435,817 retained attempts and all successfully generated signal populations independently reconciled; evidence history now has five intact records. All seven net series remain unavailable; A5.3 is not fully satisfied because FUND_CARRY could not execute and two FUND_FADE segments are unavailable. A4.4 evidence review and assembly specification are recorded; the verified assembly and provenance are retained in `research/v9/family_assembly/`. Complete net-return evidence remains unavailable. | `research/v9/a5_quality_acceptance.json`, `docs/v9/phase-a5-quality-acceptance.md` |
| Matched controls (A6) | **A6.1 and A6.2 complete for the registered diagnostic scope (2026-10-23), draft PR #30.** First run `39774700211` retained result `eb785a908dce572958336649291b8feeb4ee9575`: all 192 four-hour/daily definitions, 4,263,580 signals, 465 shards and all 670 package files verified. The source-bound audit independently reconciled generator ordinals and feature windows against 781 original candle files; seven hourly populations remain unavailable. A6.3 execution/inference rules are registered in `phase-a6-execution-inference.md`; the four-hour execution kernel is implemented with eight synthetic tests; matching/aggregation is implemented with seven synthetic tests; the source/price adapter is implemented with six synthetic tests; the bound streaming outcome driver is implemented with six synthetic tests; independent accounting/pair-arithmetic verification is implemented with seven synthetic tests; independent snapshot-based selection verification is implemented with five tests; independent price-path verification is implemented with five tests; independent statistics/day/reuse verification is implemented with five tests; the source-bound audit runner is implemented with five integration tests; the reservation-bound retention wrapper is implemented with six tests; A6 append-only evidence recording support is implemented with six tests; the execution adapter now uses indexed price windows (61 source reads versus 1,009 in the synthetic baseline); the independent audit now also indexes each source once and verifies bounded windows (1,020 synthetic price paths checked); a lossless compact-record experiment independently reconstructs all fields and reduces synthetic gzip size 24.4%; the compact format is now integrated in version-two outcome packages and independent audits with legacy read support; a complete synthetic outcome/audit probe now covers full, mixed, sparse and interrupted cases with summary/reuse sizes; isolated Linux measurements now cover process peak RSS and sampled visible scratch use at two synthetic sizes; sampled allocated blocks and local Git retention are now measured with byte verification; a reservation-pinned resource preflight now refuses missing, unrepresentative or insufficient qualification before study execution; retained-history checks now reject changed-then-restored reservations, merges, shallow history and nonregular files; the history recorder now revalidates retained resource preflight and requires it for successful attempts; a local retention-commit builder now packages partial files without moving refs and refuses changed reservation tips; a publication helper now verifies the reservation tip, performs a normal update and fetch-verifies the retained commit, with local concurrency tests; a resource-gated create-only reservation orchestrator now verifies the orphan root and saved bytes through an injected API transport; a fixed-host authenticated API transport is now implemented with redirect/error/timeout guards and simulated integration tests; a job coordinator now connects reserve/fetch/execute/prepare/publish with failure retention and no rerun; input preparation now runs inside the verified reservation and its logs are retained; a pinned-input adapter now exports raw Git blobs with object-byte checks and preparation logs; a guarded hosted entry point now connects the API, coordinator and input adapter with a fixed deadline; an inactive manual workflow template and verified local recovery-bundle helper now exist; actual hosted/remote qualification, durable workflow activation and the outcome study remain open. Funding leaves net outcomes/inference unavailable. No Phase 9 qualification or promotion follows. Hosted synthetic pilot run 40315708480 succeeded in all eight cases; artifact/report hashes and failure dispositions verified. Session-wide RSS sampling and explicit coverage gaps are implemented and synthetically tested; read-only kernel memory capability checks now distinguish shared counters from unavailable measurement. An opt-in isolated cgroup runner is implemented with mocked lifecycle tests; hosted delegation and complete accounting remain unverified. Full-scale resource qualification remains pending. | `research/v9/a6_result_verification.json`, `docs/v9/phase-a6-extraction-review.md` |
| Survivorship-free evidence engine | **v1 done.** 17 daily/4h strategies plus the coin-picks swing score, on 750 coins (170 delisted), 2020-01 to 2026-09. Every run is recorded, hash-chained and pinned to its dataset (A8). | `tools/v9/archive_fetch.py`, `tools/v9/evidence.py`, `research/v9/evidence_runs.jsonl`, branch `evidence-results` |
| Probation tier (first governed trades) | **Implemented** (`dada154`, in PR #28). XSMOM long is CONFIRMED on (a)â€“(j). It trades at half size inside a 24h window. Its forward test `V9-PROBATION-XSMOM-LONG-1` starts 2026-10-15 00:00 UTC. The live check is B8. | `docs/v9/phase-b-probation.md`, `research/v9/probation_evidence.json` |
| Live multi-venue data layer | **C1â€“C3 built** (in PR #28): `v9/market.py`, `data/v9/market.json`, an hourly history on `v9-market-history`, a Today panel and Analyzer context. 16 of 16 sources answered from Actions. | `docs/v9/market-context.md`, branch `market-results` |
| Trade alerts | **Built** (F5, in PR #28): Telegram and/or Discord on every new TRADE, with the full plan. Sends nothing until the owner adds the secrets. | `v9/alerts.py` |
| New signal research (positioning, funding, OI, liquidations, basis, regime) | **D1 and D2 done, D7 answered.** Four strategies (funding fade, taker flow, top-trader divergence, crowd fade) were pre-registered and each tested once on the phase B dataset. **None is confirmed.** XSMOM long remains the only tradable side. | `docs/v9/phase-d1-preregistration.md`, `docs/v9/phase-d2-preregistration.md`, branches `evidence-d1-results`, `evidence-d2-results` |
| Decision engine v2 (expected-R ranking, regime, sizing) | **E4 done**: the forward test is evaluated every scan, shown on Today and demotes a side automatically. E1â€“E3 not started. | section 6, phase E |
| Pro UX (rich trade plans, market board, performance ledger, alerts) | **F1 done** (full trade plan: entry, stop, trailing stop, time exit, size on the page account and in the trader's own dollars, evidence, forward test). F2 first version, F5 alerts. F3 and F4 not started. | section 6, phase F |

## 2. Diagnosis: why there are no trades, and what got worse

### Why the desk shows zero TRADE

All three causes come from the v8 design itself, not from the market.

1. **The strategy-authority gate cannot be passed.**
   - A strategy may produce a TRADE only when its policy row says `ACTIVE_REQUALIFIED` / `REQUALIFIED`.
   - Requalification needs every check in `v8/strategy_authority.py`, and two of them cannot pass:
     - `trial_census_complete` must be true, but `tools/research/strategy_census.build()` always returns
       `complete: False`. The historical research was imported as one commit, so earlier trials can never be
       counted.
     - A 180-day prospective registration must also pass, and none has been registered.
   - So no strategy can ever be requalified under v8 rules.
   - The three runtime strategies (TSMOM, TREND_EMA, XSMOM) are `LEGACY_HOLDOVER`, so their signals cap at WATCH.
     The other 21 candidates are `DISABLED`.
2. **The paper book is over its limits.**
   - The quant desk's legacy-holdover paper positions put the Phase 10 portfolio in `LIMIT_BREACHED`.
   - Every new directional signal is therefore AVOID (`PORTFOLIO_LIMIT_BREACHED`), even one that would otherwise
     qualify.
   - The book being measured holds positions the desk never recommended.
3. **The other legacy signals were never decision candidates.** The coin-picks swing score, the 15-minute radar
   and smart money only appear as "diagnostic" pages. Emerging and funding opportunities are capped at WATCH by
   policy.

### What got worse compared with the legacy product

- **Signals.**
  - The legacy picks gave entry, stop, three targets, size and 18 explained checks.
  - It also used OI, liquidations, the top-trader long/short ratio, funding, unlocks and smart money as score inputs.
  - v8 uses none of these market inputs in its decision (only funding, as a cost).
- **Evaluation.**
  - The legacy research tested today's coin list, which carries survivorship bias. v8 labelled those results
    `LEGACY_SURVIVORSHIP_UNQUALIFIED`, which was correct.
  - But v8 then waited for its own point-in-time history: 0 days on 2026-10-13, 180 needed. That left nothing to
    qualify with.
  - A survivorship-free public archive already existed. That is the gap phase A closes.
- **Data.**
  - v8 publishes a 9.8 MB audit per scan, yet the decision shows little market insight per coin.
  - Binance and Bybit APIs are blocked from the US runners, so the legacy fetchers fell back to MEXC, Gate and
    Hyperliquid for history, again on the current coin list only.

## 3. Evidence so far (survivorship-free, run of 2026-10-14)

The full table is in `docs/v9/evidence-2026-10-14.md`; the latest run is on the `evidence-results` branch.

**Setup.**

- Universe: every Binance USD-M perpetual that ever traded, 2020-01 to 2026-09. That is 750 coins in the panel, 170
  of them delisted. TradFi, index and stablecoin contracts are excluded.
- Costs: 0.045% taker fee plus 0.10% slippage on each side, and observed funding.
- Eligibility is point-in-time: $5M or more a day over the last 7 days, and at least 30 days listed.
- The legacy strategies were designed on Oct 2023 to Oct 2026 data. So **Jan 2020 to Sep 2023 is a holdout** they
  never saw, out of sample in time, and the delisted coins are out of sample in the cross-section.

**What holds up.** R is the net result in units of the stop distance, per trade.

| Hypothesis | Holdout 2020-01..2023-09 | Design window 2023-10..2026-09 | Since 2025-01 |
|---|---|---|---|
| **XSMOM long** (momentum rotation, longs) | **+0.167R, 95% low +0.030, p=0.009, 503 trades** | **+0.231R, 95% low +0.014, p=0.018, 443 trades** | +0.139R, p=0.15, 206 trades |
| XSMOM short | +0.068R (p=0.06) | **âˆ’0.131R (significantly negative)** | âˆ’0.029R |
| TSMOM short | +0.163R (p=0.001) | âˆ’0.001R | +0.106R (p=0.03) |
| TSMOM long | +0.009R | +0.062R | âˆ’0.064R |
| TREND_EMA (both sides) | âˆ’0.012R | +0.012R | âˆ’0.001R |
| Swing score, short 80+, one trade per coin at a time | +0.069R | +0.148R | 2024 +0.10, 2025 +0.27 |
| Swing score, long 80+ | **âˆ’0.128R** | +0.303R | mixed |

**What it means.**

- **Most legacy claims do not survive.**
  - TREND_EMA (legacy claim +0.095R) is flat.
  - The swing score's long side only works in the window it was built on; it loses in the holdout, a classic sign of
    overfitting.
  - 14 of 17 candidates have no positive 95% lower bound (only TSMOM, XSMOM and TSMOM_SLOW do).
- **XSMOM longs are the strongest result.** They are positive and significant in two independent windows.
  - In the holdout, among the 6 side-level hypotheses of the 3 runtime strategies, Holm-adjusted: TSMOM short
    p=0.006 and XSMOM long p=0.043 survive.
  - Only XSMOM long is also confirmed in the design window.
- **The family-wide tests do not pass.** Across all 17 candidates, White Reality Check p=0.76, Hansen SPA p=0.16 and
  PBO 0.28 (the gate needs â‰¤ 0.20).
  - Those tests ask whether the best of 17 in-sample is real.
  - The holdout test asks a different question: does a strategy chosen on other data work on unseen data? That is
    the right test for strategies whose selection happened in 2023-2026.
- **Caveat.** The side-level gate in phase B was written after this first look. Its protection is therefore the
  forward test (registered before any probation trade) and a reduced size, not the backtest alone.

## 4. Target product: what "world class" means here

A trader opens Today and, in ten seconds, knows:

- **What can be traded now**, as at most five trades. Each has its evidence tier (Validated or Probation), a full
  plan (entry zone, stop, trailing rule, time stop, size for the user's own account), and the expected R with its
  confidence interval from survivorship-free tests.
- **Why**, from the decision trace in plain words.
- **What the market regime is:** trend, volatility (DVOL), funding and OI crowding, liquidations, ETF and stablecoin
  flows, fear and greed.
- **What to watch next:** WATCH opportunities with the exact change that would make them trades.
- **How the desk itself is doing:** the live record of every tier against its backtest expectation, with automatic
  demotion when live results fall outside the expected band.

Plus:

- a coin deep-dive with every data source;
- Telegram alerts (the hook already exists in `scanner.py`);
- a funding desk with multi-venue spreads;
- a portfolio console for the governed book.

Everything is honest about uncertainty and nothing places orders.

## 5. Architecture (v9)

```
  data layer (Actions, every scan)          evidence engine (Actions, daily/weekly)        decision engine
  â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€         â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€        â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  venues: HL, OKX, Gate, Bitget, MEXC,       archive_fetch.py  â”€â”€â–º  md_bn (archive-data)    v8/decision.py + v9 tiers
  HTX, KuCoin, Kraken, dYdX, Aster,          evidence.py       â”€â”€â–º  evidence-results         (TRADE needs a tier:
  Deribit, CoinGecko derivatives             confirm.py (B)    â”€â”€â–º  research/v9/*.json         FULL or PROBATION)
  market: DVOL, F&G, ETF flows,              + new signal studies (phase D)                  governed book only
  stablecoins, DefiLlama OI,                                                                 sizing x tier multiplier
  Coinbase/Korea premium                                                                     â”€â–º decision.json â”€â–º desk
  â†’ data/v9/market.json (phase C)
```

## 6. Roadmap (in order; tick items as they land, with the commit)

### Phase A: evidence engine (survivorship-free)

- [x] A1. Probe every free source from Actions (`probe.yml`, `docs/v9/data-sources.md`).
- [x] A2. Binance archive fetcher, point-in-time universe including delisted coins (`archive_fetch.py`).
  - Only bars with volume count.
  - A gap of more than 7 days splits a coin into separate lives.
  - Non-ASCII tickers are URL-quoted.
- [x] A3. Re-test the 17 4h/daily candidates and the swing score (`evidence.py`), with Phase 9 statistics.
- [ ] A4. Run all census trials (the qgrid grids, 199 or more) on the archive. That gives a complete known-trial
  return matrix, so DSR uses measured across-trial Sharpe variance and PBO covers the known family.
  - [x] A4.1 (`7427b5e`, 2026-10-15, draft PR #30). Validate and pin all 199 trial IDs, expanded parameters, required timeframes and replay code hash. Three tests cover reproduction and corrupted identities/counts/parameters.
  - [x] A4.2 (`d292f0c`, draft PR #30). Implemented `tools/v9/census_replay.py` and the common daily return matrix; synthetic validation exercises all 192 compatible definitions and retains seven missing hourly columns. The fixed protocol is `docs/v9/phase-a4-replay-protocol.md`, committed before any A4 market-data run. Full-family statistics remain unavailable; subset statistics are explicitly diagnostic.
  - [x] A4.3 (`ad2374f`, draft PR #30; verified 2026-10-16). Replayed all 192 4h/daily definitions on phase B's pinned dataset in [run 38777519358](https://github.com/blazebrt/perp-dex-radar/actions/runs/38777519358). Results `18c14932bcc2ba9e8685f231e1725a786869edd9`: 2,670,894 trades, 2,346 daily rows, 199 columns (seven hourly columns explicitly missing). All artifact hashes and every trial/day total independently verified; appended to the hash-chained evidence history. The failed preflight is retained in `research/v9/a4_attempts.jsonl`.
  - [ ] A4.4. Evidence review and fixed assembly specification completed (2026-10-21): `phase-a4-evidence-review.md` and `phase-a4-family-assembly.md`. The pinned 199-column assembly and seven synthetic rejection tests are implemented; independent verification matches all 466,854 cells and hourly metadata. Full validation passed 1,089 tests; the artifact, manifest and independent verification are retained in `research/v9/family_assembly/`. Assembly/reporting is complete; the complete-return objective remains blocked. Seven hourly columns remain unavailable; full-family statistics cannot be calculated. Assembly/reporting completion must not imply complete return evidence.
  - **Dependency correction:** A4 cannot finish before A5. A4.1 discovers seven hourly trials: BTC_LEAD, FAIL_BRK, FUND_CARRY, FUND_FADE, LIQ_FLUSH, PULLBACK and VOL_SPIKE.
  - **Interpretation:** these are new replays of known definitions under a pinned simulator, not recovered historical returns. The unknown historical trial census remains incomplete, even after all known columns are populated. No new promotion authority follows from this inventory.
- [ ] A5. Run the 1h candidates on an hourly archive for the liquid subset (top 150 by point-in-time volume).
  - [x] A5.1 (draft PR #30). Causal daily schedule and pre-acquisition protocol implemented: prior seven complete days, 30-day segment age, $5M/day minimum, deterministic top-150 ties, no current-listing filter. Synthetic tests prove future volume cannot affect a prior selection and relistings cannot inherit age.
  - [x] A5.2 (**conditionally accepted separate research dataset, 2026-10-19**). Original collection and all conflict diagnostics remain unchanged and rejected. Registered reconstruction/quarantine policy applied and independently verified; exact candidate reproduced in run `39274041013` and durably published at `0859e683910a7eea7ef446b27cf9773f33d9e9f8` on `hourly-a5-quality-results`. All 1,386 remote file hashes verified. Coverage: 13,862,226 retained rows across 690 segments; 264 reconstructed hours; 112 quarantined plus 7,026 original missing hours (7,138 unavailable); all 663 zero-trade hours retained; 70 entry-embargo days among 2,345 scheduled days. This is retrospective quality selection, not historically known tradability. Formal conditions and provenance: `phase-a5-quality-acceptance.md`, `research/v9/a5_quality_acceptance.json`. The first registered A5.3 replay and independent verification are now recorded below; complete return evidence remains unavailable.
  - [ ] A5.3. Adapter, synthetic validation, first replay, independent reconciliation and hash-chained record are complete (2026-10-21). All seven trial identities are retained, but FUND_CARRY cannot execute under its causal-quorum disposition and two FUND_FADE segments are unavailable. All seven net series are unavailable due to explicit uncertainty. This acceptance item remains open; no gap fill, zero substitution or definition change is permitted. See `research/v9/a5_replay_verification.json`.
  - A4.4 must disclose the differing hourly top-150 and broad four-hour universes; simply filling seven columns is not a common-universe experiment.
- [ ] A6. Use 50 matched controls per signal (time, liquidity bucket, listing-age bucket; listing age is known from
  the archive) to meet the Phase 9 matched-control gate.
  - [x] A6.1. Fixed diagnostic cohort design and selector implemented with six synthetic tests. Exact time/direction and fixed volume/archive-age buckets; 50 distinct controls without replacement, deterministic outcome-independent ordering, no widening or future information.
  - **Correction:** segment first bar measures archive age, not verified listing inception. Phase 9 also requires eight observed matching dimensions; the three-dimension diagnostic does not satisfy the gate.
  - [x] A6.2. First registered source-bound extraction and independent audit completed and retained (2026-10-23). All 192 four-hour/daily definitions and 4,263,580 in-window ordinals reconcile; 16,168 warm-up signals are separately counted. All original source bindings, 465 shards, 199 trial identities and 670 package files are verified. Seven hourly populations remain explicitly unavailable under the registered scope. Report: `research/v9/a6_result_verification.json`; interpretation: `phase-a6-extraction-review.md`.
  - [ ] A6.3. Execution/inference preregistration is written (2026-10-23): independent hypothetical candidate/control trades, identical four-hour geometry/costs, explicit unknown funding and null net inference, conditional price-only diagnostics with complete missingness counts. The four-hour execution kernel is implemented and synthetically tested. Matching and disk-backed descriptive aggregation are implemented with seven synthetic tests. The source/price adapter is implemented with six synthetic tests. The bound streaming outcome driver is implemented with six synthetic tests. Independent output accounting and pair-arithmetic verification is implemented with seven synthetic tests. Independent snapshot-based selection verification is implemented with five tests. Independent price-path verification is implemented with five tests including 400 seeded direction/path cases. Independent statistics/day/reuse verification is implemented with five tests. The source-bound audit runner is implemented with five integration tests. The reservation-bound retention wrapper and publication contract are implemented with six tests. A6 append-only evidence recording support is implemented with six tests. Resource qualification currently fails: the synthetic probe exposes repeated history reads and large retained records. Execution and independent audit indexing are implemented and synthetically measured (61 source reads each, 1,020 independently checked paths). A lossless compact-record prototype and independent reader reduce synthetic gzip size 24.4%, and are now integrated in the version-two driver and independent package readers/bindings with legacy read support. The full synthetic outcome/audit probe now measures summary/reuse storage and failure retention. Isolated Linux measurements now cover peak RSS and sampled visible scratch at two sizes. Allocated scratch samples and local Git-copy/commit/repack overhead are now measured with disclosed coverage gaps. A source/profile-bound headroom preflight is implemented and integrated before study execution, and all local probes fail it as intended. Retained ancestry verification now requires a reservation-only orphan root, unchanged reservation throughout linear complete history and regular file payloads. Retained successful attempts now require revalidated resource evidence; failed preflight attempts remain recordable. A local single-child commit builder preserves partial payloads without changing refs or the caller index. A remote publication helper is implemented and locally tested for concurrent writes and identical-commit recovery; real hosted publication remains unqualified. Create-only reservation orchestration is implemented with simulated API race/error tests; its authenticated transport is now implemented and simulated end to end, but no workflow is connected. A job coordinator now connects the helpers with fresh capacity before execution and local backup retention on failure; the active workflow remains absent. Input preparation is now staged after reservation verification, with preparation-failure/log retention and preexisting-input refusal. The concrete preparation adapter now binds archive/evidence/signal/source commits, verifies exported blob bytes and accepted evidence/manifest hashes, and preserves failure logs. The guarded runner entry point now wires all components; the inactive integration contract records fixed deadlines, backup and qualification requirements. An inactive manual workflow template now includes reviewed dependency/report bindings and always-run job/bundle backup; final source-pinning and action/runtime qualification are still required. Produce independently reviewed hosted/remote qualification, then finish the durable workflow, then run once, record and reconcile every match/outcome. Full qualification remains unavailable. Hosted synthetic pilot run 40315708480 is complete and verified; its eight small scenarios do not qualify the full study. Session-wide RSS sampling is implemented; it remains sampled diagnostic evidence, not a resource bound. Kernel memory capabilities are inspected without claiming group isolation or per-run peaks. An opt-in fresh-cgroup runner is implemented/tested but not wired to hosted execution.
- [ ] A7. Cross-check on the execution venue: Hyperliquid candles, delisted coins included (56 of 234 perps are
  `isDelisted` and their candles still load). Daily from 2022, 4h for about 830 days.
- [x] A8. Pin the evidence run to a dataset hash and keep the history of evidence runs.
  - `research/v9/evidence_runs.jsonl` holds one record per run: phase A/B, D1, D2, A4 and A5 so far. Each record pins the code
    commit, the dataset digest, the data branches read, the sha256 of the evidence, report and trades files, the
    pre-registration hash and what was confirmed.
  - Records are hash-chained, so an edited or removed record breaks the chain.
  - `tests/test_v9_evidence_runs.py` (in CI) verifies the following:
    - the chain is intact;
    - the phase A/B record is the run the probation tier is bound to;
    - earlier studies retain their phase B binding; A5 pins its separate accepted hourly dataset;
    - no pre-registration document changed after its run.
  - After every new evidence run, append its record with `python tools/v9/record_run.py --study <A/B|D1|D2|A4|A5>`. Fetch the
    results branch first.

### Phase B: evidence tiers, the first governed trades (next session's main task)

Probation gate, per (strategy, side). All of these must hold on archive evidence:

- (a) The definition was fixed before the holdout was examined. This is true for the three runtime strategies.
- (b) Holdout mean R > 0, Holm-adjusted one-sided p < 0.05 over all side-hypotheses submitted.
- (c) Design-window mean R > 0, one-sided p < 0.10 (consistent, not contradicted).
- (d) The most recent third has mean R > 0.
- (e) Cost stress Ã—1.5 keeps mean R > 0.
- (f) The edge over the random twin is positive.
- (g) The Phase 9 concentration limits hold.
- (h) At least 500 trades in total and 100 in the holdout.

Added on 2026-10-14, before the evidence run that first measures them (`evidence.py` v9.archive-evidence/2,
`runtime_robustness`):

- (i) Deployable universe. The live desk ranks about 80 coins, while the archive ranks every eligible Binance perp.
  On a point-in-time proxy (the 80 eligible coins with the largest trailing 7-day volume at each bar), the side's mean
  R must be > 0 in both the holdout and the design window.
- (j) Late entry. A daily signal stays on the desk for up to a day, so a trader may enter hours after the open the
  backtest assumes. The same signals entered 4h, 8h, 12h and 24h late are tested. A delay passes when the side's mean
  R over all windows is > 0 and its holdout mean R is > 0.
  - The probation TRADE window is the longest tested delay such that it and every shorter tested delay pass. After
    the window, the signal is WATCH (`PROBATION_ENTRY_WINDOW_PASSED`).
  - If the 4h delay fails, the side is not confirmed.

Result (evidence run `fd03198`, `tools/v9/confirm.py`):

- **XSMOM long is CONFIRMED on every check (a)â€“(j).**
  - Top-80 universe: +0.19R in the holdout, +0.21R in the design window.
  - Entered 4h, 8h, 12h or 24h late: +0.18R to +0.20R, so the TRADE window is 24h.
- Every other side is NOT_CONFIRMED.

- [x] B1 (`59faf14`). `tools/v9/confirm.py` writes `research/v9/probation_evidence.json`. It is hash-bound to the archive dataset
  hash, the research code hash and `runtime_implementation_hash`, and carries per-hypothesis statistics and verdicts.
- [x] B2 (`ac74168`, record 2 `V9-PROBATION-XSMOM-LONG-1`, evaluation from 2026-10-15 00:00 UTC). Register the
  forward test in the shadow ledger (`v8/shadow_ledger.py`) **before** any probation trade.
  Primary metric: live net R of probation trades. Demotion rule: after 30 or more trades, demote if the live mean R
  falls below the archive's 5th-percentile band (bootstrap); promotion to full after the Phase 9 gate's 180 days.
- [x] B3 (`dada154`). Policy changes:
  - `quant_strategy_policy.json`: XSMOM becomes `ACTIVE_PROBATION` / `PROBATION`, with `probation: {sides: ["long"],
    risk_multiplier: 0.5, evidence, evidence_hash}`.
  - `v8/strategy_policy.py` validates it fail-closed: the evidence file must exist, its hash must match, its verdict
    must be CONFIRMED, and the runtime hash must be equal.
- [x] B4 (`dada154`). Decision engine (also: ENTERED signals, `strategy_tiers`, the unconfirmed side is not emerging
  evidence):
  - `decision_policy.json` gains `probation_deployment_states` and `probation_research_states`.
  - The `v8/decision.py` STRATEGY_AUTHORITY gate passes with `tier: PROBATION` for a confirmed side, and caps the
    other side at WATCH (`STRATEGY_SIDE_NOT_CONFIRMED`).
  - PROPOSED_TRADE risk becomes `risk_per_trade Ã— risk_multiplier`.
  - Candidates carry `authority_tier`.
- [x] B5 (`dada154`). Governed book:
  - The Phase 10 gates evaluate only the positions of trade-authorized strategy sides.
  - The legacy-holdover positions stay visible as a "legacy diagnostic book" on Portfolio.
  - Keep the audit binding consistent: compare full-book states for consistency, and gate on the governed book.
- [x] B6 (`dada154`). Desk:
  - The TRADE card shows a probation tag, the engine's plan, the archive expectation and the forward test.
  - Today names the authorized sides, and Portfolio separates the governed book from the legacy paper book.
  - The Research page and its publication logic are pinned by the owner's PR #24 scope test, so they were left
    unchanged. Showing the tiers there is a follow-up (F4).
- [x] B7 (`dada154`; `tests/test_v9_decision.py`, `tests/test_v9_scope.py`, v9b golden and manifest). Tests:
  - New invariants: only ACTIVE_REQUALIFIED/REQUALIFIED or ACTIVE_PROBATION/PROBATION can TRADE.
  - Probation requires a bound CONFIRMED record.
  - The unconfirmed side is WATCH.
  - Size is halved.
  - The governed book excludes holdovers.
  - Update the Phase 9, 10, 11 and 12 tests and goldens, with a delta manifest that pins the decision changes.
- [x] B8. Live check, after the 2026-10-15 00:00 UTC close (Research run 38661431562 on `45e387a`, the same tree
  as `main` `f58c058`; results `ee107d4` on the `research` branch).
  - Every mandatory step passed. The forward test is in effect.
  - The close produced fresh signals, all shorts:
    - XSMOM short on ETH, SOL and XLM: WATCH with `STRATEGY_SIDE_NOT_CONFIRMED`, as designed;
    - five TSMOM and TREND_EMA shorts: WATCH with `STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT`;
    - one TREND_EMA short: AVOID for an economic-exposure conflict.
  - Nothing became TRADE (24 WATCH, 336 AVOID). The governed book was WITHIN_LIMITS while the legacy paper book was
    LIMIT_BREACHED, which is diagnostic only.
  - quant.py emitted **no XSMOM long signal** at this close, so the live TRADE path has not fired yet. At the
    previous close the cause was that all top-5 coins needed stops wider than 20% (the archive's rule). The path is
    covered by `tests/test_v9_decision.py`, and the first live one will show on Today, in the journal and in the
    alerts.
  - Next session: on the first close with an XSMOM long signal, confirm it is TRADE, tier PROBATION, at 0.5Ã— size.
- [ ] B9. Known follow-ups:
  - TREND_EMA has no edge in the archive. A reviewed policy change could mark it REJECTED (AVOID).
  - Legacy WATCH signals still feed Emerging.
  - Forward-test trades count as "qualified" only when the journal has execution and funding proof (see
    `quant.py` `qualified_trade`). The demotion rule uses every closed trade.
  - XSMOM long only fires when a top-5 coin's stop fits within 20%. On volatile days there is honestly no trade. More
    trades must come from more confirmed strategies (phase D), never from loosening this rule after the fact.

### Phase C: live multi-venue data layer

- [x] C1 (`v9/market.py`, branch `v9/market-data`). Hyperliquid funding, OI and premium; Binance and Bybit funding
  through Hyperliquid's predicted-funding feed; Gate OI, long/short ratios and liquidations for the 30 most traded
  coins. The rest of this item's list is left for C1b. The Scan workflow runs it on every scan and publishes
  `data/v9/market.json`, context only:
  - funding from HL, OKX, Gate, Bitget, MEXC, dYdX, Kraken and Bitfinex, plus CoinGecko derivatives for
    Binance/Bybit values;
  - OI (OKX, Gate, Bitget, HTX, HL);
  - long/short ratios (OKX, Gate, Bitget, HTX);
  - liquidations (OKX, Gate public orders);
  - basis / premium (HL `metaAndAssetCtxs`).
- [x] C2 (`v9/market.py`). Deribit DVOL, Fear & Greed, stablecoin supply, Coinbase and Korea premiums, Bitfinex BTC
  margin, CoinGecko global and Farside ETF flows. Options summary and Upbit listings remain open. Market regime
  inputs:
  - Deribit DVOL and options summary;
  - alternative.me Fear & Greed;
  - Farside ETF flows (HTML table);
  - DefiLlama stablecoin supply and OI;
  - CoinGecko global;
  - Coinbase premium (Coinbase versus `data-api.binance.vision` spot);
  - Korea premium (Upbit/Bithumb plus FX);
  - Upbit new KRW listings.
- [x] C3 (`v9-market-history`, one record per UTC hour from the first scan after the market branch is merged). An
  append-only history of C1 and C2 on a data branch, so that forward history accumulates from day one (each record
  keeps the source and fetch time).
- [x] F2 (first version): Today's "Market context" panel and the Analyzer's per-coin market context (`desk.js`
  `views.market` / `views.marketAsset`).
- [ ] C4. Optional keys (owner action, free): `COINALYZE_API_KEY` (aggregated liquidation, OI and funding history),
  `CRYPTOPANIC_API_KEY`, `FRED_API_KEY`. The probe already checks for them.

### Phase D: signal research on the new data (each through the evidence engine; only survivors become strategies)

How every phase D study runs (D1 set the pattern):

1. Write the definitions and a pre-registration document, and commit them **before** any run on market data.
   Synthetic-archive checks are allowed; they test mechanics, not hypotheses.
2. Test once, with phase B's gate (b)â€“(j), and a Holm family per study.
3. Record the result as is. A confirmed side is a probation candidate: it still needs a runtime implementation,
   re-bound evidence, a forward-test registration and the owner's merge. A failed side is never adjusted; a changed
   definition is a new hypothesis with a new name.
4. Use names that do not collide with the legacy catalogue (`tools/research/qstrat.py`, `qexport.py`).

- [x] D1 (`8ca3f55`; result `03e596f` on `evidence-d1-results`). Funding crowding and taker flow, cross-sectional,
  on data the archive already holds: XS_FUND_FADE and XS_FLOW_MOM.
  - Pre-registered in `docs/v9/phase-d1-preregistration.md`, committed before any run on market data.
  - Code: `tools/v9/d1.py`, `tools/v9/evidence_d1.py`, `tests/test_v9_d1.py` (rankings and no look-ahead).
  - Tested once by `evidence_d1.yml` on the `archive-data` dataset: digest `cd4651ebâ€¦`, the same as phase B's.
  - **Result: no side is confirmed. Nothing deploys, and no definition will be changed.**

  | Side | Trades | Holdout R (Holm p) | Design window R (p) | Fails |
  |---|---|---|---|---|
  | XS_FUND_FADE long | 916 | +0.064 (0.30) | âˆ’0.020 (0.61) | b, c, d, f |
  | XS_FUND_FADE short | 871 | âˆ’0.071 (0.99) | âˆ’0.164 (1.00) | b, c, d, e, f, g, i, j |
  | XS_FLOW_MOM long | 2715 | +0.042 (0.20; raw p 0.050) | +0.010 (0.34) | b, c |
  | XS_FLOW_MOM short | 2116 | +0.001 (0.95) | âˆ’0.040 (0.98) | b, c, d, e, g, i, j |

  - Shorting the coins whose longs paid the most funding lost money in both windows: crowded longs kept rising more
    often than they unwound. That is an observation, not a tested hypothesis. Going long those coins would also pay
    the highest funding.
  - XS_FLOW_MOM long is positive in every window, at a 1.5Ã— cost stress (+0.013R) and against its random twin
    (+0.081R), but too small to be significant. It is not a strategy. It may be worth recording forward, since the
    live data exists (D1b).
- [ ] D1b (optional). A forward-only record of XS_FLOW_MOM long, registered in the shadow ledger before its first
  observation, with no decision authority. It would need the live 4h candles to carry taker-buy volume, which
  quant.py's candles may not; check that first.
- [x] D2 (pre-registered in `aa6f75a`; result `950d75d` on `evidence-d2-results`). Binance positioning: XS_TOP_DIV
  (follow the top traders where they disagree with the crowd) and XS_CROWD_FADE (fade the crowd's own long/short
  ratio). Both use a one-day lag, because a live desk can only read the previous day's file.
  - Data: `tools/v9/metrics_fetch.py` (`6d088bf`) through `metrics.yml` to `archive-metrics`: 532,738 daily files and
    778 coins, with none failed, in 2.7 hours. The metrics start in 2020-09. The survey and log are on
    `metrics-results`.
  - Order of events: the download finished at 18:37 UTC and the pre-registration was committed at 18:40, with nothing
    from the dataset fetched or read. The study ran once, at 18:41, triggered by that commit. The document's line
    "its download was still running" was true when written, not at commit time. The document is left unedited because
    its hash is in the result.
  - It used the same candles and funding as phase B (digest `cd4651ebâ€¦`). Signal coverage was 79% / 89% of eligible
    coin-days, from 2020-09-04.
  - **Result: no side is confirmed. Nothing deploys, and no definition will be changed.**

  | Side | Trades | Holdout R (Holm p) | Design window R (p) | Fails |
  |---|---|---|---|---|
  | XS_TOP_DIV long | 1069 | +0.025 (0.49) | âˆ’0.032 (0.86) | b, c, e, f, g, i, j |
  | XS_TOP_DIV short | 1282 | âˆ’0.021 (0.88) | âˆ’0.093 (1.00) | b, c, d, e, f, g, i, j |
  | XS_CROWD_FADE long | 1050 | +0.041 (0.16; raw p 0.039) | âˆ’0.005 (0.57) | b, c, d, f, i |
  | XS_CROWD_FADE short | 1373 | +0.004 (0.88) | âˆ’0.019 (0.79) | b, c, e, f, g, i, j |

  - Neither definition shows an edge after costs in either window. The legacy picks used these ratios as score inputs;
    as daily rotations on survivorship-free data, they do not hold up. Open interest and the taker ratio are in the
    dataset but were not part of this study.
- [ ] D3. The legacy 1-hour funding strategies, FUND_FADE (absolute thresholds) and FUND_CARRY. They need hourly
  candles, so they wait for A5's hourly archive.
- [ ] D4. Basis / premium (archive `premiumIndexKlines`).
- [ ] D5. Regime filters for the confirmed strategies: BTC trend, DVOL, ETF flows, stablecoin growth, Fear & Greed.
  Report each as a conditional result, never tuned in-sample without a holdout.
- [ ] D6. Listing effects: Binance and Upbit new listings (archive first bar = listing time).
- [x] D7 (answered by the phase A numbers; nothing to run). Swing-score short side, 80+, one trade per coin at a
  time: holdout +0.069R with a one-sided p of 0.099 before any correction (2167 trades), design window +0.148R. It
  fails check (b), holdout Holm p < 0.05, on its face. The design window is where the score was built, so it cannot
  rescue it. Not a candidate.

### Phase E: decision engine v2

- [ ] E1. Rank TRADE candidates by expected net R with intervals, calibrated from the evidence engine. No opaque
  scores.
- [ ] E2. Size by tier and volatility (risk parity across open trades), within the Phase 10 limits.
- [ ] E3. Regime-aware gating from D5, only where it is confirmed.
- [x] E4. Monitor live tiers against archive expectation and demote automatically (B2's rule, then generalised).
  - Every scan, the engine evaluates each probation side's live forward test against its archive demotion band
    (`strategy_tiers`, `_forward_test`). A side below the band is capped at WATCH automatically
    (`PROBATION_FORWARD_TEST_FAILED`).
  - Today's "Authorized to trade" note shows the live record against the band on every scan, signal or not, e.g.
    "live forward test: 40 closed, mean +0.20R, demoted below â€¦R at 30 trades". TRADE cards show the same.
  - "Generalised": the rule applies to every probation side that is registered. A full-tier (ACTIVE_REQUALIFIED)
    side is governed by Phase 9's requalification, which carries its own 180-day prospective registration. No
    full-tier side exists today.

### Phase F: product UX

- [x] F1. Rich TRADE card: entry zone, stop, trailing rule, time stop, size for the user's account (settings stored
  locally), expected R with interval, tier, and its live record.
  - The tier, the expected R with its interval and the live forward test came with B6.
  - The engine's plan shows: entry near the mark, inside the entry window that the late-entry checks confirmed (the
    entry zone); stop; risk; size on the page account.
  - The time exit, "exit at the stop or 14 days after you enter" (`6dfc56b`), and the trailing stop when the signal
    has one (`trailing_stop_pct`).
  - The plan in the trader's own dollars, from the account size saved in the Analyzer: a labelled unit conversion of
    the same fractions.
  - Shown on the desk, in the Analyzer's governed card (exits only, as the owner's exact-proposal rule keeps that card
    fixed) and in the alerts.
- [x] F2 (first version; see phase C). Market board on Today: regime, funding and OI heatmap, liquidations, flows.
  Today's Market context panel shows the regime inputs, funding extremes, liquidations and flows. A funding/OI
  heatmap was not built.
- [ ] F3. Coin deep-dive in the Analyzer, with every data source (context clearly labelled).
- [ ] F4. Performance ledger page: every tier's live trades against expectation.
- [x] F5 (`v9/alerts.py`, branch `v9/market-data`). A Telegram and/or Discord message for every new TRADE decision,
  with the engine's plan and the valid-until time. The owner adds the secrets `TELEGRAM_BOT_TOKEN` +
  `TELEGRAM_CHAT_ID` and/or `DISCORD_WEBHOOK_URL`; without them nothing is sent.

### Phase G: quality and operations

- [ ] G1. Freshness monitors and failure alerts for every source.
- [ ] G2. Keep the published artifacts small (gzip, compact JSON); trim the 9.8 MB audit or load it lazily.
- [x] G3. CI covers every v9 module; parity manifests for every published change.
  - Every module in `v9/` and `tools/v9/` has tests in CI:
    - main job: market, alerts, metrics_fetch, record_run (`test_v9_evidence_runs`), and register_forward_test with
      the probe tools (`test_v9_tools`);
    - research-checks job (numba): evidence and archive_fetch (`test_v9_evidence`), d1, d2, and confirm with the D1
      and D2 runners (`test_v9_research_tools`).
  - `test_v9_tools` proves the committed forward-test registration is exactly what the tool computes from the bound
    evidence, and that a probe never keeps an API key.
  - `test_v9_research_tools` checks the gate statistics (Holm, clustering, concentration, demotion band, every check
    (b)â€“(j)) on hand-checked values.
  - Every published change (desk.js, desk.css, analyze.js, analyze.html, quant.html, index.html and four quant.json
    leaves) is pinned in `v9b_expected_deltas.json`, and CI proves differential parity against main.

## 7. Owner actions (only these need you)

- Trade alerts (optional): add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, and/or `DISCORD_WEBHOOK_URL`, as
  repository secrets. Create the bot with Telegram's @BotFather and get your chat id from the bot's getUpdates.
- Optional, free API keys, added under GitHub repository Settings â†’ Secrets â†’ Actions:
  - `COINALYZE_API_KEY`: the best free liquidation history. Sign up at coinalyze.net, then API key.
  - `CRYPTOPANIC_API_KEY`: news.
  - `FRED_API_KEY`: macro.
- Nothing to merge. Watch the first XSMOM long TRADE: it appears only when a top-ranked coin's stop fits within 20%
  at a 00:00 UTC close. The alerts tell you when it does, once the secrets are in.
- No login-only sites are needed. Every source used is a public API or public page.

## 8. Session log

- **2026-10-14 (session 1 of v9).**
  - Probed 102 data sources from Actions.
  - Built the survivorship-free archive (900 USDT perpetual symbols, 781 research coins) and the evidence engine.
  - First results: XSMOM long confirmed out of sample; most legacy claims (TREND_EMA, the swing long score) do not
    survive. Diagnosis written.
  - Plan and this handover. Tests in `tests/test_v9_evidence.py`.
- **2026-10-14 (session 2 of v9): phase B.**
  - Merged main (PR #24 with the owner's accuracy fixes) into v9.
  - Evidence /2 added the pre-registered deployable-universe and late-entry checks (`fd03198`).
  - `confirm.py`: XSMOM long CONFIRMED, everything else not (`59faf14`).
  - Forward test registered in the ledger (`ac74168`).
  - Probation tier, governed book, entered signals, desk presentation, tests and parity (`dada154`).
  - Next: B8 after the 2026-10-15 00:00 UTC close, then phase C.
- **2026-10-14 (session 3 of v9): phases C and D1.**
  - Phase C on `v9/market-data` (draft PR #26): `v9/market.py` collects 16 free sources from Actions into
    `data/v9/market.json`, with an hourly append-only history. Today and the Analyzer show it as context only
    (`281776e`). Fixed after the first live run: live tickers for the Coinbase premium, funding extremes relative to
    the median, no partial ETF day (`9050bd8`).
  - F5: Telegram/Discord alerts on new TRADE decisions (`f0a4316`). They need the owner's secrets.
  - Phase D1 on `v9/research-d1`: two strategies pre-registered and committed before any market-data run
    (`8ca3f55`), then tested once on the phase B dataset. Neither is confirmed; the result is recorded as is.
    `FUND_FADE` was renamed `XS_FUND_FADE` before the commit, because the legacy catalogue already has a different
    FUND_FADE.
  - Phase D renumbered: D1 is this study, the Binance metrics study is D2, and the legacy hourly funding strategies
    are D3.
  - Every TRADE plan now states the strategy's time exit (`6dfc56b` on #25, merged up the stack). XSMOM's archive
    results assume it, and the governed Analyzer card had dropped it, where the legacy Analyzer always showed it.
  - D2: Binance metrics fetched (532,738 files) and two positioning strategies pre-registered and tested once. Neither
    is confirmed (see the D2 item).
  - D7 needs no run: it already fails the gate's holdout check on phase A's numbers.
  - The owner's instruction (2026-10-15 00:05 IST): do not start the 17 untouched items; finish the ones in progress,
    test, merge everything, then deliver the updated handover. Done that night:
    - A8: the evidence run history (`313e1eb`);
    - F1: the trailing stop and the plan in the trader's own account (`bc65436`);
    - G3: tests for every v9 module, including the gate statistics and the study runners;
    - E4: the forward test on Today every scan (`3fa4c91`);
    - D2 and D7, recorded above.
  - Tested on head `3fa4c91`: the full suite, CI on push and on the pull request, and live Research run 38621408999
    (every mandatory step green; four XSMOM shorts WATCH `STRATEGY_SIDE_NOT_CONFIRMED`, no XSMOM long signal yet).
  - PR #28 (`v9/research-d1` â†’ `main`) carries #25, #26 and #27. The first merge API call was blocked by the session's
    automatic safety check; the owner then asked for the merge explicitly and it went through.
  - B8 ran after the 2026-10-15 00:00 UTC close (see below and the B8 item).
  - Merged at the owner's request (2026-10-15 01:35 IST): PR #28 into `main` as merge commit `f58c058`. #25 to #27
    closed. A Scan on `main` published the v9 desk; CI on `main` is green.
  - B8 after the 00:00 UTC close: the gates behave as designed live, nothing became TRADE, and there was no XSMOM long
    signal at that close (see B8).

- **2026-10-15 (Codex continuation): A4 inventory.**
  - Started from main `0953535` on `v9/census-evidence`; read CLAUDE.md and the three A/B, D1 and D2 result reports.
  - Completed A4.1 (`7427b5e`, draft PR #30): deterministic, fail-closed inventory of all 199 known definitions and the seven-trial dependency on A5. The plan retains historical and replay code identities separately.
  - A4 remains IN PROGRESS. No new market-data evidence run, strategy promotion, merge or deployment has occurred.
  - Next: A4.2 runner and synthetic validation, then A4.3; A5 is required before A4.4. All other unchecked roadmap items remain open.
  - Validation on `7427b5e`: focused inventory tests pass; push CI [38709165498](https://github.com/blazebrt/perp-dex-radar/actions/runs/38709165498) and PR CI [38709216458](https://github.com/blazebrt/perp-dex-radar/actions/runs/38709216458) both pass, including research, no-edge, parity and desk checks. The dependency-enabled local Linux full suite also passes: 976 tests, no skips. The Windows full run (962 tests) encountered path-separator, CSV-newline and parity failures; CI runs on Linux.

- **2026-10-15 (Codex continuation): A4 replay runner.**
  - A4.2 implemented on the existing draft PR #30. Requires the exact phase B evidence binding and matching archive digest, validates the replay plan, streams trial-tagged trades, preserves all 199 columns, and writes the final evidence document only on success.
  - Synthetic end-to-end validation runs all 192 compatible definitions, reconciles saved trades with the daily matrix, checks artifact hashes, and tests dataset/plan mismatch, invalid returns, interrupted execution and missing-column handling. No production signals or evidence bindings changed.
  - A4.3 remains pending: wire the Actions run, record every result in the evidence history and review it. A5 hourly data remains required for A4.4. No market-data replay, merge or deployment has occurred in this continuation.
  - Follow-on A4.3 work: added a research-only Actions job pinned to archive `4828a2d` and evidence `e4c0f0d`. Trade artifacts are stored per trial, with a verified hash manifest. The recording tool now supports A4 and rejects corrupted trade shards or matrices. Full-suite validation is required before launching the job.
  - A4.3 attempt 1, Actions run `38775986212` on `b432a65`, stopped BEFORE any trial at the dataset digest check; failure result commit `9b6eb1e3e6968b63655eec38d45cacf68a2bf02b`. Cause: the runner hashed before constructing features; phase B hashes after feature construction, whose resampling updates partial-day panel views. Correcting the order to phase B's existing order, with a partial-day regression fixture; no definition, parameter, cost or protocol change. Retry pending validation.

- **2026-10-16 (Codex continuation): A4.3 verified and recorded.**
  - Run `38777519358` succeeded on `ad2374fa4d25f03c204ce7c0cdbecac95cba6246`; result commit `18c14932bcc2ba9e8685f231e1725a786869edd9`. The partial-day fingerprint correction matches phase B's construction order and passed the new regression test. No strategy definition, cost, parameter or pre-registered protocol changed.
  - Independently read all 192 trade shards (2,670,894 rows), verified their hashes, and reconciled every daily return against the 2,346-by-199 matrix. All seven hourly columns remain NaN. Recorded the successful run using `record_run.py --study A4`; both attempts remain visible.
  - Diagnostic 192-trial subset only: across-trial Sharpe variance 0.0004801958204680863; PBO 0.17622377622377622; White reality-check p=0.41831633673265345; Hansen SPA p=0.12297540491901619. Full-family statistics remain unavailable. No new strategy is confirmed, and unknown historical trials remain unknown.
  - Validation of replay code: 983 dependency-enabled Linux tests pass without skips; push CI `38777519267` and PR CI `38777526986` pass. This records successful reproduction, not independent review of the strategy's economic validity.
  - Next unblocked roadmap item: A5 hourly archive with point-in-time liquid-universe selection, then A4.4's seven hourly trials and complete known-family matrix. All other unchecked items remain open. PR #30 stays draft and unmerged; no production deployment.

- **2026-10-16 (Codex continuation): A5 causal universe and collector.**
  - Implemented a daily top-150 schedule using only the preceding seven complete days from pinned archive `4828a2d`, including delisted segments. It keeps the original listing clock for each relisting, rejects malformed input and missing source files, and retains empty days.
  - Implemented hourly monthly-file collection for the ever-selected union plus BTC context. Strict row validation and hourly-to-four-hour OHLC/volume reconciliation fail closed; missing hours are explicitly counted. Funding bytes are copied from the pinned archive. Every input/output is hashed, and only a final manifest indicates completed collection.
  - Fourteen synthetic tests pass, covering causality, ties, gaps, relistings, bad rows, missing months, changed plans, aggregation disagreement, artifact hashes and deterministic output. Full regression validation precedes the acquisition commit; no hourly market data has been read at this point.
  - Next: A5.2 acquisition and independent dataset verification, then A5.3 hourly adapter/replay and A4.4 family assembly. A5 remains open; no production authority changes.

- **2026-10-16: A5 acquisition attempt 1 and correction.**
  - Committed the protocol and collector as `8ffb61d` after all 997 Linux tests passed. Run `38871226842` built 2,345 daily selections covering 690 distinct segments, then stopped at an hourly/four-hour opening-price mismatch. Partial results `149da2f8d5e5fc796fcb6060cc0ce8b9b4200df5` have no completion manifest; the attempt is retained in `research/v9/a5_attempts.jsonl`.
  - Direct inspection of the specific 1000BONK source files showed a zero-trade hour with a carried price. Exchange four-hour OHLC starts with the first actual trade. The collector now aggregates prices from traded hours while retaining zero-trade observations and the same strict tolerance. `phase-a5-hourly-aggregation.md` records exact source hashes and the correction; the original protocol is unchanged.
  - Fifteen focused tests pass, including no-trade-hour regression coverage. Full regression validation and retry are next. A5.2 and A5.3 remain open; no strategy simulation or promotion occurred.

- **2026-10-16: A5 provider inconsistency and diagnostic audit.**
  - Correction `d0c4a35` passed all 998 tests; retry `38902486359` passed the earlier 1000BONK issue, then failed on 1000SHIB volume at timestamp `1657944000`. Partial results `30674ea2e5f5f876a214f6ce4461a1799a56d487` remain unaccepted; attempt 2 is recorded.
  - Independently checked the relevant pinned four-hour file and current 1m, 1h and 4h source ZIPs. All 240 minute rows exactly reproduce the four hourly rows, while the provider's four-hour row has extra quote volume and 13 extra trades. This cannot be explained by rounding. Exact values and hashes are in `docs/v9/phase-a5-data-conflicts.md`.
  - The collector now gathers all numerical conflicts in one diagnostic run, retains raw hourly data and hashes, and writes only a rejected-data manifest if any conflict exists. It still exits with failure and never emits an accepted completion marker. Sixteen focused tests pass; full validation precedes the audit run.
  - A5.2 stays incomplete. Next: quantify all conflicts and affected ranking windows before specifying a defensible dataset correction or exclusion protocol; then A5.3 and A4.4. No disputed data is used for strategy qualification.

- **2026-10-17 (Codex continuation): A5 source audit verified.**
  - Run `38903923119` on `34ec1d328034bd2a5cff7322fe14bbe8db4f0f80` deliberately failed acceptance on 189 source-field conflicts; diagnostics were successfully saved at `003ddccc825b5aeaec1beab834c56f21b8baa9a8`. Only a rejected manifest exists. Attempt 3 and the compact independent verification are recorded in `research/v9/`.
  - Independently verified every artifact hash, 13,862,338 hourly rows and coverage, 2,345 daily selection schedules, and recomputed recorded hourly conflict values. There are 94 disputed four-hour blocks across 87 segments, 7,026 missing hours and 663 zero-trade hours. Potential ranking exposure: 630 coin/day windows across 63 days; actual selection changes have not been measured.
  - Trade-level investigation of the SHIB case supports the four-hour source: minute/hourly data omit 13 records relative to the daily tape and have an incorrect hourly close. The tape itself has one ID gap, so it does not prove complete transaction coverage. Repair cannot assume finer candles are authoritative or change only volumes.
  - Validation: 999 Linux tests pass without skips; source commit push CI `38903923108` and PR CI `38903933467` pass. The audit verifies stored artifacts and structure, not every provider transaction.
  - Completed: A5.1 and diagnostic acquisition/audit. Remaining: pre-registered repair/exclusion and gap protocol, accepted A5.2 dataset, A5.3 seven hourly replays, A4.4 family assembly. All other unchecked roadmap steps remain open. PR #30 remains draft; no merge, promotion or production deployment.

- **2026-10-17 (Codex continuation): A5 trade-reconstruction diagnostics.**
  - Added `phase-a5-trade-reconstruction.md` as an additive protocol before running the new tool on market data. Scope is all 94 disputed blocks; the previous SHIB inspection is explicitly prior knowledge. Original protocols and data are unchanged.
  - Implemented offline `tools/v9/hourly_trades.py`: verifies provider checksum and UTC day, rejects malformed/out-of-order records, reconstructs every hourly OHLC/volume field with decimal arithmetic, reports missing hours and ID gaps, and compares all six four-hour fields against the pinned source. Requires bracketing trades and contiguous IDs before claiming local continuity. Matching aggregates remain diagnostic, never accepted data.
  - Eight synthetic tests pass, including hour boundaries, buyer/taker direction, ID gaps, missing hours, timestamp precision, tiny prices, corrupt checksums and immutable output/source files. Full regression validation precedes publication and market-data application.
  - Remaining: apply the committed diagnostic to all 94 blocks, review unresolved continuity/source conflicts, specify dataset replacement/exclusion and gap execution policy, verify accepted A5.2 data, then A5.3 and A4.4. No strategy trial or production change occurred.

- **2026-10-17 (Codex continuation): all-block trade diagnostic complete and verified.**
  - Protocol and offline tool committed as `2bf7eac01150f62ce75648df668eb3f9b6c77260` before application. All 1,007 Linux tests passed; push CI `38957686288` and PR CI `38957693308` passed.
  - Examined all 94 disputed blocks using 94 checksummed daily trade files (64,523,776 records scanned), with no acquisition or parsing failures. Independently recomputed all 376 hourly candidates and checked all 378 artifact hashes. Full diagnostic values and provenance are recorded in `research/v9/a5_trade_diagnostics.json`; downloaded sources remain in the local `outputs/a5-trade-diagnostics/` folder.
  - Fifty blocks match the pinned four-hour aggregate; 70 pass local ID-continuity and bracketing checks; 40 pass both. Forty-four have aggregate disagreements. Twenty have ID gaps and five lack boundary brackets, with one overlapping (24 continuity limitations). No requested candidate hour is empty. These checks do not establish complete provider transaction history or accept a dataset.
  - Exploratory ALGO precision check: summing rounded `quote_qty` gives 5326605.1193, while decimal price-times-quantity gives 5326605.75953, matching pinned 5326605.76 within the unchanged tolerance. This was discovered after the diagnostic protocol and is recorded separately; no first-pass result was altered. Price disagreements also remain (including BTC and EOS), so precision correction alone cannot settle acceptance.
  - Next: separately register and test dual quote-precision diagnostics, then address missing-ID/boundary and price conflicts before any replacement/exclusion policy and gap-aware replay. A5.2 acceptance, A5.3 and A4.4 remain open. No strategy trial, promotion, merge or deployment occurred.

- **2026-10-17 (Codex continuation): dual quote-precision diagnostic implementation.**
  - Added a separate `phase-a5-quote-precision.md` protocol and `tools/v9/hourly_quote_precision.py`. The original trade tool, protocol and first-pass report remain unchanged. The new runner binds the exact prior record and all 94 objects, reproduces published quote totals and counts, and separately reports decimal price-times-quantity volumes under the unchanged tolerance.
  - Preserves price conflicts, ID gaps and boundary limitations even when product volumes match. Streams trades with bounded accumulation memory; never accepts data or changes source candles. Eight focused tests pass, including completed and failed batch retention, corrupt inputs, empty hours and precision differences. Full-suite validation precedes publication and market-data application.
  - Next: apply the committed diagnostic once to all saved objects and independently verify it; then resolve remaining source/boundary issues and specify the dataset replacement/exclusion and gap policy. A5.2 acceptance, A5.3 and A4.4 remain incomplete.

- **2026-10-17 (Codex continuation): dual quote-precision diagnostic verified.**
  - Protocol/tool committed as `0de60555c04f3b1208dff676634d5c8651539975` before application. Applied once to all 94 original saved objects; every published quote sum and trade count reproduced. All 1,015 Linux tests pass; source-commit CI `38999580764` and `38999578499` pass. A test-fixture checksum was subsequently made independent of ZIP creation time; focused tests pass.
  - Exact rational-arithmetic verification reproduces all 376 hourly published/product volumes and differing-quote counts. Independently checked every aggregate comparison against the original reference and confirmed price/continuity limitations remain unchanged. Complete values, hashes and verification are in `research/v9/a5_quote_precision.json`.
  - Product volumes explain 29 earlier mismatches: 79 blocks now match the pinned aggregate (previously 50), with no prior matches lost. Sixty-six also pass local continuity (previously 40). Fifteen blocks still disagree, including five with price disagreements; 24 continuity limitations remain and overlap those categories. The 2,530,674 differing quote records are within the requested blocks, not a count across the entire daily tape.
  - Completed: separate precision diagnostic and independent verification. Still remaining: 15 source disagreements, 20 ID-gap blocks and five missing boundary brackets (one overlaps), explicit repair/exclusion and missing-hour execution policy, accepted A5.2 dataset, A5.3 replay, A4.4 family assembly. All earlier diagnostics remain unchanged; no data substitution, strategy trial, promotion, merge or deployment occurred.

- **2026-10-17 (Codex continuation): adjacent-day continuity diagnostic implementation.**
  - Added `phase-a5-boundary-continuity.md` and `tools/v9/hourly_boundary.py` for the five unbracketed blocks. The diagnostic reproduces original counts/gaps, checks only the immediately adjacent UTC day with checksummed same-symbol data, and preserves internal ID gaps. Existing source discrepancies and original reports are unchanged.
  - Six synthetic tests pass: both day edges, retained internal gaps, new boundary gaps, duplicate/overlapping IDs, wrong symbols/dates/checksums, changed original diagnostics, and empty/malformed adjacent data. Full validation precedes publication and market-data application.
  - Next: apply the committed diagnostic to all five cases, verify the boundary records independently, then record what remains unresolved. This cannot accept a dataset or settle the 15 aggregate disagreements or 20 existing ID-gap blocks.

- **2026-10-17 (Codex continuation): adjacent-day continuity verified.**
  - Protocol/tool committed as `a648ab08dd3032fe46fba280534cfd7fdb64833b` before acquiring three additional public daily files; two previously saved XRP objects were reused only after hash verification. All five requested diagnostics completed without failures. Regression validation: 1,021 Linux tests pass.
  - Independent CSV-level verification reproduced boundary IDs/timestamps, record counts, internal/join gap ranges and artifact hashes for every case. All five missing brackets now have valid adjacent-day records. ALPHA, EOS and both XRP blocks gain local continuity passes; TRUMP retains its original 137 internal ID-gap ranges. No new join gap appears and no original gap was removed.
  - Across the 94 disputed blocks, 74 now pass local continuity, and 66 also match the pinned aggregates after quote-precision checks. Fifteen aggregate disagreements and 20 ID-gap blocks remain, overlapping in seven blocks (28 distinct cases). Source prices, volumes, rankings and previous diagnostics are unchanged. Full evidence is in `research/v9/a5_boundary_continuity.json`.
  - Completed: adjacent-day continuity investigation. Remaining: resolve or explicitly quarantine the 28 cases under a committed data-quality policy; account for ranking effects and 7,026 missing hours; verify a separate repair/exclusion dataset; then A5.3 replay and A4.4 family assembly. No accepted dataset, strategy trial, promotion, merge or deployment.

- **2026-10-19 (Codex continuation): boundary findings recorded and quality policy registered.**
  - Completed the pending publication of verified boundary findings. Both source-code CI runs (`39018841966`, `39018838921`) passed; the final Linux suite passed all 1,021 tests. The results resolve missing day brackets, not internal ID gaps or candle disagreements.
  - Registered `phase-a5-quality-overlay.md` before building a derived archive: bind all diagnostics, reconstruct only the 66 aggregate-matching/continuous blocks, quarantine the other 28, preserve original gaps/funding/source artifacts, and embargo all new entries on days whose ranking window intersects a quarantined block. No replacement ranking or slot backfill is permitted.
  - The mask is explicitly retrospective source-quality selection. Its coverage cost must be reported; unknown trade outcomes cannot be dropped or converted to zero. Implementation, independent derived-data verification, gap-aware replay and A4.4 remain pending. PR #30 stays draft and unmerged.

- **2026-10-19 (Codex continuation): quality-overlay transformation and binding helpers implemented.**
  - Added `tools/v9/hourly_quality.py`: fixed diagnostic-hash bindings, streaming artifact verification, strict block/continuity checks, whole-block replacement, quarantine with nonduplicated missing-hour coverage, and a separate entry embargo that preserves schedule order and empty days. Source data and frozen protocols remain unchanged.
  - Ten synthetic tests cover corrupted/missing evidence, unsafe artifact paths, boundary supplementation without erasing ID gaps, complete replacement, unchanged zero-volume/unaffected rows, overlapping masks, missing replacement hours, inconsistent flags, ranking-window endpoints, and no backfill. Full dependency-enabled Linux regression validation passed all 1,031 tests (313.633 seconds).
  - This is the transformation layer, not a completed derived dataset. Remaining: join all 94 blocks by source/segment identity, integrate the archive writer with funding/manifest preservation and failure retention, independently verify derived artifacts and coverage, register execution-gap rules, then A5.3 replay and A4.4. No strategy trials or production changes.

- **2026-10-19 (Codex continuation): quality archive builder implemented.**
  - Added `hourly_quality_build.py` with exact source/day/segment/conflict joins, original archive hash verification, deterministic derived candles, unchanged funding and schedule files, before/after correction ledger, per-segment coverage and a separate entry-embargo schedule. Failed builds retain a failure record; successful builds remain unaccepted candidates pending independent verification.
  - Four new synthetic integration tests cover mismatched and missing identities, source corruption, funding/schedule/source preservation, quarantine and embargo behavior, non-overwrite behavior and injected writer failure. All 14 focused quality tests pass; the complete Linux regression suite passed all 1,035 tests in 323.964 seconds.
  - Remaining: apply the committed builder, independently verify every changed row, unchanged artifact, exclusion and embargo day, record derived coverage/acceptance, then preregister execution-gap rules and perform A5.3 replay. No strategy trials or production changes.

- **2026-10-19 (Codex continuation): corrected archive built and independently verified locally.**
  - Applied builder commit `0463010d9866fdedbe7167a03c2bef9e1a85c084` after all 1,035 tests passed. Both source CI runs (`39230631624`, `39230623860`) succeeded. All fixed diagnostic hashes, diagnostic artifact inventories and original collection artifacts passed verification before construction.
  - Completed a separate 690-segment candidate with 13,862,226 retained hourly rows: 66 corroborated blocks reconstruct 264 hours; 28 unresolved blocks quarantine 112 hours. All 7,026 original gaps remain, yielding 7,138 unavailable hours without overlap. The original 663 zero-trade hours, funding bytes, universe and ordered daily schedule are preserved.
  - An independent verifier importing no builder helpers checked all output/source artifact hashes, every modified row and before/after ledger entry, exclusions, unchanged files, funding and schedule. It independently reproduced 70 entry-embargo days among 2,345 scheduled days. This is retrospective source-quality selection and must remain disclosed in later comparisons.
  - Evidence and the complete candidate hash inventory are committed in `research/v9/a5_quality_candidate.json`; the local artifact is `outputs/a5-quality-candidate`, manifest SHA-256 `d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2`. The candidate marker intentionally remains unaccepted; the verification record is separate and does not rewrite build history.
  - Completed: builder implementation, full local construction, independent derived-data verification and coverage accounting. Still remaining: durable archive publication and formal conditional A5.2 acceptance; preregister contiguous-lookback/reset, funding and exit-gap behavior before A5.3 replay; then A4.4 family assembly. No strategy trial, promotion, merge or production deployment occurred.

- **2026-10-19 (Codex continuation): durable quality-archive publication implementation.**
  - Added a research-only workflow and `hourly_quality_publish.py` to reproduce the previously verified candidate from the pinned rejected archive and committed diagnostics. Publication requires an exact match of the complete candidate manifest and every artifact hash; this replication does not replace the prior raw-evidence audit or confer dataset acceptance.
  - The dedicated `hourly-a5-quality-results` branch preserves the exact candidate and uses ordinary fast-forward updates, retaining prior versions. The workflow never writes production branches or deploys Pages. Three focused publication tests cover exact replication, changed/missing verification evidence and output divergence without a completion marker.
  - Full regression validation passed all 1,038 tests in 335.219 seconds. Remaining: run the committed workflow, verify the remotely retained archive against the independent candidate, record formal conditional A5.2 acceptance, then register gap-aware execution before A5.3 replay.

- **2026-10-19 (Codex continuation): durable archive verified; A5.2 conditionally complete.**
  - Publication code `0a370ff8a8b74b7453b63a4cf6fa4b8139d47eb3` passed 1,038 full regression tests and both GitHub CI runs (`39274047623`, `39274040564`). Workflow `39274041013` reproduced the complete candidate byte-for-byte and published research result `0859e683910a7eea7ef446b27cf9773f33d9e9f8`.
  - Fetched the retained result and independently streamed all 1,386 Git blobs through SHA-256 verification against the previously verified inventory. Every file, including the candidate manifest, matches. Formal conditional research-data acceptance is a new record; neither the rejected source nor the historical candidate marker was edited.
  - Completed: durable publication, remote verification and conditional A5.2 acceptance. Remaining: preregister and test the A5.3 execution adapter's lookback/reset, funding and exit-gap rules; run all seven definitions and retain unresolved outcomes; independently verify trials and assemble A4.4 with universe/quality restrictions disclosed. No strategy trial, promotion, merge or deployment occurred.

- **2026-10-20 (Codex continuation): A5.3 execution contract and kernel implemented.**
  - Inspected all seven registered hourly definitions and the legacy simulator. Its preceding-close exit on missing bars and zero-default funding are not suitable for the accepted archive's explicit gaps. Added a separate `hourly_execution.py` without modifying evidence-bound code, and `phase-a5-execution-contract.md` before any hourly market replay.
  - The kernel retains unexecuted attempts, unobservable price paths and unknown funding; no previous-close fallback, delayed fill or assumed archive-end exit. Preserves stop-first, gap-open stop, next-bar trailing/breakeven and declared fee/slippage rules. Funding completeness is explicit, including the entry hour; absent records cannot become zero.
  - Eight synthetic tests cover gap/zero-volume/end censoring, entry gating, stop/target priority, gap prices, trailing/breakeven timing, funding sign and entry-instant exclusion, unknown funding, cost arithmetic and early exits unaffected by later missing bars. Full Linux regression validation passed all 1,046 tests in 316.787 seconds.
  - Still remaining: exact per-definition feature reset/warm-up and causal cross-sectional mapping, funding-completeness evidence or explicit unavailable intervals, batch position-state tracking and unavailable daily series, additional synthetic tests, committed market replay and independent verification. No hourly strategy trial or production change occurred.

- **2026-10-20 (Codex continuation): A5.3 batch ledger and feature-readiness rules.**
  - Added `hourly_batch.py`: preserves every signal attempt, uses entry-day membership/quality gates, tracks one position per trial/segment, locks unknown price states, permits reuse after observed exits with unknown funding, and makes the complete daily net series unavailable if any executed outcome is unresolved. Execution input is clipped to the study end.
  - Registered `phase-a5-feature-state.md` and implemented readiness/session boundaries in `hourly_feature_state.py`: 720 consecutive usable hours, full UTC four-hour EMA200 warm-up for PULLBACK, joint BTC/alt continuity for BTC_LEAD, no recursive state across gaps or zero-trade hours. This additional retrospective continuity restriction must be disclosed.
  - Eleven synthetic tests pass for batch uncertainty, midnight/embargo gating, no backfill, daily accounting, archive-end censoring, invalid inputs, gap restart, zero-trade reset, four-hour alignment, paired BTC context and future-append invariance. Full Linux regression validation passed all 1,057 tests in 337.683 seconds.
  - Found FUND_CARRY compatibility issue: its legacy settlement quorum uses full panel size, which includes future listings in a fixed historical union. Changing to a contemporaneous roster changes that trigger. The preregistration explicitly keeps this trial unavailable until the mapping decision is recorded; no silent substitution or zero-return column.
  - Remaining: actual session-reset indicator/signal adapter and equivalence tests, FUND_CARRY compatibility resolution, funding-completeness evidence or explicit unavailable intervals, then committed market replay and independent verification. No hourly strategy trial or production change occurred.

- **2026-10-20 (Codex continuation): A5.3 registered signal integration.**
  - Added `hourly_signals.py`, importing unchanged registered strategy functions with exact census/code bindings. Features restart on each contiguous usable session; original predicates and the registered warm-up restrictions apply. BTC context cannot emit trades.
  - FUND_FADE requires an observed finite hourly event to emit, and missing observations cannot reuse a stale funding event. No signal sentinel establishes execution-cost completeness. FUND_CARRY remains explicitly unavailable, without fabricated signals or returns.
  - Eight synthetic tests pass, including nonempty legacy equivalence, fresh-session gap reset, numerical ATR/EMA and signal future-append invariance, complete UTC four-hour alignment, input preservation and missing/off-grid funding.
  - Full Linux regression validation passed all 1,065 tests in 498.426 seconds, including the explicit observed-zero funding guard. Remaining: FUND_CARRY compatibility disposition, funding-completeness evidence or explicit unavailable intervals, archive-to-batch replay driver, committed market replay and independent verification. No hourly strategy trial or production change occurred.

- **2026-10-20 (Codex continuation): explicit funding-coverage and compatibility disposition.**
  - Added strict `hourly_funding.py`: preserves observed zero and off-grid events, rejects malformed/duplicate observations, and never infers complete hourly funding from interval hints or regularly spaced payments. The source collector can skip malformed rows; its retained files cannot prove absent settlements.
  - Registered `phase-a5-funding-disposition.md`: all execution funding coverage remains explicitly unknown; the driver must retain unresolved net outcomes. FUND_FADE remains observed-event conditional and off-grid events require unavailable status. FUND_CARRY retains its registered identity with an unavailable causal-quorum attempt rather than a redefined strategy or zero-return column.
  - Five synthetic tests pass, including execution integration proving that an observed zero rate cannot establish known net return without completeness evidence. Full Linux suite: 1,070 tests passed in 327.272 seconds. The final log-display shell command failed after successful tests because the local wrapper was edited while running; the complete unittest summary is retained in outputs/v9-a5-funding-full-tests.log. The subsequent CI-only import-guard/workflow edits were checked separately with and without scientific dependencies (13 passed; 5 passed plus 8 expected skips) and YAML parsing.
  - Remaining: bound archive-to-batch driver enforcing these dispositions, committed replay and independent result verification. A5.3 and A4.4 remain open; full-family statistics remain unavailable. No hourly market strategy trial, promotion or production change occurred.
  - Follow-up CI correction: signal commit `18c8d2d` passed local scientific-stack tests, but GitHub unit jobs `39324248728` / `39324242166` failed importing NumPy in their intentionally dependency-free environment. Signal tests now skip only when NumPy/pandas is missing, and the research CI job explicitly runs both signal and funding suites. Unexpected import errors still fail. Both local dependency configurations are checked before publication.

- **2026-10-20 (Codex continuation): pinned hourly archive replay driver.**
  - Confirmed both GitHub CI runs for funding/CI-fix commit `7e06c5e` succeeded (`39398997338`, `39398991315`).
  - Added `hourly_replay.py` and registered `phase-a5-replay-driver.md`: exact accepted manifest/inventory/hash verification, strict candle parsing, unchanged segment identities and schedule, bounded warm-up history, per-segment processing without reranking, streamed attempt artifacts and final source/artifact hashes.
  - Retains explicit FUND_CARRY unavailability, off-grid FUND_FADE unavailability, failed segment records, unknown funding and unresolved net series. Fatal preflight/writer errors retain failure records without a completion manifest; existing output directories cannot be overwritten. No market trial has run.
  - Seven synthetic driver tests pass: corruption/missing/extra-file rejection, malformed candles, all-seven trial accounting, unavailable net values, shard hashes, no overwrite, equivalence to joint batch positions, off-grid funding, failed segments and writer/preflight failure retention. Dependency-free discovery also passes with five expected scientific skips; the research CI job explicitly runs this suite. Full Linux regression validation passed all 1,077 tests in 306.651 seconds.
  - Remaining: durable replay workflow/output publication and append-only evidence-run registration support, committed market application, independent reconciliation, then A4.4 reporting of incomplete family evidence. A5.3 remains open; no promotion or production change.

- **2026-10-20 (Codex continuation): A5 replay publication and evidence recording prepared.**
  - Added `hourly_replay_publish.py`, a separate outer attempt record/report that preserves driver artifacts, partial streams and fatal failures without manufacturing a driver completion marker. Registered `phase-a5-replay-publication.md` before market use.
  - Added research-only `evidence_a5.yml`: focused tests, pinned accepted-dataset export, one replay, normal fast-forward publication to `evidence-a5-results`, failure backup and duplicate-registration guard. An export failure is retained through replay preflight; partial/failed runs report workflow failure only after publication.
  - Extended `record_run.py` for A5's distinct dataset and compressed attempt hashes, without editing historical records. Committed-history tests retain the phase-B binding for earlier studies and additionally validate all A5 preregistration hashes.
  - Five synthetic publication/recording tests cover successful, partial and fatal attempts, no overwrite, retained partial artifacts, source/data/driver binding and tamper rejection. Full Linux regression validation passed all 1,082 tests in 297.243 seconds; all workflow shell blocks passed syntax checks. Both driver CI runs (`39400986758`, `39400977952`) passed. Publishing the new workflow starts the first market attempt; result verification and history append have not happened yet; A5.3 remains open.

- **2026-10-20 (Codex continuation): first A5 market replay launched.**
  - Published workflow/recording source `491ca15b235a1f635cc5f858115d03162d8e1a5d` after all 1,082 tests passed. Both hosted CI runs (`39464886775`, `39464874869`) succeeded.
  - Research run `39464874726` passed synthetic checks and pinned dataset export and is executing the first market replay. Do not start another attempt; inspect this run and recover its `evidence-a5-results` commit when published. It is not yet verified or appended to the evidence history.
  - Prepared local independent verification scripts `work/verify_a5_replay_result.py` (artifact/source/catalogue hashes and trial/stream/daily accounting) and `work/verify_a5_replay_prices.py` (entry gates, position state and observable price outcomes against accepted candles). The price checker passes four hand-calculated cases. These scripts have not yet audited market results; signal-population verification remains separate.
  - Next: fetch the exact retained result; run artifact/accounting and price reconciliation; append its verified A5 run record; retain any unavailable/failed trial honestly and finish the remaining independent signal checks. A5.3 remains open. No merge, promotion or production deployment.

- **2026-10-20 (Codex continuation): independent signal verifier prepared while first replay runs.**
  - Original run `39464874726` completed successfully during verification preparation. No duplicate attempt was launched. The retained result still requires all independent checks and the evidence-history append.
  - Added local `work/verify_a5_replay_signals.py`, which reconstructs continuity, warm-up and paired BTC sessions independently of the new adapter, calls only unchanged original strategy functions, and compares the full retained signal population and parameters for every successfully generated segment. Failed/unavailable segments remain explicitly counted, not silently accepted.
  - Its mapping matches all six supported definitions on synthetic data. Together with the artifact/accounting and price-outcome scripts, it is ready for the retained result. All three still need to run against the actual result commit; their preparation does not complete A5.3.

- **2026-10-21 (Codex continuation): first A5 replay independently verified and recorded.**
  - Run `39464874726` succeeded and retained result `84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e` with status `COMPLETED_WITH_UNAVAILABLE_RESULTS`. Source `491ca15b235a1f635cc5f858115d03162d8e1a5d` and every preregistration/artifact hash match. No repeat market attempt was run.
  - Three retained verification tools check artifact/trial accounting, every price outcome and entry/position gate, and complete signal populations for successfully generated segments. Signal verification reconstructs sessions independently but deliberately reuses unchanged original strategy functions; it does not independently validate their mathematics. Full reports and verifier hashes: `research/v9/a5_replay_verification.json`.
  - All 435,817 attempts reconcile: 201,185 unexecuted, 173 unresolved price paths and 234,459 observed price exits with unknown funding. No segment failed. FUND_CARRY is unavailable for causal quorum mapping; two FUND_FADE segments are unavailable for off-grid funding. All seven net-return series remain unavailable, with no invented zero returns.
  - Appended A5 as evidence-history record 5 and verified the intact hash chain. The full Linux regression suite passed 1,082 tests in 341.138 seconds.
  - Completed: first replay, independent reconciliation and evidence registration. Remaining: A4.4 reporting/assembly with explicit missing hourly columns and differing universes; complete A5.3 return evidence remains blocked by the recorded funding/definition limitations. Other roadmap items remain open. PR #30 stays draft; no merge, promotion or production deployment.

- **2026-10-21 (Codex continuation): A4.4 evidence review and assembly specification.**
  - Reviewed the exact retained A4 and A5 reports and metadata. Their declared windows match, but their universes, funding treatment and execution rules differ. A5 provides no usable net-return column, so all seven hourly columns and full-family DSR/PBO/bootstrap results remain unavailable.
  - Added `phase-a4-evidence-review.md`, including every hourly attempt disposition, explicit statistical limits and remaining work. Added `phase-a4-family-assembly.md` before implementation/application: preserve all 199 identities, days, A4 values and seven missing columns; verify source hashes; reject contradictory availability; retain a separately hashed derived manifest with no new replay or statistics.
  - Completed: combined evidence review and fixed assembly rules. Remaining: assembly implementation, synthetic rejection tests, independent output verification and durable manifest. A4.4 and A5.3 remain open; existing evidence history and preregistrations are unchanged. No promotion, merge or production deployment.
  - Validation: all seven report rows match the independently verified counts; full Linux regression suite passed 1,082 tests in 371.668 seconds. Both CI runs for prior verification commit `863278f` passed (`39509241311`, `39509236434`).

- **2026-10-21 (Codex continuation): fixed-input family assembly implemented and verified locally.**
  - Added `family_assembly.py` under the committed specification. It checks source identities and hashes, the evidence chain, plan/definition bindings, exact daily axes, availability and attempt metadata; it preserves the original matrix bytes and inherited unavailable statistics. No simulation or new statistical calculation runs.
  - Seven synthetic tests cover reordered/duplicate/missing identities, changed dates/definitions/counts, corrupt hashes, invented return values or authority, contradictory availability, output overwrite and retained preflight/writer failures without a completion marker.
  - Applied the assembly to the two fixed results. Separate `verify_family_assembly.py` imported no assembler helpers and compared all 466,854 cells (2,346 by 199), exact matrix bytes, every column definition and hourly metadata, all input/output hashes and inherited statistics. All checks passed. Artifacts are in `research/v9/family_assembly/`; the derived inventory references evidence-history entries 4 and 5 without adding a fictitious replay.
  - Completed: assembly implementation, independent verification and retained artifact package. Full Linux validation passed 1,089 tests in 393.943 seconds. Seven hourly columns remain unavailable, so the complete-return objectives of A4.4/A5.3 remain open; no strategy promotion, merge or deployment.
  - Next unblocked roadmap work: A6 matched-control study design and preregistration. Keep A4/A5 complete-return limitations open; resolving funding coverage or redefining FUND_CARRY requires separate evidence/registration, not a repeat of the frozen A5 attempt.

- **2026-10-21 (Codex continuation): A6.1 matched-control design and selector.**
  - Inspected the existing Phase 9 matcher/gate and archive collection code. Corrected two planning assumptions: the full gate requires eight matching dimensions, and the archive first bar is not independently verified listing inception. No gate or existing matcher was changed.
  - Added `phase-a6-control-design.md` before A6 market use, and `control_cohort.py`: exact decision-time/direction matching, fixed seven-day-volume and archive-age buckets, 50 distinct controls without replacement, same-symbol exclusions, deterministic hash ordering and explicit sparse/unavailable results. All results remain diagnostic with authority false.
  - Six synthetic tests pass for boundaries/relisting resets, deterministic unique selection, input-order/future/outcome invariance, no bucket widening, coverage counts, missing/stale/invalid features and ambiguous identities. No A6 market matching or outcome calculation has run.
  - Full Linux validation passed 1,095 tests in 303.950 seconds. Remaining: registered disposition of known archive conflicts/gaps, source-bound complete-signal/feature adapter, separate execution/inference registration, then one recorded and independently verified study. A6 remains open; A4/A5 limitations remain unchanged.
  - Previous assembly commit `9d8b62b` passed both hosted CI runs (`39570808464`, `39570803428`). A6.1 is complete; the broader matched-control study and Phase 9 qualification remain open.

- **2026-10-21 (Codex continuation): A6.2 feature-window quality layer.**
  - Added `phase-a6-feature-quality.md` before market application: any seven-day window intersecting an original disputed A5 four-hour block is unavailable; gaps remain missing; quality exclusions are retrospective and the limited audit does not establish broad-universe correctness. The exact 94-block source-bound inventory remains to be integrated.
  - Added `control_features.py` for exact 42-bar UTC windows, observed zero volume, segment first-bar identity, reconstructed availability, explicit missing/disputed timestamps and causal window hashes. It preserves eligibility and does not qualify the underlying signal's longer indicator history.
  - Six new synthetic tests pass (12 combined cohort/feature tests): window boundaries, gap/dispute overlap, zeros, future append invariance, invalid/duplicate inputs, relisting age, preserved eligibility and rejection of unavailable inputs by the cohort selector.
  - Completed: fixed quality disposition and synthetic feature construction. Full Linux regression validation passed 1,101 tests in 294.949 seconds. Remaining: bind the actual dispute inventory/source files, complete generated-signal adapter and independent population/feature audit, then separately register execution/inference. No A6 market matching or outcome computation, strategy promotion, merge or deployment.

- **2026-10-21 (Codex continuation): A6.2 source bindings and original dispute inventory.**
  - Added `control_sources.py`: verifies the pinned original audit/plan and corroborating quality-ledger hashes; retains all 94 original disputed blocks across 87 segments and all 189 fields. The inventory preserves 782 original broad-source hash bindings, not the saved 690-segment hourly subset.
  - Added original-universe and segment loaders with exact byte hashes, full file inventory, segment identity/bounds/count, safe names and strict timestamp/volume checks. Five synthetic tests cover missing/duplicate/wrong audit evidence, changed or subset sources, malformed candles, observed zeros and segment identity.
  - Independently reconciled every retained dispute, source symbol/reference hash and all bound input objects without importing builder helpers. Records: `a6_source_inventory.json` and `a6_source_inventory_verification.json`. This verifies bindings, not actual loading/validation of the broad archive; that distinction is explicit.
  - Completed: source-binding helpers and independently verified original dispute inventory. Full Linux regression validation passed 1,106 tests in 285.189 seconds. Remaining: apply the loaders to the pinned broad archive, integrate the complete generated-signal/feature adapter and independently audit the population, then register execution/inference. No A6 market matching, outcomes, promotion, merge or deployment.
  - Both hosted CI runs for prior feature commit `0a9f4fb` passed (`39573456826`, `39573449787`). Inventory and loader implementation are complete; full archive application and generated-signal reconciliation remain pending.

- **2026-10-21 (Codex continuation): A6.2 generated-signal streaming adapter.**
  - Registered `phase-a6-signal-population.md`: retain every original generator ordinal before simulator/position/entry filtering, distinguish warm-up and after-window counts, keep duplicates and terminal signals, and retain exact geometry and eligibility. No market generator has run.
  - Added `control_signals.py`: validates array shapes, indices/directions/geometry and panel identities, streams every in-window signal, and attaches indexed feature windows equivalent to full-source construction. Own-segment missing/disputed history is annotated separately; clean volume windows never imply qualified signal history.
  - Seven synthetic tests pass for full denominator accounting, duplicates/terminal signals, false eligibility, missing/disputed history, retained unavailable features, malformed generator output, empty/after-window accounting and future-append invariance. Terminal next-bar availability may legitimately change when a new bar is observed, while existing signal identity/features remain unchanged.
  - Completed: population contract and streaming projection layer. Full Linux regression validation passed 1,113 tests in 275.435 seconds. Remaining: bound archive/generator driver with safe sharding and failure manifests, one source-validation/signal extraction application and independent population audit, then separate execution/inference registration. A6.2 remains open; no market matching/outcomes, promotion, merge or deployment.
  - Both hosted CI runs for prior source commit `3e3b2a9` passed (`39627505796`, `39627496243`).

- **2026-10-22 (Codex continuation): A6.2 bound extraction driver.**
  - Added `control_extract.py` and registered `phase-a6-extraction-driver.md` before market application. The driver verifies original research bytes, census/inventory bindings, every broad candle file, phase-B reference/panel digest and the exact window before generating signals.
  - All 199 identities are retained: 192 definitions called once, seven hourly populations explicitly unavailable. Deterministic shards have row and byte limits; partial trial outputs survive validation failures, filesystem failures abort without completion, and existing results cannot be overwritten. No matching, execution or outcomes run.
  - Eight synthetic tests cover all-199 accounting, complete ordinals, deterministic shard hashes/limits, partial and empty populations, fatal writers, source corruption and unsafe/duplicate identities. Full Linux regression validation passed all 1,121 tests in 318.689 seconds. All six original code files and the census/inventory hashes were also checked directly.
  - Remaining: durable Actions publication and duplicate guard, independent population verifier, one retained source-validation/extraction application and audit; then separate execution/inference registration. A6.2 remains open; no promotion, merge or deployment.

- **2026-10-22 (Codex continuation): A6 independent artifact accounting.**
  - Added `verify_control_artifacts.py`, which imports no extraction/projection helpers. It requires separately supplied plan/provenance anchors and checks every trial file, bounded shard, hash, size, ordinal, signal identity, feature identity, authority flag and population count. Unlisted/partial files and ambiguous JSON are rejected.
  - Five synthetic tests cover complete/partial extraction, unavailable hourly populations, corrupt/missing/extra files, changed provenance/rosters/counts, duplicate/reordered identities and tampering with recomputed hashes. This is artifact verification only: generator population and source feature values remain explicitly unverified. Full Linux regression validation passed all 1,126 tests in 317.235 seconds.
  - Remaining: independent generator/feature reconciliation, durable Actions retention and duplicate-attempt guard, first extraction and retained-result audit. A6.2 stays open; no market extraction, matching/outcomes, promotion, merge or deployment.

- **2026-10-22 (Codex continuation): A6 independent source/array reconciliation.**
  - Added `verify_control_population.py` without importing extraction, projection or feature helpers. It independently reconstructs exact 42-bar volume windows, missing/disputed history and retained row identities, then compares every original in-window generator ordinal, geometry, eligibility and terminal-entry flag. It rejects extra/missing rows and verifies all population counts.
  - Seven synthetic tests cover hand-calculated volume, clean/missing/disputed/zero-volume windows, duplicate/reordered/omitted signals, tampered geometry/features/history/identities, malformed raw arrays and source data, and empty populations. Full Linux regression validation passed all 1,133 tests in 305.500 seconds. Both prior artifact-verifier CI runs (`39673843424`, `39673836234`) passed.
  - This helper verifies supplied source rows and original arrays, not the original generator mathematics or external input provenance. Remaining: a source-bound audit runner, durable Actions retention/duplicate guard, first extraction and retained-result audit. A6.2 remains open; no market extraction, matching/outcomes, promotion, merge or deployment.

- **2026-10-22 (Codex continuation): A6 source-bound independent audit runner.**
  - Added `audit_control_extraction.py` and `phase-a6-independent-audit.md`. The runner independently reads and hashes original candles, checks unchanged research bytes and the extraction commit, reconstructs phase-B panel provenance, verifies artifacts, and compares each successfully extracted trial against the unchanged original generator and independent feature checker.
  - Six synthetic tests cover complete/partial trial dispositions, generator/source/window tampering, independent archive reading and hash rejection, failed preflight, extraction preservation and refusal to overwrite prior audits. Full Linux regression validation passed all 1,139 tests in 298.724 seconds. The source reader accepts all 781 pinned identities, including relisting suffixes and non-Latin names, with dedicated synthetic coverage.
  - Failed and hourly populations remain explicitly unverified; generator mathematics and full-family qualification are not claimed. Verification repeat calculations produce no new outcomes or strategy test.
  - Remaining: durable Actions publication and duplicate-attempt protection, first retained extraction and audit, independent result inspection. A6.2 remains open; no market extraction, matching/outcomes, promotion, merge or deployment.

- **2026-10-22 (Codex continuation): A6 durable attempt retention and first-run reservation.**
  - Added `control_publish.py`, `phase-a6-publication.md` and research-only `evidence_a6.yml`. The workflow reserves `evidence-a6-results` before exporting data, rejects any existing attempt, runs extraction and audit in separate processes, and retains every output as a normal descendant of the reservation without force pushes. A hard interruption leaves the reservation blocking accidental repeats.
  - The outer attempt record retains stage exit codes, hashed files, partial outputs and failures. Success requires 192 independently audited available trials and seven explicit hourly unavailabilities. Four synthetic tests cover success/count rejection, fatal/partial retention, exception handling and refusal to overwrite attempts. Full Linux regression validation passed all 1,143 tests in 288.274 seconds. Workflow parsing and every shell block passed syntax checks.
  - Published source `269cb2b0360310ac6bac9fd5ef8b102505c6d997` started the first registered workflow run `39774700211`. Do not launch another attempt; recover and inspect this run. Synthetic checks, reservation and pinned archive export passed; extraction/audit is running. Durable reservation `3d9162699c2507ec35b542e9e6e6031fa5d429c4` binds this source and run. Its extraction/audit results are not yet verified. Remaining: inspect that run and exact retained result, reconcile all source/artifact/audit bindings and counts, and update A6.2 only after verification. Separate execution/inference registration remains required; no matching/outcomes, promotion, merge or deployment.

- **2026-10-22 (Codex continuation): A6 retained-package verification prepared while extraction runs.**
  - Confirmed original run `39774700211` remains in its extraction/audit stage and results head is still reservation `3d9162699c2507ec35b542e9e6e6031fa5d429c4`; no duplicate attempt was launched.
  - Added `verify_control_result.py` to stream-check every retained Git blob against the outer inventory, verify reservation ancestry and source/run/protocol bindings, and reconcile all 199 trial identities, available-population counts and audited-source hashes. Interrupted/failed attempts remain explicit. This checks the retained audit and package; it does not rerun generators or reload market data locally.
  - Four synthetic tests cover successful 192/7 accounting, incomplete/failed states, corrupt/extra files, and rehashed source/audit/count/identity tampering. Full Linux regression validation passed all 1,147 tests in 322.195 seconds.
  - Remaining: run this verifier on the exact completed result commit and inspect its findings. A6.2 remains open until retained-result verification; separate execution/inference registration remains outstanding. No matching/outcomes, promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.2 first extraction/audit independently reconciled.**
  - Original run `39774700211` completed successfully and retained result `eb785a908dce572958336649291b8feeb4ee9575` as a normal descendant of reservation `3d9162699c2507ec35b542e9e6e6031fa5d429c4`. No repeat attempt was run.
  - Ran the retained-package verifier against the exact result/source commits. All 670 files, source/protocol/auditor bindings and 199 identities reconcile. The source-bound audit verified all 192 available definitions, 4,263,580 retained signals and 465 shards; 4,279,748 generated minus 16,168 pre-window signals reconciles exactly. Seven hourly populations remain unavailable; zero available trials failed.
  - Retained `research/v9/a6_result_verification.json` and `phase-a6-extraction-review.md`. A6.2 is complete for its registered scope; no full-family, original-generator-mathematics or matched-control authority is claimed. No fictitious strategy-outcome record was appended to evidence history. Full Linux regression validation passed all 1,147 tests in 314.363 seconds.
  - Next: A6.3 separate execution/inference preregistration, implementation and synthetic tests before any market matching/outcomes. The eight-dimension qualification gate remains unsatisfied; A4/A5 return-evidence limitations remain unchanged. No promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.3 execution and inference preregistration.**
  - Added `phase-a6-execution-inference.md` before market matching/outcomes. It pins the verified A6.2 inventory, defines independent paired hypothetical attempts with identical geometry/costs, preserves all missing/sparse/failed dispositions, and rejects original disputed execution bars.
  - Explicitly keeps every entered net outcome and all 398 inferential slots unavailable because funding coverage/exit timing are unestablished. Resolved-only price-after-cost summaries are descriptive and labelled conditional; no bootstrap, p-values, winner selection or edge claim is permitted. Day/reuse counts preserve dependence for audit without pretending independent observations.
  - Completed: execution/inference specification. Remaining: new four-hour kernel, streaming matcher/aggregation, synthetic tests, durable single-attempt workflow, evidence recording and independent result reconciliation. No matching/outcome application occurred. A6.3 and full qualification remain open. Full Linux regression validation passed all 1,147 tests in 379.025 seconds.

- **2026-10-23 (Codex continuation): A6.3 four-hour hypothetical execution kernel.**
  - Added `control_execution.py` under the committed execution/inference contract, without changing the legacy simulator or A5 kernel. It preserves original geometry and four-hour hold units, applies identical fixed costs, stop-before-target priority, opening gaps, next-bar trailing/breakeven and exact time exits.
  - Missing/disputed/zero-volume/malformed bars and archive-end censorship remain explicit; no delayed entry or price fill occurs. Attempts have no shared position state. Observed price-after-cost R is labelled separately while net R is always null and funding remains unknown.
  - Eight synthetic tests cover both directions, hand-calculated costs and returns, target/gap behavior, trailing/breakeven timing, unknown data, eligibility, censorship, unchanged inputs, independent reuse, future append invariance and panel-bar holds. Full Linux regression validation passed all 1,155 tests in 296.325 seconds.
  - Remaining: matching/aggregation, source-bound outcome adapter, independent verification, durable single-attempt publication and evidence recording, then one registered application. A6.3 remains open; no market matching/outcomes, promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.3 paired matching and descriptive aggregation.**
  - Added `control_pairs.py`: fixes all selected controls before any execution, applies identical signal geometry/timing to candidate and controls, retains sparse/unresolved attempts and only computes price contrasts with all 51 price outcomes observed. No net contrast or inference is produced.
  - Added `control_summary.py`: disk-backed values and exact medians, all trial/direction slots including unavailable hourly populations, matching/entry/price dispositions, conditional-versus-complete denominators, UTC decision-day sums and counts, and per-side asset/time control reuse. Duplicate IDs and altered pair arithmetic/authority are rejected.
  - Seven synthetic tests cover fixed selection, identical geometry, missing control outcomes without replacement, sparse/ineligible signals, exact means/medians/counts, reuse and duplicate detection, conditional missingness, tampering and all 398 inference slots. Full Linux regression validation passed all 1,162 tests in 371.532 seconds.
  - Remaining: source-bound outcome adapter, independent verification, durable single-attempt publication and evidence recording, then one registered application. A6.3 remains open; no market matching/outcomes, promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.3 source/price integration adapter.**
  - Added control_adapter.py, using the verified extraction context without changing original research code. It checks retained signal identities, panel indices, eligibility, source hashes, features and history before selecting controls. Price files are hash-bound and checked against feature calendars/volumes; a bounded cache avoids retaining the full OHLC archive.
  - Missing/malformed/disputed prices remain explicit, and segment/study ends censor execution. Six synthetic tests cover bound execution, corrupt bytes, signal tampering, ineligible/terminal attempts, malformed prices and disputes. Full Linux regression validation passed all 1,168 tests in 361.603 seconds.
  - This adapter requires a verified input context and independently verified A6.2 package; it does not independently prove generator geometry. Remaining: bound streaming outcome driver, independent verification, durable single-attempt publication and evidence recording, then one registered application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.3 bound streaming outcome driver.**
  - Added control_outcomes.py, pinned to the accepted A6.2 manifest hash and result commit. It verifies the full artifact inventory against source preparation before execution, rechecks each shard, streams retained signals through the adapter, and writes bounded outcome/day/reuse shards plus all direction summaries. Original generators are not rerun.
  - Existing attempts and overlapping input/output directories are rejected. Preparation or execution failures retain an explicit failed/partial manifest, processed counts and hashed partial artifacts; unavailable hourly populations stay explicit. Six synthetic tests cover complete accounting, corrupt/unregistered input, preparation/interruption failures and overwrite/input isolation. Full Linux regression validation passed all 1,174 tests in 281.589 seconds.
  - Remaining: independent matching/execution verification, durable one-attempt reservation/publication and evidence-run recording, resource qualification for the full inventory, then one registered market application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-23 (Codex continuation): A6.3 independent outcome accounting verifier.**
  - Added verify_control_outcomes.py without importing matching, execution, aggregation or the outcome driver. It verifies external input/code/protocol bindings, every output hash, exact source-to-outcome ordering and counts, control identities, geometry, complete-pair arithmetic, side/disposition counts and unavailable inference fields. Unexpected files, unsafe paths and rehashed inconsistencies are rejected.
  - Seven synthetic tests cover valid accounting, missing outcomes, changed geometry, sparse/full-pair contrast tampering, summary/inference changes, external bindings and unlisted files. Full Linux regression validation passed all 1,181 tests in 287.723 seconds.
  - This is deliberately limited accounting verification: control selection/ranks, source price paths, descriptive statistics and day/reuse aggregates still require independent audits. Remaining also includes durable single-attempt publication, evidence-run recording and resource qualification before one market application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6.3 independent control-selection checker.**
  - Completed the prior interrupted publication verification: commit 94bfec5a1d1067bfb5f4fd273fed798a62a21c10 matches the tested local files and the checkout is synchronized.
  - Added verify_control_selection.py without importing the production selection, feature or matching code. It independently checks fixed bucket boundaries, eligibility/time/direction filtering, same-symbol exclusions, exact ranks/order, retained feature fields, cohort counts and sparse/unavailable dispositions.
  - Five synthetic tests cover every bucket boundary, sparse/full/unavailable cohorts, exclusions, rank/order/feature/count tampering, omitted/duplicate population rows and future/outcome invariance. Full Linux regression validation passed all 1,186 tests in 310.092 seconds.
  - The checker requires the complete externally verified source snapshot; it does not establish snapshot provenance or execution correctness. Remaining: source-bound audit integration, independent price-path/statistics/day/reuse checks, durable publication, evidence recording and resource qualification before one market application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6.3 independent price-path checker.**
  - Added verify_control_prices.py without importing the production execution kernel. Direction-oriented candle paths independently reconstruct stop/target priority, opening gaps, delayed trailing/breakeven updates, time exits, costs and uncertainty dispositions, then compare every recorded outcome field. Float comparisons use 1e-12 relative/absolute tolerance; categorical fields remain exact. Funding and promotion authority remain unavailable.
  - Five synthetic tests cover both directions, target/stop/time/gap behavior, missing/zero/disputed/malformed/terminal data, trailing/breakeven timing, changed exits/costs/authority and 400 seeded direction/path cases with future-append invariance. Full Linux regression validation passed all 1,191 tests in 319.998 seconds.
  - The checker requires externally verified source candles; source-bound batch integration, statistics/day/reuse verification, durable publication, evidence recording and resource qualification remain before one market application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6.3 independent descriptive-statistics audit.**
  - Added verify_control_statistics.py without importing production aggregation. A separate disk-backed audit database reconstructs conditional means with math.fsum, exact medians/extrema, complete-versus-conditional availability, ordered UTC-day totals and asset/time control reuse. Duplicate signal IDs, missing/extra rows and invented inference remain failures. Numerical aggregates use 1e-10 relative/absolute comparison tolerance.
  - Five synthetic tests cover hand-calculated varied means/medians, every altered statistic, missing day rows, changed reuse counts, incomplete populations, empty sides, unavailable hourly counts and duplicate IDs. Full Linux regression validation passed all 1,196 tests in 317.916 seconds.
  - This audit requires independently checked pair records; it does not establish source provenance. Remaining: source-bound integration of accounting/selection/price/statistics audits, durable single-attempt publication, evidence recording and resource qualification before one registered market application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6.3 source-bound outcome audit integration.**
  - Added audit_control_outcomes.py, integrating independent accounting, reconstructed source features/eligibility, registered cohort selection, candle-path/cost checks and descriptive/day/reuse statistics. It pins the accepted A6.2 inventory and original extraction source, checks output implementation/protocol bytes against an explicit source commit, and independently parses/hash-checks OHLC files with a bounded cache. Original signal generators are not rerun.
  - Separate success/failure artifacts preserve outcome files; previous audits and overlapping output directories are rejected. Five synthetic integration tests cover complete layered verification, corrupted source candles, rehashed wrong exits, source-eligibility mismatch and overwrite/input isolation. Full Linux regression validation passed all 1,201 tests in 310.367 seconds.
  - Remaining: durable one-attempt reservation/publication, evidence-run recording, resource qualification, then one registered market application and retained-result reconciliation. Original-generator mathematics and net-return qualification remain unverified/unavailable. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6.3 reserved-attempt retention wrapper.**
  - Added control_outcome_publish.py and phase-a6-outcome-publication.md. The wrapper validates a source/input/protocol-bound first-attempt reservation, writes STARTED before execution, runs outcomes and audit separately, and inventories all logs and partial artifacts. Success requires the fixed signal/trial/side counts and every audit layer; net inference stays unavailable.
  - Six synthetic tests cover successful retention/hashes, incomplete audit rejection, partial exceptions, interruption retaining STARTED and blocking retry, invalid reservations/input overlap, and changed inputs failing before execution. Full Linux regression validation passed all 1,207 tests in 330.928 seconds.
  - This wrapper does not create or prove the remote reservation. Remaining: durable reservation/fast-forward workflow, evidence-run recording, resource qualification, then one registered market application and retained-result reconciliation. No workflow was activated and no market outcome attempt was run. A6.3 remains open; no promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6 outcome evidence-history support.**
  - Added record_control_outcome.py and routed record_run.py --study A6 through it. The builder verifies immutable root-reservation ancestry, source/input/protocol bindings and retained-file hashes, then prepares a canonical record for the existing append-only chain. Reserved, STARTED, failed/partial and audited states remain explicit; absent outcomes stay absent and no strategy confirmation is invented. Commit time is labelled as retention time, not execution start.
  - Six synthetic tests cover successful/unfinished/failed records, altered reservation/artifact/authority rejection, append-chain preservation, duplicate refusal and CLI routing. Full Linux regression validation passed all 1,213 tests in 293.486 seconds.
  - No real evidence record was appended: the actual A6 outcome attempt has not run. Remaining: durable reservation/publication workflow, resource qualification, one registered application, retained-result reconciliation and recording. A6.3 remains open; no promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6 synthetic resource qualification probe.**
  - Added control_resource_probe.py, its retained synthetic report and phase-a6-resource-review.md. Generated 61 synthetic assets with 400 bars and processed 20 full fifty-control comparisons; no market data or registered study attempt was used.
  - Found 1,009 price-file reads for 61 available files: the eight-segment cache repeatedly reloads histories. Pair artifacts total 1,138,170 JSON bytes / 67,602 gzip bytes. Naive full-inventory extrapolations are 242.6 GB / 14.4 GB, explicitly not reliable market-size predictions. The measured 1.964 seconds covers only local adapter/shard execution, not full pipeline or hosted-runner performance.
  - Two synthetic probe tests verify real adapter measurement, explicit nonqualification and bounded inputs. Full Linux regression validation passed all 1,215 tests in 301.624 seconds.
  - Resource qualification is NOT satisfied. Next: bounded indexed price reuse and lossless metadata/storage reduction, full synthetic pipeline/resource qualification, durable workflow, then one registered application/reconciliation/recording. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6 indexed execution price windows.**
  - Replaced repeated execution-adapter history parsing with a temporary hash-bound SQLite index. Each source file is parsed/validated once; execution retrieves only its requested hold window with eight cached windows. The outcome driver closes/removes the scratch index on completion or failure. Original geometry, source checks, gaps and execution rules are unchanged.
  - Retained a separate indexed synthetic probe: source reads decreased from 1,009 to 61 for the same 20 signals, with zero excess reloads. Pair JSON/gzip byte counts remain 1,138,170/67,602; local elapsed time was 1.348 seconds versus baseline 1.964, not a hosted-runtime guarantee.
  - Added three adapter tests for one-time source reading under memory eviction, exact full-source execution parity and scratch cleanup/closed-index rejection; 22 focused integration/probe tests pass. Full Linux regression validation passed all 1,218 tests in 350.911 seconds.
  - Resource qualification remains unsatisfied: independently index the audit reader, reduce lossless outcome storage, qualify the complete pipeline, then finish durable workflow and run/reconcile/record one registered application. A6.3 remains open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6 independent audit price windows.**
  - Added a separate temporary SQLite index to the independent audit reader without sharing the execution parser/index. Each bound source is parsed once; only requested hold windows enter the eight-window cache. Index cleanup is explicit on success and failure.
  - The expanded synthetic probe retains a new report, leaving both baselines intact. Execution and independent audit each read 61 files once; 1,020 candidate/control paths independently verify. Local execution/shard time is 1.308 seconds and price-audit time is 0.890 seconds. Pair bytes remain 1,138,170 JSON / 67,602 gzip. This excludes source preparation, selection/accounting/statistics audits and Git; it is not hosted-runner qualification.
  - Added eviction/read-once/window-parity and success/failure cleanup tests. Full Linux regression validation passed all 1,220 tests in 316.245 seconds.
  - Remaining: lossless outcome-storage reduction, complete synthetic pipeline and runner budgets, durable workflow, then one registered application/reconciliation/recording. A6.3 stays open; no market outcome run, promotion, merge or deployment.

- **2026-10-24 (Codex continuation): A6 lossless compact-record experiment.**
  - Added control_storage.py and an independently implemented verify_control_storage.py. Per-pair outcome and selected-feature tables store repeated values/keys once while retaining every field and row in order. Exact JSON number forms, nulls, unknown outcomes, source metadata and geometry survive reconstruction; malformed structures fail closed.
  - Retained a new synthetic probe: all 20 pairs reconstruct exactly and all 1,020 price paths independently verify from compact records. JSON decreases 1,138,170 to 251,790 bytes (77.9%); gzip decreases 67,602 to 51,140 bytes (24.4%). Packing/reconstruction/writing takes 0.229 seconds locally. Synthetic shared values are not representative market-size guarantees.
  - Four codec tests cover sparse/full cohorts, 80 varied seeded cases, type/signed-zero preservation, isolation and malformed tables. Full Linux regression validation passed all 1,224 tests in 301.098 seconds.
  - Remaining: enable a versioned compact format in the outcome driver, independent package readers and implementation bindings together; qualify full pipeline resources and failure retention; complete durable workflow, then one registered application/reconciliation/recording. A6.3 remains open. No market outcome run, promotion, merge or deployment.

- **2026-10-25 (Codex continuation): A6 compact package integration.**
  - Enabled version-two compact pair shards in the outcome driver while leaving logical aggregation and day/reuse formats unchanged. The encoder is included in reserved-source implementation bindings. Independent package/accounting and source/price/statistics audits reconstruct compact records through their separate reader; audit reports bind the decoder bytes.
  - Preserved version-one reading and original implementation binding rosters. Exact manifest encoding is required; mixed or unknown formats fail closed. Four new integration tests cover legacy accounting/full audits, encoding confusion and a packing interruption retaining earlier shards. Existing tampering tests now decode, alter and repack compact evidence before independent rejection.
  - Full Linux regression validation passed all 1,228 tests in 318.539 seconds. Remaining: diverse complete-pipeline resource measurements including summary/reuse storage, explicit runner/publication budgets, durable workflow, then one registered application/reconciliation/recording. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-25 (Codex continuation): A6 synthetic pipeline resource measurements.**
  - Added control_pipeline_probe.py and retained a four-case report covering synthetic extraction, compact outcomes, summaries/day/reuse storage and every independent outcome-audit layer. Full, mixed-quality and sparse cases independently verify 48 candidate and 1,556 control paths; the interrupted case retains three records and a failed audit. Both directions, variable holds, terminal entries and unavailable hourly slots remain explicit.
  - Full-case retained outcome files total 371,999 bytes: summary database 172,032, pair shards 64,691 and reuse shards 24,828. Outcome/audit times are 4.024/3.111 seconds locally. Summary storage exceeds pair storage at this small scale. Figures are retained sizes, not peak memory/disk or market-scale forecasts.
  - Two tests cover the complete successful/failure scenarios and bounded inputs. Full Linux regression validation passed all 1,230 tests in 316.023 seconds.
  - Remaining: larger/diverse scaling and peak-resource measurements, explicit hosted-runner/publication budgets, durable workflow, then one registered application/reconciliation/recording. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-25 (Codex continuation): A6 isolated resource measurements.**
  - Added control_resource_measure.py. Each case runs in a fresh Linux worker, reports OS lifetime peak RSS including native allocations, and directs scratch paths into an isolated directory sampled every 50 ms. Disk figures explicitly remain lower bounds on visible logical bytes, excluding unlinked/unsampled allocations and observer memory.
  - Retained eight local WSL cases: eight/32 signals per available trial and 1,000/4,000 bars, each full/mixed/sparse/interrupted. The larger full case took 8.785 seconds, peaked at 52,568,064 resident bytes and 18,592,478 sampled visible bytes. Successful cases pass independent audits; interruptions retain failures. No market-scale extrapolation or hosted qualification is claimed.
  - Proposed conservative operational budget criteria are documented, pending target-runner capacity and allocated-disk/publication measurements. Three tests cover visible-file accounting, isolated process metrics/failure evidence and bounded inputs. Full Linux regression validation passed all 1,233 tests in 341.791 seconds.
  - Remaining: allocated scratch/publication overhead, representative scale and hosted-runner budget enforcement, durable workflow, then one registered application/reconciliation/recording. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-25 (Codex continuation): A6 allocated scratch and local retention overhead.**
  - Added local synthetic Git retention verification and extended the observer to sampled allocated blocks, inode deduplication and accessible worker open-deleted files. Directory-removal races are handled; unavailable descriptor samples are reported. Git uses isolated config, disabled hooks/signing and no remote/network; every committed payload byte and tracked path is checked.
  - Retained eight measured cases. Larger full case: 19.009 seconds, 22,167,552 sampled allocated bytes, payload 1,430,675 bytes and Git metadata 669,236 bytes. Each case records one descriptor-access gap. These remain lower bounds and local measurements; combined subprocess memory and remote publication are not qualified.
  - Four new tests cover hard-link/open-deleted accounting, disappearing directories, reported descriptor denial and exact local retention of failed/partial artifacts. Full Linux regression validation passed all 1,237 tests in 458.926 seconds.
  - Remaining: representative-scale hosted measurements and conservative budget enforcement, remote retention/publication limits, durable workflow, then one registered application/reconciliation/recording. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-25 (Codex continuation): A6 fail-closed resource preflight.**
  - Added control_resource_gate.py and integrated it into the reserved-attempt wrapper before any study process. Reservation pins qualification bytes and guard implementation; source/input/protocol/profile and representative workload must match. Linux CLI snapshots available memory/free disk; bounds must fit half of memory/disk and 60% of remaining time. Missing, sampled, ambiguous or insufficient evidence refuses execution and retains failure.
  - Updated the operational publication contract without changing scientific definitions. Qualification reports require independent review; the checker does not prove measurement truth or monitor runtime usage. All retained local probes remain nonqualifying. No qualifying report or hosted market workflow was created.
  - Five gate tests plus two wrapper refusal tests cover exact boundaries, invalid/insufficient capacities, changed bindings/profile, incomplete workloads/coverage, ambiguous JSON, rejection of all local reports and retained refusal before execution. Full Linux regression validation passed all 1,244 tests in 486.838 seconds.
  - Remaining: independently reviewed representative hosted/remote qualification, durable workflow with pre-reservation and pre-execution checks, then one registered application/reconciliation/recording. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-26 (Codex continuation): A6 retained reservation ancestry checks.**
  - Strengthened the history recorder to inspect every retained commit, rejecting changed-then-restored reservations, merges, shallow history, results already present in the reservation root, and symlink/executable payloads. Reservation-only and interrupted partial records remain recordable without granting strategy authority.
  - Added five synthetic Git-history tests. All 1,249 full Linux regression tests passed in 355.933 seconds.
  - These checks establish local retained lineage, not that a reservation reached the remote before execution. Hosted resource qualification, durable remote workflow and the one registered outcome application/reconciliation/recording remain outstanding. A6.3 stays open; no market run, promotion, merge or deployment.

- **2026-10-26 (Codex continuation): A6 retained resource evidence validation.**
  - The history recorder now checks the reserved resource-guard hash against the pinned source and revalidates saved qualification/preflight bindings, capacity and bounds. Successful attempts require that evidence. Failed resource checks remain recordable with their invalid or missing reports retained for diagnosis; no result gains strategy authority.
  - Four regression tests cover missing success evidence, tampered reports/capacity/bounds, failed-preflight retention and wrong guard binding. All 1,253 full Linux regression tests passed in 329.769 seconds.
  - Revalidation checks the saved declarations, not measurement truth or remote durability. Hosted qualification, durable remote workflow and the registered outcome run/reconciliation/recording remain open. No market workflow was activated.

- **2026-10-26 (Codex continuation): A6 retention commit preparation.**
  - Added a local builder that creates a single child of the reservation-only root using a private index, raw Git blob writes and explicit identity. It preserves partial or reservation-only attempts, refuses changed observed tips/reservation bytes, symlinks and unsafe paths, and leaves branch refs and the caller index untouched.
  - Four synthetic Git tests cover partial binary bytes/index isolation, reservation-only failure, changed tip/reservation, nonroot ancestry and unsafe paths. All 1,257 full Linux regression tests passed in 344.206 seconds.
  - This prepares objects only: the future workflow must observe the actual remote tip, use a normal fast-forward push, verify retained bytes and handle concurrent changes without rerunning the study. Hosted qualification and durable remote workflow remain open; no market workflow or remote evidence branch was activated.

- **2026-10-26 (Codex continuation): A6 remote retention helper with local integration tests.**
  - Added explicit-destination publication of a prepared reservation-child commit, with fresh remote-tip checks, normal fast-forward push, exact post-push tip verification and fetch-back verification. Missing/changed reservations and divergent concurrent writers fail without retries or deleting local payloads; an already-published identical commit can be verified without rerunning the study.
  - Four tests use temporary local bare repositories only: exact partial bytes/recovery, missing/changed tips, a competing writer between observation and push, and differing fetch/push destinations. All 1,261 full Linux regression tests passed in 307.593 seconds.
  - No real remote result branch was written or market workflow activated. Reservation creation, hosted resource/publication qualification and workflow integration remain outstanding before the registered outcome run.

- **2026-10-26 (Codex continuation): A6 create-only reservation orchestration.**
  - Added a resource-gated reservation orchestrator with an injected API transport, fixed repository/branch, source-bound protocol and guard hashes, attempt-one restriction, atomic create-ref operation, and read-back verification of the orphan root, sole regular reservation file and exact bytes. Existing branches and API failures block execution; no PATCH or retry is used.
  - Six simulated API tests cover unexpected read-back tips/parents/trees, creation/repeat refusal, capacity/rerun rejection before API calls, non-404 failures, concurrent creation and a post-create verification failure that leaves the reservation blocking repetition. All 1,267 full Linux regression tests passed in 343.457 seconds.
  - This is orchestration only: authenticated transport, hosted resource/publication qualification and workflow integration remain outstanding. No real reservation or market run was created.

- **2026-10-26 (Codex continuation): A6 authenticated reservation API transport.**
  - Added an explicit-token transport restricted to the fixed GitHub repository, reservation ref and Git object endpoints. It refuses redirects, unsupported writes, wrong destinations and non-reservation trees; enforces request/response size and timeout limits; rejects ambiguous JSON; sanitizes errors and never retries mutations. Only a 404 on the exact ref GET maps to missing reservation.
  - Six mocked-transport tests cover headers/host/redirects, error mapping, no-retry timeout, destination/payload restrictions, malformed/oversized responses and complete orchestration through the transport. All 1,273 full Linux regression tests passed in 359.276 seconds.
  - No credential was read and no real API request/reservation was made by these tests. Workflow integration and representative hosted resource/publication qualification remain open before the single market attempt.

- **2026-10-26 (Codex continuation): A6 job coordination and failure retention.**
  - Added a coordinator requiring its clean pinned executing checkout and a separate fresh workspace. It reserves through the supplied authenticated API, fetch-verifies the exact reservation before execution, refreshes capacity, executes the retained wrapper and prepares/publishes the result. Execution errors/interruption still attempt retention; publication failure keeps local payload and commit for inspection. Ambiguous reservation failure never executes or retries.
  - Seven isolated orchestration tests cover pinned/clean checkout and fixed origin, ordering/capacity refresh/repeat refusal, ambiguous reservation, fetch failure, interruption, publication failure and workspace overlap. All 1,280 full Linux regression tests passed in 338.579 seconds.
  - No CLI or active workflow was installed and tests mock study/network operations. SIGKILL or runner loss still needs the future workflow's backup/recovery policy; the remote reservation blocks repetition. Hosted qualification and workflow activation remain outstanding.

- **2026-10-26 (Codex continuation): A6 reservation-first input preparation.**
  - Corrected the coordinator ordering: it now refuses preexisting input paths and invokes a supplied input-preparation stage only after remote reservation fetch verification. Capacity is refreshed after preparation before execution. The outcome wrapper copies and inventories the preparation log; preparation failure retains its partial log and a no-execution failure marker before publication.
  - Three new tests cover preexisting-input refusal, preparation failure without study execution and exact preparation-log inventory; existing ordering tests now include the preparation stage. All 1,283 full Linux regression tests passed in 334.070 seconds.
  - The concrete immutable-source preparation adapter and hosted qualification/workflow integration remain open. No market inputs were fetched and no workflow was activated.

- **2026-10-26 (Codex continuation): A6 immutable input preparation adapter.**
  - Added a callable preparation adapter for the registered archive, phase B evidence, accepted A6.2 extraction and original research-source commits. It exports raw regular Git blobs without archive filters, verifies object hashes, checks evidence/manifest SHA-256 bindings, rejects unsafe paths/links/overwrites and writes flushed per-file provenance/failure logs.
  - Five synthetic tests cover exact binary export, corrupted-blob refusal, unsafe/nonregular entries, complete multi-commit preparation with network calls replaced, and failed-fetch log preservation/retry refusal. All 1,288 full Linux regression tests passed in 320.295 seconds.
  - No market archive was fetched locally. Actual fetch/storage/runtime costs remain part of hosted qualification; connecting the adapter into the inactive runner/workflow is next. A6.3 remains open.

- **2026-10-26 (Codex continuation): A6 guarded hosted runner entry point.**
  - Connected the API client, coordinator and pinned-input adapter in a CLI restricted to the expected hosted Linux/X64 research environment, source/run identity and attempt one. It requires a qualification file/hash, uses a fresh runner-temp workspace, refreshes remaining time against one absolute deadline and reports success only after verified retention without authority.
  - Added the inactive runner integration contract, including deadline capture before setup, independent report review, backup/recovery limits and post-run recording/reconciliation. Six mocked tests cover environment/rerun checks, deadlines, wiring/capacity refresh, workspace reuse, final status and sanitized CLI errors. All 1,294 full Linux regression tests passed in 441.246 seconds.
  - No workflow references this entry point yet; no credential or market input was used in tests. Representative hosted resource/publication qualification and the guarded workflow remain outstanding.

- **2026-10-26 (Codex continuation): A6 inactive workflow and local recovery bundle.**
  - Added a documentation-only workflow template with manual trigger, repository/branch/attempt guards, fixed pre-setup deadline, independently hashed report/dependency lock, runtime-image checks, reserved runner invocation and always-run backups. It is outside .github/workflows and cannot trigger a job.
  - Added a local self-contained Git bundle helper for the recorded reservation/result. Four tests restore partial binary bytes in a fresh repository, preserve caller refs, handle reservation-only/absent records and reject wrong ancestry/overwrites. The inactive template parses, and all 1,298 full Linux regression tests passed in 318.843 seconds.
  - No qualifying report or reviewed dependency lock exists. Hosted qualification, final action/runtime/source pinning and activation sequence remain open; moving the template changes the source and must be accounted for. No market run or workflow activation occurred.

- **2026-10-26 (Codex continuation): A6 hosted synthetic pilot preparation.**
  - Added a branch-scoped, read-only Actions pilot for the existing eight synthetic scenarios, with commit-pinned actions, Python 3.10.12 and the validated NumPy/pandas/numba versions. It captures source/run/image identity, resolved dependencies, logs and report hashes, with always-run artifact retention. No market input, reservation or results-branch publication is used.
  - This is an exploratory pilot: transitive dependencies are recorded rather than hash-locked, memory excludes subprocess aggregation and sampled disk remains a lower bound. Hosted results are pending; A6 resource qualification and A6.3 remain open.
  - Validation: the workflow parses, and all 1,298 full Linux regression tests passed in 330.307 seconds.

- **2026-10-26 (Codex continuation): A6 hosted synthetic pilot results retained.**
  - Run `40315708480`, source `ee9082006088a7c249d4b4d564a707ce4e6b007a`, succeeded. All six non-interrupted cases passed diagnostic audits; both deliberately interrupted cases retained partial results and failed audits as expected. All eight local Git payload verifications passed.
  - Downloaded artifact `12647176082`, verified its SHA-256 and measurement checksum, and confirmed the report printed in logs matches the artifact bytes. Retained the original report plus environment/dependency/provenance record under `research/v9/a6_hosted_synthetic_pilot*.json`. Connected-app artifact/log retrieval now works, superseding the older environment limitation for this run.
  - Largest sampled allocated footprint: 22,163,456 bytes; maximum worker RSS: 52,199,424 bytes; slowest case: 9.810 seconds. These are small-case observations, not full-study bounds. Descriptor access gaps remain (one or two samples per case), and combined memory/remote publication are unqualified. Resolved python-dateutil 3.0.0 differs from local 2.9.0.post0: a reviewed hash-locked environment remains required. The setup log reports image 20261012.334.1 while captured ImageVersion reports 20261023.334.3; this unresolved metadata discrepancy is retained and prevents runner qualification. No market outcome reservation/run or evidence-history append occurred.
  - Validation: all 1,298 full Linux regression tests passed in 314.505 seconds; both hosted CI runs for the pilot source also passed. Next: combined-resource instrumentation and representative hosted qualification, followed by independent review before activation.

- **2026-10-27 (Codex continuation): A6 session-wide memory visibility.**
  - Isolated workers now use private Linux sessions. The observer samples summed RSS across visible session members, including child processes, and retains worker-only lifetime RSS separately. Schema /3 reports member counts and explicit unreadable/disappearing-process coverage gaps without changing prior reports.
  - Three new synthetic tests cover session membership and complex process names, malformed/negative/unreadable/vanished records, and a real child allocating 16 MiB. All nine focused observer tests pass; all 1,301 full Linux regression tests passed in 285.395 seconds.
  - This is not a physical-memory bound: shared pages may repeat, peaks/session-escaping children may be missed, and the observer is excluded. No hosted rerun or market input was used. Next: bounded resource instrumentation and representative hosted qualification, plus dependency/image reconciliation and remote retention before independent review/activation. A6.3 remains open.

- **2026-10-27 (Codex continuation): A6 kernel memory capability checks.**
  - Added read-only cgroup v2 membership/mount verification and current/peak/limit/swap/OOM-counter inspection. The synthetic observer records before/after snapshots. Unsupported layouts, unavailable/malformed counters and read errors remain explicitly unavailable; successful reads remain shared-group diagnostics, never isolated-run qualification. No system groups, limits or counters are changed.
  - Four synthetic tests cover valid shared counters/unlimited limits, missing/denied reads, unsafe/ambiguous membership and unsupported mounts, and malformed counters/events. All 1,305 full Linux regression tests passed in 286.035 seconds.
  - Local Linux lacks memory.peak at its current root group. Next: a verified isolated delegated group and workload placement for per-run kernel accounting; bounded disk/representative hosted measurements, environment reconciliation and remote-retention qualification remain open. No market run, hosted rerun or evidence-history append occurred.

- **2026-10-27 (Codex continuation): A6 isolated accounting runner.**
  - Added an opt-in runner requiring an existing delegated non-root cgroup parent. It creates a fresh child, checks empty/zero/clean baseline, verifies bootstrap placement before exec, retains kernel peak/events/logs/receipt, and records timeout/OOM/cleanup failures. It removes only its own group and does not configure the parent or enable controllers.
  - Six synthetic tests with mocked kernel/process lifecycle cover successful accounting, wrong placement, invalid input, contaminated baseline, unavailable peak cleanup, timeout and OOM retention. All 1,311 full Linux regression tests passed in 296.954 seconds.
  - No real delegated cgroup or hosted workflow was used. The outer observer and pre-migration bootstrap allocations are excluded; trusted workloads could escape the group. Thus this remains unqualified instrumentation. Next: hosted delegation/placement verification and complete-start accounting, then disk/scale/environment/remote-retention qualification. No market study, reservation, evidence-history append or deployment occurred.
