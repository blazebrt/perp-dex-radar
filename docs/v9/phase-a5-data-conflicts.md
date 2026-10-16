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
