# A6 incremental input restoration and remaining phase gates

Implemented 2026-11-18 in draft PR #30. Object-backed merging, terminal publication verification and retained-state verification now restore **one input unit at a time**. This removes simultaneous materialization of every unit. It does not establish a bound on the complete merged output, global summary database, original input archive, publication scratch, independent audit scratch or total process resources.

## Behavior

The merger first visits every planned unit in original order through an exclusive restore context. The unchanged transport checker validates its exact source, receipt, row identities/counts and code/protocol bindings. Each scratch unit is removed before the next is restored. Missing or corrupt units during this preflight prevent creation of the merged output.

During global reconstruction, a second sequential pass reloads and verifies each unit, requiring its receipt hash to equal the preflight value. Pairs flow into the unchanged outcome writer and global summary accumulator in the same source order. This extra read pass is deliberate: no claim is made that reducing disk also reduces wall time or network traffic. It is read-only replay of retained outcomes, not another matching/execution attempt.

The loader is closed on completion and failure, including when the last yielded pair is followed by adapter closure. Existing working paths are refused before cleanup is armed. Cleanup removes only the newly restored scratch copy; immutable source objects and original worker outputs are retained. A later object failure creates a failed/partial merge and consumes the existing claim. The partial package remains publishable, and no replacement computation is permitted.

Terminal merge recording repeats the unit checks incrementally before checking the merged package's accounting and receipt list. Whole-reservation verification similarly verifies recorded and failed input bundles one at a time. Failed units without a retained bundle stay visibly unavailable. The verifier keeps the restored merged package, but no longer leaves every unit restored. A caller needing an individual retained unit may explicitly call `hydrate` after verification; this does not run it again.

Legacy full-payload transport and the default direct local merger retain their behavior. The loader is an optional synthetic input-access mechanism; scientific outcome production, selection, pricing and statistical algorithms are unchanged. Registered market input remains refused and all execution/resource qualification flags remain false.

## Tests

Full, mixed and sparse cohorts match all canonical pair records and complete global summaries and pass the unchanged independent selection, price-path, accounting and statistics audits. The existing deliberate price corruption still fails. Integrated tests instrument restoration during merge, terminal publication and recovery and observe at most one restored input unit. They also cover a later second-pass object failure, retained partial output and permanent retry refusal, a missing preflight bundle, and preservation of a pre-existing working directory.

This is a structural input-scratch bound, not a measured hosted allocated-disk/RSS/time bound. Local Linux synthetic validation cannot establish network availability or cloud durability.

## Exact A6.3 completion gates

| Gate | Current disposition |
|---|---|
| Preserve the frozen signal population, controls, outcome rules and unavailable trials | Synthetic partition-versus-monolithic parity and independent audits pass. Market evidence has not been generated. |
| Shared one-attempt claims and retained failures | Local reference implementation and adversarial recovery tests complete. Enforced hosted coordination still unqualified. |
| Remove full result payloads from Git | Object-backed reference transport implemented and tested. Approved hosted provider/account and adapter still needed. |
| Avoid holding all input units for global merging | Implemented in merge, publication verification and recovery. |
| Bound the complete workload | Still open: merged output, summary database, source/index/audit scratch, publication copies, orphan objects and combined memory/time/disk. The synthetic bundle limits are unchanged and do not admit the large-output scenario. |
| Hosted recovery/retention and dependency/environment review | Still open. Requires a real approved storage destination and representative hosted tests, including failures. |
| Production input/auditor bindings and reviewed transport addendum | Still open. No frozen registration has been rewritten. |
| Independent qualification acceptance | Still open; local test success is not a substitute. |
| Controlled one-time market outcome run and reconciliation | Not authorized or started; only follows the preceding gates and explicit activation approval. |

The owner was asked for an existing object-storage provider/bucket and spending limit while this implementation proceeded. Do not invent an account, purchase capacity, claim hosted qualification from local fixtures, or mark A6 complete because the software tests pass. No merge/deployment/release/market reservation/promotion occurred.
