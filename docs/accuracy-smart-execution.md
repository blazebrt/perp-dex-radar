# Smart paper execution evidence (A03/A04)

The entry model remains the observed midpoint at the scan timestamp. Signal definitions, trader selection,
parameters, stops and holding durations remain unchanged. Hourly candle observations can qualify an outcome only
when the entire required path is continuous and the exit price is actually observed under that model.

- A complete hourly entry candle whose range never reaches the stop also proves that its post-entry portion did
  not reach the stop. When entry occurs inside that candle and its range reaches the stop, the ordering of the
  extreme is unknown. The outcome is `ENTRY_PATH_AMBIGUOUS`, without realized return or R. The first candle is
  checked explicitly, never ignored to qualify a later exit.
- A gap or invalid/conflicting candle cannot be skipped. Before the deadline the record remains pending for
  history recovery. At the deadline it terminates as `MISSING_HISTORY` or `MISSING_CANDLE_PATH`, without realized
  return or R. Today's midpoint is kept only as an explicitly unqualified diagnostic mark.
- An hourly-boundary deadline uses the observed close of the candle ending exactly at the absolute deadline.
  A deadline inside a candle has no exact hourly price observation and terminates as `DEADLINE_PRICE_UNAVAILABLE`.
  A stop observed in that last hour by a scan before the deadline can still qualify. A candle retrieved after a
  mid-hour deadline cannot prove that its extreme occurred before the deadline.
- A qualified stop requires continuous path observations through the stop candle. Stops and time exits retain
  the former deterministic price/cost/return/R calculations on complete, unambiguous inputs. `t_out` remains the
  observation/closing scan timestamp; execution evidence records the exit bar and observation interval.

`trade_qualified()` continues to describe entry identity independently. `execution_qualified()` requires the
versioned execution evidence; `realized_qualified()` requires both and is the sole gate for `accuracy.live`,
`accuracy.live_info` and the live verdict. Open identity-qualified records are not realized performance.
The journal audit reports independent execution classes and applies the combined requirement to closed counts.

Previously stored closed prices, timestamps and returns are never recomputed. Rows without this execution proof
are classified `LEGACY_EXECUTION_UNQUALIFIED`, even when they have valid entry identity. Historical values remain
visible only as unqualified diagnostics. The journal retains all existing closed records; the public page still
uses its bounded recent display. A retrospective missing-history, ambiguity or gap diagnosis is `UNKNOWN` unless
archived evidence proves that specific defect without hindsight.

Focused tests reproduce the missing-history midpoint and entry-hour ambiguity cases, distinguish identity from
execution, reject gaps and partial deadlines, and verify historical preservation. A direct comparison with the
pre-correction implementation confirms identical original fields for 40 complete-path stop/time outcomes. Actual
guard mutations restore the midpoint fallback, remove entry ambiguity, bypass continuity and restore the
identity-only performance filter; their corresponding regression tests fail.
