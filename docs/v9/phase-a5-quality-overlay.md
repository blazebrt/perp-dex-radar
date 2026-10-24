# A5 corroborated reconstruction and quarantine protocol

Registered after the source diagnostics and before building or replaying the
derived dataset. The 66 corroborated and 28 unresolved blocks are known findings,
not an unseen validation sample. This is a retrospective source-quality mask,
not evidence that these data defects were known at historical decision time.
All original protocols, source archives, schedules and diagnostic reports remain
unchanged. This additive protocol does not confer strategy or production authority.

## Bound evidence

- Rejected collection: result commit `003ddccc825b5aeaec1beab834c56f21b8baa9a8`.
- First trade diagnostic SHA-256:
  `4eaa3297b048621b4cd0931c95d408e51cd49aa497687953793903af0c1ba22e`.
- Quote-precision diagnostic record SHA-256:
  `6dde68dab77446a81a1fd5400acf9887348f9231fa8664dbddffe23c7e7c0394`.
- Adjacent-day diagnostic record SHA-256:
  `cf24e659052f3f56beee178e08c3ad84a60bd4ba835170bdc0a096cd53c2ce04`.

Require matching schemas, source objects, segment identities and block timestamps
across reports; verify every input artifact hash before using it. Missing or
changed evidence aborts rather than silently reducing the mask. No additional
market-data investigation is required to choose which blocks qualify under
this policy, and no strategy returns may influence the choice.

## Reconstruction and exclusion

1. Reproduce the 94 disputed blocks. A block is a corroborated reconstruction
   only if all six product-volume/price aggregates match the pinned four-hour
   source under the existing tolerance AND its local continuity check passes,
   incorporating the separately verified adjacent-day result where applicable.
   The known evidence yields 66 such blocks. This does not prove completeness
   of the provider's entire trade history.
2. In a separate derived archive, replace all four hourly rows for those blocks:
   OHLC from the first trade diagnostic and quote/taker-buy quote volumes from
   the price-times-quantity diagnostic. Do not replace only the failing field.
   Require all four candidate hours to exist and have positive observed trading.
   Preserve before/after values, hashes, reason and evidence references.
3. Quarantine all four hours of each remaining disputed block (28 known cases).
   These hours are unavailable for research execution; preserve the original
   observations in the original archive and explicit quarantine records. Never
   interpolate missing trade IDs, prices or volumes to restore continuity.
4. Preserve every other observed hour, every existing gap, all zero-trade hours,
   original segment boundaries and funding bytes. No forward fill, relisting
   merge or replacement with assumed funding is allowed. Report original gaps
   and newly quarantined hours separately, as well as their nonduplicated union.

## Ranking uncertainty

Keep the original top-150 daily schedule and its candidate order unchanged.
Never refill a slot or rank against reconstructed performance. Because a bad
volume observation can affect the cutoff for OTHER coins as well as its own,
embargo ALL new entries on every scheduled UTC day whose preceding seven-day
volume window intersects any quarantined four-hour block. Determine the exact
day set from timestamps, not from observed membership changes or strategy outcomes.
Keep empty and embargoed days in the calendar. Report this restriction and its
coverage cost separately from the original universe-selection protocol.

Outside embargoed days, the frozen top-150 list is only a ceiling: the replay
must also satisfy its ordinary signal/data eligibility rules. Existing missing
hours cannot be treated as zero volume or as evidence of an executable price.

## Dataset validation and later replay

The implementation must first be tested with synthetic evidence for corrupted
bindings, boundary joins, complete replacement, overlapping masks, ranking-window
endpoints, no backfill and preservation of unaffected data. Then build a new
versioned artifact with a complete hash manifest, repair/exclusion ledger and
coverage report. Independently verify every modified row, mask and embargo day.
Publish no completion marker on a partial or failed build. A completed derived
archive must be labelled conditional on this retrospective quality policy; it
must not be represented as the original fully observed archive.

Before A5.3 market replay, commit the execution adapter's contiguous-lookback,
indicator reset/warm-up, funding and exit-gap rules. A position spanning an
unobservable execution or funding interval must remain explicitly unresolved;
never drop that trade, assign a convenient exit, or turn unknown returns into
zero. Incomplete return paths make affected trial/family statistics unavailable,
unless separately pre-registered defensible bounds support a stated result.
Retain all attempted definitions and failures. A4.4 must continue to disclose
the different universe and this additional quality restriction.

Implementation, derived-data acceptance and strategy replay remain pending.
