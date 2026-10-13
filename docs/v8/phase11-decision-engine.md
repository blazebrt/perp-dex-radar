# Phase 11: unified decision engine, Top-5 authority and Decision Trace

Base: `main` `413d972d60fc4a1e1666c5b56eb70275fb3e3942` (Phase 10 squash merge), tree
`412dd62f42d489af228cadf4e20cb714b3b6d7fd`. Phase 12 (the final TODAY / Analyzer experience) is not included or
authorized.

Phase 11 is the single decision authority. It answers one question:

> What should the trader pay attention to right now, why, and what prevents an opportunity from being stronger?

- **Engine:** `v8/decision.py` (`v8.decision/1`).
- **Policy:** `v8/decision_policy.json` (`v8.decision-policy/1`, `POLICY_REVIEWED_INITIAL_V1`). Independent review
  approved the rules and values, unchanged, as the initial conservative Phase 11 policy. They are reviewed policy
  choices, not empirically validated, statistically proven, optimized or backtested values. The validator accepts
  only `POLICY_REVIEWED_INITIAL_V1`: the old pending status, a free-form or "validated" label, an empty status or no
  status is refused. Policy hash `8cfcdbd7…` (proposed) became `f00cce4f…` (reviewed); only `review_status` and
  `statement` changed (a values digest is pinned by a test).
- **Output:** one canonical artifact, `data/v8/decision.json`, written whole or not at all by the audit snapshot.

The engine consumes the existing authorities and never recomputes them. It executes nothing.

## Decision-source audit (before implementation)

| Source | What it is | Phase 11 treatment |
|---|---|---|
| Registry (`v8.registry`) | Every contract of the eight market lists, with venue-reported price, volume, funding (`fund8h`, interval, source and receive time) and health | **Authority** for contracts, per-venue funding and leg data |
| Identity `v8.identity/4` and exposure binding | Asset identity state, admitted exposure contracts, exposure checks | **Authority**: TRADE requires `VERIFIED_CRYPTO`. Any other state is AVOID |
| Execution liquidity `v8.liquidity/1` | KNOWN / MISSING / NOT_ON_TRADE_DEX and the $1M gate | **Authority**, via the discovery record's `execution_liquidity` |
| Universal discovery `v8.discovery/1` | One record per discovered asset. Its flags, lanes, priority points and shadow queue have `AUTHORITY = NONE` | **The candidate set** (universal). Flags are used only as labelled positive evidence or warnings for emerging observations, never as a score |
| Venue health | Discovery venue table, coverage and fallback; per-contract health; per-asset data quality | **Authority** for the VENUE_HEALTH and DISCOVERY gates |
| Strategy policy (Phase 9) | `v8.quant-strategy-policy/1`: 3 LEGACY_HOLDOVER rows. The other 21 candidates are disabled by absence | **Authority** for STRATEGY_AUTHORITY. LEGACY_HOLDOVER is at most WATCH |
| Phase 9 gate | `v8.strategy-research/1`, 0 requalified | Bound by hash; never re-adjudicated here |
| TSMOM / TREND_EMA / XSMOM signals | `quant.py` functions; quant opens a paper trade per new signal | **Signal source**, via the quant audit recording each enabled strategy's current signal at the latest closed bar with `quant.py`'s own functions |
| Portfolio risk (Phase 10) | `v8.portfolio-risk/1` evaluation of the whole open book, and `what_if()` | **Authority** for every directional proposal |
| Radar 15m scores and strategy tournament | `conv.score` (0–100 composite) and its own pass rules | **Legacy diagnostic**: not Phase 9-governed, ungoverned score. Not decision authority |
| Coin picks swing/day scores | "Ready" at 80+, "Proven" from `picks_research.json` | **Legacy diagnostic** (survivorship-unqualified research, per Phase 8/9). Not decision authority |
| Smart money | Its own test verdicts | **Legacy diagnostic**: not Phase 9-governed |
| `quant_research.json` verdicts | Stored legacy `live` verdicts (bytes preserved by Phase 9) | **Must not** become authority |
| Dashboard `signals()` / `agreement()` | Top-12 "where signals meet", ranked by a `proven` count | **Duplicated decision logic**. The quant `proven` bit is a legacy priority bit (Phase 9) |
| Analyzer `analyze.js` | Before the correction: its own `testedSignals` / `signalCoins` call (LONG / SHORT / WAIT) with tiers and size by tier | **Duplicated and contradictory logic**. Cut over to this engine by the Phase 11 correction (see "Analyzer authority") |
| Journal funding sums | Count a missing settlement as zero | **Must not** become authority (Phase 10 decision) |
| `CFG["fund_default"]` (radar cost model) | An assumed 0.01% per 8h | **Must not** become authority. The engine never reads it (tested) |
| Market cap / popularity / volume rank | Not in the repository as history | **Must not** be used for discovery or ranking (tested) |

Other audit results:

- **Current-only data:** every live input is this scan's observation. There is no PIT history in the live engine,
  and the Phase 8 isolation test still holds.
- **Missing authorities:**
  - live journal funding;
  - research authority for funding-spread persistence;
  - a hedge model for two-leg positions (Phase 10 positions need stops);
  - research authority for the radar, picks and smart-money strategies under Phase 9 governance;
  - listing inception and market-cap history.

**Finding (pre-existing), fixed by the Phase 11 correction:** `analyze.js` gave every actionable quant position
`tier: "Proven"`, derived "Proven" from the legacy `quant_research.json` verdict `live`, made LONG / SHORT calls from
the legacy sources and sized the plan by their tiers. This contradicted Phase 9 (LEGACY_HOLDOVER /
INSUFFICIENT_EVIDENCE). Independent review classified it P1. The Analyzer's call now comes from this engine alone
(see "Analyzer authority").

## Architecture

All of this happens inside the audit; no legacy engine reads any of it:

1. **Quant audit** (`v8.audit_quant`) adds `decision_inputs` to its part:
   - current signals (`signal_states`: enabled strategies only, with direction, stop, trail, bar close time, and
     kind NEW/ACTIVE including the paper trade id);
   - the Phase 10 whole-book portfolio input, with the closed daily bars of every signalled asset;
   - the strategies' timeframe and holding horizon, the page sizing and the trade DEXs.
2. **Snapshot** (`v8.snapshot._decision`) assembles the decision snapshot:
   - discovery records and provenance, and the registry contracts;
   - the quant inputs, the Phase 9 policy states and the Phase 10 audit state;
   - the previous published `decision.json`;
   - the authority hashes.

   It then calls `decision.build()`, writes `data/v8/decision.json` and adds `manifest.decision` and
   `data_health.decision`.

   The **decision time** (`as_of`) is the latest knowledge time among this scan's inputs (`decision_as_of`): the
   scanner header, discovery, the quant run, the portfolio and the latest contract receipt. Every input is then at or
   before it. The engine refuses any input after its decision time (as `INPUT_STALE` or missing funding). The first
   exact-head Research run showed why: venue funding is received a second after the scanner header time, and the
   quant run comes minutes later, so the header time alone made every live candidate look stale and unfunded.
3. **Engine** (`decision.build` / `decision.evaluate_asset`): a pure, deterministic, standard-library module. It has
   no I/O except reading its policy, and Phase 10's.

Audit version `v8.audit/10` / `v8-phase11.0`: the snapshot gains a mandatory `decision` manifest section and a new
published artifact.

## Decision states

The precedence is fixed in the policy as `AVOID > WATCH > TRADE`:

| State | Meaning | Rule |
|---|---|---|
| **TRADE** | The governed evidence is sufficient to present the opportunity as trade-ready for discretionary human consideration | Every gate PASSes, and the type may be TRADE (only `DIRECTIONAL_STRATEGY`) |
| **WATCH** | A credible current reason to monitor, without the authority or readiness to call it trade-ready | No gate FAILs, and at least one is CAP (a governed ceiling) or MISSING (an absent authority) |
| **AVOID** | Do not take this opportunity now under the governed rules (a current decision, not a permanent verdict) | Any gate FAILs (a known disqualifier) |

Unknown is never TRADE. Every missing input is a MISSING gate, never a neutral zero: not zero funding, not zero
slippage, not liquid, not crypto, not uncorrelated, not safe.

## Opportunity types and gates

Every discovered asset gets one asset record. It holds its best state, its opportunities, its identity, liquidity and
data quality, and its asset-level trace. An asset with no opportunity is AVOID with `NO_CURRENT_OPPORTUNITY`.

### `DIRECTIONAL_STRATEGY` (only a Phase 9-governed strategy signal)

| Step | PASS | CAP (WATCH) | MISSING (WATCH) | FAIL (AVOID) |
|---|---|---|---|---|
| DISCOVERY | In qualified universal discovery | — | Fallback universe or unqualified discovery; inputs not from this scan (`INPUT_STALE`) | Not in discovery or no active supported perp |
| IDENTITY | `VERIFIED_CRYPTO` | — | — | `IDENTITY_NON_CRYPTO` (tradfi); `IDENTITY_NOT_VERIFIED` (unverified, ambiguous, none) |
| ECONOMIC_EXPOSURE | No conflict | — | `EXPOSURE_METADATA_DEGRADED` | `ECONOMIC_EXPOSURE_CONFLICT` |
| VENUE_HEALTH | Data quality HEALTHY | — | `VENUE_DATA_DEGRADED` | — |
| SIGNAL | Current: the bar closed within 18000 s (4h) or 90000 s (1d) | — | — | `SIGNAL_INVALID`, `SIGNAL_STALE`, `SIGNAL_TIMEFRAME_UNKNOWN`, `POSITION_ALREADY_OPEN` |
| STRATEGY_AUTHORITY | ACTIVE_REQUALIFIED / REQUALIFIED | `STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT` (LEGACY_HOLDOVER, PAPER_ONLY) | — | `STRATEGY_DISABLED`, `STRATEGY_RESEARCH_REJECTED/INVALIDATED`, `STRATEGY_UNGOVERNED` |
| EXECUTION_LIQUIDITY | KNOWN at or above the gate | `EXECUTION_LIQUIDITY_BELOW_GATE` | `EXECUTION_LIQUIDITY_UNKNOWN` | `NOT_ON_TRADE_DEX` |
| FUNDING | A fresh observed rate on a healthy trade-DEX contract (OBSERVED or OBSERVED_ZERO) | — | `FUNDING_UNKNOWN` | — |
| PORTFOLIO_BEFORE | Phase 10 state of the whole open book (recorded) | | | |
| PROPOSED_TRADE | Quantifiable proposal with known fees and slippage | — | `PROPOSAL_UNQUANTIFIABLE`, `COST_UNKNOWN`, `PORTFOLIO_INPUT_MISSING` | — |
| PORTFOLIO_AFTER | Phase 10 after-state WITHIN_LIMITS | `PORTFOLIO_APPROACHING_LIMITS` | `PORTFOLIO_UNEVALUABLE` | `PORTFOLIO_LIMIT_BREACHED` |
| RISK_LIMITS | Breached and approaching limits and their changes (recorded) | | | |
| DECISION_STATE | The resolved state and its rejection step | | | |

- **Strategy authority** comes directly from the Phase 9 policy rows. It is never derived from profitability,
  Sharpe, wins, scores, names or rank. A strategy absent from the reviewed policy (Phase 9 disables the other 21 by
  absence) is AVOID `STRATEGY_UNGOVERNED`. The live quant desk evaluates only enabled strategies, so a disabled
  strategy has no live signal.
- **Signals.** The quant desk paper-opens every new signal at once. A NEW signal's own just-opened paper position is
  taken out of the book for its what-if, which then shows its marginal effect. Any other open position with the same
  strategy, asset and direction is AVOID `POSITION_ALREADY_OPEN`.
- **Proposal.** Mark is the discovery reference price, and stop is mark x (1 - direction x stop_pct). Sizing is the
  page default (`PAGE_DEFAULT_SIZING`: account x risk per trade). Liquidity comes from the record. Funding is the
  most adverse fresh observed rate among the asset's admitted, healthy trade-DEX contracts (venue, interval and
  receive time kept). The holding horizon is the strategy's `hold_h`. Entry and exit are both still to pay.
- **Portfolio.** Phase 10 `what_if()` evaluates the proposal against the whole open book, actionable and
  identity-blocked. Phase 10 limits are unchanged, and no portfolio model is recomputed here. APPROACHING_LIMITS is
  capped at WATCH: a conservative policy with no evidence justifying trading into the approach band.

### `EMERGING_OBSERVATION` (always at most WATCH)

**Evidence.** Positive evidence comes from labelled discovery flags plus a current enabled-strategy signal whose own
decision is WATCH:

| Discovery flag | Evidence | Primary? |
|---|---|---|
| `NEW_LISTING` | `RECENTLY_OBSERVED_BY_DESK` (first seen by this desk, not a listing date; `NEWLY_LISTED` is never claimed) | Yes |
| `STAGE1_EXTREME` | `LARGE_24H_MOVE` | Yes |
| (a WATCH directional decision) | `CURRENT_STRATEGY_SIGNAL` | Yes |
| `MULTI_VENUE` | `MULTI_VENUE_PRESENCE` | No (supporting) |

**Qualification.** An emerging candidate needs at least one primary item. It passes through the same identity,
exposure, venue and execution gates. Below-gate or missing liquidity is allowed as WATCH; NOT_ON_TRADE_DEX is AVOID.
It is always capped (`NO_GOVERNED_STRATEGY_AUTHORITY`).

**What it never does.** There is no target multiple, no "3–5x", no market cap, and no new alpha model. Warning flags
(funding extreme, price dispersion, OI/volume, thin or missing liquidity, single venue) are reported, never counted as
evidence. An AVOIDed signal is never evidence.

### `FUNDING_SPREAD` (`FUNDING_SPREAD_OPPORTUNITY`, always at most WATCH)

**Legs.** Health is part of pair eligibility (Phase 11 correction).
- A leg can only be an active, admitted trade-DEX perp with fresh venue-reported funding **and a HEALTHY contract**.
  An unhealthy contract is never a candidate leg: it is not chosen and then flagged, so a degraded venue with an
  extreme rate cannot hijack the pair. The SIGNAL gate records the eligible venues and the unhealthy ones excluded.
- At least two such contracts on different venues are required. With fewer there is no funding-spread candidate at
  all: never a zero or "no spread" finding, and never stale funding, a default rate or journal funding in its place.
- The long leg is the lowest rate and the short leg the highest; ties break by venue name.

**Gates.**

| Gate | Requirement |
|---|---|
| Spread | Positive |
| Each leg's own venue volume | At or above the execution threshold (`LEG_LIQUIDITY_BELOW_GATE` is AVOID) |
| Carry | Over 24 h at current rates, minus four taker fills and both legs' slippage tiers (the Phase 10 cost constants), must be > 0 (`CARRY_NOT_POSITIVE_AFTER_COSTS` is AVOID) |
| Basis | Within 0.5% (`BASIS_TOO_WIDE` is AVOID) |

**Always capped.**
- There is no research authority for funding persistence (`FUNDING_SPREAD_RESEARCH_AUTHORITY_MISSING`).
- Phase 10 has no hedge model (`PORTFOLIO_HEDGE_MODEL_UNAVAILABLE`).
- Every candidate carries `NOT_RISK_FREE`.

**Interval normalisation.** Normalisation is the scanner's 8h-equivalent; venues settle on different intervals, and
the interval is kept.

## Sections, ranking and Top-5 behaviour

| Section | Holds | Max | Ranking rules (policy, in order) |
|---|---|---|---|
| `best_trades_now` | TRADE `DIRECTIONAL_STRATEGY` | 5 | NEW before ACTIVE; fresher; cheaper slippage tier; smaller after-state executable risk; asset; strategy; direction |
| `emerging_opportunities` | WATCH `EMERGING_OBSERVATION` (assets not already in Best Trades Now) | 5 | More primary evidence; more evidence; fewer outstanding blockers; asset |
| `funding_opportunities` | WATCH `FUNDING_SPREAD` | 5 | Larger net carry; smaller basis; asset |

**How ranking works.**
- Ranking happens after the state is decided, among eligible states only. No rank can override a gate.
- There is no weighted score. Every ranking input is visible as `ranking_inputs`, and every rule lives in the policy.
  Volume, market cap and popularity are not ranking inputs (the policy validator refuses unknown fields).
- Each section is up to five, never a minimum, and a WATCH is never promoted.

**Selection trace.** Each section's `selection_trace` answers:
- why A ranks above B: `order`, the first differing rule;
- why #6 is out: `cutoff`, and `EXCLUDED_BY_SECTION_MAXIMUM` with its rank;
- why there are fewer than five: `why_fewer`;
- which gate removed an otherwise strong candidate: `removed_by_gate`, with its step and codes.

## Decision Trace

Every opportunity carries `trace`. Each entry is `{step, input, rule, result, code, effect}` (INPUT -> RULE -> RESULT
-> EFFECT), covering every step from DISCOVERY to DECISION_STATE. Its `placement` adds RANKING and SECTION_PLACEMENT.

Explanations:
- **AVOID** exposes `rejection_step` and the exact blockers.
- **WATCH** exposes `why_interesting`, `why_not_trade`, `missing_authority` and `to_become_trade` (each capping or
  missing step and rule).
- **TRADE** exposes `why_trade`, the rule of every passed gate.

## Validity horizon

`valid_until` (document and every candidate) is the time after which the decision's own policy ages would no longer
hold: the document horizon is the earliest declared input time (or the decision time) plus
`freshness.max_input_age_s`; a directional candidate also ends at its signal bar plus `signal.max_age_s` for its
timeframe and at every used funding observation's receipt plus `funding.max_rate_age_s`; a funding spread at its
legs' receipts plus `funding.max_rate_age_s`. It re-decides nothing: it tells a consumer when to stop relying on the
decision and fail closed.

## Analyzer: the same engine

`evaluate_asset(snapshot, asset)` runs the same `_evaluate_asset` code path as `build()`. A test proves the one-asset
and market-wide results are byte-identical in state, gates, blockers, evidence, ranking inputs, authority and trace.
Rank and section are market-relative, so they come only from `build()`.

## Analyzer authority (Phase 11 correction)

The Analyzer's call (`analyze.js` `decide` / `signalCoins`, shown by `analyze.html`) is governed by the published
`data/v8/decision.json` alone. The JavaScript reads the governed result; it re-implements no gate (identity, strategy
authority, funding, portfolio risk, liquidity or the state).

| Phase 11 on the analyzed coin | Analyzer |
|---|---|
| A directional candidate is TRADE (current) | LONG or SHORT in the decision's direction only, with the quant desk position's own stop, trailing stop and time limit, sized at the chosen risk |
| WATCH | `WATCH`: no call, no plan, no size; the exact caps and missing authorities, and what Phase 11 needs before it can be a trade |
| AVOID | `AVOID`: no call, no plan; the rejection step and blockers |
| No directional candidate | `WAIT`: no call; legacy sources cannot manufacture one |
| Document missing, malformed or past `valid_until`; a malformed or expired decision on the coin; TRADEs disagreeing in direction | `WAIT`: fail closed, never a fallback to the old authority |

- Only a Phase 11 TRADE has a risk share (`RISK_SHARE = {TRADE: 1}`). Legacy signals keep their own levels as context
  and are never sized.
- A quant desk position is labelled by its Phase 9 deployment state (`Legacy holdover` / `Requalified`, as on the
  Quant desk page), never "Proven"; its old research record is a "Legacy record".
- Swing and smart-money records keep their own labels as legacy records ("Proven record"); they cannot make, promote,
  flip, size or block a call.
- The chart read's own sized plans are no longer shown when there is no call, and they are no longer sent to the
  optional AI note, whose instructions now name the Phase 11 decision as the only source of the call.
- `signalCoins` (the page's quick list) lists only coins with a current Phase 11 TRADE.
- `analyze()` (the chart read engine, also used by the research tools) is unchanged and labelled context.

## Change explanation

The snapshot reads the previously published `data/v8/decision.json`, using the same mechanism as first-seen and
identity state. For every candidate, `changes` reports:
- previous and current state, rank and section;
- the blockers added or removed;
- the ranking inputs that changed;
- whether the policy changed.

On the first Phase 11 scan there is no previous governed snapshot. The result is then `previous_available: false`,
`NO_PREVIOUS_PHASE11_AUTHORITY`, and no past rank is inferred.

## Authority binding

`decision.json` `authority` records:

| Authority | What is recorded |
|---|---|
| Identity | Version and config hash |
| Discovery | Schema and the exact document hash |
| Strategy policy | Schema and hash |
| Runtime implementation | Hash (`b14aa0ab…`, unchanged) |
| Phase 9 | Version, gate hash and implementation hash |
| Phase 10 | Policy hash and implementation hash |
| Phase 11 | Decision policy hash, review status and implementation hash |

`authority_hash` is the digest of all of them. A changed ranking rule changes the policy hash and the authority hash
(tested, and mutation-checked).

## Audit

`manifest.decision` holds:
- schema, policy hash, implementation hash and authority hash;
- the market summary, section counts, top selections and blocker histogram;
- degraded authorities and trace availability;
- the portfolio binding (Phase 10 audit state = engine book state);
- the file SHA-256 and the previous-decision source.

`data_health.decision` holds the status. History records are unaffected.

## Legacy-output preservation and parity

- `quant.py`, the scanner, picks, smart money, dashboard, the other pages, the planner, the strategy policy and the
  Phase 10 limits are unchanged.
- The one approved legacy delta is the Analyzer authority cutover. The Phase 11 golden differs from the Phase 10
  golden only in the `analyze.js` and `analyze.html` digests (and so the combined digest), and the delta manifest
  pins both files to their exact base and head digests (`ANALYZER_PHASE11_AUTHORITY_CUTOVER`). Every engine output,
  universe, identity, DEX status, decision, signal, ranking, stop, size and journal is identical.
- New outputs are audit-only: `data/v8/decision.json`, the quant part's `decision_inputs` and the snapshot's decision
  section.
- Earlier tests changed for the intentional audit-version bump (`v8.audit/10`). One Phase 10 isolation test now
  lists `v8/decision.py` as the one new reader of the portfolio-risk authority. The correction changed the Analyzer
  tests that asserted the old legacy authority (a "Proven" quant tier, legacy LONG / SHORT calls, legacy sizing and
  legacy quick-list coins) to the Phase 11 authority, and added the Analyzer-authority tests.

## Current truth and limitations

- **Zero TRADE today.** With today's Phase 9 truth, zero strategy-based TRADE opportunities is the expected and valid
  result: every live strategy is LEGACY_HOLDOVER.
- **Book state.** Live funding of the open book is MISSING (Phase 10), and the paper book has been over its limits.
  A directional proposal is therefore AVOID (`PORTFOLIO_LIMIT_BREACHED`) or WATCH (`PORTFOLIO_UNEVALUABLE`) even with a
  requalified strategy.
- **Funding spreads** are always WATCH (no persistence research, no hedge model).
- **Emerging evidence** is limited to discovery's observational flags and current WATCH signals: no listing date, no
  market-cap history, no participation history.
- **Sizing** is the page default, not a real account.
- **Cutoff.** Only the quant strategies (Phase 9-governed) create directional opportunities. Radar, picks and smart
  money stay legacy diagnostics until governed.
- **No historical decision research.** There is no historical Phase 11 research because no qualified PIT overlap
  exists, and none is fabricated.

## Boundary with Phase 12

Phase 12 may render `decision.json` and call `evaluate_asset()`. It owns the TODAY layout (Best Trades Now, Emerging
Opportunities, Funding Arbitrage, Portfolio), the Analyzer redesign, navigation and styling. The Phase 11 correction
changed only the Analyzer's call authority and the wording that names it, not its layout.
