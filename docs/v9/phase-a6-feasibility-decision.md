# A6 feasibility decision: current single-job design is no-go

Decision date: 2026-11-17. Reviewed source: `4d66149925bc4b51b6277cdb207cd87cc5052c6e`. This closes the engineering feasibility review, not A6.3 research acceptance. Do not activate the existing inactive single-job template or start another small timing benchmark by default. No market outcome study, reservation or promotion is authorized by this decision.

## Why the existing evidence cannot justify activation

The inactive template sets a 21,000-second deadline before setup, inside its 360-minute job timeout. The existing resource gate permits at most 60% of remaining time. Even before setup consumes time, that leaves at most 12,600 seconds (3.5 hours) for qualified work. Processing 4,263,580 signals therefore requires at least 338.38 signals/second across the complete required pipeline. Setup, auditing, publication and failure retention reduce the usable margin further.

The latest retained 1,280-signal full/mixed synthetic cases took 112.016/113.593 seconds: 11.43/11.27 signals per second. Matching the minimum required average would require approximately 29.6/30.0 times those observed rates. Two sensitivity calculations illustrate the gap:

| Scenario | Full case | Mixed case |
|---|---:|---:|
| Whole workload at observed average throughput | 103.64 hours | 105.10 hours |
| Whole workload using the observed 320-to-1,280 incremental slope, excluding fixed setup | 42.77 hours | 53.75 hours |
| Output bytes scaled at observed bytes per signal | 42.07 GB | 42.07 GB |
| Original output plus local publication checkout scaled similarly | 105.31 GB | 105.32 GB |

These are engineering sensitivity scenarios, **not predictions, lower bounds or upper bounds**. The two sizes were sequential observations; coordinates differ, cache reuse can favor these fixtures, and they cover only 96 assets/five available definitions rather than 781/192. No linear scaling law is established. The conclusion is insufficient evidence for a go decision, not proof that no implementation can ever fit.

The retained hosted capacity snapshot gave 92.11 GB free disk; its half-disk criterion is 46.06 GB. The output-only scenario nearly consumes that budget before source indexes, audit scratch, publication copies and recovery bundles. The copy scenario exceeds even that historical free-space snapshot. The local publication checkout already includes its payload and Git metadata; the calculation adds the original output once, not a second checkout. Allocated peak disk and remote publication remain unqualified. The memory snapshot's half-capacity is 7.88 GB, but sampled small-workload RSS cannot establish a full-workload combined-process upper bound. These are historical capacity observations, not current reservations.

Exact source hashes and unrounded calculations are retained in `research/v9/a6_feasibility_decision.json`. Formulas: required rate = 4,263,580 / 12,600; average-throughput hours = population * observed seconds / observed signals / 3,600; incremental scenario = population * (attempt14 seconds - attempt13 seconds) / 960 / 3,600; byte scenarios = population * observed bytes / 1,280. All 14 earlier measurements remain unchanged.

## Concrete execution redesign

Prefer partitioned execution with one logical, immutable study attempt over another selector/cache micro-optimization. A larger runner is an alternative only after its actual time, memory, storage, publication and cost constraints are reviewed; no service or spending is authorized here. Partitioning does not remove total compute, network, global-statistics or storage costs.

The pinned A6.2 manifest was read as metadata only and its raw SHA-256 matched `ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e`. `tools/v9/control_partition_plan.py` produced `research/v9/a6_partition_plan.json`: 465 work units, exactly one per original input shard, retaining all 4,263,580 rows and all 199 trial slots, including seven unavailable hourly slots. No signal rows or candles were downloaded and no outcomes computed. The plan preserves source hashes, byte counts, order and per-trial retained-row ranges. Those ranges are file offsets, not replacement scientific signal ordinals. The original signals' identities and ordinals must remain unchanged.

This plan is not a qualification report or an active workflow. It does not claim the referenced shard bytes were newly reverified. It does not assign resource limits or imply 465 simultaneous jobs. Units can contain different workloads; full-history qualification remains necessary.

The next implementation target is a bounded unit executor plus an independent global reconciliation step, with these acceptance requirements:

1. One reservation pins the source manifest, original protocols, implementation and exact unit plan before any market execution. Partition transport/recovery needs a separately reviewed addendum; do not edit the frozen original preregistration or weaken its one-attempt rules.
2. Unit execution verifies the original shard bytes and complete required source bindings, retains every original candidate/control selection and uncertainty disposition, and never regenerates signals. Synthetic partitioned-versus-monolithic comparisons must prove full logical record equivalence.
3. Completion receipts are immutable and content-addressed. Failed/interrupted units and partial outputs remain visible. No silently repeated market unit, discarded failure, changed cohort, new reservation or automatic outcome rerun is permitted.
4. A separate reconciler rejects missing, duplicated, overlapping or reordered units; verifies all candidate/control paths; and rebuilds exact global day, reuse, concentration and statistical summaries. Do not average per-unit averages or treat partially completed units as a successful study. Seven unavailable trials remain unavailable.
5. Enforce per-unit combined-process memory, allocated scratch, time and publication limits; bound the global reconciliation stage and total retained storage too. Demonstrate remote publication/failure recovery and dependency/environment review before qualification.
6. Retain the original activation gate until a reviewed qualification mechanism covers the redesigned architecture. Only then request controlled market activation and record/reconcile the single study attempt.

Remaining blockers are thus explicit: the partition executor/reconciler is unfinished software; representative hosted resource and remote-retention evidence is missing; qualification review and market activation are not yet authorized. A6.3 remains open, but the old "keep benchmarking the same single-job design" path is rejected.

## Implementation follow-up, 2026-11-17

The synthetic worker, independent transport checker and global reconstruction prototype are now implemented and parity-tested; see `a6-partition-execution.md`. The current single-job no-go decision is unchanged. Production transport/binding integration, durable once-only execution, global storage/resource qualification and activation remain outstanding.
