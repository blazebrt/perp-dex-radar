# A6 source validation and signal extraction driver

Registered before any A6 market extraction. This stage produces a diagnostic
population inventory, not a matched-control outcome study or strategy evidence.
The control design, feature-quality and signal-population contracts still apply.

`control_extract.py` verifies the frozen census plan and source-inventory hashes,
and compares all six evidence-bound research files with A4 source
`ad2374fa4d25f03c204ce7c0cdbecac95cba6246`. It verifies every original broad-universe
candle file through the source loader before invoking any strategy. The phase-B
evidence file must match the retained probation binding. The panel digest,
computed after the unchanged feature constructor as in phase B, must match that
evidence. The inclusive decision window is `[1588204800, 1790812800]`.

Each of 192 four-hour/daily definitions is invoked once with its original
parameters. All generated ordinals are passed to the projection contract before
execution filtering. Seven hourly identities remain explicitly unavailable;
the frozen A5 replay is not rerun or substituted. No simulator, control matcher,
outcome calculation, inference or promotion runs here.

Outputs are deterministic gzip JSON-lines shards, capped at 25,000 records and
16 MiB uncompressed per shard. A record larger than that limit fails its trial;
it is never truncated. Each closed shard records its digest, compressed and
uncompressed sizes and row count. Empty successful populations have zero shards.
Trial validation/generator errors retain closed partial shards and an explicit
failure instead of a fabricated zero population. Ordinary trial failures allow
the remaining definitions to be inspected once. Filesystem errors and unexpected
fatal exceptions abort the extraction and retain a failure record where storage
permits. Existing output directories containing evidence are never overwritten.

Individual trial records are written after their shards close. The manifest is
written last and distinguishes partial extraction from completion with seven
unavailable hourly populations. A fatal failure has no completion manifest;
abrupt process termination may leave an incomplete shard and no failure record,
which must remain an incomplete attempt. A later publisher must retain all
files, including partial ones, and must not fabricate completion.

The manifest binds original source, plan, inventory, panel, adapter and protocol
hashes. Broad archive quality is still limited to known disputes; historical
funding handling is inherited solely to reproduce original signals, not to
qualify funding or returns. Source-bound generator execution is not independent
validation of the generators' mathematics.

Before the first market application, add durable Actions publication and a
duplicate-attempt guard, plus independent population reconciliation. No local
archive fetch or market extraction is authorized by these synthetic tests.
Execution/inference requires its separate preregistration before matching or
outcomes. A6.2 remains open until the retained extraction is independently audited.
