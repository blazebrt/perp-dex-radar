# A6 registered outcome-attempt retention

This operational contract supplements the committed execution/inference rules.
It changes no signal, matching, execution, cost or statistical definition.

Before loading market sources, a future workflow must reserve the previously
absent branch `evidence-a6-outcome-results`. The reservation pins the source
commit, Actions run ID, attempt `1`, accepted A6.2 result commit and manifest hash,
and both this document and the execution/inference protocol hashes. Its status
is `RESERVED` and promotion authority is false. Any existing branch or prior
attempt blocks a fresh application, including after interruption. Recovery must
inspect retained files; it cannot silently rerun the study.

`control_outcome_publish.py` validates and copies that reservation, refuses an
existing output directory, records `STARTED`, executes outcomes and the independent
audit in separate processes, then inventories all retained files and logs.
Partial outputs and exceptions produce `FAILED_OR_PARTIAL`. Success requires the
entire registered 4,263,580-signal population, 199 definitions, seven explicitly
unavailable hourly populations, 398 sides and all independent audit layers.
Net inference and promotion remain unavailable even on success.

The workflow must always publish retained files as a normal fast-forward
descendant of the durable reservation, without force pushes. A hard interruption
leaves the reservation blocking repetition. The local wrapper cannot prove remote
reservation ancestry; the workflow and retained-package verifier must enforce it.
The workflow must report failure only after retention, and preserve a backup
artifact when possible. A successful wrapper is not sufficient to mark A6.3 done.

Before the single market attempt: qualify runtime/storage, implement durable
workflow retention and append-only evidence recording, and test failure recovery.
No workflow is activated by adding this contract or wrapper. The actual outcome
attempt, including failure or unavailability, must be recorded in the evidence
history and independently reconciled after durable publication.

## Resource preflight before reservation and execution

The future workflow must run `control_resource_gate.py` before reserving the market
attempt, using an independently reviewed qualification report pinned by hash and
a current capacity snapshot. The reservation must additionally pin
`resource_qualification_sha256` and `resource_gate_sha256`. The wrapper repeats
that check before reading the signal inventory or invoking either study process.
It retains the report and successful preflight snapshot with the attempt. A
missing/invalid report or insufficient capacity yields retained failure without
outcome execution; a prior remote reservation continues to block repetition.

The report must match the exact source commit, execution protocol, accepted input
manifest and runner profile. It must cover at least 4,263,580 synthetic signals,
199 definitions, 781 assets and the bound archive's history lengths, with the full
pipeline, publication limits and failure retention reviewed on the hosted runner.
Only bounded combined-process memory and allocated-disk evidence is accepted;
sampled/lower-bound reports do not qualify. Bounds must fit within half of live
available memory, half of free disk, and 60% of the remaining job time, including
audits and publication. Current local reports deliberately fail this gate.

The CLI obtains memory/disk capacity on Linux; the workflow must supply the
verified runner profile and conservatively remaining timeout. Qualification report
content and its hash need independent review: the gate verifies the declared
contract and arithmetic, not the truth of measurements. It is a preflight, not
a runtime resource monitor. No qualification report or market activation is created
by adding the guard. The hosted workflow and review remain outstanding.
