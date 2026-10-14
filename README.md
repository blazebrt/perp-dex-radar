# v9 market history (append-only)

One gzipped JSON record per UTC hour (`market/YYYY/MM/DD/HH.json.gz`, schema v9.market-history/1), written by the Scan workflow from `python -m v9.market`. Files are only added, never changed. Context only: no engine reads this branch; phase D research may.
