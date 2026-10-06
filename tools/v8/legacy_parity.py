"""Legacy behaviour parity harness (v8 Phase 1).

Runs the production pipeline - scanner, smart money (two runs), quant desk, coin picks, dashboard - offline on a
deterministic fake market that also serves all eight DEX market lists with the edge cases the legacy universe
filters out (builder markets, delisted and inactive contracts, tradfi ticker collisions, duplicates, price
conflicts, missing and zero volume, low-liquidity and newly listed coins, coins without candles). Time is frozen
and every outbound HTTP call is answered by the fake or refused, so two runs of the same code give byte-identical
legacy files.

The harness does not import anything from the v8 package: it must run unchanged on the untouched main branch to
produce the golden digests (tests/fixtures/v8/legacy_parity_golden.json) and on the Phase 1 branch to prove that
the observability hooks changed no legacy output. Files written under data/v8/ are new audit outputs and are
listed separately, never digested as legacy files.

    python tools/v8/legacy_parity.py --out /tmp/parity              # run and print the digest summary
    python tools/v8/legacy_parity.py --out /tmp/parity --check tests/fixtures/v8/legacy_parity_golden.json
    python tools/v8/legacy_parity.py --out /tmp/parity --write-golden tests/fixtures/v8/legacy_parity_golden.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

T_NOW = 1_791_014_400 + 7 * 60 + 13      # a fixed scan time (2026-10-03 07:07:13 UTC)
SMART_T1 = T_NOW - 3600                  # the first smart-money run, one hour earlier
STAGES = ("scanner", "smart1", "smart2", "quant", "picks", "dashboard")
AUDIT_PREFIX = "data/v8/"                # new audit files: listed, never part of the legacy digest
VOLATILE_KEYS = {"duration_s"}           # wall-clock durations (0 under frozen time, dropped anyway)


# --------------------------------------------------------------------------- the fake market
def _make_exchange():
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import scanner as sc
    from fake_exchange import FakeExchange, BAR

    class ParityExchange(FakeExchange):
        """FakeExchange plus every DEX market list, the Hyperliquid leaderboard and account states, and coins
        made to hit each legacy filter."""

        def __init__(self, now=T_NOW, seed=int(os.environ.get("V8_PARITY_SEED", "17"))):
            super().__init__(n_coins=30, days=130, seed=seed, now=now)
            rng = random.Random(seed * 7 + 1)
            base = self.c15["ETH"]

            def clone(coin, px, qv_k=1.0, days=None, vol=0.006):
                out, p = [], px
                for x in base:
                    r = rng.gauss(0, vol)
                    o, c = p, p * math.exp(r)
                    out.append({"t": x["t"], "o": o, "h": max(o, c) * (1 + abs(rng.gauss(0, vol / 2))),
                                "l": min(o, c) * (1 - abs(rng.gauss(0, vol / 2))), "c": c,
                                "qv": rng.uniform(2e5, 4e6) * qv_k})
                    p = c
                if days is not None:
                    out = out[-(days * 96 + 1):]
                self.c15[coin] = out

            # coins with candles that exercise a filter each
            clone("TINY", 0.8)                      # DEX volume $300k: below the $1M executability floor
            clone("NEW40", 2.0, days=40)            # 40 days listed: passes 30 days, not 90
            clone("NEW10", 3.0, days=10)            # 10 days listed: passes neither history gate
            clone("THINREF", 1.5, qv_k=0.0002)      # tiny reference (CEX) volume
            clone("LONLY", 4.0)                     # only on Lighter, which sends no volume for it
            clone("ZEROV", 5.0)                     # Hyperliquid reports exactly zero volume
            clone("SCALEX", 1.0)                    # the DEX price is 3x the exchange candles: other asset
            clone("BB", 0.12)                       # crypto (BounceBit) on Hyperliquid, a stock on Aster
            clone("PURR", 0.2)                      # crypto on Hyperliquid, an equity listing on Extended
            clone("QNT", 90.0)                      # crypto on Variational, a 24/5 market on Extended
            self.extra = ["TINY", "NEW40", "NEW10", "THINREF", "LONLY", "ZEROV", "SCALEX", "BB", "PURR", "QNT"]
            self.vol24.update({"TINY": 3e5, "NEW40": 6e6, "NEW10": 6e6, "THINREF": 3e6, "ZEROV": 0.0,
                               "SCALEX": 4e6, "BB": 5e6, "PURR": 7e6, "QNT": 4e6, "NOCAND": 3e6, "LONLY": None})
            self.smart_round = 1

        # ---- helpers
        def px(self, coin):
            return self.c15[coin][-1]["c"] if coin in self.c15 else 1.0

        def hl_markets(self):
            """(name, ctx) rows of metaAndAssetCtxs."""
            rows = []
            for c in self.coins + ["TINY", "NEW40", "NEW10", "THINREF", "ZEROV", "SCALEX", "BB", "PURR", "NOCAND"]:
                px = self.px(c) * (3.0 if c == "SCALEX" else 1.0)
                vol = self.vol24[c] * (1.2 if c in self.coins else 1.0)
                rows.append(({"name": c}, {"markPx": str(px), "dayNtlVlm": str(vol), "openInterest": "1000",
                                           "funding": "0.0000125"}))
            rows.append(({"name": "kFAKE05"}, {"markPx": str(self.px("FAKE05") * 1000), "dayNtlVlm": "250000",
                                               "openInterest": "10", "funding": "0.00002"}))
            rows.append(({"name": "xyz:TSLA"}, {"markPx": "250.0", "dayNtlVlm": "9000000", "openInterest": "5",
                                                "funding": "0.00001"}))
            rows.append(({"name": "OLDCOIN", "isDelisted": True}, {"markPx": "0.5", "dayNtlVlm": "1000",
                                                                   "openInterest": "0", "funding": "0"}))
            return rows

        def hl_names(self):
            return [a["name"] for a, _ in self.hl_markets()]

        # ---- DEX market lists
        def dex(self, url):
            if url == sc.VAR_STATS:
                L = [{"ticker": c, "name": c, "mark_price": self.px(c), "volume_24h": self.vol24[c], "funding_rate": 0.05,
                      "open_interest": {"long_open_interest": 1e6, "short_open_interest": 9e5}, "base_spread_bps": 5}
                     for c in self.coins]
                L += [{"ticker": "QNT", "name": "Quant", "mark_price": self.px("QNT"), "volume_24h": 4e6,
                       "funding_rate": 0.02, "open_interest": {}, "base_spread_bps": 8},
                      {"ticker": "1000FAKE06", "name": "1000FAKE06", "mark_price": self.px("FAKE06") * 1000,
                       "volume_24h": 1e5, "funding_rate": 0.01, "open_interest": {}, "base_spread_bps": 9},
                      {"ticker": "VANATOKEN", "name": "Vana", "mark_price": 6.0, "volume_24h": 2e6,
                       "funding_rate": 0.01, "open_interest": {}, "base_spread_bps": 9},
                      {"ticker": "AAPL", "name": "Apple", "mark_price": 230.0, "volume_24h": 8e6,
                       "funding_rate": 0.0, "open_interest": {}, "base_spread_bps": 3},
                      {"ticker": "ACME", "name": "Acme Holdings Inc", "mark_price": 12.0, "volume_24h": 2e6,
                       "funding_rate": 0.0, "open_interest": {}, "base_spread_bps": 3},
                      {"ticker": "", "name": "blank", "mark_price": 1.0, "volume_24h": 1.0}]
                return {"listings": L}
            if url == sc.ASTER_INFO:
                return {"symbols": [
                    {"symbol": "FAKE01USDT", "baseAsset": "FAKE01", "contractType": "PERPETUAL", "status": "TRADING",
                     "underlyingType": "COIN"},
                    {"symbol": "BTCUSDT", "baseAsset": "BTC", "contractType": "PERPETUAL", "status": "TRADING",
                     "underlyingType": "COIN"},
                    {"symbol": "BBUSDT", "baseAsset": "BB", "contractType": "PERPETUAL", "status": "TRADING",
                     "underlyingType": "STOCK"},
                    {"symbol": "FAKE02USDT_260925", "baseAsset": "FAKE02", "contractType": "CURRENT_QUARTER",
                     "status": "TRADING", "underlyingType": "COIN"},
                    {"symbol": "FAKE03USDT", "baseAsset": "FAKE03", "contractType": "PERPETUAL", "status": "SETTLING",
                     "underlyingType": "COIN"}]}
            if url == sc.ASTER_TICKER:
                return [{"symbol": "FAKE01USDT", "lastPrice": str(self.px("FAKE01")), "quoteVolume": "2500000"},
                        {"symbol": "BTCUSDT", "lastPrice": str(self.px("BTC")), "quoteVolume": "90000000"},
                        {"symbol": "BBUSDT", "lastPrice": "4.1", "quoteVolume": "800000"}]
            if url == sc.ASTER_PREMIUM:
                return [{"symbol": "FAKE01USDT", "markPrice": str(self.px("FAKE01")), "lastFundingRate": "0.0001"},
                        {"symbol": "BTCUSDT", "markPrice": str(self.px("BTC")), "lastFundingRate": "0.00008"}]
            if url == sc.EDGEX_META:
                return {"data": {"contractList": [
                    {"contractName": "FAKE02USD", "enableTrade": True, "enableDisplay": True},
                    {"contractName": "BTCUSD", "enableTrade": True, "enableDisplay": True},
                    {"contractName": "FAKE04USD", "enableTrade": False, "enableDisplay": True},
                    {"contractName": "USD", "enableTrade": True, "enableDisplay": True}]}}
            if url == sc.LIGHTER_BOOKS:
                return {"order_book_details": [
                    {"symbol": "FAKE03", "market_type": "perp", "status": "active", "mark_price": self.px("FAKE03"),
                     "daily_quote_token_volume": 2.5e6},
                    {"symbol": "LONLY", "market_type": "perp", "status": "active", "mark_price": self.px("LONLY")},
                    {"symbol": "FAKE04", "market_type": "perp", "status": "inactive", "mark_price": self.px("FAKE04"),
                     "daily_quote_token_volume": 1e6},
                    {"symbol": "FAKE05", "market_type": "spot", "status": "active", "mark_price": self.px("FAKE05"),
                     "daily_quote_token_volume": 1e6}]}
            if url == sc.DYDX_MARKETS:
                return {"markets": {
                    "FAKE07-USD": {"status": "ACTIVE", "oraclePrice": str(self.px("FAKE07") * 1.3),
                                   "volume24H": "200000", "openInterest": "100", "nextFundingRate": "0.00001"},
                    "FAKE08-USD": {"status": "FINAL_SETTLEMENT", "oraclePrice": str(self.px("FAKE08")),
                                   "volume24H": "0", "openInterest": "0", "nextFundingRate": "0"},
                    "FAKE09-USD": {"status": "ACTIVE", "oraclePrice": str(self.px("FAKE09")),
                                   "volume24H": "700000", "openInterest": "50", "nextFundingRate": "0.00002"}}}
            if url == sc.PARADEX_SUMMARY:
                return {"results": [
                    {"symbol": "FAKE09-USD-PERP", "mark_price": str(self.px("FAKE09")), "volume_24h": "650000",
                     "open_interest": "40", "funding_rate": "0.00003"},
                    {"symbol": "BTC-USD-PERP", "mark_price": str(self.px("BTC")), "volume_24h": "30000000",
                     "open_interest": "40", "funding_rate": "0.00001"},
                    {"symbol": "FAKE09-USD-30OCT26-1-C", "mark_price": "0.1", "volume_24h": "1000"}]}
            if url == sc.EXTENDED_MARKETS:
                return {"data": [
                    {"name": "FAKE10-USD", "assetName": "FAKE10", "active": True, "status": "ACTIVE",
                     "type": "PERPETUAL", "category": "Crypto", "description": "Fake ten",
                     "marketStats": {"markPrice": str(self.px("FAKE10")), "dailyVolume": "900000",
                                     "openInterest": "50000", "fundingRate": "0.00001"}},
                    {"name": "PURR-USD", "assetName": "PURR", "active": True, "status": "ACTIVE", "type": "PERPETUAL",
                     "category": "Equity", "description": "Purr Equity",
                     "marketStats": {"markPrice": str(self.px("PURR")), "dailyVolume": "100000"}},
                    {"name": "QNT_24_5-USD", "assetName": "QNT", "active": True, "status": "ACTIVE",
                     "type": "PERPETUAL", "category": "Crypto", "description": "Quant 24/5",
                     "marketStats": {"markPrice": str(self.px("QNT")), "dailyVolume": "50000"}},
                    {"name": "FAKE11-USD", "assetName": "FAKE11", "active": False, "status": "ACTIVE",
                     "type": "PERPETUAL", "category": "Crypto", "marketStats": {}},
                    {"name": "EURUSD-USD", "assetName": "EURUSD", "active": True, "status": "ACTIVE",
                     "type": "PERPETUAL", "category": "Forex", "description": "Euro",
                     "marketStats": {"markPrice": "1.08", "dailyVolume": "3000000"}}]}
            return None

        # ---- Hyperliquid accounts (scanner smart money and smart.py)
        def addr(self, i):
            return "0x%040x" % (i + 1)

        def board(self):
            def row(i, av, all_pnl, month_pnl, vlm=5e6):
                return {"ethAddress": self.addr(i), "accountValue": str(av), "windowPerformances": [
                    ["day", {"pnl": "0", "roi": "0", "vlm": "0"}], ["week", {"pnl": "1000", "roi": "0", "vlm": "1"}],
                    ["month", {"pnl": str(month_pnl), "roi": str(month_pnl / av), "vlm": str(vlm)}],
                    ["allTime", {"pnl": str(all_pnl), "roi": "1", "vlm": str(vlm * 5)}]]}
            rows = [row(i, 400_000, 2_000_000 - i * 50_000, 30_000) for i in range(8)]
            rows.append(row(8, 400_000, 900_000, 20_000, vlm=1e9))     # a market maker
            rows.append(row(9, 10_000, 900_000, 2_000))                 # account too small
            return {"leaderboardRows": rows}

        def positions(self, i):
            """(hl name, size, entry) per trader; round 2 adds new shorts on FAKE02 and longs on FAKE03."""
            p = [("BTC", 0.5 + i * 0.1, self.px("BTC")), ("ETH", -10.0 - i, self.px("ETH")),
                 ("xyz:TSLA", 10.0, 250.0), ("@107", 100.0, 1.0)]
            if i < 3:
                p.append(("kFAKE05", 50.0 + i, self.px("FAKE05") * 1000))
            if i == 7:
                p.append(("FAKE12", 1000.0 / self.px("FAKE12"), self.px("FAKE12")))   # $1k: below the minimum
            if self.smart_round >= 2:
                if i < 4:
                    p.append(("FAKE02", -60_000.0 / self.px("FAKE02"), self.px("FAKE02")))
                if 4 <= i < 7:
                    p.append(("FAKE03", 60_000.0 / self.px("FAKE03"), self.px("FAKE03")))
            return p

        def hl_info(self, body):
            t = (body or {}).get("type")
            if t == "metaAndAssetCtxs":
                rows = self.hl_markets()
                return [{"universe": [a for a, _ in rows]}, [x for _, x in rows]]
            if t == "clearinghouseState":
                i = int(body["user"], 16) - 1
                ps = [{"position": {"coin": n, "szi": str(sz), "positionValue": str(abs(sz) * px),
                                    "entryPx": str(px), "unrealizedPnl": "100", "leverage": {"value": 3}}}
                      for n, sz, px in self.positions(i)]
                return {"marginSummary": {"accountValue": "400000"}, "assetPositions": ps}
            if t == "allMids":
                return {n: str(self.px(n[1:]) * 1000 if n.startswith("k") else self.px(n))
                        for n in self.hl_names() if ":" not in n}
            if t == "candleSnapshot":
                req = body["req"]
                name, k = req["coin"], 1.0
                if name.startswith("k") and name[1:] in self.c15:
                    name, k = name[1:], 1000.0
                if name not in self.c15:
                    return []
                tf = req.get("interval", "1h")
                if tf not in ("1h", "4h", "15m"):
                    return []
                rows = self._candles(name, tf, req["startTime"] // 1000, req["endTime"] // 1000) \
                    if tf != "15m" else [x for x in self.c15[name]
                                         if req["startTime"] // 1000 <= x["t"] <= req["endTime"] // 1000]
                return [{"t": x["t"] * 1000, "o": str(x["o"] * k), "h": str(x["h"] * k), "l": str(x["l"] * k),
                         "c": str(x["c"] * k), "v": str(x["qv"] / x["c"])} for x in rows]
            return None

        def fetch(self, url, body=None, timeout=25):
            if url == sc.HL_INFO:
                d = self.hl_info(body)
                if d is not None:
                    self.calls += 1
                    return d
                raise sc.HttpError(404, "not in the fake exchange")
            if url == sc.HL_LEADERBOARD:
                self.calls += 1
                return self.board()
            d = self.dex(url)
            if d is not None:
                self.calls += 1
                return d
            return super().fetch(url, body, timeout)

    return ParityExchange, sc, BAR


# --------------------------------------------------------------------------- one stage in its own process
def run_stage(stage, out, now):
    """Run one engine like the Scan workflow does (its own process), offline, at a frozen time."""
    import urllib.error
    import urllib.request

    def offline(*a, **k):
        raise urllib.error.URLError("offline parity run")

    urllib.request.urlopen = offline
    time.time = lambda: float(now)
    ParityExchange, sc, _ = _make_exchange()
    fx = ParityExchange()
    if stage == "smart2":
        fx.smart_round = 2
    sc.FETCH = fx.fetch
    sc.CFG["workers"] = 1          # one worker: the order threads finish in cannot change sums or notes
    if stage == "scanner":
        sc.run(out, replay_days=2)
    elif stage in ("smart1", "smart2"):
        import smart as SM
        jp = os.path.join(out, "data", "smart_journal.json") if stage == "smart2" else os.path.join(out, "none.json")
        if stage == "smart2":
            shutil.copyfile(jp, os.path.join(out, "smart_journal_1.json"))
            jp = os.path.join(out, "smart_journal_1.json")
        SM.run(out, journal_path=jp, now=now)
    elif stage == "quant":
        import quant as Q
        Q.run(out, journal_path=os.path.join(out, "none.json"))
    elif stage == "picks":
        import picks as P
        P.CFG["gap_stocktwits"] = P.CFG["gap_coingecko"] = 0.0   # request pacing only
        P.GEMINI_KEY = ""
        P.run(out, journal_path=os.path.join(out, "none.json"))
    elif stage == "dashboard":
        import dashboard as D
        D.main(["--out", out])
    else:
        raise SystemExit(f"unknown stage {stage}")


def clean_env():
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR",
                                                        "TEMP", "TMP", "PYTHONPATH", "PYTHONIOENCODING",
                                                        "V8_PARITY_SEED")}
    env.update(PYTHONHASHSEED="0", TZ="UTC", PYTHONDONTWRITEBYTECODE="1", V8_PARITY="1")
    return env


def run_pipeline(out, log=None):
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    for stage in STAGES:
        now = SMART_T1 if stage == "smart1" else T_NOW
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--stage", stage, "--out", out,
                            "--now", str(now)], cwd=ROOT, env=clean_env(), capture_output=True, text=True,
                           timeout=900)
        if log is not None:
            log.write(f"==== {stage} (exit {r.returncode})\n{r.stdout}\n{r.stderr}\n")
        if r.returncode != 0:
            raise SystemExit(f"parity stage {stage} failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    # the journal copy smart2 reads is a working file of the harness, not an engine output
    os.remove(os.path.join(out, "smart_journal_1.json"))


# --------------------------------------------------------------------------- digests
def _strip(x):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in VOLATILE_KEYS:
                continue
            if k == "errors" and isinstance(v, list):
                out[k] = sorted((_strip(e) for e in v), key=lambda e: json.dumps(e, sort_keys=True))
            else:
                out[k] = _strip(v)
        return out
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def normalized_bytes(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        try:
            obj = json.loads(raw.decode("utf-8"))
        except ValueError:
            return raw
        return json.dumps(_strip(obj), sort_keys=True, separators=(",", ":")).encode()
    return raw


def digest_tree(out):
    legacy, audit = {}, []
    for dp, _, files in os.walk(out):
        for f in files:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, out).replace(os.sep, "/")
            if rel.startswith(AUDIT_PREFIX):
                audit.append(rel)
                continue
            legacy[rel] = hashlib.sha256(normalized_bytes(p)).hexdigest()
    return dict(sorted(legacy.items())), sorted(audit)


def decisions(out):
    """A readable summary of what each engine decided: the parity evidence in words."""
    def load(name):
        try:
            with open(os.path.join(out, "data", name)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None
    d = {}
    L = load("latest.json") or {}
    cov = L.get("coverage") or {}
    d["radar"] = {"picks": [[p["coin"], p["sid"], p["conv"]["score"]] for p in L.get("picks") or []],
                  "watch": [[p["coin"], p["sid"]] for p in L.get("watch") or []],
                  "coins": cov.get("coins"), "crypto": cov.get("crypto"), "scanned": cov.get("scanned"),
                  "deep": cov.get("deep"), "signals": cov.get("signals"), "tradfi": cov.get("tradfi"),
                  "nodata": cov.get("nodata"),
                  "dexes": {k: [v.get("ok"), v.get("markets"), v.get("crypto")] for k, v in (cov.get("dexes") or {}).items()}}
    Q = load("quant.json") or {}
    d["quant"] = {"coins": Q.get("coins"), "open": sorted([t.get("c"), t.get("s"), t.get("d")] for t in Q.get("open") or []),
                  "signals": len(Q.get("signals") or [])}
    P = load("picks.json") or {}
    d["picks"] = {f"{k}_{side}": [[r.get("coin"), r.get("side"), r.get("score")] for r in (P.get(k) or {}).get(side) or []
                                  if isinstance(r, dict)]
                  for k in ("swing", "daytrade") for side in ("all", "long", "short")}
    S = load("smart.json") or {}
    d["smart"] = {"traders": S.get("traders_n"), "read": S.get("read"), "positions": S.get("positions"),
                  "signals": [c["coin"] for c in S.get("coins") or [] if c.get("signal")],
                  "info": [c["coin"] for c in S.get("coins") or [] if c.get("info")],
                  "open": sorted(t.get("coin") for t in S.get("open") or [])}
    return d


def summary(out):
    legacy, audit = digest_tree(out)
    combined = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    return {"schema": "v8.parity/1", "t_now": T_NOW, "stages": list(STAGES), "combined": combined,
            "files": legacy, "audit_files": audit, "decisions": decisions(out)}


def compare(golden, got):
    """Differences between a golden summary and this run (legacy files and decisions only)."""
    diffs = []
    g, h = golden["files"], got["files"]
    for k in sorted(set(g) | set(h)):
        if g.get(k) != h.get(k):
            diffs.append(f"{k}: {g.get(k, 'missing')[:12]} -> {h.get(k, 'missing')[:12]}")
    if golden.get("decisions") != got.get("decisions"):
        diffs.append("decisions differ")
    return diffs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--now", type=int, default=T_NOW, help=argparse.SUPPRESS)
    ap.add_argument("--check", default=None, help="golden summary to compare with")
    ap.add_argument("--write-golden", default=None, help="write this run's summary as the golden file")
    ap.add_argument("--log", default=None, help="write every stage's output here")
    a = ap.parse_args(argv)
    if a.stage:
        run_stage(a.stage, a.out, a.now)
        return 0
    log = open(a.log, "w") if a.log else None
    try:
        run_pipeline(a.out, log)
    finally:
        if log:
            log.close()
    s = summary(a.out)
    if a.write_golden:
        os.makedirs(os.path.dirname(os.path.abspath(a.write_golden)), exist_ok=True)
        with open(a.write_golden, "w") as fh:
            json.dump(s, fh, indent=1, sort_keys=True)
            fh.write("\n")
    print(json.dumps({"combined": s["combined"], "legacy_files": len(s["files"]), "audit_files": s["audit_files"]},
                     indent=1))
    if a.check:
        with open(a.check) as fh:
            golden = json.load(fh)
        diffs = compare(golden, s)
        if diffs:
            print("PARITY FAILED:\n  " + "\n  ".join(diffs))
            return 1
        print(f"PARITY OK: {len(s['files'])} legacy files identical to the golden run ({golden['combined'][:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
