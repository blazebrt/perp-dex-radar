# A6 generated-signal population contract

Additive registration before any A6 market signal extraction. Preserve the
unchanged 192 four-hour/daily generators and exact census parameters. Their
complete output arrays are the denominator, before `qsim.run`, position limits,
entry checks, trade qualification, control selection or outcome availability.
The seven hourly trial identities remain explicitly unavailable.

The adapter accepts source-validated segment rows and original panel/feature
objects. It streams one record per generated signal whose decision close lies
in the registered A4 window, including both endpoints. Warm-up signals before
the start and outputs after the end are counted separately, not confused with
missing or failed signals. A terminal signal is retained with
`next_entry_bar_observed=false`; it cannot silently disappear because no later
price exists. Original duplicates and original ordering are retained; a source
ordinal distinguishes otherwise identical generated signals.

Require identical-length arrays `i,j,d,stop,target,trail,be,hold`, valid panel
indices, directions of -1/+1, finite geometry, positive stops and integer
positive holding periods. Reject malformed output with retained failure at the
future writer layer. Never coerce NaN into zero or repair a strategy definition.
Record the exact geometry, trial ID, generator ordinal, decision timestamp,
segment identity and original eligibility. Do not apply position-state filters.

Use the exact A6 feature helper on the seven-day window at that decision. An
indexed segment view may select the window plus the original first-bar record
to avoid repeatedly scanning a full archive; synthetic equivalence must show
that this gives the same feature output as the full source arrays. No missing
bars are synthesized. Preserve source-file hashes and explicit missing/disputed
feature reasons. Keep signal quality unqualified even when the volume window
is available.

Separately count missing source bars and known disputed opens from the segment's
first bar through the decision close. These are conservative own-segment
history annotations, not exact indicator dependency proofs. A zero count does
not validate cross-asset inputs, recursive state, funding or unexamined sources.
Known disputes are retrospective. Do not reset indicators or suppress affected
signals. Apply actual reconstructed market eligibility supplied by the unchanged
feature object, and preserve false eligibility rather than overriding it.

The remaining archive driver must verify all original source bytes, generator
and dependency hashes, complete census identities and source panel fingerprint;
call each registered generator once; retain empty and failed trial records;
write bounded shards without overwriting prior artifacts; and publish a final
manifest only after all streams close. A separate verifier must reconcile every
raw generator ordinal/parameter and feature window. This adapter alone is not
that completed application, nor permission for market matching or outcomes.

Synthetic acceptance includes full denominator accounting, duplicates, terminal
signals, malformed arrays/indices/geometry, unchanged eligibility, missing and
disputed history annotations, future-append invariance of existing features and
equivalence of indexed versus full-source windows.
