# Phase D1 pre-registration: funding crowding and taker flow

Written and committed on 2026-10-14, **before any test of these definitions on market data**. The only runs before
this commit were mechanical checks on the synthetic archive (`tools/v9/make_fake_archive.py`, random prices), which
say nothing about either hypothesis. The run that tests them is `tools/v9/evidence_d1.py`, run by
`.github/workflows/evidence_d1.yml` on the survivorship-free Binance archive that phase B used (the `archive-data`
branch). If this document and the code disagree, the code in the same commit is the definition. Changing any
definition after the results are seen would make it a new hypothesis, with a new name and a new multiple-testing
family.

## Why these two

Both use data the archive already holds for every USD-M perpetual that ever traded:

- observed funding settlements;
- taker-buy quote volume per 4-hour bar.

Both are cross-sectional daily rotations like XSMOM, so they could later run in `quant.py` with data the live desk
already has: funding from every venue, and 4-hour candles with taker volume. Each is a widely discussed perp
mechanism.

Neither is a legacy strategy. XS_FUND_FADE is not the legacy 1-hour `FUND_FADE` (`qstrat.funding_fade`: absolute
funding thresholds, a 48-hour hold), which this 4-hour archive cannot test. That one and `FUND_CARRY` stay in
HANDOVER item D3.

## Definitions

**Shared rules for both strategies.**

- They are evaluated at each daily close (00:00 UTC) on the point-in-time eligible coins (the evidence engine's
  rule: alive, 30 days of history, at least $5M traded a day over the last 7 days).
- Each 3-day window is the 18 4-hour bars that end at the daily close. A funding settlement stamped exactly 00:00 UTC
  belongs to the next day's window, so nothing at or after the close enters the signal.
- Ranks are taken among the day's eligible coins that have a signal value. Tied values share their average rank
  (pandas `rank`, as XSMOM does), so a tie across fifth place can select fewer or more than 5 coins.
- The stop is 2.5 daily ATRs with a 1.5% floor; there is no trailing stop. A selected coin whose stop would be wider
  than 20% gets no trade that day and is not replaced by the next-ranked coin (the research library's rule for every
  strategy).
- Entry is at the next open, one trade per coin at a time.
- Costs are the evidence engine's: 0.045% taker fee plus 0.10% slippage on each side, and observed funding while
  held.

**XS_FUND_FADE (funding crowding fade).**

- **Signal:** each coin's funding paid by longs over the last 3 days (the sum of observed settlements, as a fraction
  of notional). A coin needs at least 3 settlements in the window.
- **Long side:** the 5 coins with the lowest 3-day funding (shorts paying the most).
- **Short side:** the 5 coins with the highest 3-day funding (longs paying the most).
- **Hold:** 7 days.

**XS_FLOW_MOM (taker-flow momentum).**

- **Signal:** each coin's taker-buy share of quote volume over the last 3 days (18 4-hour bars). The coin needs volume
  in the window.
- **Long side:** the 5 coins with the highest share (aggressive buying).
- **Short side:** the 5 coins with the lowest share (aggressive selling).
- **Hold:** 3 days.

Where the parameters come from:

- **5 coins per side and the 2.5-ATR stop** are what every cross-sectional rotation in the research catalogue uses
  (`xs_momentum`, `xs_reversal`, XSMOM).
- **The 3-day hold of XS_FLOW_MOM** is `xs_momentum`'s default.
- **The 3-day window and the 7-day hold of XS_FUND_FADE** were chosen once, from the horizon over which funding
  crowding is usually said to unwind.

None was searched, and no variant will be tested.

## Hypotheses and gate

There are four side hypotheses: XS_FUND_FADE long, XS_FUND_FADE short, XS_FLOW_MOM long and XS_FLOW_MOM short.

**Gate.** It is the probation gate of `docs/v9/HANDOVER.md` (phase B), checks (b) to (j). Check (a) holds by this
document's commit order.

- The holdout runs from the end of the 120-day warm-up (late April 2020) to 2023-09; the design window is 2023-10 to
  the archive's end (2026-09).
- None of these definitions was fitted on either window, so both windows are out of sample. The split is kept so
  that results stay comparable with phase B.
- The Holm correction runs over these four holdout p-values only. It is a separate family from phase B's six runtime
  sides, which were tested on the same archive.

**Decision rule, fixed now.**

- **A side that passes every check** is a candidate for the probation tier, never a trade by itself. Deployment
  would still need:
  - a runtime implementation in `quant.py`, checked against the research definition;
  - re-bound evidence;
  - a forward-test registration in the shadow ledger before its first trade;
  - the owner's merge.
- **A side that fails** is reported as failed. Its definition is not adjusted to pass.
