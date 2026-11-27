# GitHub-only synthetic recovery alternative

The owner's 2026-11-18 instruction supersedes the request for an externally supplied storage account: use available alternatives or explicitly skip unavailable dependencies. Do not ask the owner to supply a bucket, credentials or budget. Skipped acceptance evidence remains unavailable, never passed.

## Implemented hosted check

`.github/workflows/a6_hosted_recovery.yml` uses the existing repository and ordinary GitHub-hosted jobs, with contents:read and no secrets. It triggers only when this workflow file changes on `v9/census-evidence`. It does not deploy, publish releases, write any GitHub branch, access market data or activate a study. Each job has a ten-minute timeout. Action revisions are pinned to the repository's existing checkout/Python/upload revisions and the verified download-artifact v4 commit.

The producer creates a tiny synthetic reservation with four units: RECORDED, FAILED, CLAIMED and PENDING. It packages the bound source files, immutable object chunks and a local Git bundle of the coordination history. Original working directories are deleted before transfer. The allowed package is capped at 8 MiB. The transfer manifest pins every filename, byte count and SHA-256, the coordination head, exact source commit and workflow run/attempt. Its digest is passed as a separate upstream job output.

The consumer downloads the exact uploaded artifact ID in a different job, compares Linux boot-identifier hashes to demonstrate separate runner boots, and verifies the complete file inventory before importing the local Git bundle. It reconstructs and checks retained records/partial failures without running a worker or merger. Attempts to restart each recorded, failed or uncertain unit must be refused. Pending work stays pending. Wrong run/source/digest, missing/extra/corrupt files and an unproven distinct boot fail the check.

The consumer emits a small JSON report in its log and as a separate artifact. Both transfer and report artifacts request one-day retention and overwrite=false. A passing hosted report can be copied into the existing PR through the connected GitHub app for durable review; the workflow itself has no repository-write authority. Local regression tests do not claim that the hosted run has already succeeded.

## What this can and cannot close

This can supply real hosted upload/download and separate-job recovery evidence for the small synthetic format without a new account or provider. It is not a live multi-writer remote lock service, provider outage test, full-scale storage bound, permanent object store or market qualification. The producer's claims are coordinated in a local bare repository before an immutable handoff; the artifact is a snapshot, not a writable distributed ledger.

GitHub documents artifacts as immutable archives with distinct IDs, but they can be deleted and expire; the v4 actions support downloading an explicit artifact ID. These capabilities justify this limited handoff test, not indefinite evidence retention. Sources checked 2026-11-18: [upload-artifact v4](https://github.com/actions/upload-artifact/blob/v4/README.md), [download-artifact v4](https://github.com/actions/download-artifact/blob/v4/README.md).

No external-account dependency is assigned to the owner. If this available route cannot meet permanent/full-volume requirements, record that route as unavailable and continue other actionable roadmap items. Keep A6 activation disabled until the genuine acceptance evidence exists. Do not build more interchangeable local storage backends or label an expired snapshot as durable retention.

## Observed hosted result (2026-11-18)

[Run 44368737167](https://github.com/blazebrt/perp-dex-radar/actions/runs/44368737167) passed at source `4c4b7df0cd57b7022962c60b8fb7776cc3a4438c`. Both producer and consumer jobs succeeded. Different boot hashes were verified; 26,513 bytes transferred; all states survived; three prohibited recomputations were refused. The exact parsed report and workflow/job references are retained in `research/v9/a6_github_recovery.json`. Resource, long-term-retention and execution-authority flags remain false. The input snapshot artifacts can expire after one day; this committed report preserves the observation, not the original snapshot or indefinite recovery capability.
