# A4 replay protocol: known definitions, no promotion

Fixed before the first A4 market-data replay. This is a replay of the existing
199 census definitions, not a new strategy search. The original historical trial
count remains incomplete. No definition, parameter, selection rule, or live
strategy authority changes as a result of this study.

## Inputs and scope

- Validate the committed `census_replay_plan.json` against the current census and
  implementation before executing anything. Preserve trial IDs and column order.
- Require the exact phase B evidence file bound by `probation_evidence.json`, and
  require the archive's panel digest to match that evidence. Record universe,
  plan, protocol, runner and dependency hashes with the output.
- Replay all 192 four-hour/daily definitions using the unchanged phase B
  `ArchivePanel`, `Feat` and `trades_of` machinery, including the same 120-day
  warm-up, eligibility, funding treatment, fees and slippage. Existing simulator
  limitations remain; these are diagnostic archive returns, not independently
  qualified live execution evidence.
- Keep the seven hourly definitions in the output matrix as missing. They await
  A5 and must not be simulated using four-hour candles.

## Accounting and statistics

- Store each simulated trade with its trial ID. Sum net R by exit UTC day on one
  common daily calendar. Include the endpoint day when a last-bar close falls
  exactly at the archive end; never silently discard an exit. This endpoint rule
  is explicit because the original phase A matrix excluded that day.
- Zero denotes a completed simulation with no exit on that day. Missing or
  failed simulations are never zero. Abort on simulator exceptions, invalid
  timestamps, non-finite returns, or a changed dataset/plan.
- Preserve all 199 columns in `daily_returns.npz`. The full known-family DSR,
  PBO and bootstrap tests remain unavailable while any column is missing.
- Separately label the 192-column four-hour/daily subset as diagnostic. Use the
  existing multiple-testing functions: daily Sharpe dispersion (sample variance),
  16 CSCV segments with 14 days minimum, 7-day bootstrap blocks and 5,000
  replications. Do not drop constant or sparse columns to obtain an available
  statistic. A zero-variance column makes across-trial Sharpe dispersion
  unavailable. Preserve the statistical routines' other unavailable reasons.
- DSR always carries historical-trial completeness false. Full known-family
  results and promotions remain pending even if a subset statistic is positive.

## Artifacts and acceptance

The runner writes one `trades/<trial_id>.jsonl.gz` file per completed trial,
`trades_a4.json` binding their hashes and row counts, `daily_returns.npz`, `REPORT_A4.md`, and
last, `evidence_a4.json` with artifact hashes. Refuse a nonempty output directory.
An interrupted run without the final evidence document is incomplete.

A4.2 is complete when synthetic tests exercise the real replay and artifact
path, all 199 columns, the seven pending trials, hand-calculated day accounting,
dataset binding, corruption rejection and explicit unavailable statistics.
A4.3 still requires an Actions workflow, one market-data run on the pinned
archive, and recording its evidence in the append-only run history. A4.4
requires A5's hourly data and a separately specified common-family assembly.
Neither this protocol nor its tests mark those steps complete.
