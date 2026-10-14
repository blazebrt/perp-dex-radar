# Phase D2 pre-registration: Binance positioning (top traders, the crowd)

Written and committed on 2026-10-14, **before any test of these definitions on market data**.

**What was seen first.** Before this commit, nothing from the metrics archive had been looked at; its download was
still running. The only runs were mechanical checks on synthetic data (`tests/test_v9_d2.py`). The D1 result (no
side confirmed) was known when these were chosen.

**The run.** `tools/v9/evidence_d2.py`, run by `.github/workflows/evidence_d2.yml` on the survivorship-free archive
that phase B used (`archive-data`) and on the Binance metrics dataset (`archive-metrics`, built by
`tools/v9/metrics_fetch.py`).

**Fixed definitions.** If this document and the code disagree, the code in the same commit is the definition.
Changing any definition after the results are seen would make it a new hypothesis, with a new name and a new
multiple-testing family.

## The data

Binance's daily `metrics` files hold, every 5 minutes and per USD-M perpetual:
- open interest;
- the top traders' long/short ratio, by accounts and by positions (the top 20% of accounts by margin balance);
- the all-accounts long/short ratio;
- the taker buy/sell volume ratio.

These are the positioning inputs the legacy picks used. `tools/v9/metrics_fetch.py` reduces them to the archive's
4-hour bars: the bar's last 5-minute row; a row stamped exactly at a bar's end belongs to the next bar.

Coverage is recorded by the run itself (`evidence_d2.json`, `data.coverage`): the share of eligible coin-days with a
signal value, and the first day with one. No coverage figure was known when these definitions were fixed.

**Live availability sets a one-day lag.** From the GitHub runners the desk runs on, these numbers are reachable only
through data.binance.vision's daily files, published after each UTC day ends; fapi.binance.com is geo-blocked there.
So the signal at the close of day D uses the metrics through the end of day D-1. That is exactly what a live
implementation would hold at the same moment.

## Definitions

**Shared rules (as in D1).**

- They are evaluated at each daily close (00:00 UTC) on the evidence engine's point-in-time eligible coins (alive, 30
  days of history, at least $5M traded a day over the last 7 days).
- The signal is a 3-day mean: the 18 4-hour bars that end one day before the close (lag of 6 bars). A coin needs at
  least 12 of the 18 bars; otherwise it has no value that day.
- Ranks are taken among the day's eligible coins that have a value. Tied values share their average rank (pandas
  `rank`, as XSMOM and D1 do).
- The stop is 2.5 daily ATRs with a 1.5% floor; there is no trailing stop. A selected coin whose stop would be wider
  than 20% gets no trade that day and is not replaced.
- Entry is at the next open, one trade per coin at a time. The hold is 3 days.
- Costs are the evidence engine's: 0.045% taker fee plus 0.10% slippage on each side, and observed funding while held.

**XS_TOP_DIV (follow the top traders where they disagree with the crowd).**

- **Signal:** the mean of ln(top-trader long/short ratio by positions) − ln(all-accounts long/short ratio).
- **Long side:** the 5 coins with the highest value (top traders' positions most long relative to the crowd).
- **Short side:** the 5 coins with the lowest value.
- **Mechanism:** the largest accounts are assumed better informed than the crowd, so where they lean against it, the
  price follows them.

**XS_CROWD_FADE (fade the crowd's own positioning).**

- **Signal:** the mean of ln(all-accounts long/short ratio).
- **Long side:** the 5 coins with the lowest value (the most accounts short).
- **Short side:** the 5 coins with the highest value (the most accounts long).
- **Mechanism:** a one-sided crowd is the fuel for the opposite move (squeezes and liquidations).

**Where the parameters come from.**

- 5 coins per side, the 2.5-ATR stop and the 3-day hold are the catalogue's cross-sectional conventions (`xs_momentum`
  defaults), as in D1.
- The 3-day window matches D1.
- The 12-of-18 rule only keeps a coin with patchy metrics from being ranked on a few bars.

None was searched, and no variant will be tested. Open interest and the taker ratio are in the dataset but are not
used here. A study of them would be a new pre-registration.

## Hypotheses and gate

There are four side hypotheses: XS_TOP_DIV long, XS_TOP_DIV short, XS_CROWD_FADE long and XS_CROWD_FADE short.

**Gate.** It is the probation gate of phase B, checks (b) to (j), applied as in D1. Check (a) holds by this document's
commit order.

- The holdout covers decisions before 2023-10, from the first day the metrics give a value; the design window is
  2023-10 to the archive's end (2026-09). Neither window was used to choose anything here.
- The Holm correction runs over these four holdout p-values only. It is a separate family from phase B's runtime sides
  and from D1, all tested on the same candles.
- The sample-size check (h) needs 500 trades in total and 100 in the holdout. The shorter metrics history makes it
  harder to meet, and that is accepted, not adjusted.

**Decision rule, fixed now.**

- **A side that passes every check** is a candidate for the probation tier, never a trade by itself. Deployment
  would still need:
  - a runtime implementation that reads the daily metrics files with the same one-day lag;
  - re-bound evidence;
  - a forward-test registration in the shadow ledger before its first trade;
  - the owner's merge.
- **A side that fails** is reported as failed. Its definition is not adjusted to pass.
