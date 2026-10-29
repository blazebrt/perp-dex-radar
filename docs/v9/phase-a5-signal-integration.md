# A5.3 session-reset signal integration

Registered before any hourly market replay. This implementation applies the existing
execution and feature-state contracts; it does not confer strategy acceptance.

`tools/v9/hourly_signals.py` validates the committed census against the unchanged
catalogue/code bindings and calls the registered functions and parameters. Each
positive-volume contiguous session constructs fresh original `qstrat.Feat` features.
Original liquidity and finite-indicator predicates remain, with the registered
720-hour continuity ceiling, segment calendar age and PULLBACK four-hour warm-up.
BTC_LEAD uses joint BTC/alt sessions; the context column cannot emit a trade.
These retrospective observability restrictions must accompany later results.

FUND_FADE can emit only at an explicitly observed, finite, exactly hour-aligned
funding event. Zero sentinels supplied to the legacy feature container express no
signal event, never complete funding costs. They are not supplied to execution.
A recorded zero rate cannot trigger a threshold crossing through stale event state.
Off-grid funding is rejected rather than rounded. Funding-cost completeness remains
unestablished and must be supplied separately or retained as unknown.

FUND_CARRY returns an explicit unavailable status and no signal array, pending the
causal quorum decision documented in `phase-a5-feature-state.md`. It must not be
reported as a successful zero-signal run or receive a zero-return daily column.

Eight synthetic tests cover the six supported definitions, nonempty legacy signal
equivalence, fresh-session equivalence after gaps, future-append invariance for
signals and numerical ATR/EMA features, partial four-hour edge exclusion, input
preservation, missing/off-grid funding and paired BTC continuity. No market trial
is run by this module. Remaining: funding completeness, FUND_CARRY disposition,
archive-to-batch driver, committed replay and independent result reconciliation.
