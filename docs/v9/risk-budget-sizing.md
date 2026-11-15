# Constrained incremental position sizing

Implemented 2026-11-15 on draft PR #30. Policy version 4 is explicitly pending owner merge review; no production activation occurred.

## What changes

Each directional candidate receives a covariance-aware allocation against the existing governed book. Existing positions remain fixed. The candidate's original tier-adjusted stop-risk allowance is an upper bound, never an invitation to increase leverage. A reduced allocation is passed through the existing Phase 10 what-if calculation, costs, stress scenarios and limits. Those rules are unchanged; the smaller proposal can legitimately change its after-state.

The candidate reports its size, target and actual variance-contribution shares, daily volatility, common-return count, last observation time and each existing position's target/actual contribution. Missing input produces no proposed size and cannot support TRADE. The method does not rewrite journals or place orders.

## Calculation

Use common closed daily log returns under the unchanged Phase 10 trailing-window and minimum-overlap policy (currently 60 bars and at least 30 common returns). Require a common return ending within the latest daily interval. The candidate and every retained position use exactly the same observation dates. Future bars cannot contribute. Missing, duplicate, stale or degenerate history is unavailable.

Tier budget is the square of its size multiplier: FULL has budget 1 and the current half-size probation tier has budget 0.25. This is a proposed allocation policy, not a fitted economic claim. Let V be the fixed book's return variance, c its covariance with a unit candidate exposure (including direction), v the candidate variance, and b its share of the sum of tier budgets. For candidate notional/equity x, its variance contribution is x(c + vx), and total variance is V + 2cx + vx². Solve:

`(1-b) v x² + (1-2b) c x - bV = 0`

Take the positive root using a cancellation-resistant calculation, then cap x by the existing tier-adjusted stop-risk allowance divided by stop distance. Recalculate actual contribution shares after the cap. Nonpositive candidate contribution, negative existing contributions, nonfinite arithmetic or an unavailable existing book fail closed. With no existing positions, a valid nonzero volatility history is still required, and the original tier allowance is retained.

## Acceptance boundary

This completes the **incremental sizing implementation**, not E2's broader whole-book parity objective. Fixed existing positions may already have unequal risk contributions, and the cap can prevent the new position reaching its target. The output explicitly reports `whole_book_parity: false` for a nonempty book. Equalizing all existing positions would require a separately specified rebalance recommendation, turnover/cost treatment and review; this change does not silently perform or claim one. E2 remains unchecked in the handover.

Covariance is a trailing historical estimate, not a guarantee of future risk. Perfectly hedged/degenerate books and unsupported negative contributions remain unavailable rather than acquiring unlimited capacity. Phase 10 remains the final authority for limits.

## Validation

Tests include a hand-calculated perfectly correlated pair (doubling candidate volatility halves its full-tier notional), the probation budget, binding stop-risk caps, missing/stale/duplicate/constant history, future-bar invariance, invalid tiers/numbers, preservation of the original book, and the actual decision/Phase 10 path. Existing tests still cover breached books and prevent ranking from overriding a block. Expected assertions for the previous larger size and missing-size diagnostics are updated explicitly.

`risk-budget-delta.json` pins source hashes and intentional output changes. `risk-budget-golden.json` pins complete before/after synthetic decision hashes and the independently checked 0.005 to 0.0025 stop-risk change, while confirming nonportfolio gates and input records are unchanged. Earlier E1 goldens remain historical records of that earlier commit. Final validation: all 1,426 Linux regression tests passed in 321.005 seconds. The focused consumer/engine checks passed after preserving the exact-proposal contract; a narrow scope guard now permits only the sizing import and also checks that helper for market-context dependencies. Earlier incomplete/failing runs were retained locally, then the complete suite was rerun on the final malformed-ID fix. Legacy differential parity passed with zero unexpected changes; `risk-budget-legacy-parity.json` retains the report. Existing legacy golden bytes are unchanged, and the new decision-output hashes are pinned separately.
