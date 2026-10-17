# A5 source-data conflict investigation

Acquisition attempt 2, run `38902486359` on `d0c4a35`, passed the corrected
zero-trade-hour aggregation for 1000BONK and then failed on a different issue:
1000SHIB quote volume at Unix timestamp `1657944000`. Partial results are at
`30674ea2e5f5f876a214f6ce4461a1799a56d487`. No accepted manifest or strategy
result was produced. The original protocol and acceptance tolerance are intact.

## Direct source comparison

All four hourly rows exist. The corresponding 240 minute rows also exist.
The minute data matches the hourly aggregation exactly:

| Source resolution | Quote volume | Taker-buy quote volume | Trade count |
|---|---:|---:|---:|
| 240 minute rows | 26617593.918222 | 12265173.899848 | 47696 |
| Four hourly rows | 26617593.918222 | 12265173.899848 | 47696 |
| Current exchange four-hour row | 26631927.249474 | 12279507.231100 | 47709 |
| Provider trade-level file, same window | 26631927.249474 | 12279507.231100 | 47709 unique IDs |

The pinned four-hour export agrees with the current exchange four-hour row
after its ten-significant-digit rounding. This is a provider inconsistency,
not an export rounding error. The matching finer resolutions are corroboration,
not authority to silently replace the pinned source or its historical rankings.

Follow-up trade-level inspection supports the four-hour totals. The 47,709
unique records in the provider's daily trades file reproduce its quote and
taker-buy volumes exactly using decimal arithmetic. Its published checksum
matches the downloaded file. The minute/hourly sources omit 13 records relative
to this tape. Those records also change the 05:00 UTC hour's close: the tape
closes at 0.010651, whereas the hourly file closes at 0.010637. Repairing only
volume would therefore leave a price error. Any proposed repair must reconstruct
all hourly fields for the affected block and preserve the originals.

The tape contains one gap in its ID span, so this cross-check is not a claim of
proven transaction completeness. No dataset acceptance rule has been relaxed.
The source format is documented in [Binance Public Data](https://github.com/binance/binance-public-data#futures).

SHA-256 of the files inspected:

- Pinned `h4/1000SHIB.csv.gz`:
  `e7310eb736424566feaa7005c2a6d5ac70e7dbea5df8c3a0243638c2d5cc48c0`.
- Monthly `1000SHIBUSDT-1h-2022-07.zip`:
  `03f07fe9d1e0858cb7156dcdf9db43de06e99a98f0e0a7cdd31efb1775b89111`.
- Monthly `1000SHIBUSDT-4h-2022-07.zip`:
  `85ebc2bf34df02d59bce39479e0b477bc32a3fafbb242e179e62c62f9954d432`.
- Monthly `1000SHIBUSDT-1m-2022-07.zip`:
  `b3699d788c61ded5afb0a97a780ad9ee812efc3481a62de954b9795f89738c61`.
- Daily `1000SHIBUSDT-trades-2022-07-16.zip` (also matches its `.CHECKSUM`):
  `5c00d9e3fcc51bb292b7cc712bd4f62eac13fdaf7e5b2dc8324ec118f3d6ee76`.

## Completed conflict audit

Run `38903923119` on `34ec1d328034bd2a5cff7322fe14bbe8db4f0f80`
collected all requested segments. Its acceptance step failed as intended and
its preservation step succeeded. Results are pinned at
`003ddccc825b5aeaec1beab834c56f21b8baa9a8`; only `rejected_manifest.json`
exists, with SHA-256 `2f6af2c6ded2bca99c07b88cf9bc8d046261767a91afca4347e81da0fa613d09`.

Independent verification checked every artifact hash, all 13,862,338 saved
hourly rows, coverage, 19,425 source-object identities, the structure of 2,345
daily schedules and every recorded hourly conflict value. The collection spans
690 segments, with 7,026 explicitly missing hours and 663 zero-trade hours.
These checks do not establish transaction completeness or independently
redownload and authenticate every provider four-hour candle.

There are 189 conflicting fields in 94 four-hour blocks across 87 segments:
93 quote-volume, 85 taker-buy-volume, four close, two open, three low and two
high conflicts. Potential ranking exposure covers 630 coin/day windows over
63 days. This counts windows whose prior seven-day volume includes disputed
blocks; it does not establish that actual top-150 membership changes.

The compact verification record is `research/v9/a5_audit_verification.json`.
All three attempts remain in `research/v9/a5_attempts.jsonl`. No strategy trial
was run on this hourly collection. All 999 regression tests pass; source-commit
push and PR CI passed. The failed acquisition status is a data-quality result,
not a failing regression suite.

## Remaining acceptance work

Pre-register a defensible reconstruction or exclusion protocol and explicit
missing-hour handling before any replay. Preserve original observations and
hashes, reconstruct all affected fields, and verify repaired blocks against
independent evidence. Do not treat matching minute/hourly data as authoritative:
the trade-level case above contradicts them. No tolerance has been relaxed.

The existing A4 replay reproduced its pinned inputs; it did not independently
establish that every provider candle is correct. A5.2 acceptance, A5.3 hourly
strategy replay and A4.4 complete-family assembly remain incomplete.

## Trade reconstruction diagnostic (2026-10-17)

The additive protocol and tool were committed as `2bf7eac` before the all-block
run. All 94 disputed blocks were examined using 94 checksummed daily files,
scanning 64,523,776 records. No source download or parsing failed. Independent
recomputation reproduced all 376 hourly candidates; all 378 saved artifact
hashes match. The complete diagnostic and provenance record is
`research/v9/a5_trade_diagnostics.json`. Raw downloaded files are retained in the
local task's `outputs/a5-trade-diagnostics/` directory, not the production archive.

| Check | Blocks |
|---|---:|
| Aggregate matches pinned four-hour source | 50 |
| Locally continuous IDs with both boundary brackets | 70 |
| Both of the above | 40 |
| Aggregate disagrees | 44 |
| ID gaps | 20 |
| Missing boundary brackets | 5 |

ID gaps and missing brackets overlap in one block. No candidate hour was empty.
These checks do not establish complete transaction history, and none
of the candidates has replaced source candles or been accepted for replay.

A separate exploratory ALGO check identifies a precision issue: for 19,477
trades, the file's quote amounts sum to 5326605.1193, but decimal price times
quantity sums to 5326605.75953. The latter matches pinned 5326605.76 within the
original tolerance. Of those trades, 12,760 have a reported quote amount different
from price times quantity. Taker-buy product volume similarly gives
2636605.69158 versus pinned 2636605.692. This observation is post-protocol and
preserved separately; the first-pass report still uses the published quote field.

The next diagnostic must explicitly preserve and compare both volume treatments,
without relaxing tolerance or changing the original report. Price discrepancies
also persist: the BTC 2023-11-10 trade close is 37092.6 versus pinned 37118.4;
EOS 2020-01-19 differs in all four price fields. Missing-ID and boundary cases
remain unresolved. A replacement/exclusion and missing-hour execution protocol
must follow that investigation before A5.2 acceptance or A5.3 replay.

## Completed dual quote-precision diagnostic

Protocol and tool were committed at `0de6055` before application to all 94 saved
trade objects. Published quote sums and trade counts reproduce the first-pass
report exactly. The new report preserves both quote treatments, all price
conflicts and every continuity limitation. Independent exact rational arithmetic
verifies all 376 hourly results; every aggregate flag is separately checked
against the pinned reference. See `research/v9/a5_quote_precision.json`.

Price-times-quantity volumes explain 29 of the original 44 aggregate mismatches.
All 50 previous matches remain; 79 blocks now match all six aggregate fields,
and 66 also pass local continuity. Fifteen blocks still disagree, including five
with price conflicts. The 24 continuity limitations are unchanged and overlap
these categories. Within the requested blocks, 2,530,674 trade records have a
published quote amount different from price times quantity. This is an observed
precision difference, not proof that every remaining discrepancy is rounding.

Remaining aggregate-disagreement cases: ALPHA (2023-07-31), API3 (2023-04-14),
BTC (2023-11-10), CRV (2023-08-16), EOS (2020-01-19), ETC and FIL (2021-05-06),
HBAR (2023-08-31), ID (2023-04-14), RUNE (2023-09-21), SXP (2021-02-22),
TRUMP (2025-01-29), UNFI (2023-08-16), XRP (2020-01-16 and 2020-01-17).

No source observations, rankings or first-pass reports were replaced. The next
work is resolving these disagreements and the ID/boundary limitations, then
registering a defensible repair/exclusion and missing-hour execution policy.
A5.2 acceptance, A5.3 and A4.4 remain open. Regression validation: 1,015 tests
pass; both source-commit GitHub CI runs pass.
