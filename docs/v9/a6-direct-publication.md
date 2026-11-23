# A6 object publication without a duplicate payload tree

Implemented 2026-11-19 in draft PR #30. Object-backed publication now independently verifies the original retained unit or merged result and streams it into immutable chunks directly. It no longer copies the entire result into the temporary coordination checkout. Legacy full-payload Git mode is unchanged.

## Integrity and recovery

The publisher captures an exact source-file hash inventory before doing any work. The coordinator may verify a separate retained directory, but rejects source/registry overlap and symlink paths. Existing input, code, protocol, plan, receipt and accounting checks still apply. A receipt or merged-manifest hash is captured before independent verification and must remain identical afterward; a changed verification document rolls back the ledger transaction.

The ledger digest recorded by verification must also match the initial source snapshot, preventing a receipt swap-and-restore race. After verification, chunk packaging must match both the initial inventory and a fresh inventory of the original directory. Different bytes before or after packaging cannot publish a success record. Only the small bundle reference and ledger state go into the fresh shared-history commit. Source output directories are never deleted by publication, including failed or interrupted uploads. Unreferenced chunks from an interrupted publication remain retained as before; no automatic garbage collection or outcome retry is introduced.

When a publication response is lost, recovery reads and hashes the already-retained chunks directly. It checks the complete file hashes, the stored receipt/manifest digest against the ledger, and the unchanged local inventory, without restoring another result tree. A corrupt object or inconsistent stored reference fails recovery. This is bounded chunk reading, not a provider durability guarantee.

Each global verification still restores input units one at a time. The original merged result and summary database remain on disk. This change removes the extra full publication copy and the extra full restore used by idempotent publication recovery; it does not remove source/index/audit scratch, object storage, metadata, orphan objects or the original merged result. The local reference object store itself still occupies disk, so total local test storage is not claimed to equal just one payload.

## Validation and remaining scope

Tests forbid `copytree` throughout complete unit/merge publication and failed-output retention, inject lost acknowledgements, and forbid restoring a merged result during retention recovery. Exact recovered bytes match preserved original output. Other tests inject mutations during independent unit/merge verification and before/after chunk packaging, require the shared claim to remain incomplete, and then verify recovery after restoring the original bytes. Corrupted stored chunks fail idempotent recovery.

No scientific definitions, outcome producer, price/selection/statistics algorithms, published product files or parity goldens changed. No market run, deployment, merge, new storage account or credential request occurred. Existing synthetic byte caps and resource/activation flags remain unchanged.

The earlier hosted handoff evidence (`a6_github_recovery.json`) remains pinned to its original implementation commit; it is not silently relabelled as hosted evidence for this later code. Full-volume/history resource bounds, permanent-retention capability, live hosted coordination, production bindings and independent qualification remain open. No new timing benchmark or interchangeable local backend was added.
