# A5 adjacent-day continuity diagnostic

Register before acquiring or applying adjacent-day evidence. Scope is the five
unbracketed blocks in the unchanged first trade diagnostic: ALPHA 2023-07-31,
EOS 2020-01-19, TRUMP 2025-01-29, XRP 2020-01-16 and XRP 2020-01-17.
Use the immediately preceding UTC day for a missing opening bracket and the
immediately following UTC day for a missing closing bracket. Reuse already
saved objects only if their original hashes match; otherwise preserve new
daily trade ZIPs and published checksums. Do not search further days until a
match is found or select boundaries using strategy returns.

Validate complete daily files with the existing trade parser, keeping timestamp
precision and strict ID/time ordering. Recompute and reproduce the original
in-day bracket status, trade count and missing-ID ranges before extension.
Use the last preceding-day trade or first following-day trade as appropriate.
Require chronological timestamps and strictly increasing IDs at each join;
record nonconsecutive ID ranges as gaps. Empty/missing/invalid adjacent data is
unresolved, never evidence of zero trading or permission to invent a record.

Report original and extended brackets, gap ranges, hashes and per-object record
counts. An added bracket does not remove an internal missing-ID range, alter
volumes/prices, or settle disagreement with the pinned candles. Consecutive IDs
are a local consistency check, not proof of complete exchange history.

Keep all previous protocols and results unchanged. The 20 prior ID-gap blocks
remain unresolved unless separate evidence addresses their missing IDs; this
diagnostic does not interpolate them. It cannot emit accepted candles, change
historical ranking, run strategies, or authorize production. Record failures
and completed diagnostics before designing the dataset repair/exclusion policy.
