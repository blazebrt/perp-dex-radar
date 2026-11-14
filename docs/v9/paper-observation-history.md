# Durable paper observations

Implemented on 2026-11-14 in draft PR #30. Not activated in production.

## What is preserved

`v9/paper_history.py` reads the same three files used by the retained-ledger page: audit, decision and full retained quant journal. It rejects duplicate JSON keys, nonfinite values, malformed/duplicate journal identities, ambiguous references and mismatched byte sizes/SHA-256 hashes. It requires an OK decision audit and binds both decision and journal to that audit before packaging anything. Source reads are capped at 64 MiB each, and a capture above 20,000 rows fails rather than silently dropping records.

Each complete record version, including every original field and its open/closed state, is stored under `paper-observations/records/<sha256>.json.gz`. A content-addressed snapshot under `paper-observations/snapshots/` preserves the ordered record references, observed authority projection, policy/implementation identifiers, recorder hash, audit time and exact input file hashes. Unchanged versions are shared between captures. Changed versions are additional immutable objects; a record pruned from a later journal remains in earlier snapshots.

Original audit/decision bytes are not duplicated into this archive. Their hashes and capture verification result are retained, but this is not a complete standalone replay package. `verify_archive(read, snapshot_path)` reconstructs a snapshot from one caller-pinned archive revision, checking all content hashes, paths, schemas, states and identities. It returns ARCHIVE_CONTENT_VERIFIED and explicitly says the original source documents were not reverified. It does not turn stored diagnostics into qualified performance.

## Publication contract

The writer uses only the existing `v9-market-history` branch and a separate `paper-observations/` namespace. It refuses to create a missing branch. Existing history objects must have exactly matching decompressed content; alternate gzip encodings are accepted without replacing the old bytes. Commits are based on the fetched branch head, add missing objects only, and push without force. A concurrent writer causes a refetch/retry, preserving that writer's files. The remote tree is fetched and checked after success. Idempotent captures create no extra commit. An immutable-content conflict stops publication.

The Scan workflow runs capture after the audit, only on main with successful core checks. The step is nonblocking for the rest of Scan; normal capture/publication failures produce a warning and a diagnostic report retained as an Actions artifact for 14 days. Cancellation, host loss or timeout can prevent the report itself from being written. These are capture gaps, not fabricated observations. Five-minute step and per-command timeouts bound an individual attempt; long-term branch storage growth still needs operational monitoring.

## What remains unknown

Observed authority is authority reported at the snapshot time. It is never substituted for authority at entry. The recorder grants no trade authority, modifies no journal row or strategy, and assigns no tier to old entries. Previously pruned records, missed scans and missing entry-time evidence cannot be recovered by this capture. Capture has not run in production yet: merge authorization and a verified Scan are still required. The browser page continues to show the currently retained journal; historical archive browsing is not yet wired into that page.

F4 therefore remains open as a full historical per-tier ledger, although the retained page and durable observation-capture implementation are now present. This is a concrete preservation mechanism, not another resource benchmark or a claim of full historical completeness.

## Validation

Synthetic tests cover exact source binding, content addressing/deduplication, record recovery after journal pruning, changed versions, missing R, no retroactive authority, malformed inputs, duplicate identities/references, alternate gzip encoding, immutable conflicts, missing-branch refusal, diagnostic retention, and a real local Git concurrent-writer race with both writers preserved. Workflow tests enforce post-audit ordering, main-only capture and nonblocking behavior. Validation: all 1,413 Linux regression tests passed in 339.081 seconds, including all 11 capture/publication tests and the existing scope checks. No production data or GitHub writes were used by the tests.

All Git publication tests use temporary local repositories. No test writes to GitHub, consumes market data, creates a production branch or activates capture. Published pages, scientific code, numerical outputs and existing parity goldens are unchanged by this change.
