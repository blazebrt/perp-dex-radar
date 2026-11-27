# B9 follow-up dispositions

Prepared on 2026-11-16 in draft PR #30. These are implementation/disposition decisions pending owner merge review, not independent scientific review or production activation.

## Strategy status

Keep TREND_EMA as LEGACY_HOLDOVER / INSUFFICIENT_EVIDENCE, with no TRADE authority. The bound `research/v9/probation_evidence.json` records NOT_CONFIRMED for both sides. Long fails checks b, c, d, e, g, i and j; short fails b and c. A positive point estimate for the short side is not confirmation, and failure to confirm is not proof that every possible effect is zero. The earlier handover wording “no edge” was too absolute. No strategy-policy row, runtime definition, confirmation threshold or evidence record changes. A REJECTED policy transition is not necessary to remove the unsupported Emerging boost and is not inferred from these results.

## Emerging evidence

Previously, any WATCH directional signal except an explicitly unconfirmed probation side could count as CURRENT_STRATEGY_SIGNAL. This included legacy/paper-only signals and probation sides demoted by their forward test, missing registration or expired entry window. That could create an Emerging candidate or increase its evidence count despite insufficient strategy authority.

Draft decision policy version 6 requires exactly one passing STRATEGY_AUTHORITY gate on the WATCH directional candidate before including its signal as Emerging evidence. No rule grants a new TRADE. Independent discovery flags can still support an observational WATCH, with no unsupported signal contribution. Authorized strategies held at WATCH by other gates remain eligible as observations. The original directional diagnostics are retained. Removing evidence can change Emerging selection/counts/ranking and the derived asset summary, as declared in `emerging-authority-delta.json`; five pinned synthetic before/after decisions are in `emerging-authority-golden.json`.

## Qualified outcomes versus demotion diagnostics

Retain the registered all-closed-paper-record demotion diagnostic. `v8.audit_quant.forward_tests` publishes its closed count/mean separately from `qualified_closed` and `qualified_mean_R`; `v8.decision._forward_test` uses the registered closed count/mean. Qualification still requires the frozen execution/funding proof checked by `quant.qualified_trade`. The Performance page explicitly labels the forward summary as a diagnostic that may include unqualified paper outcomes. It does not label the all-closed mean as qualified net performance.

This is not proof that the all-closed statistic is unbiased: unqualified wins as well as losses can influence it. We do not switch the registered population after observing outcomes, use qualified-only selection to rescue results, or award new authority from the diagnostic. Any different qualification population or demotion band requires a separately registered rule and review, not a silent edit of this experiment. The current disposition is to preserve the registered rule and disclose its limitation.

## Signal frequency

Keep XSMOM's top-five selection and maximum 20% stop unchanged. No trade is a valid outcome when the frozen signal has no eligible entry. There is no lowered threshold, extra strategy or synthetic trade to fill the page. Additional trade authority still depends on the separately tracked research items.

## Verification and acceptance

Regression cases cover legacy/paper/rejected strategies; valid authorized WATCH and TRADE; unconfirmed, missing, not-yet-effective, expired and failed probation authority; and independent discovery observations. A parent-version comparison verifies unchanged directional candidates, proposals, gates, best-trade/funding sections, portfolio, tier summaries and source inputs. The full five-case before/after golden uses the actual parent decision module and policy. Existing source-bound research and legacy output goldens remain unchanged.

B9's four follow-ups now have explicit dispositions and the Emerging correction is implemented. This completes B9 implementation/review preparation; merge review and production verification remain release requirements. It does not complete the remaining research roadmap.

Final validation: 1,447 Linux regression tests passed in 362.538 seconds; all 29 focused frontend/authority checks passed. The frontend fixture now supplies independent move flags to retain its original trace-coverage minimum. Legacy fixtures reproduce exactly and differential parity reports zero unexpected changes (`emerging-authority-legacy-parity.json`).
