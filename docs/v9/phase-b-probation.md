# v9 phase B: the probation tier

Under v8, the desk could never show a trade. Every strategy needed full Phase 9 requalification, and two of its
checks cannot pass: the trial census is incomplete by construction, and no 180-day prospective record exists yet.
On top of that, legacy paper positions that the desk never recommended kept the portfolio over its limits.

Phase B adds a narrower, honest route to a trade:

- A strategy side that the survivorship-free archive confirms out of sample may trade at a reduced size.
- Before its first trade, a forward test is registered in the shadow ledger.
- The side is demoted automatically if its live record falls below the archive's band.

Nothing here is requalification. Nothing places orders.

## What the archive confirms

The archive is every Binance USD-M perpetual that ever traded, 2020-01 to 2026-09: 750 coins, 170 of them delisted. It
counts fees, slippage and observed funding.

The archive's tool is `tools/v9/confirm.py`. It applies the gate below to both sides of the three runtime strategies,
using evidence run `fd03198`. The result is in `research/v9/probation_evidence.json`.

| Side | Verdict | Holdout 2020-01..2023-09 | Design window 2023-10..2026-09 | Top-80 universe (holdout / design) | Entered 4h / 8h / 12h / 24h late |
|---|---|---|---|---|---|
| XSMOM long | **CONFIRMED** | +0.167R, Holm p 0.043, 503 trades | +0.231R, p 0.018, 443 trades | +0.193R / +0.211R | +0.20 / +0.19 / +0.20 / +0.18R |
| XSMOM short | not confirmed | +0.068R | −0.131R | +0.070R / −0.007R | −0.02 / −0.01 / −0.01 / +0.00R |
| TSMOM long | not confirmed | +0.009R | +0.062R | +0.040R / +0.136R | +0.05 / +0.04 / +0.04 / +0.05R |
| TSMOM short | not confirmed | +0.163R | −0.001R | +0.123R / −0.058R | +0.09 / +0.09 / +0.09 / +0.07R |
| TREND_EMA long | not confirmed | −0.104R | −0.026R | −0.118R / +0.035R | −0.06 / −0.06 / −0.06 / −0.06R |
| TREND_EMA short | not confirmed | +0.093R | +0.053R | +0.104R / +0.021R | +0.06 / +0.06 / +0.07 / +0.07R |

Other figures for XSMOM long:

- 946 trades across 279 coins.
- The largest single coin accounts for 3% of the positive R; the largest month for 9%.
- Costs ×1.5: +0.18R.
- Edge over a random coin at the same moment: +0.14R.

Gate (all must hold), from `docs/v9/HANDOVER.md`:

- (a) The definition was fixed before the holdout was examined.
- (b) Holdout mean R > 0, with a Holm-adjusted one-sided p < 0.05 over the six runtime sides.
- (c) Design window mean R > 0 with p < 0.10.
- (d) The recent third > 0.
- (e) Costs ×1.5 > 0.
- (f) Random-twin edge > 0.
- (g) The Phase 9 concentration limits hold.
- (h) At least 500 trades, at least 100 of them in the holdout.
- (i) The deployable-universe proxy (the 80 most traded eligible coins) is > 0 in the holdout and in the design window.
- (j) The side stays > 0 when entered late, which gives the TRADE window (24h).

Gates (a)–(h) were written after a first look at the archive. Gates (i) and (j) were written before they were first
measured. That is why the protection is not the backtest alone: the side trades at half size, behind a forward test
registered before its first trade, with automatic demotion.

## The policy

`v8/quant_strategy_policy.json` (schema `v8.quant-strategy-policy/2`) sets XSMOM to `ACTIVE_PROBATION` /
`PROBATION`. Its `probation` record holds four things:

- `sides: ["long"]`.
- `risk_multiplier: 0.5`. The validator never accepts more than 0.5.
- The evidence file, bound by SHA-256.
- The forward-test registration `V9-PROBATION-XSMOM-LONG-1`
  (`research/shadow-ledger/000002-REGISTRATION-V9-PROBATION-XSMOM-LONG-1.json`), bound by SHA-256. It was registered
  2026-10-14 11:51 UTC, and its evaluation starts at 2026-10-15 00:00 UTC.

`v8/strategy_policy.py` validates all of this fail closed: the hash, the CONFIRMED verdict with every check true, the
runtime definition and runtime implementation hashes, the entry window, the band, and the registration's kind, status,
authority, parameters and start.

A change to `quant.py` therefore invalidates the probation until the evidence is re-bound:

```
python tools/v9/confirm.py --from-branch evidence-results
```

Then update the evidence `sha256` in the policy row.

## The decision engine

The policy is `v8/decision_policy.json`, version 2, review status `POLICY_REVIEWED_V2_PROBATION`. Every version 1 value
is unchanged.

**STRATEGY_AUTHORITY** decides a probation strategy's signal as follows:

| Situation | Effect | Code |
|---|---|---|
| Confirmed side, signal bar at or after the forward test's start, signal younger than the entry window, forward test within its band | **PASS**: probation TRADE | – |
| The other side | WATCH | `STRATEGY_SIDE_NOT_CONFIRMED` (also not counted as emerging evidence) |
| Before the registered start | WATCH | `PROBATION_NOT_YET_EFFECTIVE` |
| Past the entry window | WATCH | `PROBATION_ENTRY_WINDOW_PASSED` |
| 30 or more closed forward-test trades averaging below the band's 5th percentile for that n | WATCH | `PROBATION_FORWARD_TEST_FAILED` |
| Forward-test record or probation terms missing | WATCH | `FORWARD_TEST_RECORD_MISSING` / `PROBATION_TERMS_MISSING` |

**Size.** A probation strategy's proposal risks `risk_per_trade × risk_multiplier`, which is 0.25% of the page account.

**Governed book** (`portfolio.gating_book = GOVERNED_TRADE_AUTHORIZED`):

- The Phase 10 gates evaluate the paper positions of trade-authorized strategy sides that were entered since that
  authority took effect.
- Each position's funding projection is the asset's current observed rate.
- Legacy-holdover positions are reported as the full paper book. That book is a diagnostic and no longer gates
  anything. The audit binding still compares the full book with the Phase 10 audit.

**Entered signals.**

- A signal whose own paper position was opened from that same signal in an earlier scan of the same bar is `ENTERED`.
  It stays the same opportunity until it ages out; before this change it became AVOID one scan after it appeared.
- Any other open position of the same strategy, coin and direction is still `POSITION_ALREADY_OPEN`.

**Published tiers.** `strategy_tiers` publishes which strategy sides may trade at all, and on what terms. The desk uses
it to say what to expect when nothing is trade-ready.

## The desk

- **TRADE card.**
  - A "Probation · reduced size" tag.
  - The engine's own plan: enter near the mark, the stop, the exit ("at the stop or 14 days after you enter"), the risk,
    the size on the page account, and the time left in the entry window.
  - The archive's out-of-sample expectation with its 95% interval, and the live forward test.
- **The exit.** The proposal publishes `time_exit_hours`, the strategy's hold from quant.py (336 hours for XSMOM). The
  archive results assume both exits: the stop, and the time exit counted from the trader's own entry. That is how the
  late-entry checks (j) simulated it. No profit target is stated, because the strategy has none.
- **Today.** The empty state names the authorized sides. The Portfolio panel separates the governed book from the
  legacy paper book.
- **Portfolio page.** It lists the governed positions, then the legacy paper book as a diagnostic.
- **Analyzer and Quant page.** They label XSMOM "Probation (confirmed side only)". The Analyzer's exact governed
  proposal card also states the exit, which the legacy Analyzer always showed and the governed card had dropped.

## Proofs and tests

- `tests/test_v9_decision.py`: the decision policy invariants and the fail-closed probation binding (every mutation),
  plus the engine's tiers, half size, entry window, registered start, demotion band, governed book, entered signals,
  the quant-side inputs and the desk.
- `tests/test_v9_scope.py`: against main at the start of phase B, only the declared files and functions change.
  `quant.py`, signals, universe, identity, liquidity, research methods, the Phase 10 limits and the Research
  publication are byte-identical.
- Parity:
  - `tests/fixtures/v8/legacy_parity_golden_v9b.json`.
  - `tests/fixtures/v8/v9b_expected_deltas.json` pins quant.json's XSMOM states and policy hash, and the four changed
    pages.
  - `tools/v8/delta_parity.py` proves that nothing else differs.
