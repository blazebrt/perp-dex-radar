# A6.2 extraction and audit review

Verified on 2026-10-23. The first registered workflow run `39774700211` completed
successfully. Source commit: `269cb2b0360310ac6bac9fd5ef8b102505c6d997`.
Retained result: `eb785a908dce572958336649291b8feeb4ee9575`, a direct descendant
of reservation `3d9162699c2507ec35b542e9e6e6031fa5d429c4`. No repeat attempt ran.

| Measure | Verified result |
|---|---:|
| Planned trial identities | 199 |
| Four-hour/daily definitions extracted and audited | 192 |
| Hourly populations explicitly unavailable | 7 |
| Failed available definitions | 0 |
| Original candle files checked | 781 |
| Generated signals | 4,279,748 |
| Signals before the registered window | 16,168 |
| Signals after the registered window | 0 |
| Retained in-window signals | 4,263,580 |
| Signal shards | 465 |
| Retained package files | 670 |

The retained source-bound audit independently reconstructs source windows and
signal projections while reusing the unchanged original strategy generators.
It reconciles original ordinals, geometry, eligibility, next-entry observations,
feature values, missing/disputed history and all population counts. It does not
independently prove the original generators' mathematics.

The local package verification streamed every retained artifact to check its
hash, then reconciled source/protocol/auditor bindings, reservation ancestry,
trial sidecars, shard counts and audit records. It did not fetch the market
archive again or rerun original generators locally. The machine-readable result
and verifier hash are retained in `research/v9/a6_result_verification.json`.

A6.2 is complete for its registered 192-definition extraction scope. This is an
inventory of signals and diagnostic features, not a study of trades or returns.
The seven hourly populations remain unavailable. Known-dispute screening is
retrospective and not exhaustive; archive age is not actual listing age; clean
feature windows do not establish complete indicator or funding correctness.
The eight required Phase 9 matching dimensions remain unsatisfied. No matching,
outcomes, inference, qualification, promotion or production change occurred.

No new strategy evidence-run entry is appropriate for this derived population
inventory. Existing A4/A5 return-series limitations remain open. The next step
is A6.3: register execution and inference before matching, implement and test
the registered rules, then perform and independently verify the single study.
