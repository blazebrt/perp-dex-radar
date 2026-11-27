# Whole-book tier-weighted balancing

Implemented 2026-11-16 in draft PR #30. E2's planning implementation now includes both incremental candidate sizing and a whole-book target. Policy version 5 remains pending owner merge review; nothing is activated in production.

## Contract

The decision's `portfolio.rebalance` model covers every governed open position. It preserves assets, sides and strategy identities. Each target is capped by the current notional and the original tier-adjusted stop-risk allowance. It never adds exposure, flips a side, removes a difficult position from the calculation, modifies a journal or places an order. Unknown or identity-blocked positions make the model unavailable.

The model uses the same closed daily return window and minimum common coverage as Phase 10. All positions share the same dates; future data is excluded, stale common history is rejected and zero/unknown volatility never becomes a usable allocation. Direction-adjusted sample covariance is calculated from those aligned returns. The target fraction of variance contribution is proportional to the square of each tier's size multiplier.

Positive coordinate descent solves the risk-budget objective `0.5*x'Cx - sum(b_i*log(x_i))`. Each coordinate has an analytical positive root; a cancellation-resistant expression is used. Acceptance requires positive contributions and a maximum risk-share error no larger than 1e-8. The final scaled targets are checked again from the covariance matrix, independently of the convergence flag.

Numerical limits are explicit: at most 64 positions, 2,048 sweeps and 32 uniform scale attempts. These are operational bounds, not fitted trading thresholds. Nonconvergence, degenerate hedges and numerical failure return UNAVAILABLE without target rows. No regularization is silently added to make a failed model pass.

## Reductions, costs and limits

The parity shape is scaled uniformly beneath every current-notional and tier stop-risk cap. One-way reduction turnover is priced at the existing Phase 10 taker fee and each position's known slippage tier. Both estimated costs are deducted from the supplied paper-account equity before the target book is evaluated. Cap checks use that lower equity too.

If the modeled after-book is approaching or breaching a limit, or a post-cost cap is exceeded, the scale is halved and evaluated again. Uniform scaling preserves the risk-budget proportions. The model does not claim to maximize capital use or minimize turnover. Costs exceeding the available equity, missing costs, unavailable risk evaluation or exhausted scale attempts yield no verified target.

Only a WITHIN_LIMITS after-book with verified parity receives MODEL_WITHIN_LIMITS. The report retains current/target notionals, reductions, target and modeled contribution shares, turnover, estimated fees/slippage, post-cost equity, numerical diagnostics and the Phase 10 after-summary. The actual book and all candidate gates/proposals remain unchanged by this read-only model.

## Product and authority

Portfolio displays the target beside the actual governed book, including costs and the limitations. Stale decision documents, incomplete targets and inconsistent authority flags are withheld. Labels are escaped and no execution controls are added.

This is a hypothetical paper-account planning model, not an executable order list or a claim about future realized risk. Venue lot sizes, minimum orders, execution sequencing and actual fills are not modeled. The input equity is the supplied account budget; no live NAV, realized PnL or historical trade qualification is inferred. `trade_authorization` and `existing_positions_changed` remain false. Whole-book parity is true only for a successfully verified model, never for the actual unchanged book.

E2's software/planning acceptance is complete. Production activation remains subject to merge review and a post-merge Scan check; an execution product would require additional venue-specific work outside this paper desk's scope.

## Verification

Tests cover analytic inverse-volatility solutions, a perfectly correlated pair, mixed-asset risk shares independently recomputed from price paths, tier weights, both sides, order invariance, modeled fees/slippage and post-cost caps, unchanged inputs/candidates, unknown and malformed data, empty/single-position books, future invariance, bounded failure, degenerate hedges, unaffordable turnover, and Portfolio rendering/escaping/fail-closed behavior.

`rebalance-delta.json` pins the source changes and intended output scope. `rebalance-golden.json` pins full synthetic before/after decision hashes using the actual parent code and parent sizing module; every candidate and the actual portfolio match after removing only the new model field. The existing legacy golden changes only for `desk.js`; all numerical output files, legacy decisions and the audit inventory match the parent golden before acceptance. Validation: all 1,437 Linux regression tests passed in 373.192 seconds. Differential parity passed with zero unexpected changes and reproduced both pinned goldens; `rebalance-legacy-parity.json` retains the report. The Portfolio panel was checked with the JavaScript runtime for rendering, escaping, missing/inconsistent targets and stale-document rejection; no browser visual inspection is claimed.
