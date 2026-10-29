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

### Retained pilot result

Run [40315708480](https://github.com/blazebrt/perp-dex-radar/actions/runs/40315708480)
succeeded at source `ee9082006088a7c249d4b4d564a707ce4e6b007a`. The artifact ZIP
digest, measurement checksum and report bytes printed in logs were independently
compared. The unmodified report and provenance are retained as
`research/v9/a6_hosted_synthetic_pilot.json` and its `_provenance.json` companion.
Six normal cases passed audits; two intentional interruptions retained partial
outputs with failed audits. All eight local Git payload checks passed.

Maximum observed worker RSS was 52,199,424 bytes, maximum sampled allocated disk
22,163,456 bytes and slowest case 9.810 seconds. Descriptor access gaps occurred
in all cases (one or two samples). These values do not bound the full study.
The runner resolved python-dateutil 3.0.0 versus local 2.9.0.post0; the environment
record preserves this difference. A reviewed hash lock and combined-resource,
representative-scale, remote-retention qualification remain outstanding.

Runner identity also remains unresolved: the setup log reports image
`20261012.334.1`, while the captured ImageVersion is `20261023.334.3`. Both are
recorded in provenance without selecting one as authoritative. Qualification
must reconcile this discrepancy against an independently verified runner image.

## Session-wide memory sampling (2026-10-27)

The isolated observer now starts each synthetic worker in a private Linux session
and samples the sum of RSS for its visible session members, including Git children.
It preserves the original worker lifetime peak separately. Report schema /3 adds
maximum sampled summed RSS, member count, scan-gap counts, unreadable entries and
vanished processes. Process names containing spaces/parentheses are parsed safely;
unrelated sessions are excluded. Global proc scan errors are conservatively
reported even when membership cannot be established.

This closes the worker-only visibility gap, not the qualification requirement.
Summed RSS can count shared pages repeatedly; short-lived peaks and children that
escape the session can be missed. The observer itself is excluded. Samples are
non-atomic, and scan work adds overhead beyond the nominal sleep interval. These
measurements are neither a combined physical-memory bound nor runtime enforcement.
Existing /2 reports remain unchanged. New /3 measurements are still explicitly
NOT_RESOURCE_QUALIFIED; bounded disk measurement, representative scale, dependency
locking, runner identity and remote retention remain open.

## Kernel memory capability inspection (2026-10-27)

The synthetic observer now records read-only cgroup v2 capability snapshots before
and after its scenarios. `control_cgroup_memory.py` verifies unified membership
and a full-root cgroup2 mount, then reads current/peak memory, memory/swap limits
and OOM/limit event counts. Unsupported layouts, unavailable counters, permission
errors and malformed values stay UNAVAILABLE; they are never represented as zero.

Readable counters are SHARED_GROUP_COUNTERS_ONLY, with isolated_run_verified and
resource_qualified false. They may include earlier or unrelated work. No peak
difference is calculated, no counters are reset, and no processes are moved.
As specified by the [kernel cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html),
memory.peak covers the group and descendants since creation or an applicable
file-descriptor reset. A new isolated delegated group and verified workload
placement are still needed for per-run accounting. Local Linux inspection found
unified membership but no memory.peak at its current root group.

## Opt-in isolated accounting runner (2026-10-27)

`control_cgroup_run.run` accepts an explicit, already delegated non-root cgroup v2
parent and a trusted synthetic command. It verifies the mount/controller, creates
a unique child, requires empty membership, zero peak and clean event counters,
and verifies bootstrap membership before exec. It never enables controllers or
changes parent limits. Outcomes, bootstrap receipt, logs, kernel peak, OOM events
and cleanup status are retained in a fresh output directory. Timeout/failure
cleanup targets only the created group; an empty group is removed even if peak
measurement is unavailable. Caller groups are never reused or removed.

Six mocked lifecycle/bootstrap tests cover placement before exec, invalid inputs,
fresh-group success, dirty-group refusal, unavailable peak cleanup, timeouts and
OOM disposition. No real delegated group or hosted support has been verified;
the runner is not connected to a workflow. These tests do not measure real kernel
accounting. All reports remain resource_qualified=false.

This is for trusted workloads, not adversarial containment. The outer observer,
bootstrap allocations made before migration and workloads escaping the group are
explicit exclusions. Controller accounting includes descendants that remain in
the group, per the kernel documentation linked above. A hosted isolation check,
complete-start accounting, bounded disk use, representative workload and reviewed
environment/retention qualification remain necessary.

## Hosted isolated pilot preparation (2026-10-27)

A separate read-only branch-scoped workflow, `a6_isolated_probe.yml`, runs the
eight existing synthetic scenarios through the isolated runner. On the disposable
Actions host only, sudo creates a new run-specific cgroup parent and enables its
memory subtree controller. It refuses if the root memory controller is not
already enabled; it does not reconfigure the root or existing groups. The trusted
synthetic command runs in the runner-created child; only its new empty groups
are removed. Parent cleanup state, placement, accounting, logs, environment and
measurements are retained even on failure. No repository credential is supplied
to the elevated process; checkout credentials are not persisted.

Hosted results are pending. This experiment tests real placement/accounting and
cleanup, not representative scale, disk bounds or a reviewed dependency/runtime
lock. Pre-migration bootstrap allocations and the outer accounting process remain
excluded. The original pilot workflow and retained reports remain unchanged.

### Verified hosted isolation result

Run [40386820291](https://github.com/blazebrt/perp-dex-radar/actions/runs/40386820291)
at source `30e8bbcf0af39cea4fd09c6d53a0a2a246047ae8` succeeded. The retained
report and provenance are `research/v9/a6_hosted_isolated_pilot.json` and its
`_provenance.json` companion. ZIP digest and measurement checksum were verified.
The placement receipt, both in-workload membership snapshots and accounting group
agree; the final in-workload peak matches the outer accounting value. Both new
groups were removed. Six normal audits passed and both deliberate interruptions
retained partial results, with all eight local Git payload checks passing.

Kernel peak was 83,361,792 bytes over 23.170 seconds, with all memory-event counters
zero. This verifies the small hosted isolation/accounting path. It does not cover
pre-migration bootstrap/outer accounting allocations, representative workload,
allocated-disk bounds, reviewed runtime/dependency identity or remote retention.
The report remains NOT_RESOURCE_QUALIFIED and no real study was reserved or run.

The runner-image discrepancy recurred: setup logs report `20261012.334.1`, while
captured ImageVersion is `20261023.334.3`. Provenance records both, with consistency
false; this experiment does not resolve runtime identity qualification.

## Service-managed startup accounting adapter (2026-10-27)

`control_service_memory.py` runs a trusted synthetic workload in a transient
systemd exec service. The manager starts a Python holder inside the service group;
the holder launches the workload, atomically writes its exit receipt, then waits
for the collector. The collector reads properties while the group is populated,
releases the holder and stops only the generated unit. Fresh-unit absence,
explicit argument handling, workload exit and inactive/absent cleanup are checked.
Logs, receipts and properties are retained on failure. No caller environment or
credentials are forwarded. The [systemd-run documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html)
describes manager-launched services and runtime inspection.

The original oneshot approach retained the unit but lost its empty cgroup and
MemoryPeak on the hosted runner; attempt 1 is preserved below. Schema /2 explicitly
scopes the peak THROUGH_WORKLOAD_COMPLETION_BEFORE_HOLDER_SHUTDOWN. Holder shutdown,
manager/orchestrator memory and escaped workloads are excluded. It is not a whole
job resource bound. Six tests cover mocked service lifecycle/failures and a real
local holder that stays alive after its child exits until the collector releases it.
Hosted startup verification and full resource qualification remain separate gates.

## Hosted service-startup pilot preparation (2026-10-27)

A separate `a6_service_probe.yml` read-only, branch-scoped workflow runs the
eight existing synthetic scenarios as a transient service on the disposable
Actions host. The orchestrator invokes systemd through sudo; the workload is
started by the service manager with no forwarded caller environment/credentials.
It retains service logs/properties/cleanup, the scenario report, runtime details
and explicit placement verification. Both workload membership snapshots must
match the service group, and their peaks cannot exceed the final service peak.

Startup placement relies on the service-manager launch contract plus in-workload
membership receipts; it is not an independent kernel trace of interpreter startup.
The manager and outer orchestrator are excluded. Hosted attempts are recorded below;
the reports remain unqualified for full-study resource budgets.

### Service pilot attempt 1: retained failure

Run [40413541548](https://github.com/blazebrt/perp-dex-radar/actions/runs/40413541548)
at `cda2b30b06c7dc69b37b869ae48f6b342473f163` completed all eight synthetic cases,
but failed service verification. After the oneshot exited, ControlGroup was empty
and MemoryPeak was [not set], although the unit remained active/exited. Cleanup
was verified. This disproved the assumption that retaining the exited unit also
retains its kernel peak on this runner. The ZIP digest was verified; the original
measurement and provenance are retained as `a6_hosted_service_attempt1*.json`.
No measurement checksum file was produced before failure; provenance records that
absence and the measurement's hash from the verified ZIP. No success is inferred.

The revised holder/collector handshake captures counters before the group empties.
The corrected synthetic pilot used a distinct workflow run; it does not replace this
failed attempt or constitute a market-study retry. Runtime identity discrepancies and
full-study resource qualification remain unresolved.

## Corrected hosted service pilot

[Run 40458892344](https://github.com/blazebrt/perp-dex-radar/actions/runs/40458892344)
at source `242fd30e47ffa7c912c49506d4fc2a5462f904a4` succeeded. Artifact
`12713547882` has verified ZIP SHA-256
`206a41cbb553eb15562ebee52e956c6ce8eb1990d77f891742dd83f176e1e048`;
the embedded measurement checksum also matches. Unchanged measurements and provenance
are retained as `research/v9/a6_hosted_service_attempt2*.json`; attempt 1 is preserved.

All eight synthetic scenarios completed as expected: six normal audits and two retained
intentional failures, with eight local Git byte verifications. Both workload membership
snapshots match the transient service. The final kernel peak and live service peak agree
at **90,574,848 bytes**; adapter elapsed time was **22.791 seconds**, all captured memory
events were zero, and the service was inactive/absent after cleanup.

The correction is hosted-verified for its disclosed scope: workload completion before
holder shutdown. Startup placement relies on the manager launch contract and in-workload
receipts, not an independent startup trace. Manager/orchestrator memory and the shutdown
tail remain excluded. This is not a whole-job bound or representative-scale qualification.
Disk sampling, dependency locking, remote retention and runtime reconciliation remain open:
setup logs again report image 20261012.334.1 while the environment reports 20261023.334.3.
No market inputs, reservation, evidence-history record or promotion authority were created.

## Live capacity respects ancestor limits

The preflight previously used only host `MemAvailable`. A job can have less usable
memory because its current cgroup or any ancestor has a hard limit shared with
other processes. The live reader now takes the minimum of host availability and
`max(0, memory.max - memory.current)` for every visible non-root ancestor, retaining
the raw limit/usage/headroom receipts. Unlimited groups add no extra constraint;
the root uses host availability. No swap or expected reclaim is credited.

This follows the hierarchical limits documented in the
[kernel cgroup v2 reference](https://docs.kernel.org/admin-guide/cgroup-v2.html).
The reader requires unified-only membership and a full-root cgroup2 mount, rejects
missing or malformed counters, and checks that membership stayed unchanged during
collection. Tests cover ancestor/sibling pressure, exhausted limits, unlimited/root
groups and invalid inputs. A synthetic case that passed with host-only capacity now
fails the existing two-times memory-headroom gate under its ancestor limit.

This is a conservative snapshot of visible capacity, not a memory reservation.
Concurrent usage and limits can change, and namespace/host identity still requires
the independently qualified hosted environment. It does not qualify sampled disk,
small synthetic scale or remote publication, and does not authorize the market run.

## Explicit synthetic measurement sizes

The measurement CLI now honors paired `--signals` and `--bars` options for all
four scenarios and records `requested_scales`. Previously these options were
accepted by the normal entry point but ignored. Omitting both preserves the
eight-case protocol; a partial or invalid pair fails before measurement.
Signals are **per available trial**, not total study signals. The fixed synthetic
asset/trial population and bounds (3..100 signals, 400..4,000 bars) remain unchanged.
These are diagnostic samples, not full-study qualification or an extrapolation.

## Cleanup after observer failure

If disk or memory observation raises, the probe now terminates the worker's
private process group, waits at most two seconds, and forcibly stops remaining
group members before a bounded five-second leader reap. Previously only the
leader received termination and its wait had no timeout. A leader exiting does
not imply its children exited; escalation therefore also runs in that case.
Real Linux tests cover a child ignoring termination and both leader and child
ignoring it. Processes that deliberately leave the private group/session remain
outside this contract. This improves failed-probe cleanup, not resource bounds.

## Configurable synthetic population width

Both probe CLIs accept `--assets`, `--definitions` and `--unavailable` alongside
signal/history sizes. Defaults remain 61 assets, three definitions and one
unavailable definition. Bounds permit 781 assets and 199 definitions, with an
explicit unavailable count that leaves at least two available definitions. Trial
identities are unique and preserve the original three identities by default.
The sparse scenario deliberately retains eight assets; reports distinguish its
actual assets from requested population dimensions. Expected signals are
`(definitions - unavailable) * signals_per_available_trial`; interrupted cases
report their smaller processed count separately.

Validation covers the 199-definition/seven-unavailable roster without executing
that population. End-to-end tests execute a small 62-asset expanded population,
including independent audit and isolated CLI forwarding. Neither is a resource
bound. The limits of 100 signals per available definition and 4,000 history bars,
repetitive synthetic prices, sampled disk and excluded remote publication still
prevent representative qualification. No workflow was activated or dispatched.

## Study-volume signal generation capacity

The signal limit is now 25,000 per available definition, with an additional
capacity check against the eight-asset sparse scenario. Generation fills each
asset's pre-terminal indices 180 through `bars-2`, then moves to the next asset;
the final attempt remains asset zero at `bars-1`. No asset/time pair is repeated.
Original <=100-signal cases retain their exact coordinates. With 400 bars, the
sparse-case maximum is 1,753; with 4,000 bars, 22,207 signals are possible and
192 available definitions would yield 4,263,744 signals.

That full volume has **not been executed or measured**. Tests generate its index
arrays only, and separately execute/audit a 221-signal sparse case that crosses
an asset boundary. All definitions still share simplified signal geometry and
synthetic price histories; these counts do not establish representative diversity.
History lengths, shard/publication volume, combined resource bounds and hosted
identity remain unresolved. No workflow was dispatched by this change.

## Output shard sizing for representative measurements

The synthetic pipeline formerly forced four-row output shards. It now accepts
`--shard-rows` from 1 through 25,000 in both CLIs, preserving four as the default
while allowing the intended outcome runner's 25,000-row setting. The existing
16 MiB uncompressed byte cap can still split a file earlier. Reports disclose
both limits and pair/day/reuse shard counts. Input extraction sizing is unchanged.

A small sparse test compares every retained packed pair, day and reuse record,
side summaries, independently verified statistics and audit success between
four-row and 25,000-row output layouts. Pair shards drop from four to two with
identical records. CLI integration verifies forwarding to isolated workers.
This is logical-layout parity, not large-volume compression, runtime, storage
or remote-publication qualification. No workflow was dispatched by this change.

## Intermediate local attempt 1: no measurement report

A local synthetic invocation at `a39b753f73fa8b0514edf9873ad9177486f2af7d`
requested 128 assets, 12 definitions (two unavailable), 128 signals per available
definition, 4,000 bars and 25,000-row shards across four scenarios. It used a clean
checkout under WSL, with a requested 180-second timeout and ten-second kill grace.
The tool returned exit 1; no final report was created and the log was empty.
The underlying timeout exit status and termination cause are **unknown**. This
is not evidence of an OOM, a runtime bound, or a defect in scientific results.

The original environment and log plus provenance are retained under
`research/v9/a6_intermediate_attempt1_*`. A later process snapshot found no matching
probe processes; that does not establish graceful cleanup. Kernel messages about
unclean journal handling do not identify the cause. With no durable case-level
receipts, neither completed cases nor local Git verification can be inferred.
Add durable progress receipts before another larger attempt. No successful
measurement or qualification is claimed, and no market study was started.

## Per-case progress receipts

The parent measurement CLI now creates `OUT.progress` by default, or accepts a
fresh `--checkpoint-dir`. It records the plan/source hashes before work, a
started receipt before each case, and the original measurement after completion.
A later exception preserves earlier cases and records only its class. An abrupt
exit can leave a started-only case without a failure receipt; that is incomplete,
not success. Existing directories are refused, and no automatic resume is offered.

Each receipt is exclusively created and file-flushed, published by a non-overwriting
hard link, then directory-flushed. The new directory's parent is flushed too.
Ignore `.pending` files. The final marker says measurements completed and includes
the expected final-report hash; it does not prove the report exists or was published.
Tests cover abrupt process exit, later exceptions, overwrite refusal and actual
CLI case/report equality. Durability still depends on OS/filesystem semantics;
this is not a guarantee against VM or storage loss. Active-case internal progress
and observer/checkpoint overhead are not measured by completed-case timings.
Attempt 1 remains unchanged; no replacement large measurement has been run.

## Intermediate local attempt 2: completed with progress receipts

A smaller run at `12397a3204eaaecb89d6f62b1e9844645e72491b` used 96 assets
(eight for sparse), six definitions/one unavailable, 64 signals per available
definition, 2,000 bars and 25,000-row shards. Both observed exit codes were zero.
Three normal cases each processed 320 signals and passed their independent audits;
the intentional interruption retained its expected failure after three signals.
All four local Git byte checks passed. All case receipts, their hashes and the
final-report hash were verified. Raw records and provenance are retained in
`research/v9/a6_intermediate_attempt2/`; attempt 1 remains unchanged.

| Scenario | Measured seconds | Worker peak RSS bytes | Sampled session RSS bytes | Sampled allocated disk bytes |
|---|---:|---:|---:|---:|
| Full | 25.185 | 51,195,904 | 60,854,272 | 21,606,400 |
| Mixed | 24.950 | 50,950,144 | 95,657,984 | 21,307,392 |
| Sparse | 3.599 | 24,936,448 | 34,500,608 | 2,686,976 |
| Intentional interruption | 3.663 | 44,855,296 | 49,180,672 | 12,111,872 |

Every case recorded a descriptor-access gap; session scan gaps also occurred.
These are local WSL diagnostic samples, not combined memory/disk upper bounds,
representative histories or hosted-runner qualification. Session RSS can double
count shared pages. Observer/checkpoint overhead and remote publication are
excluded. This smaller successful run does not identify attempt 1's cause.

## Longer histories and distributed signal placement

The synthetic history cap is now 32,768 bars (minimum 400). This is a diagnostic
limit, not a verified bound on the pinned archive's longest source. Neither
source-history coverage nor full-scale resources are qualified by this change.

Both CLIs accept `--signal-placement spread`. It distributes distinct signal
positions through the flattened pre-terminal time/asset grid and keeps the final
asset-zero terminal attempt separate. The default `prefix` retains earlier
behavior. Reports and per-case progress plans identify the chosen placement.
Pure tests verify maximum bounds, uniqueness and terminal handling; a small
8,192-bar sparse case with spread placement passes the independent audit, and
CLI integration verifies worker forwarding. Synthetic prices and definitions
remain simplified. No large history/population combination or market archive
was measured here; all prior retained reports remain unchanged.

## Intermediate local attempt 3: long histories with spread placement

Source `ccfc29e90f606ebdf962777b8c01dc2f62b87f4c` completed all four scenarios
with 16,384-bar synthetic histories, spread placement, 96 requested assets (eight
for sparse), six definitions/one unavailable, 64 signals per available definition
and 25,000-row shards. Wrapper and tool exit codes were zero. Each normal case
processed 320 signals and passed its independent audit; the intentional interruption
retained its expected failure after three signals. All four local Git byte checks,
case-receipt hashes and the final-report hash verified. Original files are retained
in `research/v9/a6_intermediate_attempt3/`; earlier attempts remain unchanged.

| Scenario | Measured seconds | Worker peak RSS bytes | Sampled session RSS bytes | Sampled allocated disk bytes |
|---|---:|---:|---:|---:|
| Full | 58.167 | 156,151,808 | 168,386,560 | 115,019,776 |
| Mixed | 52.718 | 156,397,568 | 169,697,280 | 114,974,720 |
| Sparse | 5.535 | 54,296,576 | 59,670,528 | 10,584,064 |
| Intentional interruption | 19.309 | 153,546,752 | 163,115,008 | 91,693,056 |

All cases recorded descriptor-access and session-scan gaps. These local samples
are not resource upper bounds. Long synthetic histories do not establish coverage
of every real bound source; signal/definition/asset counts and prices remain
unrepresentative. Shared-page double counting, missing peaks, observer/checkpoint
overhead, incomplete dependency attestation and remote-publication exclusions
still apply. No hosted qualification, market attempt or promotion follows.

## Optional synthetic price diversity (2026-10-29)

Both probe entry points accept `--price-profile baseline|diverse`; baseline remains the default and preserves the original OHLC/volume values. The deterministic diverse profile varies bounded asset-offset triangular trends, signed within-bar returns, wick widths and quote volume using integer mixing, without random state, network calls or market inputs. Existing mixed-case faults remain applied after price generation. Reports, worker results and progress plans identify the selection; report and receipt source bindings include `control_probe_prices.py`.

This addresses repetitive-fixture coverage only. The profile is not calibrated to market distributions, does not prove worst-case compressibility or outcome diversity, and is not a resource bound. Prior retained attempts remain baseline measurements. Larger diverse-profile measurements, representative archive dimensions and full-volume resource/publication bounds are still required. Qualification remains unsatisfied.
