# A5.3 funding coverage and compatibility disposition

Registered before hourly market replay; no strategy outcomes inform this decision.
This adds the explicit unavailable-coverage disposition permitted by the execution
contract, without modifying the original evidence-bound collector or strategies.

## What the retained funding archive establishes

The original `archive_fetch.py` writes observed settlement timestamp, rate and an
optional interval hint. Its source parser can skip malformed records, and the
retained settlement file has no independent per-hour absence-of-payment proof.
Neither a regular sequence of eight-hour records nor a row's interval hint proves
complete coverage. A future replay must not infer zero funding between rows.

`hourly_funding.py` parses the exact retained schema. It rejects duplicate times,
malformed rows, nonfinite rates and invalid interval hints. Observed zero is kept.
Off-grid events are retained separately, never rounded. No record or interval hint
produces a true completeness mask: all requested execution hours remain unknown.
The module returns `UNAVAILABLE_SOURCE_COVERAGE` and an empty completeness mapping.
A newly supported independent coverage source would require another registration.

Price-only definitions may produce gross-price diagnostics, but any entered trade
has unresolved net funding under this disposition. The existing execution/batch
contracts retain those outcomes and invalidate the complete daily net series.
Do not label gross results as net, substitute a resolved-only sample or publish
full-family significance/promotion from those unavailable columns.

FUND_FADE is conditional on recorded observed events, not a claim that all historical
signals were recovered. Any off-grid event within its replay window makes the trial
unavailable under the current signal timing model. Preserve that reason, without
rounding or silently excluding the event. The archive driver must enforce this.

## FUND_CARRY disposition

The original settlement quorum depends on full panel size, including future listings
in a historical union. A contemporary roster would change the registered trigger.
Therefore retain the exact trial ID and parameters, record an unavailable attempt
with `UNAVAILABLE_CAUSAL_QUORUM_MAPPING`, and omit its daily return column. Do not
rewrite the definition or encode an empty successful run. A future causal variant
would need a distinct registration and cannot fill this known-family column.

This resolves how to report the compatibility limitation; it does not complete the
seven-definition evidence matrix. A4.4 full-family statistics remain unavailable
while any registered column is missing. The next step is a bound archive driver
that retains successful, unresolved, unavailable and failed attempts, followed by
committed replay and independent verification.
