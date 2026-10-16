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

The pinned four-hour export agrees with the current exchange four-hour row
after its ten-significant-digit rounding. This is a provider inconsistency,
not an export rounding error. The matching finer resolutions are corroboration,
not authority to silently replace the pinned source or its historical rankings.

SHA-256 of the files inspected:

- Pinned `h4/1000SHIB.csv.gz`:
  `e7310eb736424566feaa7005c2a6d5ac70e7dbea5df8c3a0243638c2d5cc48c0`.
- Monthly `1000SHIBUSDT-1h-2022-07.zip`:
  `03f07fe9d1e0858cb7156dcdf9db43de06e99a98f0e0a7cdd31efb1775b89111`.
- Monthly `1000SHIBUSDT-4h-2022-07.zip`:
  `85ebc2bf34df02d59bce39479e0b477bc32a3fafbb242e179e62c62f9954d432`.
- Monthly `1000SHIBUSDT-1m-2022-07.zip`:
  `b3699d788c61ded5afb0a97a780ad9ee812efc3481a62de954b9795f89738c61`.

## Next diagnostic run

Catalogue every numerical source conflict across the requested data instead of
stopping at the first. Save each segment, timestamp, field and both values, with
source-object and output hashes, in `rejected_manifest.json`. The job still fails
and does not create `hourly_manifest.json` if any conflict remains. Missing source
months, malformed data and failed downloads still abort. No tolerance is relaxed,
no conflicting field is overwritten and no rejected dataset may enter a replay.

After the audit, quantify affected dates and selection windows before specifying
any new dataset or exclusion protocol. The existing A4 replay reproduced its
pinned inputs; it did not independently establish that every provider candle is
correct. A5.2 and subsequent strategy replay remain incomplete.
