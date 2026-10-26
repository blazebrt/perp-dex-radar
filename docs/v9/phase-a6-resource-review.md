# A6 synthetic resource review: not qualified

The 2026-10-24 local probe in `research/v9/a6_synthetic_resource_probe.json`
uses generated candles only: 61 assets, 400 bars each, 20 signals, 50 controls
per signal and six-bar holds. No market files were loaded and no study attempt
was reserved or executed. The report pins the measured implementation bytes.

The adapter and pair-shard stage took 1.964 seconds on this local Windows
environment. It read compressed price files 1,009 times, despite only 61 files
being available. The eight-segment cache is smaller than one full comparison,
so repeated comparisons evict and reload histories. Real source files can be
much longer than the synthetic files. This result does not qualify runtime on
a hosted runner or include preparation, summaries, independent audit or Git.

The 20 pair records occupy 1,138,170 uncompressed JSON bytes and 67,602 gzip
bytes. Straight-line multiplication by 4,263,580 signals gives roughly 242.6 GB
uncompressed or 14.4 GB compressed. These are diagnostic extrapolations, not
predictions: synthetic prices are repetitive, actual cohort availability and
geometry differ, and compression varies with shard boundaries. They nevertheless
show that the current fully repeated record layout needs storage qualification.

Before the registered market attempt:

- Remove repeated full-history parsing using bounded indexed storage or equivalent
  reuse while preserving exact source hashes, gaps, disputes and exit semantics.
- Reduce redundant retained metadata through a lossless, auditable layout. Preserve
  every signal, selected control, geometry, outcome and failure disposition; update
  readers and independent verifiers together and prove logical equivalence.
- Benchmark the complete outcome/audit/retention pipeline with diverse synthetic
  cohorts, long histories and holds, sparse and unknown outcomes, and failures.
- Establish explicit runtime, memory, disk, per-file and publication budgets on the
  intended runner before enabling the durable one-attempt workflow.

No scientific definition or preregistered threshold is changed by this review.
The existing outcome workflow remains unactivated. A6.3 stays open and resource
qualification is explicitly unsatisfied.

## Indexed execution-adapter follow-up (2026-10-24)

The retained follow-up a6_synthetic_resource_probe_indexed.json repeats the same
20-signal synthetic case after adding a hash-bound SQLite price index. Source
reads fell from 1,009 to 61, with zero reloads beyond the available files. The
adapter loads only the required hold window and keeps at most eight windows in
memory. The temporary index is closed and removed after the outcome stage.

Measured local adapter/shard time changed from 1.964 to 1.348 seconds; these
single measurements are not hosted-runner guarantees. Pair JSON and gzip byte
counts remain exactly 1,138,170 and 67,602. Execution-parity tests compare indexed
windows against complete source mappings, including ineligible and terminal
attempts. Source corruption, malformed/disputed prices and cleanup remain tested.

This remedies repeated source loading in the execution adapter only. The independent
audit reader still needs its own bounded index, and redundant outcome storage
still needs reduction. Full pipeline/resource qualification remains unsatisfied.

## Independent audit index follow-up (2026-10-24)

The separate audit reader now owns its own temporary SQLite index and parser.
Source hashes, calendars and volume checks precede indexing; up to eight bounded
hold windows are cached. Success and failure both remove the scratch database.

The new `research/v9/a6_synthetic_resource_probe_audit_indexed.json` preserves
both earlier baselines. Its expanded scope includes independent verification of
all 1,020 candidate/control paths. Execution and audit each read 61 source files,
once per file. Execution/shard time was 1.308 seconds; independent price auditing
was 0.890 seconds locally. Pair JSON/gzip sizes remain 1,138,170/67,602 bytes.

These measurements exclude source preparation, independent selection/accounting/
statistics audits and Git publication. Source histories still require temporary
disk space and one-file parsing memory. Storage reduction and complete pipeline
budgets remain necessary; this does not qualify the registered market attempt.

## Lossless compact-record experiment (2026-10-24)

`control_storage.py` packs each pair independently. The envelope
`v9.a6-packed-pair/1` carries the unchanged pair metadata plus two tables:
candidate/control outcomes in original order, and selected-control features in
original order. Each table stores identical fields once in `shared`, remaining
field names once in `columns`, and explicit values in `rows`. Empty control sets
remain empty. No value is inferred from a default or recomputed; numerical JSON
representations (including integer versus float and signed zero), nulls, flags,
geometry, source identities, ranks and uncertainty dispositions are preserved.

`verify_control_storage.py` reconstructs the records without importing the writer.
It rejects ambiguous columns, wrong widths/counts, duplicate storage locations,
unknown envelopes and nonfinite values. This is a structural reader, not a
replacement for source-bound semantic auditing. Packing is not enabled in the
outcome driver or its manifest readers yet.

The retained `research/v9/a6_synthetic_resource_probe_packed.json` measures the
same 20 synthetic comparisons. All 20 pairs reconstruct to identical canonical
JSON, and the independent price audit checks all 1,020 paths from reconstructed
compact records. Raw JSON falls from 1,138,170 to 251,790 bytes (77.9%); gzip falls
from 67,602 to 51,140 bytes (24.4%). Packing, independent reconstruction and
writing took 0.229 seconds locally. Earlier reports remain intact.

Identical synthetic prices make many outcome values common: these savings are
not market-size forecasts. Four new tests also cover 0/1/49/50 controls, 80 seeded
mixed-disposition cases, integer/float/bool/null distinctions, signed zero,
input isolation and malformed tables. Before adoption, integrate versioned
manifest readers, implementation bindings and all package audits together, then
qualify varied full-pipeline storage/runtime including partial failures. Current
large-scale resource qualification remains unsatisfied.

## Compact package integration (2026-10-25)

The outcome driver now writes `v9.a6-outcomes/2` with the explicit
`pair_encoding: v9.a6-packed-pair/1`. Aggregation still consumes the original
logical records. Only pair shards use compact encoding; day/reuse shards and
side summaries retain their existing formats. The encoder's source hash is part
of the outcome implementation bindings checked against the reserved source.

Both independent accounting and integrated source/price/statistics audits use
the separate structural reader. Version-one packages continue to read ordinary
records; their source bindings retain the original five implementation files.
Version two requires the exact encoding and packed envelopes. The audit report
also hashes the independent decoder. Unknown/mixed encodings fail closed.

Synthetic integration tests verify new and legacy packages, rehashed changed
geometry/arithmetic/exits, missing records and packing interruptions. A packing
failure retains earlier compact shards, marks the attempt failed/partial and
never grants successful audit authority. No market study has run. Full pipeline
resource budgets, publication workflow and retained-result reconciliation remain
open; earlier size measurements are historical synthetic experiments.

## Synthetic pipeline measurements (2026-10-25)

`control_pipeline_probe.py` now exercises synthetic preparation/extraction, the
version-two outcome writer, summary/reuse/day storage, and the complete independent
accounting, selection, price and statistics audit. The retained report is
`research/v9/a6_synthetic_pipeline_probe.json`; all prior reports are preserved.

Each successful case uses two available trial definitions with eight signals each,
plus an unavailable hourly slot; both directions, six/36-bar holds and terminal
entries are included. Full and mixed cases have 61 generated assets with 1,000
bars; sparse has eight. The mixed case adds absent candles, zero volume, malformed
closes, disputes and ineligible entries. No market data or original generators
are used. The fourth case injects an interruption after three recorded signals.

| Case | Outcome seconds | Audit seconds | Retained outcome bytes | Summary database | Pair shards | Reuse shards |
|---|---:|---:|---:|---:|---:|---:|
| Full | 4.024 | 3.111 | 371,999 | 172,032 | 64,691 | 24,828 |
| Mixed | 3.328 | 2.761 | 306,857 | 143,360 | 51,163 | 19,791 |
| Sparse | 0.515 | 0.596 | 92,542 | 49,152 | 13,564 | 3,430 |
| Interrupted | 1.047 | 0.022 | 39,832 | 24,576 | 12,780 | 0 |

Successful cases independently verify 48 candidate paths and 1,556 control paths
in total, including full day/reuse/statistical reconciliation. The interrupted
case retains three compact records and an audit failure, never a successful
qualification. Source/input bytes, preparation time, largest file and audit files
are also recorded with source hashes.

These are retained file sizes, not peak scratch disk or memory measurements.
Real archive preparation, hosted-runner behavior and Git publication are excluded.
At this scale the summary database is larger than pair shards; it must be included
in storage budgets. No market-scale extrapolation is claimed. Resource qualification
remains open pending larger/diverse cases, peak measurements, explicit runner and
publication budgets, and durable single-attempt workflow completion.

## Isolated Linux resource measurements (2026-10-25)

`control_resource_measure.py` runs each synthetic pipeline case in a separate
Linux process. Linux `ru_maxrss` is converted from KiB to bytes and measures the
worker's lifetime peak resident memory, including imports and native allocations.
The observer directs TEMP/TMP/TMPDIR and SQLITE_TMPDIR to one isolated scratch
root and samples visible logical file sizes every 50 ms. Sampling includes the
source files, input/output artifacts and visible index/statistics/journal files.
It is a lower bound, not a true allocated-disk peak: brief files and unlinked
open files may be missed. The observer's own memory is outside the worker metric.

`research/v9/a6_isolated_resource_probe.json` retains two sizes for each of four
cases. Small means eight signals per available trial / 1,000 bars per asset;
larger means 32 signals / 4,000 bars. Asset/trial populations otherwise match the
previous pipeline probe. Runs occurred locally in WSL, not on a hosted runner.

| Case | Size | Wall seconds | Peak resident bytes | Sampled visible peak bytes |
|---|---|---:|---:|---:|
| Full | Small | 4.159 | 30,175,232 | 4,810,088 |
| Mixed | Small | 3.561 | 29,847,552 | 4,704,215 |
| Sparse | Small | 1.163 | 21,458,944 | 732,688 |
| Interrupted | Small | 1.983 | 29,134,848 | 4,246,549 |
| Full | Larger | 8.785 | 52,568,064 | 18,592,478 |
| Mixed | Larger | 8.463 | 51,204,096 | 18,236,842 |
| Sparse | Larger | 1.885 | 28,205,056 | 2,570,512 |
| Interrupted | Larger | 4.331 | 49,823,744 | 16,293,286 |

Every successful case still passes all independent outcome audit layers; both
interrupted cases retain failure evidence. Previous measurement reports remain
unchanged. No timings or sizes are extrapolated to the 4,263,580-signal inventory.

### Resource limits still required before activation

The intended hosted runner and its available memory, disk and configured timeout
must be measured before choosing absolute budgets. Use conservative engineering
headroom: combined process memory at most half of available RAM, allocated scratch
plus retained files plus Git publication copies at most half of initial free disk,
and execution plus audits plus failure publication at most 60% of the job timeout.
These are proposed operational acceptance criteria, not measured compliance or
scientific thresholds. Check publication file/repository limits independently.

The current sampled disk observer cannot certify that disk criterion. Remaining
work must measure allocated/peak scratch use and publication overhead on the
intended runner, cover the real history lengths and trial/asset scale synthetically,
and enforce a preflight refusal when budget evidence is absent. No market workflow
or registered attempt is enabled by this report; A6.3 remains open.

## Allocated blocks and local Git retention (2026-10-25)

The version-two isolated observer now sums Linux `st_blocks * 512`, deduplicating
inodes and including visible directories plus the worker's accessible open deleted
scratch files. Descriptor access gaps are counted explicitly. Directory-removal
races during Git repacking are tolerated; other traversal failures remain errors.
This remains a sampled lower bound: transient allocations, inaccessible descriptors
and Git subprocesses' unlinked open files may be missed. Worker peak RSS does not
measure combined worker/Git-subprocess memory.

`control_publication_probe.py` copies synthetic outcomes and audit artifacts into
a fresh local repository, commits and repacks them, then checks every committed
file hash and the exact tracked inventory. It uses no remote or network, disables
hooks/signing and isolates Git configuration. Existing simulation checkouts are
never reused. Failed/partial outcomes and failed audits are retained identically.
This is not a remote reservation or publication test.

The new `research/v9/a6_allocated_publication_probe.json` preserves all earlier
reports. Eight cases use the same two sizes as the prior isolated measurement:

| Case | Signals per trial | Wall seconds | Sampled allocated peak | Retained payload | Git metadata |
|---|---:|---:|---:|---:|---:|
| Full | 8 | 8.329 | 5,955,584 | 374,956 | 169,970 |
| Mixed | 8 | 7.731 | 5,660,672 | 309,815 | 138,598 |
| Sparse | 8 | 2.408 | 983,040 | 95,500 | 35,158 |
| Interrupted | 8 | 4.602 | 4,571,136 | 39,977 | 17,504 |
| Full | 32 | 19.009 | 22,167,552 | 1,430,675 | 669,236 |
| Mixed | 32 | 15.263 | 20,934,656 | 1,086,472 | 502,837 |
| Sparse | 32 | 3.632 | 3,248,128 | 282,275 | 123,581 |
| Interrupted | 32 | 8.602 | 16,744,448 | 39,977 | 17,503 |

All bytes columns are bytes, not MiB. Each case records one descriptor-access-denied
sample. The larger full case's Git metadata adds about 47% to the payload, and the
original payload also coexists with its checkout copy. Neither this overhead nor
runtime is extrapolated to the full inventory. Remaining: representative-scale
hosted measurements, combined memory and adequately bounded allocated-disk use,
remote publication limits/retention, budget preflight enforcement and the durable
single-attempt workflow. A6.3 and resource qualification remain open.

## Fail-closed resource preflight (2026-10-25)

`control_resource_gate.py` implements the operational headroom policy. The CLI
reads Linux MemAvailable and free scratch disk; remaining timeout and the verified
runner profile must come from the workflow. Report bytes must match the hash
pinned in the reservation, source/input/protocol/profile bindings must match, and
representative workload plus hosted/publication/failure-retention qualifications
must be present. Nonpositive/noninteger capacities, ambiguous JSON, lower-bound
measurements and insufficient headroom are rejected.

`control_outcome_publish.py` retains the qualification input and accepted preflight
snapshot, and refuses before study execution when the gate fails. The reservation
also pins the guard's bytes. A future workflow must check before reserving, then
repeat immediately before executing. The guard is not a runtime monitor or an
independent measurement auditor: qualification reports require independent review.
All existing local reports are explicitly tested to fail. No qualifying report
has been produced and no market workflow is activated.

## Hosted synthetic pilot (2026-10-26)

`.github/workflows/a6_resource_probe.yml` runs only on the research branch when
that workflow changes (or by manual dispatch where supported). It has read-only
repository permission, does not persist checkout credentials, and uses immutable
action commits. The existing eight synthetic cases run with Python 3.10.12,
NumPy 2.2.6, pandas 2.2.3 and numba 0.61.2. Source/run/image identity, resolved
dependencies, logs and measurement hashes are retained as a 90-day artifact;
the report is also printed in job logs. No market archive or outcome runner is used.

This pilot does not provide a reviewed dependency lock or resource qualification.
Transitive packages are resolved at installation and recorded. Process RSS is not
combined process-tree memory, disk sampling remains a lower bound, and local Git
retention does not test remote publication. Existing report exclusions remain
unchanged even on a hosted runner. Inspect and preserve the hosted results before
progressing to representative-scale measurement and independent qualification.
