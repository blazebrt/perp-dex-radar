# A5.3 pinned archive replay driver

Registered before any hourly market trial. The driver binds the accepted candidate
manifest SHA-256 d9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2
from result commit 0859e683910a7eea7ef446b27cf9773f33d9e9f8. Verify the complete
artifact inventory and every content hash before strategy execution. Recheck each
segment file immediately before reading it. Never accept an alternate dataset by
CLI override. Original acceptance and preregistrations remain unchanged.

Read the plan's exact study window, segment identities, first-bar dates and ordered
quality schedule. Validate unique segments, exact day coverage, membership and BTC
context. Use the complete retained earlier history for feature warm-up, clip bars
at study end, and submit emitted signals from the hour before study start onward.
A terminal signal entering exactly at study end remains an unexecuted attempt.
Funding events follow phase-a5-funding-disposition.md; no completeness is inferred.

Process segments in lexical identity order with independent per-trial position
ledgers. There is no shared position budget in this registered replay. Project each
day's selected list to the segment without reranking, replacing members or changing
the global embargo. This must give the same attempts and outcomes as a joint batch
ledger, apart from local emission ordinals and physical output order. Do not combine
relisted segments. BTC is context only for BTC_LEAD, not for the other definitions.

Write gzip JSON-lines streams for all seven trial aliases, including a segment
record and every supplied signal attempt. Within a segment the batch preserves its
registered time ordering. FUND_CARRY has one explicitly unavailable trial record;
its daily values are null. FUND_FADE is unavailable for any segment with off-grid
funding in [study start minus one hour, study end); retain the reason instead of
rounding or dropping events. It remains conditional on observed funding events.

Retain failed segment records with their error and continue other segments. Any
failed/unavailable segment invalidates that trial's full net series, as does any
unresolved execution. Never substitute zero for those daily values or present a
resolved subset as the trial. A genuinely completed trial with no executed outcomes
can have zero daily outcomes within the stated restrictions, not a claim of known
historical funding coverage. Gross-price diagnostics confer no net qualification.

Write the final evidence manifest only after closing all seven attempt streams.
Include per-trial statuses/counts, daily values, artifact hashes, source/protocol
hashes and all retrospective restrictions. A fatal preflight/writer error creates a
failure record; output folders cannot be overwritten. Full-family matrix and
historical census completeness, promotion authority and confirmed sides remain
false/empty. This completes driver implementation only. Before market application,
the code and protocol must be committed; results need durable publication,
append-only evidence-run registration and independent reconciliation.
