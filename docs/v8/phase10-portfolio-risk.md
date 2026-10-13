# Phase 10: portfolio and risk realism

Base: `main` `19596979d4d2f2e700f4a405c4a76c667b167f04` (Phase 9 squash merge), tree
`f1d9f7f59f6b05c747874c5c2755dd98176972e5`. No Phase 11 work is included.

Phase 9 decides whether a single strategy has research authority. Phase 10 answers a different question: **when
several positions are open at once, what is the portfolio-level risk** after shared exposures, dependence,
concentration, liquidity, leverage, funding, execution costs and adverse conditions?

The answer is one governed, versioned, deterministic authority, `v8.portfolio-risk/1` (`v8/portfolio_risk.py`). Its
thresholds live in one reviewed policy file, `v8/portfolio_risk_policy.json` (`v8.portfolio-risk-policy/1`). The
authority observes and reports; it never sizes, ranks, opens or closes a trade, and no engine reads it back.

## Baseline found before Phase 10 (unchanged by this phase)

| Area | What the code assumed | Why that is optimistic, stale or ungoverned |
|---|---|---|
| Independence | `quant.py` and `quant.html` size every position on its own (account x risk / stop) | No correlation, beta, shared-asset or same-direction view; no portfolio stop-risk cap. |
| Leverage | `quant.html` shows `notional / account` per position; `qport.simulate` caps 5x per position, 10x total, 60 open, 20 per strategy | The page has no cap. The simulator's caps are unlabelled literals that nothing reviews; leverage there is a capacity, not a risk. |
| Stops | `sim_trade` and `qsim` fill at the stop price, except a gap through the open | No stop-slippage stress and no statement that a stop is not a maximum loss. |
| Funding | `sim_trade` adds `fund.get(t, 0.0)`; legacy research data fills unobserved funding | A missing settlement counts as zero, so a journal's funding is not an authority. |
| Liquidity | Live slippage is today's tier for today's position (correct for now) | No degraded or unknown-liquidity risk, and no separation of theoretical versus executable risk. |
| Planner | `qexport` growth planner bootstraps legacy backtest days at fixed-fraction risk | Already labelled `LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY`. Its survivorship, independence and cost assumptions are Phase 8/9 limitations. |
| Presentation | The only portfolio numbers shown are the legacy planner and account curves | There was no governed current-portfolio risk anywhere. |

Phase 10 does not change any of these legacy paths (see [Parity](#parity-and-change-control)). It builds the
governed authority beside them, as the Phase 10 brief prefers when changing legacy numbers would add scope risk.

## What Phase 10 does not solve

- No Top-5 engine, no TRADE/WATCH/AVOID ranking, no opportunity boards, no Decision Trace UI and no redesign. These
  are Phase 11 and remain unauthorized.
- No execution, no sizing recommendation, no automatic de-risking.
- No fitted tail model, VaR or expected shortfall: the repository has no qualified portfolio history to fit one.
- No historical portfolio backtest: the legacy planner is untouched and still labelled a diagnostic.
- No new data source: funding stays MISSING live (see [Funding](#funding)).

## Policy versus empirical evidence

Every number in `portfolio_risk_policy.json` carries a `basis`:

- **POLICY**: a reviewed choice (every limit, the approach band, every dependence and stress setting, the tail
  sample minimum).
- **GOVERNED_CONSTANT**: the cost constants shared with the cost model: taker fee 0.045% (`v8.fees/1`) and the
  scanner's slippage tiers. Tests bind them to `quant.CFG` and `pit_cost`.

The schema rejects any other basis, including `EMPIRICALLY_VALIDATED`. No limit is statistically proven, because
Phase 9 has 0 PIT overlap days and 0 fully qualified trades. `review_status` is `POLICY_DEFAULT_PENDING_REVIEW`. The
only empirical quantity is the observed tail loss beyond stops in identity-qualified closed trades
(`stop_realism.empirical_tail`). It is labelled `EMPIRICAL_DIAGNOSTIC`, it is `INSUFFICIENT` below 100 trades, and it
never sets or validates a limit.

Policy defaults (reviewable in one file):

| Limit | Default | Measured as |
|---|---|---|
| `max_position_leverage` | 2.0 | position notional / equity |
| `max_gross_leverage` | 3.0 | sum of absolute notional / equity |
| `max_net_leverage` | 1.5 | absolute value of (long notional - short notional) / equity |
| `max_executable_risk` | 3% | sum of (stop risk + expected fees and slippage + adverse funding) / equity |
| `max_asset_stop_risk` | 1% | stop risk of every position on one asset |
| `max_strategy_stop_risk` | 2% | stop risk of one strategy |
| `max_side_stop_risk` | 2.5% | stop risk of all longs, or of all shorts |
| `max_cluster_stop_risk` | 2% | stop risk of one dependence cluster |
| `max_stressed_loss` | 6% | worst governed stress scenario |
| `approach_fraction` | 0.8 | at or above this share of a limit is APPROACHING |

`v8/portfolio_risk.py` holds no threshold literal; a test parses it to check that. Another test mutates every policy
value and requires the governed result to change.

## Portfolio risk model

All quantities are fractions of equity unless named `*_usd`.

**Trade level.** Each position reports:

- direction, entry, mark, stop, stop distance, quantity, notional and leverage;
- account risk (stop distance x leverage), in R units (nominal 1R, stressed 1 + gap);
- expected fees: one order for an entered position, two for a proposal;
- expected slippage, only from a KNOWN `v8.liquidity` volume tier;
- expected funding: direction x rate x hours/8 x leverage. Accrued funding is reported when observed, otherwise
  UNKNOWN;
- remaining planned holding hours;
- three risk figures:
  - theoretical stop risk;
  - expected executable risk: stop + costs + adverse funding; credits never reduce it;
  - degraded-liquidity bound: unknown liquidity pays the worst tier x `unknown_liquidity_multiplier`.

**Exposure.** Gross, long, short and net leverage and USD. Net never offsets gross; the net limit applies to the
absolute value.

**Concentration.**

- Per asset, per strategy and per side, as notional and as stop risk.
- Largest, top-3 and top-5 shares of nominal exposure and of stop risk, by position and by asset.
- Shared assets, offsetting assets (long and short on one asset) and multi-strategy assets.
- `strategy_overlap`: which strategy pairs hold the same asset.
- Positions on one asset are one exposure. Their stop risks add, even in opposite directions (a conservative choice).

**Dependence.** Computed only from daily closes closed at the evaluation time (point-in-time):

- pairwise Pearson correlation of log returns;
- beta to the market asset (BTC);
- down-market correlation, on bars where the market return is below 0: a diagnostic only.

Settings: trailing `lookback_bars` (60), `min_overlap_bars` (30), `min_regime_bars` (15).

- Same-asset pairs count as correlation 1.
- Direction-adjusted correlation (d_i x d_j x rho) clusters positions at `cluster_correlation` (0.7) or above.
  The cluster limit is the dependence limit.
- `diversified_stop_risk` (sqrt(r' rho r)) is reported next to the independence and no-diversification figures. It
  is a DIAGNOSTIC: it assumes losses scale with return correlation, so it is never a limit.
- A missing pair is `DEPENDENCE_UNAVAILABLE`, never independence. A missing beta is `BETA_UNAVAILABLE`.

## Liquidity

The authority distinguishes:

- **theoretical stop risk**: the stop is hit at its price;
- **expected executable risk**: plus fees, slippage under the KNOWN liquidity tier, and adverse funding;
- **degraded bound**: unknown liquidity at the worst tier x the multiplier.

MISSING, NOT_ON_TRADE_DEX, an invalid KNOWN volume, or a liquidity input that is absent is never zero slippage and
never a tier. Executable risk is then unavailable.

Historical states take liquidity only from the point-in-time history:
`tools/research/portfolio_risk_pit.historical_liquidity` uses `v8.pit.History.liquidity_at(t, asset)`. It keeps a
value KNOWN only when the record is fresh and precise enough to decide every tier threshold. A v8.history/1 value, or
a value recorded on a threshold, is `LIQUIDITY_PRECISION_UNQUALIFIED`. Live modules never import `v8.pit`; the
Phase 8 isolation test enforces this.

## Funding

- **Known funding** (OBSERVED, or OBSERVED_ZERO with rate 0): expected cost is signed. A long pays a positive rate; a
  short receives it.
- **Credits** never reduce executable risk.
- **Unknown funding** (MISSING, an invalid rate, or no holding horizon): `FUNDING_UNKNOWN` / `HOLD_HORIZON_UNKNOWN`.
  It is never zero, and the portfolio cannot be WITHIN_LIMITS.
- **Cumulative exposure for held positions**: accrued funding is reported when observed, with a list of positions
  whose accrual is unknown.

The live desk has no authoritative funding input. The journal's funding sums count a missing settlement as zero.
The live evaluation therefore reports every position `FUNDING_UNKNOWN`, and its state is UNEVALUABLE unless a limit
is already breached. That is the truthful state.

## Stress scenarios

All six scenarios are deterministic. Their sizes are POLICY, and no probability is attached. Losses are fractions
of equity.

| Scenario | Rule |
|---|---|
| `CORRELATED_MARKET_MOVE` | Market factor +/- `market_move` (10%). Each position moves by its beta. Losses are capped at the stop; hedge gains count. The worse direction is used. Needs every beta. |
| `DIVERSIFICATION_FAILURE` | Correlation spike: correlations go to 1 against every position, so every stop is hit at once, plus expected costs. |
| `STOP_SLIPPAGE` | Every stop fills `stop_gap_fraction` (50%) of its distance beyond the stop, plus costs. |
| `EXECUTION_COST` | Every stop is hit, with fees and slippage at `cost_multiplier` (2x). |
| `LIQUIDITY_DEGRADATION` | Every stop is hit. KNOWN volumes pay `liquidity_tier_steps` (1) tiers worse. Unknown liquidity pays worst tier x 2. |
| `FUNDING_DETERIORATION` | Every stop is hit at the end of the remaining horizon, after paying max(`adverse_funding_8h` = 0.05%, observed adverse rate) per 8 hours. |

A scenario missing an input is UNAVAILABLE and reports its known lower bound. The stressed-loss limit uses the
worst available loss or lower bound. An unavailable scenario is never a pass.

**Stop-loss realism.** `stop_realism` reports:

- normal stop risk;
- the gap/slippage allowance (POLICY, not a fitted tail);
- adverse cost (executable risk minus stop risk);
- the empirical tail diagnostic.

**Leverage realism.** The authority reports leverage per position, gross and net, and leverage after a proposed
position (via what-if), each against its limit. Leverage is never treated as risk capacity: every risk limit is
grounded in equity, stop geometry, liquidity and adverse execution.

## Risk states (fail-closed)

| State | When |
|---|---|
| `UNEVALUABLE` | Policy, equity, `as_of` or the positions list is invalid; or any required authority is missing and no limit is already proven breached. |
| `LIMIT_BREACHED` | A metric is above its limit. A known lower bound above a limit is a proven breach, even with authorities missing. |
| `APPROACHING_LIMITS` | Every authority is present, no breach, and a metric is at or above `approach_fraction` x limit. Exactly at a limit is APPROACHING, never BREACHED. |
| `WITHIN_LIMITS` | Every authority is present and every metric is below the approach band. |

Missing-authority codes:

- `POSITION_MALFORMED:<id>`, `STOP_MISSING:<id>`, `STOP_WRONG_SIDE:<id>`;
- `LIQUIDITY_UNKNOWN:<id>`, `FUNDING_UNKNOWN:<id>`, `HOLD_HORIZON_UNKNOWN:<id>`;
- `DEPENDENCE_UNAVAILABLE:<a>|<b>`, `BETA_UNAVAILABLE:<asset>`;
- `EQUITY_INVALID`, `AS_OF_INVALID`, `POSITIONS_INVALID`, `PORTFOLIO_RISK_POLICY_INVALID`.

A malformed position is excluded from every sum and blocks WITHIN_LIMITS. Unknown never becomes safe.

## What-if contract

`what_if(portfolio, proposal)` evaluates the portfolio before and after one change, under the same policy:

- `{"action": "ADD", "position": {...}}`: a proposal pays entry and exit;
- `{"action": "REDUCE", "id": ..., "fraction": (0, 1]}`.

It returns:

- `before` and `after` summaries (state, breached, approaching, missing authorities, every metric, every limit
  status);
- the full `before_result` and `after_result`;
- per-metric `delta` and `limit_changes`;
- `effect`, with an `explanation` and a trace.

`effect` takes the first of these that applies:

1. `INSUFFICIENT_AUTHORITY`: the change makes the portfolio UNEVALUABLE, or adds missing authority.
2. `BREACHES_LIMIT`: a newly breached limit.
3. Otherwise, from the metric deltas: `REDUCES_RISK`, `INCREASES_RISK`, `MIXED` (for example a hedge: gross up, net
   down) or `NO_CHANGE`.

`PROPOSAL_INVALID` covers a bad action, a duplicate ID, an unknown REDUCE ID or an invalid fraction. The input
portfolio is never modified. `authority` is `DIAGNOSTIC_NO_EXECUTION_NO_RANKING`, and the public API has no ranking or
execution function.

## Trace contract

Every evaluation carries a `trace` of `{category, input, rule, result, effect}` entries (INPUT -> RULE -> RESULT ->
EFFECT), in this fixed order:

1. `POLICY`, `EQUITY`;
2. one `POSITION` per position;
3. `GROSS_EXPOSURE`, `CONCENTRATION`, `DEPENDENCE`, `LIQUIDITY`, `FUNDING`, `STRESS`;
4. one `LIMIT` per limit;
5. `STATE`.

What-if adds `PROPOSAL`, `PROPOSED_TRADE_RISK`, one `LIMIT_DELTA` per changed metric, and
`FINAL_PORTFOLIO_EFFECT`. Phase 11 can consume this trace; no UI renders it yet.

## Audit and provenance

- **Live evaluation.** `v8.audit_quant.portfolio_risk_part` evaluates the scan's actionable open paper positions:
  - sizing is the page's default (`CFG["account"]` x `CFG["risk"]` per trade at the entry stop distance), recorded
    as `PAGE_DEFAULT_SIZING`;
  - liquidity comes from `v8.liquidity` on this scan's universe;
  - returns come from the scan's closed daily bars;
  - funding is MISSING.

  It never raises: an error is UNEVALUABLE `PORTFOLIO_RISK_ERROR`.
- **Snapshot.** `v8.audit/9` / `v8-phase10.0`. The snapshot carries:
  - `manifest.portfolio_risk`: version, policy schema, policy hash, review status, bases, the SHA-256 of
    `v8/portfolio_risk.py`, the policy file and `v8/audit_quant.py`, and the compact evaluation (state, breached,
    approaching, missing authorities, limits, exposure, stress);
  - `data_health.portfolio_risk`: the state;
  - a `portfolio_risk` section: the full result with inputs and trace.
- **Unchanged.** `v8.history` records only selected manifest fields, so the append-only history is unaffected.

## PIT guarantees

- Returns are read only for bars closed at `as_of` (bar start + bar seconds <= as_of), inside the window ending at
  `as_of`. Appending, or changing, a later or unclosed bar never changes an evaluation (tested).
- An evaluation whose bars all lie before the window is UNEVALUABLE, never stale data.
- Historical liquidity comes only from `v8.pit`. Historical funding has no point-in-time portfolio input and stays
  MISSING.
- Market cap, listing age and future identity are not inputs.

## Parity and change control

Phase 10 changes no legacy output:

- `quant.py` is byte-identical, and the Phase 9 runtime implementation hash is still `b14aa0ab…`;
- policy hash `f2e10f99…`; runtime order `[TSMOM, TREND_EMA, XSMOM]`; all three LEGACY_HOLDOVER;
- 24 candidates; 199 known trials;
- unchanged: universe, identity, discovery, signals, rankings, stops, sizing, journal, TODAY, Analyzer, smart money,
  radar and picks;
- the dashboard and quant page are untouched.

`tests/fixtures/v8/legacy_parity_golden_phase10.json` equals the Phase 9 golden (combined `c41c6c7f…`).
`tests/fixtures/v8/phase10_expected_deltas.json` authorizes no delta at all. Only audit outputs (under `data/v8/`,
never digested as legacy files) and the audit version change.

## Current limitations

- Every limit and stress size is a POLICY default pending review. None is empirically validated.
- Live funding is not an authority, so the live state is UNEVALUABLE unless a limit is already breached.
- Live sizing is the page default, not a real account. Identity-blocked journal positions are counted but not
  evaluated.
- Dependence uses at most 60 daily returns. It is a short, regime-specific sample, and the down-market correlation
  is a diagnostic only.
- Same-asset opposite positions add their stop risks: conservative, not netted.
- The market-move scenario caps losses at the stop price. Gaps are covered separately by STOP_SLIPPAGE.
- The fee schedule is one constant for every venue and date (`v8.fees/1`).
- No historical portfolio backtest under PIT authority. The legacy planner keeps its survivorship and independence
  assumptions and its diagnostic label.
- The research-side PIT liquidity adapter exists. No historical portfolio state is evaluated yet, because there is
  no qualified PIT history overlap.

## Boundary with Phase 11

Phase 11 may later call `evaluate()` and `what_if()` and render their traces. Phase 10 provides only the authority,
the machine-readable result and its audit. It does not rank, select or present opportunities.
