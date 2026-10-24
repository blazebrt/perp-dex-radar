# A6 first extraction and audit retention

Registered before market application. This is a source-validation and complete
generated-signal inventory attempt, not matching, execution or outcome research.
All prior A6 contracts and the independent audit protocol apply unchanged.

Before exporting market data, the workflow creates a durable reservation on
`evidence-a6-results`. Any existing branch blocks a new attempt, including a
reservation whose process was cancelled or never finished. Reservation races
are resolved by normal fast-forward Git updates; no force push is used. Recover
an existing attempt rather than launching another. A new authorized attempt
requires separate registration and deliberate recovery planning.

Export exactly original archive `4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7`
and phase-B evidence from `e4c0f0d8a5926ab54dd17da9ba7309518c77f611`.
The source commit is the workflow commit. Call the extraction once, then the
independent audit once if a completion manifest exists. Run these as separate
processes so large archive and feature arrays are released between stages.
An export failure is preserved as a failed extraction preflight, not retried.

`control_publish.py` writes an outer STARTED marker before execution and retains
logs, partial shards, failure records, extraction outputs and audit outputs. A
hashed inventory covers every retained file except the outer self-referencing
attempt record. Success requires 192 audited trials and seven explicitly
unavailable hourly populations. Failure or partial status never becomes an
empty successful population. A killed process can leave STARTED or temporary
files; those remain incomplete evidence, not completion markers.

Publish all retained files as a normal descendant of the reservation commit,
without deleting historical evidence. Publication runs after failed stages when
the runner remains available. An artifact backup is a recovery aid, not a
replacement for the results branch. A hard cancellation can prevent publication;
the durable reservation still blocks accidental repeats. Report failure only
after attempting retention. Never force-update the results branch.

Do not mark A6.2 complete until the exact retained commit, manifests, source
bindings, independent audit and trial counts have been inspected. This inventory
is not a strategy evidence run and adds no fictitious return-study record to
`evidence_runs.jsonl`. No matched outcomes, strategy promotion, merge or production
deployment follow from this attempt. Separate execution/inference registration
is still required before market matching or outcomes.
