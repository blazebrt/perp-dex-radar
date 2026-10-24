# A5.3 execution contract, registered before hourly strategy replay

This is the execution layer of the forthcoming adapter, not authorization to run
the seven definitions yet. The signal-feature adapter, its exact reset/warm-up
mapping and funding-completeness evidence must also be committed and synthetically
tested before market replay. No market strategy outcomes informed this contract.

Use only the conditionally accepted archive at
`0859e683910a7eea7ef446b27cf9773f33d9e9f8`, with its complete quality schedule.
Retain the seven trial IDs and parameters in `census_replay_plan.json`. The
original evidence-bound signal and simulator files remain unchanged.

## Timing and observable execution

A signal candle opens at time s and becomes known at s+3600. Entry is at the
next candle's open, at s+3600, if that UTC day's frozen membership and quality
entry gate permit it. Membership is checked at entry time, including midnight
changes. Do not refill a rejected cross-sectional slot. Signal close and entry
open sharing a timestamp is the declared bar-model assumption, not a latency
claim. Future availability must not screen out a signal before entry.

An entry requires an observed positive-volume hourly candle and a finite positive
open. Otherwise retain an unexecuted attempt with its reason; never delay entry
to the next available candle. This bar-volume requirement is a retrospective
execution-observability condition and must be disclosed, not presented as volume
known at the opening instant.

Once entered, inspect contiguous hourly bars. Missing, quarantined or zero-trade
bars make the price path unresolved at that hour. Do not close at the preceding
close, jump over the gap, interpolate or pretend the planned time exit occurred.
The batch adapter must keep that trial/segment unavailable for later entries
through archive end, because its position state is unknown. Never merge relisted
segments. Funding uncertainty alone does not change a fully observed price exit.

Hold lengths count actual consecutive elapsed hours, including the entry hour.
On observable bars: stop before target if both touch; later opens beyond a stop
exit at that open; target fills are capped at the target; close-based trailing
and favorable-excursion breakeven updates apply only from the next bar. A time
exit uses the final planned hour's close. If the archive ends first, retain a
censored unresolved position instead of an assumed end-of-archive liquidation.
Intrabar exits are reported at bar-close resolution, not as known exact event times.

Entry/market-exit costs are 0.045% taker fee plus 0.10% slippage each way. A target
exit uses the preserved 0.015% maker fee. Risk is entry price times the registered
stop fraction. Preserve direction, stop/target/trail/breakeven and hold parameters;
no performance-driven tuning or assumed execution-venue liquidity.

## Funding and unresolved accounting

Maintain an explicit distinction between observed zero funding and unknown
funding. Missing rows are not zero. At an hourly opening after entry, charge an
observed settlement to the held position before assessing an exit in that bar;
do not charge a settlement exactly at the entry instant. An aggregate marked
complete may include zero only when independent settlement-schedule/coverage
evidence establishes there were no omitted payments in that interval. It must
not be inferred merely from neighboring nonzero payments or a blanket eight-hour
schedule. Off-grid settlement timestamps require an explicit timing adapter before
use; they must not be silently rounded into this opening-time model.

The execution kernel accepts per-hour funding amounts only with a separately
supplied completeness mask. A false/missing mask or missing rate makes net return
unresolved, even if price exit and gross return are observable. The current
entry hour also requires completeness, although its opening payment is excluded:
the adapter must establish that no unrepresented intrahour payment is omitted.
The current
funding archive alone does not establish that mask; constructing or documenting
its unavailable portions remains a pre-replay dependency. Never use observed
future settlements to generate an earlier signal.

Each attempt records status, entry, observable exit or first uncertainty time,
reason, gross return when known, and net R only when both price and funding paths
are known. Preserve all unresolved rows. If any executed outcome is unresolved,
the trial's complete daily net-return column and downstream full-family statistics
remain unavailable; a resolved-only subset cannot substitute for the trial.

## Required later feature and batch adapter

Missing/quarantined/zero-trade observations break indicator continuity. Recursive
indicators reset at each break; finite lookbacks cannot bridge it. Aggregate 4h
features require all constituent hours and map only completed bars. BTC_LEAD needs
contemporaneous complete BTC/alt features; FUND_CARRY needs an explicitly causal
cross-sectional settlement/membership mapping. Commit exact per-definition
warm-up and mapping rules, with synthetic future-append and gap/reset tests,
before replay. The execution kernel alone does not complete A5.3.
