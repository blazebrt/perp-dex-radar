"""Synthetic archive in the md_bn layout (12 coins, two delisted) for local smoke tests of tools/v9/evidence.py.

    python tools/v9/make_fake_archive.py /tmp/fake_md
"""
import csv, gzip, json, math, os, random, sys
out = sys.argv[1]
random.seed(3)
os.makedirs(os.path.join(out, "h4"), exist_ok=True); os.makedirs(os.path.join(out, "fund_bn"), exist_ok=True)
T0 = 1577836800  # 2020-01-01
coins = []
names = ["BTC", "ETH", "SOL", "AAA", "BBB", "CCC", "DDD", "EEE", "DEAD1", "DEAD2", "NEWX", "LUNA"]
for k, n in enumerate(names):
    start = T0 + (0 if k < 8 else (200 if n == "NEWX" else 0)) * 86400
    days = 1400 if not n.startswith("DEAD") else 500 + 200 * k % 300
    if n == "NEWX": days = 900
    px, drift = 100.0, (0.0004 if k % 2 else -0.0002)
    rows, fund = [], []
    for b in range(days * 6):
        t = start + b * 14400
        r = random.gauss(drift, 0.02)
        o = px; px = max(0.01, px * math.exp(r)); h = max(o, px) * (1 + abs(random.gauss(0, 0.005))); l = min(o, px) * (1 - abs(random.gauss(0, 0.005)))
        qv = abs(random.gauss(4e6, 1e6)) * (3 if n in ("BTC", "ETH") else 1)
        rows.append([t, f"{o:.6f}", f"{h:.6f}", f"{l:.6f}", f"{px:.6f}", f"{qv:.2f}", f"{qv/2:.2f}"])
        if t % 28800 == 0:
            fund.append([t, f"{random.gauss(0.0001, 0.0002):.8f}", 8])
    with gzip.open(os.path.join(out, "h4", f"{n}.csv.gz"), "wt") as fh:
        w = csv.writer(fh); w.writerow(["t", "o", "h", "l", "c", "qv", "tbqv"]); w.writerows(rows)
    with gzip.open(os.path.join(out, "fund_bn", f"{n}.csv.gz"), "wt") as fh:
        w = csv.writer(fh); w.writerow(["t", "rate", "interval_h"]); w.writerows(fund)
    coins.append({"t": n, "symbol": n + "USDT", "first_bar": rows[0][0], "last_bar": rows[-1][0], "delisted": n.startswith("DEAD"), "excluded": None, "trade_vol": 5e6})
json.dump({"schema": "v9.binance-archive/1", "source": "fake", "archive_end_month": "2023-10", "coins": coins,
           "counts": {"research_coins": len(coins), "delisted_research_coins": 2}}, open(os.path.join(out, "universe.json"), "w"))
print("ok", len(coins))
