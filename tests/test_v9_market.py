"""v9 market context (v9/market.py): parsers on the sources' real payload shapes, failure isolation, missing never
zero, the regime summary, the hourly append-only history and the context-only boundary.

Run from the repository root:  python -m unittest tests.test_v9_market -v"""
from __future__ import annotations

import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from v9 import market as M  # noqa: E402

NOW = 1791984800                      # 2026-10-14 13:33:20 UTC
H = 3600


# --------------------------------------------------------------------------- fixtures (the shapes the probe recorded)
def hl_ctx():
    meta = {"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}, {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
                         {"name": "MATIC", "szDecimals": 1, "maxLeverage": 20, "isDelisted": True},
                         {"name": "kPEPE", "szDecimals": 0, "maxLeverage": 10}, {"name": "TINY", "szDecimals": 0, "maxLeverage": 3},
                         {"name": "SOL", "szDecimals": 2, "maxLeverage": 20}]}
    ctxs = [{"funding": "0.0000125", "openInterest": "30000.5", "prevDayPx": "80000", "dayNtlVlm": "2500000000",
             "premium": "0.0001", "oraclePx": "83300", "markPx": "83350"},
            {"funding": "-0.00002", "openInterest": "500000", "prevDayPx": "2600", "dayNtlVlm": "900000000",
             "premium": "-0.0002", "oraclePx": "2550", "markPx": "2548"},
            {"funding": "0.01", "openInterest": "1", "prevDayPx": "1", "dayNtlVlm": "1", "premium": None, "oraclePx": "1", "markPx": "1"},
            {"funding": "0.0001", "openInterest": "1000000000", "prevDayPx": "0.010", "dayNtlVlm": "40000000",
             "premium": None, "oraclePx": "0.011", "markPx": "0.011"},
            {"funding": "0.0005", "openInterest": "100", "prevDayPx": "2", "dayNtlVlm": "50000", "premium": "0.001",
             "oraclePx": "1.9", "markPx": "1.9"},
            {"funding": None, "openInterest": "200000", "prevDayPx": "150", "dayNtlVlm": "300000000", "premium": "0",
             "oraclePx": "151", "markPx": "151.5"}]
    return [meta, ctxs]


def hl_predicted():
    return [["BTC", [["BinPerp", {"fundingRate": "0.0001", "nextFundingTime": 1, "fundingIntervalHours": 8}],
                     ["HlPerp", {"fundingRate": "0.0000125", "nextFundingTime": 1, "fundingIntervalHours": 1}],
                     ["BybitPerp", {"fundingRate": "0.00005", "nextFundingTime": 1, "fundingIntervalHours": 4}]]],
            ["ETH", [["BinPerp", None], ["HlPerp", {"fundingRate": "-0.00002", "fundingIntervalHours": 1}]]],
            ["junk"]]


def gate_rows(base_oi=4.0e9, n=25, liq=(1000.0, 2000.0)):
    rows = []
    for k in range(n):
        rows.append({"time": NOW - (n - 1 - k) * H, "lsr_taker": 1.1, "lsr_account": 1.2 + k / 100, "top_lsr_account": 0.6,
                     "open_interest_usd": base_oi * (1 + k / 100), "long_liq_usd": liq[0], "short_liq_usd": liq[1],
                     "long_taker_size": 3.0, "short_taker_size": 2.0, "mark_price": 83000})
    return rows


def dvol(level=40.0):
    start = (NOW - 8 * 86400) // H * H
    return {"jsonrpc": "2.0", "result": {"data": [[(start + k * H) * 1000, level, level, level, level + k / 100]
                                                  for k in range(8 * 24 + 1)]}}


FNG = {"name": "Fear and Greed Index", "data": [{"value": str(60 - k), "value_classification": "Greed",
                                                 "timestamp": str(NOW // 86400 * 86400 - k * 86400)} for k in range(8)]}
STABLE = [{"date": str(NOW // 86400 * 86400 - k * 86400), "totalCirculatingUSD": {"peggedUSD": 300e9 - k * 1e9}}
          for k in range(40)][::-1]
CG = {"data": {"total_market_cap": {"usd": 2.79e12}, "market_cap_change_percentage_24h_usd": 1.5,
               "market_cap_percentage": {"btc": 58.2, "eth": 12.1}, "updated_at": NOW - 60}}
FARSIDE = """<html><table class="etf"><tr><th>Date</th><th>IBIT</th><th>Total</th></tr>
<tr><td><span>06 Oct 2026</span></td><td>10.0</td><td>100.5</td></tr>
<tr><td>07 Oct 2026</td><td>(5.0)</td><td>(20.0)</td></tr>
<tr><td>08 Oct 2026</td><td>-</td><td>-</td></tr>
<tr><td>09 Oct 2026</td><td>1,000.0</td><td>1,234.5</td></tr>
<tr><td>10 Oct 2026</td><td>0.0</td><td>0.0</td></tr>
<tr><td>13 Oct 2026</td><td>3.0</td><td>55.0</td></tr>
<tr><td>Total</td><td>9</td><td>99999</td></tr></table></html>"""


def payloads():
    return {
        "metaAndAssetCtxs": hl_ctx(), "predictedFundings": hl_predicted(), "perpsAtOpenInterestCap": ["TINY", "ZZZ"],
        "currency=BTC": dvol(40.0), "currency=ETH": dvol(55.0), "alternative.me": FNG, "stablecoins.llama": STABLE,
        "coinbase.com": [[NOW // 60 * 60, 83000, 83500, 83100, 83400, 12.0], [NOW // 60 * 60 - 60, 83000, 83500, 83100, 83300, 10.0]],
        "binance.vision": [[(NOW // 60 * 60 - 60) * 1000, "83000", "83500", "83100", "83300"], [(NOW // 60 * 60) * 1000, "83000", "83500", "83100", "83350"]],
        "upbit.com": [{"market": "KRW-BTC", "trade_price": 113000000.0}], "er-api.com": {"result": "success", "rates": {"KRW": 1350.0}},
        "tBTCUSD:long": [[(NOW - k * 60) * 1000, 89000 + k] for k in range(1441)],
        "tBTCUSD:short": [[(NOW - k * 60) * 1000, 3000.0] for k in range(1441)],
        "coingecko.com": CG, "farside.co.uk": FARSIDE,
        "BTC_USDT": gate_rows(4.0e9), "ETH_USDT": gate_rows(2.0e9, liq=(5000.0, 100.0)), "PEPE_USDT": gate_rows(1.0e8),
    }


def fake_fetch(table, fail=()):
    calls = []

    def fetch(url, body=None, headers=None, kind="json", timeout=15):
        key = (body or {}).get("type") if body else None
        calls.append((url, key, dict(headers or {})))
        for k, v in table.items():
            if (key == k) or (key is None and k in url):
                if k in fail:
                    raise RuntimeError(f"down: {k}")
                return copy.deepcopy(v)
        raise RuntimeError("HTTP Error 400: unknown " + url)
    fetch.calls = calls
    return fetch


def collect(fail=(), table=None, key="demo"):
    f = fake_fetch(payloads() if table is None else table, fail)
    return M.collect(now=NOW, fetch=f, cg_key=key, top_n=30, workers=4), f


# --------------------------------------------------------------------------- tests
class Parsers(unittest.TestCase):
    def test_hyperliquid_contexts(self):
        a = M.parse_hl_ctx(hl_ctx())
        self.assertNotIn("MATIC", a)                                   # delisted perps are not listed
        self.assertEqual(a["BTC"]["funding_8h"], 0.0001)                # hourly x 8
        self.assertEqual(a["BTC"]["oi_usd"], round(30000.5 * 83350))
        self.assertAlmostEqual(a["BTC"]["chg_24h"], 83350 / 80000 - 1, places=6)
        self.assertIsNone(a["SOL"]["funding_8h"])                       # missing stays missing, never zero
        self.assertIsNone(a["kPEPE"]["premium"])
        self.assertEqual(a["ETH"]["max_leverage"], 25)

    def test_predicted_funding_is_scaled_from_each_interval(self):
        p = M.parse_hl_predicted(hl_predicted())
        self.assertEqual(p["BTC"], {"binance": 0.0001, "hyperliquid": 0.0001, "bybit": 0.0001})
        self.assertEqual(p["ETH"], {"hyperliquid": -0.00016})
        self.assertNotIn("junk", p)

    def test_gate_positioning(self):
        g = M.parse_gate_stats(gate_rows(4.0e9))
        self.assertEqual(g["oi_usd"], round(4.0e9 * 1.24))
        self.assertAlmostEqual(g["oi_chg_24h"], 1.24 / 1.0 - 1, places=6)
        self.assertEqual((g["liq_long_24h_usd"], g["liq_short_24h_usd"]), (24000, 48000))
        self.assertEqual(g["lsr_taker_24h"], 1.5)
        self.assertEqual(g["lsr_account"], 1.44)
        short = M.parse_gate_stats(gate_rows(4.0e9, n=10))                # fewer than 25 hours: no 24h figures
        self.assertIsNone(short["oi_chg_24h"])
        self.assertIsNone(short["liq_long_24h_usd"])
        with self.assertRaises(ValueError):
            M.parse_gate_stats([])

    def test_dvol_fng_stablecoins_global(self):
        d = M.parse_dvol(dvol(40.0), NOW)
        self.assertEqual(d["value"], round(40.0 + 192 / 100, 2))
        self.assertAlmostEqual(d["chg_24h"], 0.24, places=6)
        self.assertAlmostEqual(d["chg_7d"], 1.68, places=6)
        f = M.parse_fng(FNG)
        self.assertEqual((f["value"], f["label"], f["last_7d"][:3]), (60, "Greed", [60, 59, 58]))
        s = M.parse_stablecoins(STABLE)
        self.assertEqual(s["total_usd"], round(300e9))
        self.assertAlmostEqual(s["chg_7d"], 300 / 293 - 1, places=6)
        g = M.parse_cg_global(CG)
        self.assertEqual((g["btc_dominance"], g["mcap_chg_24h"]), (0.582, 0.015))

    def test_farside_flows(self):
        e = M.parse_farside(FARSIDE)
        self.assertEqual(e["unit"], "USD millions")
        self.assertEqual([v for _, v in e["days"]], [100.5, -20.0, 1234.5, 0.0, 55.0])     # '-' is missing, not zero
        self.assertEqual(e["last_total_musd"], 55.0)
        self.assertEqual(e["sum_5d_musd"], 1370.0)
        with self.assertRaises(ValueError):
            M.parse_farside("<html>no table</html>")


class Collect(unittest.TestCase):
    def test_document(self):
        doc, f = collect()
        self.assertEqual((doc["schema"], doc["as_of"], doc["fresh_until"]), (M.VERSION, NOW, NOW + 2 * H))
        self.assertTrue(doc["authority"].startswith("CONTEXT_ONLY"))
        self.assertEqual({s for s, v in doc["sources"].items() if v["status"] != "OK"}, set())
        btc = doc["assets"]["BTC"]
        self.assertEqual((btc["funding_8h_binance"], btc["funding_8h_bybit"], btc["at_oi_cap"]), (0.0001, 0.0001, False))
        self.assertEqual(doc["assets"]["TINY"]["at_oi_cap"], True)
        self.assertEqual(btc["gate"]["oi_usd"], round(4.0e9 * 1.24))
        self.assertIn("gate", doc["assets"]["kPEPE"])                      # kPEPE is PEPE_USDT on Gate
        self.assertNotIn("gate", doc["assets"]["TINY"])                    # below $1M a day: not requested
        r = doc["regime"]
        self.assertEqual(r["sentiment"]["value"], 60)
        self.assertEqual(r["premiums"]["coinbase"], round(83400 / 83350 - 1, 6))
        self.assertEqual(r["premiums"]["korea"], round(113000000 / 1350 / 83350 - 1, 6))
        self.assertEqual(r["btc_margin"]["longs"]["btc"], 89000.0)
        self.assertAlmostEqual(r["btc_margin"]["longs"]["chg_24h"], 89000 / 90440 - 1, places=6)
        self.assertEqual(r["etf_flows"]["last_total_musd"], 55.0)
        self.assertEqual(r["global"]["btc_dominance"], 0.582)
        cg = [c for c in f.calls if "coingecko" in c[0]]
        self.assertEqual(cg[0][2], {"x-cg-demo-api-key": "demo"})
        self.assertLess(len(json.dumps(doc)), 200_000)

    def test_regime_summary(self):
        doc, _ = collect()
        f = doc["regime"]["funding"]
        # liquid (>= $1M a day): BTC 0.0001, ETH -0.00016, kPEPE 0.0008 (SOL funding missing; TINY below $1M)
        self.assertEqual(f["liquid_coins"], 3)
        self.assertEqual(f["median_8h"], 0.0001)
        self.assertEqual(f["share_positive"], round(2 / 3, 6))
        self.assertEqual(f["highest"][0], ["kPEPE", 0.0008])
        self.assertEqual(f["lowest"][0], ["ETH", -0.00016])
        b = doc["regime"]["breadth"]
        self.assertEqual(b["liquid_coins"], 4)                            # SOL's change is known even without funding
        self.assertEqual(doc["regime"]["open_interest"]["largest"][0][0], "BTC")
        p = doc["regime"]["positioning"]
        self.assertEqual(p["liquidations_24h_usd"], {"long": 24000 + 120000 + 24000, "short": 48000 + 2400 + 48000, "coins": 3})

    def test_a_failed_source_leaves_only_its_own_fields_missing(self):
        doc, _ = collect(fail=("predictedFundings", "farside.co.uk", "currency=BTC"))
        self.assertEqual(doc["sources"]["hl.predicted"]["status"], "ERROR")
        self.assertIn("down", doc["sources"]["hl.predicted"]["error"])
        self.assertIsNone(doc["assets"]["BTC"]["funding_8h_binance"])     # missing, never zero
        self.assertEqual(doc["assets"]["BTC"]["funding_8h"], 0.0001)        # Hyperliquid's own funding is unaffected
        self.assertIsNone(doc["regime"]["etf_flows"])
        self.assertIsNone(doc["regime"]["volatility"]["btc_dvol"])
        self.assertIsNotNone(doc["regime"]["volatility"]["eth_dvol"])

    def test_everything_down_is_still_a_document(self):
        doc, _ = collect(table={})
        self.assertEqual(doc["assets"], {})
        self.assertTrue(all(v["status"] in ("ERROR", "SKIPPED") for k, v in doc["sources"].items()))
        self.assertIsNone(doc["regime"]["funding"])
        json.dumps(doc, allow_nan=False)

    def test_no_key_no_call(self):
        doc, f = collect(key=None)
        self.assertEqual(doc["sources"]["cg.global"]["status"], "MISSING_KEY")
        self.assertFalse([c for c in f.calls if "coingecko" in c[0]])
        self.assertIsNone(doc["regime"]["global"])

    def test_stale_premium_inputs_are_not_compared(self):
        t = payloads()
        t["coinbase.com"] = [[NOW - 3600, 1, 1, 1, 90000.0, 1]]
        doc, _ = collect(table=t)
        self.assertIsNone(doc["regime"]["premiums"]["coinbase"])

    def test_no_engine_reads_the_market_context(self):
        for path in list(ROOT.glob("v8/*.py")) + [ROOT / n for n in ("quant.py", "scanner.py", "picks.py", "smart.py")]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("v9.market", text, path)
            self.assertNotIn("data/v9/market.json", text, path)
            self.assertNotIn("from v9", text, path)


class History(unittest.TestCase):
    def test_record_and_path(self):
        doc, _ = collect()
        rec = M.history_record(doc)
        self.assertEqual(rec["schema"], M.HISTORY_VERSION)
        self.assertEqual(sorted(rec["assets"]), ["BTC", "ETH", "SOL", "kPEPE"])
        row = dict(zip(rec["fields"], rec["assets"]["BTC"]))
        self.assertEqual((row["funding_8h"], row["gate_lsr_account"]), (0.0001, 1.44))
        self.assertEqual(M.history_path(NOW), "market/2026/10/14/13.json.gz")

    def test_append_once_per_hour_without_force(self):
        doc, _ = collect()
        with tempfile.TemporaryDirectory() as d:
            remote, repo = os.path.join(d, "remote.git"), os.path.join(d, "repo")
            git = lambda *a, cwd=repo: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
            subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
            os.makedirs(repo)
            git("init", "-q")
            git("remote", "add", "origin", remote)
            self.assertEqual(M.append_history(repo, "v9-market-history", doc), "market/2026/10/14/13.json.gz")
            self.assertIsNone(M.append_history(repo, "v9-market-history", dict(doc, as_of=NOW + 60)))   # same hour
            self.assertEqual(M.append_history(repo, "v9-market-history", dict(doc, as_of=NOW + H)),
                             "market/2026/10/14/14.json.gz")
            log = subprocess.run(["git", "log", "--format=%s", "v9-market-history"], cwd=remote, capture_output=True,
                                 text=True).stdout.split("\n")
            self.assertEqual(log[:2], ["Market context market/2026/10/14/14.json.gz", "Market context market/2026/10/14/13.json.gz"])
            files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "v9-market-history"], cwd=remote,
                                   capture_output=True, text=True).stdout.split()
            self.assertEqual(files, ["README.md", "market/2026/10/14/13.json.gz", "market/2026/10/14/14.json.gz"])
            blob = subprocess.run(["git", "cat-file", "blob", "v9-market-history:market/2026/10/14/13.json.gz"], cwd=remote,
                                  capture_output=True).stdout
            self.assertEqual(json.loads(gzip.decompress(blob))["as_of"], NOW)

    def test_cli_writes_the_file_and_never_fails_on_sources(self):
        down = M.collect(now=NOW, fetch=fake_fetch({}), cg_key=None)       # every source down
        orig = M.collect
        M.collect = lambda **kw: down
        try:
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(M.main(["--out", d]), 0)
                doc = json.load(open(os.path.join(d, "data", "v9", "market.json")))
        finally:
            M.collect = orig
        self.assertEqual((doc["schema"], doc["as_of"]), (M.VERSION, NOW))
        self.assertIn("0/", M.summary_line(doc))


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- the desk's market panel (node)
import shutil  # noqa: E402

NODE = shutil.which("node")
RUN = r"""
const D = require(process.argv[1]);
const F = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const out = {};
for (const [k, c] of Object.entries(F.cases)) out[k] = c.coin ? D.views.marketAsset(c.doc, c.coin, c.now) : D.views.market(c.doc, c.now);
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node unavailable")
class DeskPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc, _ = collect()
        down, _ = collect(table={})
        evil = copy.deepcopy(doc)
        evil["assets"]['X"><img src=x onerror=alert(1)>'] = copy.deepcopy(evil["assets"]["BTC"])
        evil["regime"]["funding"]["highest"][0][0] = '<script>alert(2)</script>'
        cases = {"ok": {"doc": doc, "now": NOW + 60}, "stale": {"doc": doc, "now": NOW + 3 * H},
                 "down": {"doc": down, "now": NOW + 60}, "missing": {"doc": None, "now": NOW},
                 "malformed": {"doc": "MALFORMED", "now": NOW}, "other": {"doc": dict(doc, schema="v9.market/0"), "now": NOW},
                 "evil": {"doc": evil, "now": NOW + 60},
                 "btc": {"doc": doc, "coin": "BTC", "now": NOW + 60}, "sol": {"doc": doc, "coin": "SOL", "now": NOW + 60},
                 "absent": {"doc": doc, "coin": "NOPE", "now": NOW + 60},
                 "evilcoin": {"doc": evil, "coin": 'X"><img src=x onerror=alert(1)>', "now": NOW + 60}}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "in.json"
            f.write_text(json.dumps({"cases": cases}))
            cls.out = json.loads(subprocess.check_output([NODE, "-e", RUN, str(ROOT / "desk.js"), str(f)], timeout=60))

    def test_panel(self):
        h = self.out["ok"]
        for text in ("Fear &amp; Greed", "<b>60</b> Greed", "BTC implied vol", "Funding (Hyperliquid)", "Highest funding",
                     "kPEPE +0.080%", "Breadth", "Stablecoin supply", "US spot BTC ETFs", "BTC premiums", "Coinbase",
                     "Korea", "BTC margin (Bitfinex)", "Liquidations 24h", "At OI cap (Hyperliquid)", "TINY",
                     "Crypto market cap", "it is not a trade signal and changes no decision"):
            self.assertIn(text, h)
        self.assertNotIn("past its own freshness time", h)
        self.assertIn("past its own freshness time", self.out["stale"])
        for banned in ("bullish", "bearish", "buy signal", "sell signal", "guaranteed", "risk-free"):
            self.assertNotIn(banned, h.lower())

    def test_unavailable_and_down(self):
        for k in ("missing", "malformed", "other"):
            self.assertIn("Market context is not available right now", self.out[k])
        self.assertIn("No market source answered in this scan.", self.out["down"])
        self.assertIn("0 of ", self.out["down"])

    def test_coin_context(self):
        btc = self.out["btc"]
        for text in ("Hyperliquid <b>+0.010% / 8h</b>", "Binance <b>+0.010% / 8h</b>", "Bybit <b>+0.010% / 8h</b>",
                     "Positioning (Gate)", "accounts long/short <b>1.44</b>", "Liquidations 24h", "not part of the decision above"):
            self.assertIn(text, btc)
        sol = self.out["sol"]
        self.assertIn("Hyperliquid <b>– / 8h</b>", sol)             # missing funding shows as missing, never 0
        self.assertNotIn("Positioning (Gate)", sol)
        self.assertIn("is not in the market context", self.out["absent"])

    def test_escaping(self):
        for k in ("evil", "evilcoin"):
            self.assertNotIn("<script>", self.out[k])
            self.assertNotIn("<img", self.out[k])
