# A5 trade reconstruction diagnostic protocol

This additive protocol follows the rejected hourly audit, before running the
new reconstruction tool on market data. The SHIB investigation already described
in `phase-a5-data-conflicts.md` is prior knowledge, not an unseen validation case.
The original acquisition protocol and rejected archive remain immutable.

## Fixed diagnostic scope

Investigate every distinct disputed four-hour block in rejected results
`003ddccc825b5aeaec1beab834c56f21b8baa9a8` (94 blocks, 87 segments).
Use the matching Binance USD-M daily raw trades ZIP and published checksum.
Preserve object identity, ZIP hash, checksum-file hash and source reference hash.
Do not select blocks by subsequent returns or strategy performance. Missing
objects or invalid records are failures, never inferred zero-trade observations.

The [provider format](https://github.com/binance/binance-public-data#futures)
contains trade ID, price, base quantity, quote quantity, time and buyer-maker flag.
Use decimal arithmetic, retain timestamp precision, and preserve trade-ID order
for trades sharing a timestamp. Buyer-maker false means taker-buy volume.
Reject duplicate/decreasing IDs, decreasing timestamps, wrong-day records,
invalid booleans and nonfinite/nonpositive numeric fields. Report ID gaps;
consecutive IDs are a consistency check, not proof of complete provider history.

Reconstruct every OHLC and volume field from records in each affected block,
not just the originally conflicting field. Empty hours remain absent, with no
invented price or zero-volume candle. Require an observed trade before and after
the block within the same daily file and consecutive IDs throughout that span
before marking local continuity as checked. Blocks touching the day's boundaries
remain unbracketed; future support for adjacent days requires a separate change.

Compare all six reconstructed four-hour fields with the unchanged pinned source
using relative tolerance 1e-8 and zero absolute tolerance. Output every mismatch,
gap, missing hour and boundary limitation. A matching aggregate does not prove
hourly path correctness. The tool must never overwrite the original candles,
emit an accepted dataset manifest, revise the top-150 schedule, or run strategies.

## Acceptance remains separate

The output is a diagnostic candidate, even when continuity and reconciliation
checks pass. A later dataset protocol must bind original and replacement hashes,
specify unresolved exclusions and missing-hour execution handling, and assess
ranking effects. In particular, exclusions cannot silently remove bad trades or
backfill the top-150 universe. Existing four-hour replay results remain bound to
their original inputs. No new strategy or production authority follows.
