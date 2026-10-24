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
