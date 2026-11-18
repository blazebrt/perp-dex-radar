# Durable paper observations

Implemented on 2026-11-14 in draft PR #30. Not activated in production.

## What is preserved

`v9/paper_history.py` reads the same three files used by the retained-ledger page: audit, decision and full retained quant journal. It rejects duplicate JSON keys, nonfinite values, malformed/duplicate journal identities, ambiguous references and mismatched byte sizes/SHA-256 hashes. It requires an OK decision audit and binds both decision and journal to that audit before packaging anything. Source reads are capped at 64 MiB each, and a capture above 20,000 rows fails rather than silently dropping records.

Each complete record version, including every original field and its open/closed state, is stored under `paper-observations/records/<sha256>.json.gz`. A content-addressed snapshot under `paper-observations/snapshots/` preserves the ordered record references, observed authority projection, policy/implementation identifiers, recorder hash, audit time and exact input file hashes. Unchanged versions are shared between captures. Changed versions are additional immutable objects; a record pruned from a later journal remains in earlier snapshots.

Earlier captures retain only original audit/decision hashes. New captures additionally retain the exact three public source documents under immutable `paper-observations/sources/<sha256>.json.gz` objects, referenced by `original_sources` in the snapshot. `verify_archive(read, snapshot_path)` reconstructs a snapshot from one caller-pinned archive revision, checking all content hashes, paths, schemas, states and identities. It returns ARCHIVE_CONTENT_VERIFIED. For older captures, original_source_documents_reverified is false. For new captures, it reads and hash-verifies all original source objects, repeats the audit-to-decision/journal bindings, reconstructs record references and compares snapshot times, observed authority, policy/implementation identifiers and source bindings before returning original_source_documents_reverified=true. It does not turn stored diagnostics into qualified performance.

## Publication contract

The writer uses only the existing `v9-market-history` branch and a separate `paper-observations/` namespace. It refuses to create a missing branch. Existing history objects must have exactly matching decompressed content; alternate gzip encodings are accepted without replacing the old bytes. Commits are based on the fetched branch head, add missing objects only, and push without force. A concurrent writer causes a refetch/retry, preserving that writer's files. The remote tree is fetched and checked after success. Idempotent captures create no extra commit. An immutable-content conflict stops publication.

The Scan workflow runs capture after the audit, only on main with successful core checks. The step is nonblocking for the rest of Scan; normal capture/publication failures produce a warning and a diagnostic report retained as an Actions artifact for 14 days. Cancellation, host loss or timeout can prevent the report itself from being written. These are capture gaps, not fabricated observations. Five-minute step and per-command timeouts bound an individual attempt; long-term branch storage growth still needs operational monitoring.

## What remains unknown

Observed authority is authority reported at the snapshot time. It is never substituted for authority at entry. The recorder grants no trade authority, modifies no journal row or strategy, and assigns no tier to old entries. Previously pruned records, missed scans and missing entry-time evidence cannot be recovered by this capture. Capture has not run in production yet: merge authorization and a verified Scan are still required. The browser defaults to the currently retained journal and now offers opt-in archive browsing; the implementation is documented below.

F4 therefore remains open as a full historical per-tier ledger, although the retained page and durable observation-capture implementation are now present. This is a concrete preservation mechanism, not another resource benchmark or a claim of full historical completeness.

## Validation

Synthetic tests cover exact source binding, content addressing/deduplication, record recovery after journal pruning, changed versions, missing R, no retroactive authority, malformed inputs, duplicate identities/references, alternate gzip encoding, immutable conflicts, missing-branch refusal, diagnostic retention, and a real local Git concurrent-writer race with both writers preserved. Workflow tests enforce post-audit ordering, main-only capture and nonblocking behavior. Validation: all 1,413 Linux regression tests passed in 339.081 seconds, including all 11 capture/publication tests and the existing scope checks. No production data or GitHub writes were used by the tests.

All Git publication tests use temporary local repositories. No test writes to GitHub, consumes market data, creates a production branch or activates capture. Published pages, scientific code, numerical outputs and existing parity goldens are unchanged by this change.

## 2026-11-16: historical browser implementation

The Performance page can list archived captures and load one selection. It resolves the history branch once, then pins all directory and content reads to that commit. Requests omit credentials and begin only after the user chooses archive browsing. The nonrecursive Git tree traversal avoids unrelated market-history contents; truncated listings or a directory over 20,000 entries fail explicitly. Empty history is shown as no captures, never as zero lifetime trades. Public GitHub availability and unauthenticated rate limits can make browsing unavailable.

New captures add an immutable dated index and a content-addressed gzip view bundle. The index binds capture time, snapshot, view and record count. The bundle carries the exact original snapshot and record JSON strings, preserving Python float and Unicode representations for byte hashing. Its expanded content must fit 64 MiB; exceeding that limit fails the capture rather than truncating it. This duplicates record content for efficient two-object selected-capture reads, so long-term storage growth needs monitoring. Existing record/snapshot formats and old archive objects are not rewritten. Captures without indexes remain listed with unknown dates until loaded and fetch their individual records in batches of four.

The browser verifies SHA-256, schemas, counts, paths, identity/state references and duplicate identities. Its strict JSON parser rejects duplicate keys, nonfinite or unsafe integer-valued numbers and excessive nesting. Compressed and expanded responses have a 64 MiB limit. Unsafe numeric historical payloads remain unavailable rather than rounded. Listing/loading has a two-minute timeout, cancellation and a request-generation guard; failures clear the ledger and never display partial results. This is content integrity, not a signature or renewed verification of original audit/decision documents.

Archived expectations are labelled **Authority observed at capture**, separately from current authority and unrecorded entry-time authorization. Filtering applies to the selected snapshot only; there is no cumulative lifetime P&L or inferred per-tier historical performance. This browser does not solve capture gaps, restore earlier pruned records, activate production capture or authorize trading.

The publication delta is limited to performance.html, performance.js and the new paper-history.js asset. Numerical outputs, decision fixtures and audit inventory are unchanged. The pinned legacy golden and delta manifest are updated only after checking those exact differences. Synthetic browser tests use actual Python-generated gzip captures, mock public responses and the JavaScript runtime; no visual-browser inspection is claimed.

Final browser validation: 1,441 Linux regression tests passed in 374.672 seconds; differential parity passed with zero unexpected changes. See `history-browser-legacy-parity.json` for the retained report.

## 2026-11-17: standalone original-source verification

New immutable captures preserve the exact public audit, decision and journal bytes, including original whitespace and number representations. Existing objects are never rewritten. The publisher accepts only content-addressed source paths and applies the same add-only conflict/idempotency behavior as record objects. Each source remains bounded at 64 MiB. Retaining three source documents increases archive storage, with deduplication only for exactly identical bytes; capacity monitoring and production qualification remain necessary.

The offline Python reader independently reconstructs the captured fields under the current capture-validation contract. A rehashed snapshot with changed authority, times, record inventory or source bindings is rejected if it disagrees with the original documents. Missing sources, altered bytes, partial source inventories and path escapes fail verification. This is internal content consistency, not upstream authentication, historical engine re-execution, qualification of paper returns or authority at entry.

The browser remains a content-only reader: it does not download/reverify the extra source objects or claim the stronger Python verification result. Its existing bundle format remains compatible, and no published page or numerical decision output changes. Older snapshots without source references keep the explicit weaker result; unavailable original documents are never fabricated. Production capture remains inactive pending owner merge authorization and qualification.
