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
