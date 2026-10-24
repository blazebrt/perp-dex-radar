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
