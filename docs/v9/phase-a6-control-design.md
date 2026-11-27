# A6 matched-control design and cohort specification

Fixed before any A6 market-data matching or outcome calculation. Prior A4/A5
results have already been inspected; this is not an unseen-data qualification.
The existing Phase 9 authority gate and evidence-bound code remain unchanged.

## Scope and authority

Start with every generated signal of the 192 four-hour/daily definitions in
`research/v9/census_replay_plan.json` (SHA-256
`7910cb5678771db32e2ebfe162a916c5cd7ff209987a598f6be6c4f470551af1`).
Use the pinned phase-B archive `4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7`
and A4 source `ad2374fa4d25f03c204ce7c0cdbecac95cba6246` to reconstruct
unchanged definitions. Preserve all signal identities after the registered
warm-up, including signals subsequently blocked by position state. The existing
executed-trade files alone are not a complete signal denominator. Preserve the
seven hourly identities as unavailable; do not rerun the frozen A5 registration.

A6.1 implements cohort selection only. It neither evaluates outcomes nor marks
the matched-control gate satisfied. Phase 9 additionally requires BTC beta,
realized volatility, point-in-time liquidity, market cap, actual listing age,
funding, trend state and market regime, with full matching for at least 90% of
signals and at least 50 controls per signal. Time/liquidity/archive-age matching
does not establish those conditions. Historical market-cap and actual listing
provenance remain unestablished. Archive-derived measurements must not be
labelled `PIT_OBSERVED`.

## Fixed A6.1 diagnostic cohort

- Input rows describe one immutable pre-entry snapshot per segment at the exact
  signal decision timestamp and direction. Require `ARCHIVE_RECONSTRUCTION`
  provenance. A row includes asset segment ID, original exchange symbol,
  eligibility, mean daily quote volume over the seven preceding complete UTC
  days, its window end, and that segment's first observed bar. The adapter must
  prove all 42 four-hour observations exist before constructing a volume value.
  No missing-volume fill, current volume, future listing filter or end-of-study
  survivorship filter is allowed.
- The volume window ends at the latest UTC midnight at or before the decision.
  Both volume and first-bar information must have availability timestamps no
  later than the decision. The seven-day window is exact and complete; a stale
  snapshot is unavailable. Same-time rows with wrong direction or ineligible
  status cannot become controls.
- Archive age is `(decision_time - segment_first_bar) / 86400`, not true listing
  age. Relistings restart at their own segment's first bar. Minimum archive age
  is 30 days. Fixed age buckets in days are `[30,90)`, `[90,180)`, `[180,365)`,
  `[365,730)`, `[730,infinity)`. Fixed mean-daily quote-volume buckets in USD are
  `[5M,10M)`, `[10M,25M)`, `[25M,50M)`, `[50M,100M)`, `[100M,infinity)`.
  Upper boundaries enter the next bucket; no quantile fitting or bucket widening.
- Match exact decision time, direction and both buckets. Exclude the signal's
  segment and every segment with the same original exchange symbol. Require
  unique eligible asset IDs and original symbols at a timestamp; reject ambiguous
  overlaps rather than choosing a surviving relisting.
- Choose exactly 50 distinct controls without replacement when available.
  Rank eligible matches by ascending SHA-256 of canonical JSON
  `["v9.a6-cohort/1", trial_id, decision_time, direction, signal_asset, control_asset]`,
  using UTF-8, compact separators and `ensure_ascii=False`; break hash ties by
  asset ID. This deterministic sampling cannot depend on future outcome, net R,
  signal performance or input order. Reuse across separate signals is allowed
  and must be accounted for in later inference.
- If fewer than 50 match, retain every available match and report insufficient
  controls. If the signal's features are missing or invalid, retain an
  unavailable record. Never broaden buckets, sample with replacement, select
  controls after seeing exits, or replace a control whose later outcome is unknown.
- Record counts of eligible, feature-unavailable, bucket-mismatched, same-symbol
  excluded and matching candidates. Include selected row provenance and rank
  hashes. Every result carries `full_matched_authority=false` and
  `promotion_authority=false`, even with 50 selected controls.

## Required later stages, before any outcome study

The phase-B archive has known source disagreements and gaps documented during A5.
Pin and register their A6 disposition before market matching: verify the relevant
feature inputs, retain exclusions/uncertainty, and do not silently substitute the
restricted 690-segment hourly archive for the broad four-hour universe. This
selector's synthetic validation does not accept the archive for new qualification.

1. Build a source/hash-bound adapter for the full generated-signal population,
   segment identities and decision-time features. Independently verify signal
   completeness and feature windows. Retain failures and all 199 trial identities.
2. Commit a separate execution/inference registration before matching market
   data or calculating any control outcome. Specify exact signal geometry,
   stop/target/trail/hold and costs, missing-price and funding behavior, candidate
   versus control execution consistency, position-state treatment, correlated
   control reuse, daily clustering/block inference, all-side multiplicity and
   incomplete-denominator reporting. Outcome-dependent selection is prohibited.
   This document does not authorize using legacy gap fills or zero funding to
   claim fully qualified outcomes.
3. Test once under that committed registration, record all results in the
   append-only evidence history, and independently reconcile the matches and
   outcomes. Missing Phase 9 dimensions keep the result diagnostic; no gate or
   live policy change follows from having 50 controls alone.

A6 remains open. A6.1 is complete only when the selector and synthetic tests
establish bucket boundaries, exclusion, unique controls, deterministic selection,
future/input-order invariance and explicit unavailable/insufficient status.
