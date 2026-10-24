# A6.3 execution and inference preregistration

Registered before any A6 market matching or outcome calculation. A4/A5 outcomes
and the A6.2 signal inventory have already been inspected; this is exploratory
historical research, not an unseen-data qualification. No market matching or
outcomes may run until the adapter, tests, durable reservation/publication and
independent verification are committed. This document does not itself launch a run.

## Frozen inputs and population

Use the 4,263,580 retained signals from extraction result
`eb785a908dce572958336649291b8feeb4ee9575`, source
`269cb2b0360310ac6bac9fd5ef8b102505c6d997`, and its verified original archive
`4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7`. Preserve the census plan SHA-256
`7910cb5678771db32e2ebfe162a916c5cd7ff209987a598f6be6c4f470551af1` and all 199
trial identities. Seven hourly populations remain unavailable. Do not regenerate
or tune strategy signals, substitute the restricted A5 archive, or rerun A5.

Every retained signal gets exactly one matching disposition and one candidate
attempt, including false eligibility, missing features and terminal signals.
Match all eligible original panel assets using the frozen A6.1 selector, original
decision-time eligibility and independently reconstructed A6.2 feature windows.
Preserve its same-symbol exclusions, fixed buckets and deterministic ranking.
No replacement, widened buckets or post-outcome filtering is permitted.
Relisted segments retain distinct identities and cannot share price history.

Retain 0–49 controls for insufficient cohorts, but do not compute a paired contrast
for them. A contrast requires the pre-outcome status `DIAGNOSTIC_COHORT_50`.
Signal ordinals remain distinct even when their asset/time/geometry are identical;
reuse of the same selected cohort is retained and counted. Deduplicated storage
or execution caching is allowed only with exact inputs and references that
reconstruct every original ordinal and all 50 ordered selections.

## Hypothetical paired execution

Each candidate/control attempt is an independent hypothetical trade. There is no
portfolio budget, cross-signal position filter or one-position-at-a-time gate.
This deliberately estimates signal-conditional contrasts, not an implementable
portfolio return. Overlapping attempts and repeated controls must remain visible.
Candidate and controls use the signal's identical direction and raw geometry:
`stop` is a fraction of entry price, `target` and `be` are multiples of initial
risk, `trail` is a fraction of entry price, and `hold` is the original positive
integer number of four-hour panel bars. Daily generators already return panel-bar
holds; do not multiply them by six again. No outcome-based clipping or tuning.

Entry is at the original decision timestamp, at the next four-hour candle open.
False original eligibility prevents candidate entry; controls must satisfy their
own original eligibility. Eligibility is measured at the signal decision and
must not be replaced by end-of-study membership. The signal-close/entry-open
coincidence is a bar-model assumption, not zero real execution latency.

Require a real, finite, valid positive OHLC candle and positive observed quote
volume for entry. Missing, known-disputed or zero-volume entry bars produce an
unexecuted attempt, not delayed entry. Positive volume is a retrospective
execution-observability condition, not information known at that candle's open.
Reject all original 94 disputed four-hour blocks for execution, regardless of
which field was disputed. This is retrospective, incomplete quality screening.

After entry inspect consecutive four-hour bars, counting the entry bar as hold
bar one. A missing, disputed, malformed or zero-volume bar makes the remaining
price outcome unresolved at that timestamp. Do not skip, fill, interpolate or
liquidate at a preceding close. Archive end before the planned exit is censored.
Unknown outcomes do not prevent unrelated hypothetical attempts; there is no
shared portfolio state to recover. They never become zero returns.

Initial risk is entry price times the stop fraction. At each observed bar:

1. On later bars, an opening price beyond the active stop exits at that open.
2. Otherwise a touched stop exits at the stop; stop wins if stop and target both
   touch. A target-only touch exits at the target, including favorable opening
   gaps, without awarding a better price.
3. If neither touches and this is the final hold bar, exit at its close.
4. Otherwise update a close-based trailing stop from the most favorable close
   since entry, offset by entry price times `trail`. Apply it from the next bar.
   If this bar's favorable high/low excursion reaches `be` initial-risk units,
   move the next bar's stop to entry if that tightens it. Never loosen a stop.

Stop and target checks precede the time exit. A zero target/trail/breakeven
parameter disables that mechanism. Intrabar exits are labelled with the candle
close as their reporting resolution, not an exact intrabar event time.

Price-only gross R is `direction * (exit/entry - 1) / stop`. Fixed modeled costs
are 0.045% taker fee plus 0.10% slippage on entry; market/stop/time exit has the
same cost, while target exit uses 0.015% maker fee without extra slippage. Costs
are fractions of entry notional, matching the registered A5 convention. Report
`price_after_cost_R = gross_R - cost_fraction/stop` with that exact label;
it excludes funding and is not net R or evidence of actual venue fills.

## Funding and paired missingness

The current broad archive does not prove complete settlement coverage or exact
intrabar exit timing. Therefore this registration sets `net_R=null` and
`funding_path_known=false` for every entered hypothetical attempt. Observed
settlements may be retained as observations, never substituted for a complete
funding total. Missing rows are not zero and no eight-hour schedule is assumed.
No future funding value enters matching. Establishing complete funding and
settlement/exit ordering would require a new registration; it cannot be silently
added to this run after seeing outcomes.

For each pre-outcome 50-control cohort, a price-only contrast is available only
if candidate and all 50 selected controls have observable price exits. It is
candidate price-after-cost R minus the arithmetic mean of the 50 control values.
If any member is unexecuted/unresolved, retain the cohort and its reasons with a
null contrast. Do not reduce the control count, replace it, assume zero, pair
only survivors or rank signals by realized outcomes. Sparse-cohort outcomes may
be retained individually but are excluded from paired contrasts by the fixed
pre-outcome rule. Net contrasts are unavailable under this registration.

## Estimands, dependence and inference

Report every trial and both directions, including empty directions and seven
unavailable hourly trials. The fixed family has 398 trial/direction slots;
combined-side descriptive summaries do not create an alternative testing family.
For each slot retain total signals, each matching disposition, candidate/control
entry and price-path dispositions, fully observable 50-control cohorts and all
missingness counts. Report matching coverage against all original signal ordinals
in that slot, never just resolved trades. Full eight-dimension coverage is not
established by the diagnostic three-dimension selector.

The primary intended estimand is mean net candidate-minus-control R across the
pre-outcome 50-control population. It is unavailable here because funding is
unresolved. Its estimate, confidence interval, p-value, full-family DSR/PBO and
net bootstrap statistics must be null with an explicit funding reason. A missing
p-value must never pass a significance or multiplicity gate.

Secondary price-only summaries are descriptive: arithmetic mean candidate and
control R, paired difference mean and median, minimum/maximum, and counts. The
resolved-only subset must be labelled conditional on observable outcomes, with
its missing denominator beside it. Do not present its mean as the full-population
effect. If any pre-outcome pair is unresolved, the corresponding complete-pair-
population price mean is also unavailable, even though the conditional summary
may be reported. No confidence interval, p-value, ranking-based winner selection
or edge claim is permitted for those conditional summaries.

Retain per-UTC-decision-day sums and counts, and control-asset/time reuse counts,
so dependence remains auditable. Do not treat 50 controls, overlapping trades or
repeated signal ordinals as independent replicates. No resampling, daily t-test,
effective-sample-size shortcut or multiple-testing adjustment is run in this
registration: all 398 inferential slots are explicitly unavailable. A future
inferential registration must address shared-control and temporal dependence,
hold-length-aware calendar blocks, day clustering, missing outcomes and the
complete 398-slot family before computing any inferential result.

## Required implementation and acceptance

Before one market application, commit a new four-hour execution adapter, bounded
streaming matcher/aggregation, exact input/output/protocol hashes, a durable
attempt reservation and append-only evidence-run support. Do not change the
evidence-bound legacy simulator or A5 kernel. Synthetic tests must cover both
directions, exact geometry units, stop/target ambiguity, opening gaps, next-bar
trailing/breakeven, time/censored exits, zero/missing/disputed prices, false
eligibility, sparse cohorts, duplicate/reused controls, unknown funding, complete
versus conditional denominators and invariant selection under future/outcome
changes. Independent verification must reconcile all original signal identities,
control ranks, execution paths, costs, counts and null inferential fields.

One retained market attempt under this registration is recorded as a new A6
outcome study in the append-only evidence history, including failures and
unavailable results. Keep the A6.2 inventory as its separate immutable input.
The existing Phase 9 authority gate stays unchanged; every output has
`full_matched_authority=false` and `promotion_authority=false`. A6.3 remains open
until implementation, application, recording and independent reconciliation;
complete net-outcome qualification remains unavailable under these inputs.
