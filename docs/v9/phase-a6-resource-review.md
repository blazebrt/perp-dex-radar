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
