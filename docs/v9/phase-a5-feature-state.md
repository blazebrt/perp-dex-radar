# A5.3 feature-state and batch preregistration

Registered before hourly strategy replay. This supplements the execution contract
and leaves the seven catalogue IDs, parameters and evidence-bound code unchanged.
It fixes data-readiness and accounting rules; indicator/signal integration and
funding completeness are still required before market replay.

## Continuous feature sessions

Missing, quarantined and observed zero-trade hours terminate a session. Begin all
recursive indicators from a fresh seed on the first subsequent usable hour;
never carry EMA, Wilder ATR, RSI or previous-close state across the break. Apply
the original qind formulas to each session independently, without truncating its
earlier valid history. Finite rolling windows and shifted values stay inside
that session. Do not forward-fill missing prices or sum their volume as zero.

Every definition requires at least 720 consecutive positive-volume hourly bars
through the closed signal candle, as well as the original calendar listing-age,
liquidity and finite-indicator conditions. This is an additional retrospective
data-continuity restriction, not a tuned strategy parameter. Resetting after gaps
can change which signals exist; report the coverage cost explicitly.

For FAIL_BRK, LIQ_FLUSH, VOL_SPIKE, FUND_FADE and FUND_CARRY, this 720-hour ceiling
applies alongside their unchanged indicator periods and minimum observations.
PULLBACK additionally requires 200 complete UTC-aligned four-hour candles since
the latest reset, supporting its EMA200. Discard incomplete leading four-hour
buckets and expose a four-hour state only after its last hour closes. BTC_LEAD
uses a joint BTC/alt continuous session: a break in either resets beta and the
paired feature state. Require 720 joint hours and preserve beta_h=720 and its
original half-window minimum; do not silently change it to a full-window estimator.
BTC context presence never grants a trade slot.

`hourly_feature_state.py` implements these boundaries and readiness ceilings only.
It does not yet calculate indicators or emit signals. The completed feature
adapter must prove reset equivalence to a fresh standalone session, hourly/4h
close-time mapping and future-append invariance before being run on market data.

## Cross-sectional compatibility still to resolve

FUND_CARRY's legacy settlement trigger compares nonzero funding observations with
one third of the entire panel's column count (`p.N`). A fixed union of historically
selected segments includes future listings; replacing that denominator with the
current eligible roster changes the trigger. Neither choice may be silently
presented as an identical causal replay. Record an explicit compatibility
decision before integrating this trial; until then its replay remains unavailable,
not a zero-return or silently modified column. Observed zero funding remains a
real observation even where the legacy signal's predicate excludes it.

## Per-trial position ledger and daily accounting

Sort supplied signals by signal-open time, segment ID and original emission
ordinal. Reject duplicate (segment, signal time, direction) identities. Retain
every attempt and reason. Check the entry day's original ordered selection and
quality embargo, including midnight changes. Never rerank or refill slots.

Maintain one position per trial/segment. An observed exit at the previous bar's
close permits entry at the next bar's open, the same timestamp under this model.
An unknown price path locks the segment through study end; other segments remain
eligible. An observed price exit with unknown funding frees the position but
preserves an unresolved net outcome. Relisted segment IDs have separate state.
Clip execution input to the pinned study end, so later appended observations
cannot resolve an originally censored position in that run.

Keep every UTC day, plus the terminal exit-date row used by A4. Resolved exits
contribute net R on their reported exit day. Days without exits are zero only
when the whole trial's executed outcomes are resolved. Any unresolved executed
outcome makes the entire complete daily net-return series unavailable (null),
while retaining all attempts and observable gross results. No resolved-only
series may replace it in family statistics. Input/schema failure aborts the run;
it must not become an empty successful trial.
