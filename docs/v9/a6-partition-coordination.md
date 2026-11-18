# Local synthetic partition coordination

Implemented 2026-11-18 in draft PR #30. `control_partition_coordinator.py` adds persistent at-most-once claims within one local synthetic reservation. It has no market CLI, hosted scheduling, remote publication or activation authority. The registered market manifest remains explicitly refused.

## Reservation and state transitions

Initialization requires a new reservation directory with an existing parent. It binds the exact input manifest, complete partition plan, frozen execution document and every Python file under `tools/v9`. SQLite stores the reservation and fixed unit/merge roster using rollback journals and synchronous=EXTRA. Code, protocol or input changes prevent further claims/recovery; use the original pinned implementation rather than accepting drift.

Each unit moves PENDING → CLAIMED → RECORDED or FAILED. A BEGIN IMMEDIATE transaction serializes competing claims and commits the claim before the worker is called. There is no lease expiry, reset, retry transition or failed-unit replacement. A crash before computation begins can therefore consume the unit's opportunity; the ledger deliberately favors avoiding duplicate outcomes over automatic progress. A failed/uncertain unit blocks global merging.

Short numeric output directories follow the immutable plan order; the full unit identity and original source references remain in receipts. Unknown identities and symlink paths escaping the reservation are refused. The global merge is claimed through the same transaction mechanism after all units are RECORDED. Existing worker and merge directories remain exclusive.

## Recovery without recomputation

`record_unit` revalidates an existing complete receipt and retained shards using the independent transport checker, flushes retained files before recording their digest, then commits RECORDED. If execution finished but recording was interrupted, the same operation completes bookkeeping without calling the worker. Missing, corrupt, failed or inconsistent output cannot be converted into success. Already-recorded receipts must remain byte-identical.

`record_merge` rechecks every recorded unit, the reconstructed output's independent accounting, implementation/source/protocol bindings and transport references before recording the merged manifest digest. It can recover a completed but unrecorded merge without reconstructing it. Its explicit status is MERGE_ACCOUNTING_RECORDED_NOT_PRICE_AUDITED: the separate selection, price-path and statistics audits remain required.

An ordinary worker failure records FAILED and preserves its partial files. An abrupt host/process loss can leave CLAIMED. Neither state is executable again through the coordinator. The raw worker library remains a synthetic development API: this coordinator is not an authorization boundary against arbitrary code, deletion of the ledger, a different reservation directory, or callers bypassing it.

## Durability scope and remaining production work

SQLite commits plus explicit file flushes are local retention, conditional on the filesystem honoring those operations. Linux directory entries are also flushed; Windows lacks the same directory-flush implementation here. Tests exercise committed claims surviving process exit, not power-loss guarantees or destruction of the storage volume. This is not a distributed lock service, signed ledger, remote backup or proof that network filesystems support SQLite locking safely. Moving production workers across disposable runners requires one reviewed durable coordination/receipt store and a qualified recovery protocol.

The worker's cooperative deadlines remain cooperative; memory, allocated disk, full-workload/global-merge capacity, remote publication and failure retention are not qualified. Existing outcome CLI audit preparation does not yet accept the partition implementation bindings. A reviewed transport addendum and production source/auditor integration are still required before any activation.

## Validation

Tests cover a complete synthetic run/merge, concurrent claims with one winner, abrupt process exit immediately after a committed claim, permanent failed-unit refusal, blocked incomplete merges, unit and merge recovery without computation, changed receipt/code/input rejection, exclusive reservation/output behavior, registered-market refusal and Linux symlink escape rejection. Earlier focused tests exposed a Windows read-only-file flush error and path-length failure; flush handles now use non-truncating read/write access and output directories use fixed plan ordinals. File content is not changed by flushing.
