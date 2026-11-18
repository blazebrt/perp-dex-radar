# Shared synthetic claims and retained results

Implemented 2026-11-18 in draft PR #30. `tools/v9/control_partition_transport.py` is an executable reference transport for the synthetic partition coordinator. Separate checkouts share one append-only Git branch in a local bare repository. It exercises competing writers and recovery across working directories. **It is not hosted/network storage qualification or a production backend selection.** Only absolute local bare-repository paths are accepted; HTTP, SSH and other network URLs are refused. The registered market input remains refused. There is no workflow or market CLI.

## Claim before computation

The shared branch contains the bound SQLite reservation and retained outputs. Each operation fetches its current head into a new checkout. SQLite remains a local state format, never a database opened concurrently on network storage. A worker commits its claim locally, then publishes it with an ordinary fast-forward Git push. Only after that publication returns successfully may computation start. Two checkouts based on the same head cannot both update it: their commits are siblings. A rejected or ambiguous claim publication never triggers computation. Even if the server accepted the claim but its acknowledgement was lost, the unit remains consumed and cannot be claimed again.

There is no force push, automatic computation retry, lease expiry, failed-unit replacement or reset. An abandoned claim can prevent completion indefinitely. This is the explicit tradeoff required to avoid silent reruns. Callers must use this transport API; direct access to the lower-level synthetic worker/coordinator, deleting or rewinding the store, and malicious writers are outside its guarantee. Production would require an enforced append-only store and a separately reviewed authorization boundary.

## Atomic result and failure retention

Each terminal publication starts from the latest shared head and checks the exact reservation and claim token. It copies only that job's retained output, rejects symlinks and non-regular files, enforces a 512 MiB per-job synthetic transfer limit, and checks that source and destination file hashes match. Successful units pass the independent transport verifier; a successful merge also passes accounting and full unit/transport bindings. The files and terminal ledger update are committed together. Failed work retains available partial files and a FAILED state, never a success label. If no output was created, its failed claim is still retained.

Publication conflicts retry bookkeeping at most four times against fresh shared heads, preserving unrelated claims/results. No worker or merger is called by that recovery path. If a push succeeded but its response was lost, a subsequent read accepts only the same token, terminal state and byte-identical retained file inventory. Different terminal bytes are refused. Exhausted publication retries leave the original working directory intact for an explicit later `publish` call.

A hard loss before publication can lose unpublished files. The shared CLAIMED state still prevents recomputation; missing files cannot be converted into success. This does not promise recovery of data that never reached the store.

## Recovery and verification

`verify_retained` fetches an independent checkout, rechecks input/code/protocol bindings and revalidates every recorded unit and recorded merge without executing either. Complete shared results survive deletion of the original worker checkouts. Original pinned inputs and implementation remain necessary for verification; the transport does not duplicate or replace those input archives.

Its result concerns retained synthetic state. Merge accounting is explicitly **not** independent selection/price-path/statistics acceptance. Those original scientific audits remain separate. Failed/claimed/pending states stay visible and never become completed units during recovery. Git history preserves previously published claims and failures; there are no signed-provenance or hostile-store claims.

## Validation and remaining gates

Eleven Linux tests use actual temporary bare repositories and separate checkouts. They cover complete worker/merge retention after deletion of worker directories; simultaneous claims with exactly one computation; abrupt process exit after a shared claim; exhausted publication followed by read-only recovery; lost claim and result acknowledgements; unrelated concurrent claims; retained partial failures and retry refusal; wrong token/input/network destinations; interrupted merge publication without reconstruction; corrupted stored receipts; and transfer-size/symlink refusal. The Windows sandbox could not launch Git's local transport subprocess, so these are Linux results, not Windows qualification.

This reference backend transfers whole repository histories/checkouts and has not established acceptable full-volume cost. Do not select it for the approximately 42 GB output sensitivity scenario merely because small synthetic tests pass. Still required: reviewed production transport/storage choice and one-attempt addendum; production source/auditor bindings; real hosted/network recovery, retention and outage tests; representative full-history/full-volume worker and global merge memory/disk/time measurements; independent qualification review; then explicitly authorized activation. Power-loss durability, server backups, Git server policy and network authentication were not tested. Frozen research registrations and outcome definitions are unchanged.

## Object-backed mode follow-up (2026-11-18)

The optional object-backed mode now keeps only the ledger, mode and bundle references in Git; exact result bytes are stored in separate immutable chunks. It is selected at initialization with a local object-store adapter. Claims/publication no longer copy other units' payloads. Global merge/whole-reservation verification still restore all required bytes and remain resource-unqualified. Existing full-payload reservations retain their original behavior. See `a6-storage-decision.md` for the architecture decision, tests and remaining hosted/global-resource gates; no cloud adapter or production activation is present.
