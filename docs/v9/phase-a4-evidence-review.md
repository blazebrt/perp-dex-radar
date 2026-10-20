# A4.4 evidence review: known family remains incomplete

Reviewed 2026-10-21. This report summarizes already retained evidence; it is not a new replay, a combined matrix artifact, or a new statistical calculation.

## Retained sources

| Study | Exact result commit | Recorded history entry | Outcome |
|---|---|---:|---|
| A4 four-hour/daily | `18c14932bcc2ba9e8685f231e1725a786869edd9` | 4 | 192 completed diagnostic return series; 2,670,894 trades |
| A5 hourly | `84412b14ae8a1dee7299c2ebdbb32a45ac5d0e0e` | 5 | 435,817 retained attempts; all seven net-return series unavailable |

Both studies declare window `[1588204800, 1790812800]`. The A4 matrix retains 2,346 UTC days including the terminal exit day, and all 199 census columns in their registered order. Its seven hourly columns remain missing. A common calendar does not establish comparable universes or execution assumptions.

The A5 independent verification record is `research/v9/a5_replay_verification.json`. It binds artifact accounting, price-path reconciliation and signal-population reconciliation to the exact result. Signal verification reuses unchanged original strategy functions while independently reconstructing adapter sessions; it does not independently prove the strategy mathematics.

## Hourly evidence disposition

| Definition | Attempts | Unexecuted | Unknown price path | Observed price exit, unknown funding | Net series |
|---|---:|---:|---:|---:|---|
| BTC_LEAD | 30,230 | 8,378 | 1 | 21,851 | unavailable |
| FAIL_BRK | 243,504 | 109,512 | 91 | 133,901 | unavailable |
| FUND_CARRY | 0 | 0 | 0 | 0 | unavailable: causal quorum mapping |
| FUND_FADE | 55,185 | 39,308 | 42 | 15,835 | unavailable: partial replay and unknown funding |
| LIQ_FLUSH | 34,112 | 12,227 | 5 | 21,880 | unavailable |
| PULLBACK | 48,286 | 21,032 | 26 | 27,228 | unavailable |
| VOL_SPIKE | 24,500 | 10,728 | 8 | 13,764 | unavailable |
| Total | 435,817 | 201,185 | 173 | 234,459 | seven unavailable columns |

No segment failed. Two FUND_FADE segments were explicitly unavailable for off-grid funding. FUND_CARRY's zero attempts mean the registered strategy could not be executed under the causal-quorum disposition; they do not mean a completed zero-return strategy. Observed price exits do not establish net returns when funding completeness is unknown. No unresolved attempt may be dropped to obtain a complete column.

## Statistical interpretation

The retained A4 full-family DSR, PBO and bootstrap results all have status `UNAVAILABLE_INSUFFICIENT_DATA`, with reason: every planned trial needs a finite common daily series. A5 supplies no usable replacement columns, so the information needed to change that disposition is still absent. This report does not recompute those statistics or recast the existing 192-column subset diagnostics as full-family evidence.

Historical trial-census completeness remains false even if the 199 known columns are eventually populated. Neither study grants promotion authority or confirms a strategy. The live probation policy is outside this report's scope.

The four-hour/daily study uses the broad phase-B archive and its unchanged legacy simulator, including its existing funding and gap limitations. The hourly study uses a causal top-150 liquidity schedule, a separately accepted archive, retrospective quality exclusions, 70 entry-embargo days, and contiguous positive-volume warm-up resets. It preserves 7,026 original missing hours, 112 quarantined hours and 663 zero-trade hours. These differences must accompany any later combined inventory; that inventory is not a common-universe experiment.

## Completion and next work

Completed: review of both retained studies, explicit disposition of every hourly definition, and identification of the unchanged full-family statistical limitation. The five-entry evidence history remains unchanged because this document is a review of existing runs.

Remaining: implement and synthetically validate the separately specified assembly in `phase-a4-family-assembly.md`; bind both source artifacts and preserve all 199 columns; retain a new assembly manifest and verify the output independently. A4.4 remains open until that artifact and review exist. A5.3 remains open because the registered execution/return requirements are not fully satisfied.

Closing missing returns requires additional completeness evidence or a separately registered study. A causal redefinition of FUND_CARRY would be a new trial, not a repair of the existing result. Do not rerun the frozen A5 registration, infer zero funding, silently change membership, or overwrite either study.
