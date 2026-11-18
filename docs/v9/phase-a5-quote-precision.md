# A5 dual quote-precision diagnostic

Register this supplement before applying the new tool to the 94 disputed blocks.
The prior ALGO observation is known evidence, not a holdout. Preserve the first
trade diagnostic, its protocol and its raw inputs unchanged.

Use exactly the 94 checksummed trade objects already bound in
`research/v9/a5_trade_diagnostics.json` at commit `03dc88a`.
For every trade in every requested block, separately sum (a) the published
quote amount and (b) decimal price times decimal base quantity. Report both
hourly and four-hour totals, including taker-buy totals. Keep 80-digit decimal
arithmetic; apply the unchanged relative 1e-8, zero-absolute comparison to the
pinned four-hour source. Do not choose a volume treatment by strategy returns.

Validate the complete daily files, object checksums, UTC date, timestamp and ID
ordering, positive finite fields and buyer-maker flags. Verify original quote
sums and trade counts reproduce the prior hourly diagnostics exactly before
reporting the product sums. Count records whose two quote treatments differ.
Use a streaming implementation; retaining all trades in memory is unnecessary.

Separate unchanged price conflicts from quote-volume conflicts. Carry forward
all missing-ID and boundary-bracketing limitations; product-volume agreement
does not resolve them. Do not invent precision bounds or assume every difference
is rounding: report the actual signed differences. A matching product sum is
corroboration only, not proof of transaction completeness or a replacement rule.

The output is a second diagnostic with source, protocol, code and prior-record
hashes. Preserve failed runs. Never overwrite prior files, change the causal
schedule, emit an accepted dataset marker, or run strategies. Dataset repair,
exclusions, adjacent-day boundary evidence and replay gap handling remain
separate acceptance work.
