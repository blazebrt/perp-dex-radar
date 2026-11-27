# A6 feature-window quality specification

Additive to `phase-a6-control-design.md`, before A6 market application. The
original broad four-hour archive and strategy definitions remain unchanged.
This stage constructs diagnostic input rows only; it neither generates market
signals nor selects market cohorts nor simulates outcomes.

## Known disputes and coverage

Use every original disputed four-hour block identified by the A5 audit (94
blocks across 87 segments), without treating subsequent corroboration of some
blocks as permission to alter this source. The source-binding adapter must
derive the exact segment/timestamp inventory from the pinned A5 audit artifacts,
verify those hashes and counts, and register that inventory before market use.
The accepted hourly quality ledger can corroborate identities but must not
replace the original four-hour files or broad-universe membership.

A seven-day volume window intersecting any original disputed block is unavailable
for cohort matching. This is a retrospective source-quality exclusion, not a
historically observed decision input. Keep the unavailable row and reason;
never drop the signal denominator, fill volume, replace a candle or widen a
bucket to recover control coverage. The rule deliberately covers all original
disputes rather than only the ultimately unresolved subset.

The A5 audit covered the hourly-selected subset. Absence from that dispute
inventory is not exhaustive validation of the broad four-hour universe.
Every output must state `KNOWN_DISPUTES_ONLY_NOT_EXHAUSTIVE` and keep full
authority false. Missing actual listing metadata, historical market cap and
other Phase 9 dimensions remain missing.

## Exact feature construction

Inputs are original segment ID/symbol/first-bar metadata, ordered four-hour
timestamps and quote volumes, exact decision timestamp and direction, the
unchanged strategy eligibility flag, and an explicit dispute inventory. A
missing inventory is an error, not an empty mask. The eventual file adapter
must bind the inventory and source bytes; the pure helper cannot establish
that external provenance itself.

1. Require integer aligned timestamps, nonnegative finite numeric volumes,
   unique ascending rows, and exact equality of first-row time with the segment
   metadata's first bar. Reject malformed data rather than silently sorting,
   deduplicating, coercing booleans or interpreting missing values as zero.
2. At decision time `t`, let `end=floor(t/86400)*86400`. Require exactly the
   42 opens `end-7 days, end-7 days+4h, ..., end-4h`. A bar opening at `end`
   cannot influence volume. All required bars are closed by `end <= t`.
3. An absent bar yields `UNAVAILABLE_MISSING_VOLUME_BAR`; any intersection
   with a disputed open yields `UNAVAILABLE_DISPUTED_VOLUME_BAR`. Retain both
   reasons when both occur and retain explicit missing/disputed timestamps.
4. Otherwise use `math.fsum(42 volumes)/7`. Zero volume is observed zero and
   counts as an observation. The selector separately applies minimum volume,
   archive-age and bucket rules. No prices or return outcomes enter this helper.
5. Label first-bar age as archive-segment age. Record reconstructed availability
   at first-bar close and volume-window close, not a claim of genuine historical
   publication time. Keep `ARCHIVE_RECONSTRUCTION` provenance.
6. Preserve input eligibility; this helper must not turn an ineligible row into
   an eligible one. A missing/unavailable feature must be unusable by the cohort
   selector. Keep source-window hashes over the exact available window records
   and relevant dispute timestamps for later independent verification.

The resulting window status does not qualify the signal or its outcome. The
full signal adapter must retain all generated signals, describe original
indicator-history gaps/conflicts separately, bind the unchanged generator, and
independently reconcile its complete population. Do not reset or filter the
generator without a separately registered definition. Execution and inference
remain subject to the later registration required by A6.1.

Synthetic acceptance: exact UTC/window boundaries, all 42 observations,
observed zeros, missing/disputed overlap, invalid/duplicate input rejection,
relisting first-bar identity, future-append invariance, preserved eligibility,
and integration proving unavailable rows cannot enter a diagnostic cohort.
