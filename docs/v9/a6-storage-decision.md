# A6 storage decision: separate coordination from result bytes

Decision date: 2026-11-18. Scope: engineering design and synthetic implementation in draft PR #30. **Select content-addressed object storage for result payloads; reject whole-payload Git histories/checkouts as the production design.** A production account/provider, spending, hosted deployment and market execution are not selected or authorized by this document.

## Evidence and alternatives

The retained `research/v9/a6_feasibility_decision.json` has a roughly 42.07 GB output sensitivity scenario and roughly 105.32 GB original-plus-publication-copy scenario. These are not workload bounds or predictions. Independent partition copies plus a global merge can add more storage; this decision does not treat one output copy as the entire retention budget.

Official documentation checked on 2026-11-18:

| Option | Finding | Decision |
|---|---|---|
| Git payloads | GitHub recommends a 10 GB on-disk repository limit and external storage for generated files. It enforces a 2 GB push limit and 100 MB individual-object limit. | Reject full result payloads in Git. Existing chunk boundaries do not solve history/checkout duplication. |
| Git metadata | GitHub recommends at most six pushes per minute per repository. | Retain as a synthetic reference, not an automatically qualified production scheduler. A 465-unit claim/result sequence needs explicit throughput review or a different conditional-update store. |
| Release assets | GitHub documents 1,000 assets per release, each below 2 GiB, without a total release-size/bandwidth limit. | Possible archival packaging alternative, not selected as the live per-chunk claim/result store. These limits alone do not prove lifecycle, recovery or conditional-update suitability. |
| Conditional object storage | Amazon S3 supports create-only `If-None-Match` and version-conditioned `If-Match` writes, with conditional-write policy enforcement available. | Preferred production capability contract: immutable payload creation and a separately controlled conditional-update ledger. No AWS account, bucket, credentials or bill has been created. Other providers must prove equivalent semantics rather than inherit S3 claims. |

Sources: [GitHub repository limits](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits), [GitHub release storage limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), [S3 conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html). The design decisions are engineering inferences from those documented capabilities and this repository's retained workload evidence, not vendor qualification.

## Implemented split

`control_partition_objects.py` packs exact existing bytes into SHA-256-addressed chunks, 1 MiB by default. It does not decode, recompress or change research records. A small manifest retains ordered chunk sizes/hashes, each complete-file hash/size, original relative filenames and the total bytes. Empty files remain explicit. Chunk reads/writes are bounded; manifests reject traversal, Windows device paths, case-insensitive collisions, conflicting paths, missing/extra chunks, malformed hashes/counts and excessive bundles.

The reference `LocalObjects` adapter creates fully written/flushed objects with an atomic create-only link. Existing objects are accepted only after byte/hash verification; there is no overwrite or deletion API. Publication may leave unreferenced chunks after interruption. They are preserved rather than automatically garbage-collected. This is a local filesystem adapter, not evidence of cloud consistency, retention or power-loss durability.

The optional object-backed mode is integrated into `control_partition_transport.py`. It is selected when a new synthetic reservation is initialized, not silently migrated onto an existing one. Git carries the claim ledger, transport mode and per-job bundle manifests only. A successful unit is independently verified before its output is offloaded; every object must be stored before the terminal metadata commit. An upload failure leaves the shared claim incomplete, with the original output available for retention recovery. A lost metadata acknowledgement is accepted only after reconstructed bytes match the original inventory. Failed/partial outputs use the same retention path.

Workers do not fetch other units' payloads merely to claim or publish their own work. The merger and whole-reservation verifier still materialize all required units, verify them, and preserve global accounting. This removes payload duplication from Git, **not** the global merge's disk/time requirement. Existing full-payload synthetic reservations remain readable in their original mode. Missing objects, wrong storage mode and corruption fail closed; none causes recomputation.

## Acceptance status and next gate

- Complete: storage architecture decision; byte-exact chunk format and local create-only adapter; integration with shared claims/results/failures; exact independent-checkout reconstruction; metadata-only Git tree verified by tests.
- Open: select an approved provider/account and enforce conditional writes plus non-deletion/retention policy; implement and test its adapter against real hosted storage; review authentication and costs without embedding secrets.
- Open: qualify the control-store throughput and failure semantics. Git metadata remains the tested reference only; no claim that 465 jobs can meet its publication rate is made.
- Open: interrupted network uploads, accepted-but-unacknowledged writes, server outages, independent-runner restoration, backup/retention verification and bounded orphan storage. Verify actual remote bytes, not only provider ETags.
- Open: representative full-volume/history resource evidence, including units plus global merge output, source/index/audit scratch, object manifests, orphan chunks, downloads and publication overhead. The current synthetic 512 MiB per-bundle and 10,000-file caps remain; lifting them is not qualification. Full merge/audit materialization remains a blocker for the retained large-output scenario.
- Open: production source/auditor bindings, separately reviewed one-attempt transport addendum and independent qualification review before owner-authorized activation.

Next work must address provider integration/hosted evidence or the global merge resource blocker. Do not add another interchangeable local backend or return to serial small timing benchmarks. No market reservation, new study, release, deployment, promotion or frozen-protocol edit occurred.
