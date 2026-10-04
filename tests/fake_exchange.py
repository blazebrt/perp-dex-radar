"""A fake exchange for offline tests: answers scanner.py's requests (DEX market lists, MEXC
candles) from a random-walk market, so the whole scan can run without a network.

    from tests.fake_exchange import FakeExchange
    fx = FakeExchange(n_coins=60, days=16)
    scanner.FETCH = fx.fetch
"""
from __future__ import annotations

import math
import random
import time
import urllib.parse

import scanner as sc

BAR = 900


class FakeExchange:
    def __init__(self, n_coins=60, days=16, seed=7, now=None):
        rng = random.Random(seed)
        self.now = int(now or time.time())
        last_start = (self.now // BAR) * BAR  # the candle still forming at `now`
        n = days * 96 + 1
        t0 = last_start - (n - 1) * BAR
        self.coins = ["BTC", "ETH"] + [f"FAKE{i:02d}" for i in range(n_coins - 2)]
        self.c15 = {}
        mkt = [rng.gauss(0, 0.0025) for _ in range(n)]
        for k, coin in enumerate(self.coins):
            vol = 0.0024 if k == 0 else rng.uniform(0.004, 0.008)
            beta = 1.0 if k == 0 else rng.uniform(0.8, 1.4)
            p = 60000.0 if k == 0 else math.exp(rng.uniform(math.log(0.1), math.log(50)))
            base_qv = rng.uniform(2e5, 5e6)
            out = []
            for i in range(n):
                r = beta * mkt[i] + math.sqrt(max(vol ** 2 - (beta * 0.0025) ** 2, (0.4 * vol) ** 2)) * rng.gauss(0, 1)
                o = p
                c = p * math.exp(r - 0.5 * r * r)
                h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
                low = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
                qv = base_qv * math.exp(rng.gauss(0, 0.5)) * (1 + 30 * abs(r))
                out.append({"t": t0 + i * BAR, "o": o, "h": h, "l": low, "c": c, "qv": qv})
                p = c
            self.c15[coin] = out
        self.vol24 = {c: rng.uniform(1.5e6, 4e7) for c in self.coins}
        self.calls = 0
        self._agg = {}

    # ---- responses
    def _candles(self, coin, tf, start, end):
        c = self.c15[coin]
        if tf in ("1h", "4h"):
            key = (coin, tf)
            if key not in self._agg:
                self._agg[key] = sc.agg_tf(c, 3600 if tf == "1h" else 14400)
            c = self._agg[key]
        return [x for x in c if start <= x["t"] <= end]

    def fetch(self, url, body=None, timeout=25):
        self.calls += 1
        if url.startswith(sc.MEXC_KLINE.split("{")[0]):
            sym = url.split("/kline/")[1].split("?")[0]
            q = urllib.parse.parse_qs(url.split("?", 1)[1])
            coin = sym.replace("_USDT", "")
            if coin not in self.c15:
                raise sc.HttpError(400, "unknown symbol")
            tf = {"Min15": "15m", "Min60": "1h", "Hour4": "4h"}[q["interval"][0]]
            rows = self._candles(coin, tf, int(q["start"][0]), int(q["end"][0]))[-2000:]
            return {"success": True, "data": {"time": [x["t"] for x in rows], "open": [x["o"] for x in rows],
                                              "high": [x["h"] for x in rows], "low": [x["l"] for x in rows],
                                              "close": [x["c"] for x in rows], "amount": [x["qv"] for x in rows]}}
        if url.startswith("https://contract.mexc.com/api/v1/contract/funding_rate/history"):
            q = urllib.parse.parse_qs(url.split("?", 1)[1])
            coin = q["symbol"][0].replace("_USDT", "")
            if coin not in self.c15:
                raise sc.HttpError(400, "unknown symbol")
            page, size = int(q["page_num"][0]), int(q["page_size"][0])
            first = self.c15[coin][0]["t"]
            ts = list(range((self.now // 28800) * 28800, first, -28800))
            chunk = ts[(page - 1) * size: page * size]
            return {"success": True, "data": {"totalPage": (len(ts) + size - 1) // size, "resultList": [
                {"symbol": q["symbol"][0], "fundingRate": 0.0001, "settleTime": t * 1000} for t in chunk]}}
        if url == sc.VAR_STATS:
            return {"listings": [{"ticker": c, "name": c, "mark_price": self.c15[c][-1]["c"],
                                  "volume_24h": self.vol24[c], "funding_rate": 0.05,
                                  "open_interest": {"long_open_interest": 1e6, "short_open_interest": 9e5},
                                  "base_spread_bps": 5} for c in self.coins]}
        if url == sc.HL_INFO and (body or {}).get("type") == "metaAndAssetCtxs":
            return [{"universe": [{"name": c} for c in self.coins]},
                    [{"markPx": str(self.c15[c][-1]["c"]), "dayNtlVlm": str(self.vol24[c] * 1.2),
                      "openInterest": "1000", "funding": "0.0000125"} for c in self.coins]]
        if url == sc.HL_INFO and (body or {}).get("type") == "clearinghouseState":
            return {"assetPositions": []}
        raise sc.HttpError(404, "not in the fake exchange")
