# A5.3 replay publication and evidence-run recording

Registered before market application. Use the pinned dataset and driver protocol
in phase-a5-replay-driver.md; all earlier gap, funding and signal restrictions apply.
This publication layer adds no strategy parameters, optimization or qualification.

A run exports only accepted result commit 0859e683910a7eea7ef446b27cf9773f33d9e9f8.
Run focused synthetic tests before export/application. A failed dataset export must
reach the replay preflight and be retained as a failed attempt, not disappear.
Use a fresh output directory and run the driver once. Do not retry individual
segments or discard failed trials. Keep all partial streams and the failure record.

The outer replay_run.json records COMPLETED_WITH_UNAVAILABLE_RESULTS,
PARTIAL_FAILURE or FAILED. It is a run-attempt record, not the driver's completion
marker. Retain the original evidence_a5.json only when the driver produced it;
never synthesize that marker following failure. A5 full-family completeness and
promotion authority remain false, and confirmed sides remain empty.

Write REPORT_A5.md, attempts_a5.json (hashes of all available compressed attempt
streams), input/protocol bindings, and hashes of every retained driver artifact.
An empty attempt manifest after fatal preflight is explicitly failed, not a zero
return run. The outer record binds every preregistration used by the attempt.
Run metadata identifies source branch, exact source commit, timestamp and Actions
run/attempt. Publication uses a normal fast-forward update of evidence-a5-results;
prior result commits remain recoverable. Never force-push, deploy or update main.

The workflow refuses to start another replay when its publication protocol hash
already has a retained result on the result branch. Failure is evidence too. Any
necessary retry requires a separately reviewed registration/decision, not repeated
sampling until a preferred result appears. Publication failures retain a backup
Actions artifact; an unpublished attempt must be recovered before any retry.

After publication, fetch the exact result commit, verify each artifact and append
an A5 entry using record_run.py to the existing hash-chained evidence history. The
recording layer recognizes the separate accepted A5 dataset, preserves all prior
records, verifies compressed stream hashes, and never labels A5 as phase-B data.
Independent result reconciliation is still required after artifact verification.
