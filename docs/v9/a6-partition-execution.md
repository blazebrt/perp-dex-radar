# A6 synthetic partition executor and global reconstruction

Implemented on 2026-11-17 in existing draft PR #30. This is a synthetic-only implementation and parity proof. The registered market input hash is explicitly refused by both worker and merger. There is no market CLI or workflow wiring, no reservation, no new outcome study and no resource qualification.

## Worker

`control_partition_execute.run_unit` validates the entire supplied extraction against the prepared synthetic context, reproduces the metadata plan exactly and selects one original source shard. It checks that shard's hash again, passes each original signal to the unchanged adapter and packs the resulting pair through the unchanged encoder. It never regenerates signals, renumbers ordinals, changes the cohort or adjusts execution rules.

Each worker requires a fresh output directory, writes a start record and a terminal receipt, and retains partial shards on an ordinary execution, packing, budget or validation failure. Receipts bind the input manifest, plan, exact unit, frozen execution document, implementation hashes, provenance, record/byte counts and output hashes. A retry into the same directory is refused. No global scheduler or durable once-only reservation exists yet: separate directories do not prevent a caller from repeating computation, so this is not claimed as production one-attempt enforcement.

The output-byte budget is checked before each packed record is emitted. Deadlines are cooperative checks around matching and finalization, not forced process termination; a stuck adapter, allocation failure or host loss can bypass a terminal receipt. STARTED or missing receipts are never accepted as completion. There is no combined-process memory, allocated-disk or hosted bound. Default limits are prototype safety limits, not market qualification evidence. The full input verification/preparation per worker is deliberately conservative and can be expensive; its resource cost is unqualified.

## Separate transport verifier and global reconstruction

`verify_control_partitions` does not import the worker or matching/execution implementation. It reconstructs the required source-shard inventory from the manifest and rejects missing, extra, duplicate, reordered, failed or wrongly bound units. It checks exact plan metadata, start/terminal receipts, implementation/protocol hashes, source identities, compressed hashes, expanded row/byte limits and every retained signal ID and original ordinal. It grants no price-path or study authority.

`control_partition_merge` uses those verified units in original source order. It feeds decoded pairs into the existing global outcome writer and summary accumulator, so day/reuse/concentration statistics are rebuilt from every record rather than averaged from per-unit statistics. All original trial slots, including unavailable hourly slots, remain. New merged outputs cannot overlap sources/units or overwrite an earlier merge. Preflight rejects invalid unit sets before creating the destination; ordinary later failures retain the existing outcome writer's partial/failure manifest. Replay streams are explicitly closed on both success and failure.

The merged manifest retains plan and receipt hashes and adds the actual worker/planner/merger/transport-verifier hashes to the implementation bindings. Existing market-audit CLI preparation intentionally does not accept this new implementation set. The tests provide reviewed local bindings to the existing independent accounting, selection, price-path and statistics auditors. Integration of externally pinned partition bindings and durable original receipts is part of the forthcoming reviewed transport process, not silently enabled here. A merged manifest is not an independent audit.

## Validation

Tests compare complete canonical pair records and global side/day/reuse outputs against the original single-run implementation. Full 50-control-capable, mixed missing/invalid-data, and sparse cases pass all existing independent audit layers with matching counts/statistics. A changed exit price with updated file hashes fails that independent audit. Separate tests cover split source shards, exact record ranges, failed/partial units, output/deadline refusal, exclusive output directories, missing/extra/duplicate/reordered units, corrupt files, rehashed wrong signal identities, modified plans and registered-market refusal.

Early focused validation found a retained replay generator leaving its final gzip file open; explicit close fixed it. An initial test wrapper also intercepted the merger recursively; the wrapper now invokes the original writer for the comparison. Neither issue was hidden by reducing acceptance checks.

## Remaining acceptance work

The worker, transport checker and global reconstruction prototype are implemented and synthetically verified. Still required before market use: a reviewed transport/recovery addendum preserving the frozen study; one global reservation and immutable durable unit receipts; controlled scheduling without silent recomputation; production source/auditor binding integration; bounded combined-process and global-merge resources; full-roster/long-history hosted qualification; remote publication/failure-recovery evidence; independent qualification review; then controlled activation and reconciliation of the one registered attempt. Global merge/output retention still has the storage pressure identified in `phase-a6-feasibility-decision.md`; partitioning alone does not solve it.

## 2026-11-18: local persistent coordination

A SQLite reservation/claim ledger and non-recomputing recovery path are now implemented and tested; see `a6-partition-coordination.md`. At-most-once claims apply within one preserved local reservation only. Distributed durable storage, production bindings, full-workload qualification and market activation remain outstanding. Earlier limits on direct worker APIs and synthetic-only scope remain.
