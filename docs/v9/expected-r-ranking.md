# Expected-net-R directional ranking

E1 implementation, 2026-11-14, draft PR #30. Not activated in production; the proposed policy explicitly awaits owner merge review.

## Behavior

After the existing decision gates, eligible directional candidates sort by descending out-of-sample archive mean net R. The remaining tie-breaks stay signal kind, age, execution cost, portfolio risk, asset, strategy and direction. Unknown estimates sort after known estimates, including negative ones: unknown is never converted to zero. Ranking cannot turn WATCH or AVOID into TRADE, alter a proposal or bypass a Phase 10 limit.

The source is the existing validated strategy-policy adapter's bound probation evidence. Each candidate retains the mean, lower/upper 95% interval and evidence file/hash in `ranking_expectation`. The numerical mean also appears in `ranking_inputs.expected_net_R`, so existing section selection and adjacent-order explanations report the rule that decided the position. Intervals remain alongside the candidate and the existing probation evidence presentation.

Only `out_of_sample_*` estimates are used. The all-window/design-window statistic and current forward results cannot substitute. Nonfinite/bool/string values, inverted intervals and absent or malformed evidence references produce UNAVAILABLE. The upstream adapter remains responsible for validating the original file contents and policy binding; this code does not claim that a well-formed hash alone verifies an arbitrary input.

## Interpretation and boundaries

This is an archive strategy-side mean net of the archive's costs and observed funding. It is not an estimate adjusted for this coin's current spread/funding, a new inference study, or a promise of realized return. The interval describes uncertainty in the archive mean, not the distribution of one trade. All candidates of the same side share the estimate; existing execution and age tie-breaks resolve equal means.

The current FULL-tier adapter supplies no comparable estimate, so it remains explicitly unknown. No new evidence or qualification is fabricated to populate it. Adding an expectation for a future full-tier strategy requires its own bound, comparable evidence adapter and review. E1 is implemented for the currently available governed evidence; E2 volatility/tier sizing and E3 evidence-dependent regime gating remain separate.

## Verification

Focused tests compare positive/negative/unknown means, opposing age order, equal estimates, malformed intervals/bindings, ignored design-window values and failed forward gates. They verify unchanged gates, sizes, portfolio calculations and input snapshots. A comparison against the actual parent implementation additionally checks every candidate after removing only ranking/placement fields and verifies the whole portfolio document remains equal.

`expected-r-delta.json` pins the parent, changed engine/policy hashes and intentional output differences. `expected-r-golden.json` pins the complete before/after synthetic decision hashes and observed order. These supplement the legacy parity harness, which deliberately excludes `data/v8/` from its legacy digests. Final validation: all 1,418 Linux regression tests passed in 353.576 seconds. The initial full run found one outdated scope assertion; it was narrowed to explicitly permit the new helper, then the complete suite passed. Legacy differential parity reproduced both pinned goldens with zero unexpected changes; its retained report is `expected-r-legacy-parity.json`. Existing legacy golden bytes are unchanged because no legacy output changed; the new decision-output golden is pinned separately.

No strategy signal, research definition, journal, published page or risk limit was changed. No production activation occurred. This change remains on the draft development branch.
