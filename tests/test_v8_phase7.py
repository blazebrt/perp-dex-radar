"""v8 Phase 7: full-universe discovery and the hierarchical scan.

    Discovery sees everything. Execution remains selective.

Pinned here:

* the denominator: every active perpetual of every venue whose market list loaded is in exactly one discovery record
  (tradfi, ambiguous, unverified and verified crypto alike); a failed venue is VENUE_UNAVAILABLE / DATA_DEGRADED /
  VENUE_MARKET_LIST_UNAVAILABLE and its markets are counted outside the denominator; NO_MARKETS and
  ZERO_ACTIVE_MARKETS are told apart; the fallback universe says fallback_universe=true, full_discovery_qualified=false;
* visibility is never gated: identity, execution liquidity, 1h history and the stage-2 budget only decide the stage,
  the lane and the reason an asset was not deep-researched; execution liquidity is its own field and a missing value
  stays null;
* research flags (NEW_LISTING from first-seen history only, funding, price dispersion, open interest, stage-1 move,
  liquidity, identity), lanes, research priority and the shadow deep-research queue are observational: no engine
  imports v8.discovery, the queue makes no request, and nothing it holds changes a final disposition;
* the Decision Trace (nine steps, Input -> Rule -> Result -> Effect) and the accounting (unaccounted 0 in every scope);
* the bounded quant-audit fix: an open position on a coin below current execution liquidity is SURFACED as an existing
  position to hold and manage (POSITION_LIFECYCLE_ONLY, new_entry_executable false, DEX_VOLUME_BELOW_LEGACY_MIN), the
  journal is untouched, published == ledger, and a new signal on an illiquid coin stays NOT_EXECUTABLE;
* end to end on the parity fixture: discovery.json and the snapshot's discovery section, legacy outputs identical to the
  Phase 6 golden (tests/fixtures/v8/legacy_parity_golden_phase7.json), identity version and config hash unchanged.

ScanGateInvariants is cheap enough for every scheduled scan.

Run from the repository root:  python -m unittest tests.test_v8_phase7 -v"""
from __future__ import annotations

import copy
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "v8"))

from v8 import audit_quant as AQ  # noqa: E402
from v8 import discovery as DS  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import liquidity as LQ  # noqa: E402
from v8 import provenance  # noqa: E402
from v8 import taxonomy as T  # noqa: E402

VENUES = ("aster", "dydx", "edgex", "extended", "hyperliquid", "lighter", "paradex", "variational")
TRADE = ("hyperliquid", "lighter", "aster", "variational")
TS = 1_800_000_000
DAY = 86400
IDENTITY_CONFIG_HASH = "96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c"     # unchanged since Phase 6
HEADER = {"scan_id": "gh-7-1", "git_sha": "f" * 40, "identity_config_hash": IDENTITY_CONFIG_HASH}
STATE = {"CRYPTO": ID.VERIFIED_CRYPTO, "TRADFI": ID.VERIFIED_TRADFI, "AMBIGUOUS": ID.AMBIGUOUS,
         "UNVERIFIED": ID.UNVERIFIED}
DEEP_STAGES = ("deep_dive", "signal", "plan", "block", "publish")


class World:
    """A synthetic scan: registry contracts and assets, the scanner's discovery part and the ledgers."""

    def __init__(self, cfg=None):
        self.contracts, self.assets, self.coins, self.radar, self.universe = [], {}, {}, [], []
        self.venues = {v: {"ok": True, "raw": 0, "kept": 0, "skipped": 0, "mismatch": 0, "payload": True}
                       for v in VENUES}
        self.cfg = dict({"stage2_n": 40, "stage2_extra": 16, "min_dex_vol": 1_000_000, "trade_dexes": list(TRADE)},
                        **(cfg or {}))
        self.fallback = False
        self.engines = {}

    def down(self, v):
        self.venues[v].update(ok=False, payload=False)
        return self

    def market(self, t, venue, price=1.0, vol=2e6, oi=None, fund=None, legacy="SELECTED", active=True, typ="perp",
               first=TS - 30 * DAY, health=T.HEALTHY, raw=None):
        c = {"id": f"{venue}:{raw or t}", "venue": venue, "raw": raw or t, "asset": t, "mult": 1.0, "type": typ,
             "active": active, "legacy": legacy, "price": price, "npx": price, "vol": vol, "oi": oi, "fund8h": fund,
             "first_seen": first, "health": health}
        self.contracts.append(c)
        self.venues[venue]["raw"] += 1
        return c

    def coin(self, t, state, markets, stage="stage2", code=None, h1=None, via=None, collision=False, reason=None,
             checks=None, x=None, legacy=None):
        """One asset: its markets [(venue, kwargs)], identity state, and where the radar left it."""
        cs = [self.market(t, v, **kw) for v, kw in markets]
        sel = [c for c in cs if c["legacy"] == "SELECTED"]
        st = STATE[state]
        tradfi = state in ("TRADFI", "AMBIGUOUS")
        ib = {"state": st, "reason": reason or {"CRYPTO": ID.R_BOUND, "TRADFI": "TRADFI_CONTRACT_EVIDENCE",
                                               "AMBIGUOUS": "CONFLICTING_CONTRACT_EVIDENCE",
                                               "UNVERIFIED": ID.R_NO_EVIDENCE}[state],
              "authority": "TICKER_LIST" if state == "CRYPTO" else "VENUE_METADATA", "decision": "D",
              "exposures": [{"id": f"{t}#1", "class": state, "reason": reason or "R", "anchor_price": cs[0]["price"],
                             "members": [c["id"] for c in sel], "admitted": state == "CRYPTO", "attached": False,
                             "recorded": state == "UNVERIFIED"}],
              "evidence": [], "wrapper_evidence": [], "exposure_checks": checks or []}
        self.assets[t] = {"contracts": [c["id"] for c in cs], "venues": sorted({c["venue"] for c in cs}),
                          "legacy": legacy or state, "collision": collision, "identity": ib}
        mine = [c["vol"] for c in sel if c["venue"] in TRADE and c["vol"] is not None]
        rec = {"venues": {c["venue"]: {} for c in sel}, "trade_vol": max(mine) if mine else None}
        e = LQ.evaluate(rec, TRADE)
        vols = [c["vol"] for c in sel if c["vol"] is not None]
        coin = {"identity": st, "tradfi": tradfi, "name": t, "ref_price": sel[0]["price"] if sel else None,
                "best_vol": max(vols) if vols else None, "tot_vol": sum(vols) if vols else None,
                "trade_vol": rec["trade_vol"], "venues": sorted(rec["venues"]),
                "liquidity": {"state": e["state"], "value": e["value"], "basis": e["basis"]}, "crypto": state == "CRYPTO"}
        if state == "CRYPTO":
            charted = stage not in ("universe", "stage1")
            coin["h1"] = {"requested": True, "returned": charted, "charted": charted}
            if charted:
                coin["h1"].update(rank=1, score=1.0, r24=0.01)
            coin["h1"].update(h1 or {})
            if stage in DEEP_STAGES:
                coin["deep"] = {"selected": True, "via": via or "TOP_N", "completed": stage != "deep_dive"}
        else:
            stage = "universe"
            code = code or ("TRADFI_CLASSIFIED" if state == "TRADFI" else "AMBIGUOUS_EXPOSURE" if state == "AMBIGUOUS"
                            else "IDENTITY_UNVERIFIED")
        self.coins[t] = coin
        if code is None:
            code = {"stage1": "INSUFFICIENT_1H_HISTORY", "stage2": "RADAR_STAGE2_NOT_SELECTED",
                    "deep_dive": "INSUFFICIENT_15M_HISTORY", "signal": "NO_STRATEGY_SIGNAL"}[stage]
        r = {"a": t, "d": T.REASONS[code][0], "c": code, "st": stage, "h": T.HEALTHY}
        if x:
            r["x"] = x
        self.radar.append(r)
        return self

    def registry_only(self, t, venue, legacy="DELISTED", active=False, typ="perp", reason="NO_ACTIVE_PERP_CONTRACT"):
        c = self.market(t, venue, legacy=legacy, active=active, typ=typ)
        self.assets[t] = {"contracts": [c["id"]], "venues": [venue], "legacy": reason, "collision": False,
                          "identity": None}
        self.universe.append({"a": t, "d": T.REASONS[reason][0], "c": reason, "st": "universe", "h": T.HEALTHY})
        return self

    def reg(self):
        return {"contracts": self.contracts, "assets": self.assets, "venues": self.venues, "fallback": self.fallback}

    def scan(self):
        return {"coins": self.coins, "dex_ok": not self.fallback, "config": self.cfg, "stages": {},
                "requests": {"stage1_1h": 0, "stage2_15m": 0, "discovery_extra": 0}}

    def build(self, since=TS - 60 * DAY, scan=True):
        disp = dict({"radar": self.radar, "universe": self.universe}, **self.engines)
        return DS.build(self.reg(), self.scan() if scan else None, disp, HEADER, {"since": since, "source": "site"}, TS)


def recs(doc):
    return {r["asset"]: r for r in doc["assets"]}


def mixed():
    """Every identity state, every liquidity state, every radar stage."""
    w = World()
    w.coin("BTC", "CRYPTO", [("hyperliquid", {"price": 82000, "vol": 3e9, "oi": 2e9, "fund": 1e-4}),
                             ("aster", {"price": 82010, "vol": 1e9, "fund": 1.2e-4})], stage="signal")
    w.coin("ILLQ", "CRYPTO", [("hyperliquid", {"vol": 2e5})], code="DEX_VOLUME_BELOW_LEGACY_MIN")
    w.coin("NOVOL", "CRYPTO", [("lighter", {"vol": None})], code="DEX_VOLUME_MISSING")
    w.coin("OFFDEX", "CRYPTO", [("dydx", {"vol": 9e6})], code="NOT_ON_TRADE_DEX")
    w.coin("NOHIST", "CRYPTO", [("hyperliquid", {"vol": 5e6})], stage="stage1")
    w.coin("BUDGET", "CRYPTO", [("hyperliquid", {"vol": 5e6}), ("aster", {"vol": 4e6})], stage="stage2")
    w.coin("AAPL", "TRADFI", [("extended", {"price": 230, "vol": 8e6, "oi": 1e6, "fund": 2e-5}),
                              ("aster", {"price": 230.2, "vol": 3e6})])
    w.coin("MYST", "UNVERIFIED", [("variational", {"price": 0.4, "vol": 3e5})])
    w.coin("AMBI", "AMBIGUOUS", [("aster", {"vol": 1e5}), ("lighter", {"vol": 2e5})], collision=True)
    w.registry_only("DEAD", "paradex")
    return w


# --------------------------------------------------------------------------- synthetic discovery tests 1-15
class Discovery(unittest.TestCase):
    def test_01_every_active_perp_of_a_healthy_venue_is_in_discovery(self):
        doc, s = mixed().build()
        r = recs(doc)
        self.assertEqual(set(r), {"BTC", "ILLQ", "NOVOL", "OFFDEX", "NOHIST", "BUDGET", "AAPL", "MYST", "AMBI"})
        a = doc["accounting"]
        self.assertEqual((a["active_perps"], a["active_perps_in_denominator"], a["active_perps_in_discovery"]),
                         (13, 13, 13))
        self.assertEqual(a["unaccounted"], 0)
        self.assertEqual({k: 0 for k in a["unaccounted_by_scope"]}, a["unaccounted_by_scope"])
        self.assertEqual(doc["registry_only"], [{"asset": "DEAD", "reason": "NO_ACTIVE_PERP_CONTRACT", "contracts": 1,
                                                 "venues": ["paradex"]}])
        self.assertEqual(doc["provenance"]["schema"], "v8.discovery/1")
        self.assertTrue(doc["provenance"]["full_discovery_qualified"])
        self.assertEqual(s["unaccounted"], 0)

    def test_02_failed_venue_is_degraded_and_outside_the_denominator(self):
        w = mixed()
        w.coin("EDGY", "CRYPTO", [("edgex", {"legacy": "ADAPTER_FAILED"})], legacy="VENUE_ADAPTER_FAILED")
        w.radar.pop()                      # the venue failed: no coin, no radar record
        del w.coins["EDGY"]
        w.universe.append({"a": "EDGY", "d": T.INSUFFICIENT_DATA, "c": "VENUE_ADAPTER_FAILED", "st": "universe"})
        w.down("edgex")
        doc, _ = w.build()
        v = doc["venues"]["edgex"]
        self.assertEqual((v["state"], v["health"], v["reason"]),
                         (DS.VENUE_UNAVAILABLE, DS.DATA_DEGRADED, DS.VENUE_MARKET_LIST_UNAVAILABLE))
        self.assertEqual(v["active_perps"], 0)
        self.assertNotIn("EDGY", recs(doc))
        self.assertIn({"asset": "EDGY", "reason": "VENUE_ADAPTER_FAILED", "contracts": 1, "venues": ["edgex"]},
                      doc["registry_only"])
        p = doc["provenance"]
        self.assertEqual((p["venues_failed"], p["venues_failed_names"], p["coverage_state"]), (1, ["edgex"], "DEGRADED"))
        self.assertEqual(doc["accounting"]["active_perps_on_unavailable_venues"], {"edgex": 1})
        self.assertEqual(doc["accounting"]["unaccounted"], 0)

    def test_03_unavailable_no_markets_and_zero_active_are_distinct(self):
        w = World()
        w.coin("BTC", "CRYPTO", [("hyperliquid", {})], stage="signal")
        w.down("edgex")
        w.registry_only("OLD", "paradex", legacy="NOT_PERPETUAL", typ="other", active=True)
        w.venues["dydx"]["raw"] = 0
        doc, _ = w.build()
        st = {v: x["state"] for v, x in doc["venues"].items()}
        self.assertEqual((st["edgex"], st["dydx"], st["paradex"], st["hyperliquid"]),
                         (DS.VENUE_UNAVAILABLE, DS.NO_MARKETS, DS.ZERO_ACTIVE_MARKETS, DS.VENUE_OK))
        self.assertEqual(doc["venues"]["dydx"]["health"], DS.HEALTHY)

    def test_04_fallback_universe_is_never_full_discovery(self):
        w = World()
        for v in VENUES:
            w.down(v)
        w.fallback = True
        w.coins["SOL"] = {"identity": ID.VERIFIED_CRYPTO, "tradfi": False, "ref_price": None, "best_vol": None,
                          "tot_vol": None, "trade_vol": None, "venues": [], "crypto": True,
                          "liquidity": {"state": LQ.MISSING, "value": None, "basis": "MISSING"},
                          "h1": {"requested": True, "returned": True, "charted": True, "rank": 1}}
        w.assets["SOL"] = {"contracts": [], "venues": [], "legacy": "CRYPTO", "collision": False, "identity": None,
                           "fallback": True}
        w.radar.append({"a": "SOL", "d": T.REJECTED, "c": "RADAR_STAGE2_NOT_SELECTED", "st": "stage2"})
        doc, s = w.build()
        p = doc["provenance"]
        self.assertEqual((p["fallback_universe"], p["full_discovery_qualified"], p["coverage_state"]),
                         (True, False, "FALLBACK"))
        r = recs(doc)["SOL"]
        self.assertEqual((r["price"], r["best_volume"], r["data_quality"]), (None, None, DS.DATA_DEGRADED))
        self.assertEqual(r["execution_liquidity"]["legacy_gate"], "BYPASSED_FALLBACK_UNIVERSE")
        self.assertEqual(s["coverage"]["full_discovery_qualified"], False)

    def test_05_identity_never_gates_visibility(self):
        r = recs(mixed().build()[0])
        for t, lane in (("AAPL", DS.NON_CRYPTO), ("MYST", DS.IDENTITY_RESEARCH), ("AMBI", DS.IDENTITY_RESEARCH)):
            self.assertEqual(r[t]["priority_lane"], lane, t)
            self.assertEqual(r[t]["discovery_stage"], DS.LIGHT_ONLY)
            self.assertEqual(r[t]["deep_research_state"]["reason"], DS.IDENTITY_NOT_CRYPTO)
            self.assertIsNotNone(r[t]["price"])
            self.assertFalse(r[t]["execution_state"]["new_entry_executable"])
            self.assertIn(DS.IDENTITY_NOT_CRYPTO, r[t]["execution_state"]["reasons"])
        a = r["AAPL"]
        self.assertEqual((a["open_interest"]["value"], a["open_interest"]["basis"]), (1000000, "PARTIAL_SUM"))
        self.assertEqual(a["funding"]["venues_reporting"], 1)
        self.assertIn("IDENTITY_UNVERIFIED", r["MYST"]["anomaly_flags"])
        self.assertIn("ECONOMIC_EXPOSURE_CONFLICT", r["AMBI"]["anomaly_flags"])
        self.assertNotIn("IDENTITY_UNVERIFIED", a["anomaly_flags"])

    def test_06_liquidity_never_gates_visibility_and_missing_stays_null(self):
        r = recs(mixed().build()[0])
        el = r["ILLQ"]["execution_liquidity"]
        self.assertEqual(el, {"state": LQ.KNOWN, "observed_value": 200000, "threshold": 1_000_000, "passes": False})
        self.assertIn("THIN_LIQUIDITY", r["ILLQ"]["anomaly_flags"])
        self.assertEqual(r["ILLQ"]["deep_research_state"]["reason"], DS.EXECUTION_LIQUIDITY_BELOW_MIN)
        n = r["NOVOL"]
        self.assertEqual((n["execution_liquidity"]["observed_value"], n["best_volume"], n["liquidity_value"]),
                         (None, None, None))
        self.assertIn("LIQUIDITY_MISSING", n["anomaly_flags"])
        self.assertEqual(n["deep_research_state"]["reason"], DS.EXECUTION_LIQUIDITY_UNKNOWN)
        self.assertEqual(r["OFFDEX"]["deep_research_state"]["reason"], DS.NOT_ON_TRADE_DEX)
        for t in ("ILLQ", "NOVOL", "OFFDEX"):
            self.assertEqual(r[t]["discovery_stage"], DS.CHARTED_1H)
            self.assertEqual(r[t]["priority_lane"], DS.EMERGING)
            self.assertEqual(r[t]["execution_state"]["state"], "GATES_BLOCKED")

    def test_07_history_never_gates_visibility(self):
        r = recs(mixed().build()[0])["NOHIST"]
        self.assertEqual((r["discovery_stage"], r["deep_research_state"]["reason"]),
                         (DS.LIGHT_ONLY, DS.INSUFFICIENT_1H_DATA))
        self.assertEqual(r["execution_state"]["state"], "GATES_PASSED")       # history is not a shared gate
        self.assertEqual(r["best_volume"], 5000000)

    def test_08_stage2_budget_never_gates_visibility(self):
        r = recs(mixed().build()[0])
        self.assertEqual((r["BUDGET"]["discovery_stage"], r["BUDGET"]["deep_research_state"]["reason"]),
                         (DS.CHARTED_1H, DS.DEEP_BUDGET_NOT_SELECTED))
        self.assertEqual((r["BTC"]["discovery_stage"], r["BTC"]["deep_research_state"]["reason"]),
                         (DS.STRATEGY_EVALUATED, DS.DEEP_COMPLETED))
        self.assertEqual(r["BTC"]["stage_path"], [DS.DISCOVERED, DS.CHARTED_1H, DS.DEEP_RESEARCH,
                                                  DS.STRATEGY_EVALUATED])

    def test_09_new_listing_only_from_first_seen_after_tracking_started(self):
        w = World()
        w.coin("NEWB", "CRYPTO", [("hyperliquid", {"first": TS - 2 * DAY})])
        w.coin("OLDB", "CRYPTO", [("hyperliquid", {"first": TS - 60 * DAY})])        # = tracking start
        w.coin("OLDNEW", "CRYPTO", [("hyperliquid", {"first": TS - 9 * DAY})])
        r = recs(w.build(since=TS - 60 * DAY)[0])
        self.assertIn("NEW_LISTING", r["NEWB"]["anomaly_flags"])
        self.assertEqual(r["NEWB"]["listing_age"]["basis"], "FIRST_SEEN_AFTER_TRACKING_START")
        self.assertEqual(r["OLDB"]["listing_age"], {"state": "UNKNOWN", "days": None, "basis": "BEFORE_TRACKING_START",
                                                   "at_least_days": 60})
        self.assertNotIn("NEW_LISTING", r["OLDB"]["anomaly_flags"])
        self.assertNotIn("NEW_LISTING", r["OLDNEW"]["anomaly_flags"])           # older than 7 days
        # a first scan (no history): nothing is new, every age is unknown
        r = recs(w.build(since=TS)[0])
        self.assertFalse(any("NEW_LISTING" in x["anomaly_flags"] for x in r.values()))
        self.assertEqual(r["NEWB"]["listing_age"]["state"], "UNKNOWN")

    def test_10_structural_flags_and_their_thresholds(self):
        w = World()
        w.coin("FUND", "CRYPTO", [("hyperliquid", {"fund": 0.0012, "vol": 5e6}), ("aster", {"fund": 0.0011})])
        w.coin("FDIS", "CRYPTO", [("hyperliquid", {"fund": 0.0004, "vol": 5e6}), ("aster", {"fund": -0.0002})])
        w.coin("PDIS", "CRYPTO", [("hyperliquid", {"price": 1.0, "vol": 5e6}), ("aster", {"price": 1.025})])
        w.coin("OIHI", "CRYPTO", [("hyperliquid", {"vol": 2e6, "oi": 5e7})])
        # matched venues only: OI 30x Hyperliquid's volume; Aster reports no OI and stays out of the ratio
        w.coin("OIMIX", "CRYPTO", [("hyperliquid", {"vol": 1e6, "oi": 3e7}), ("aster", {"vol": 1e8})])
        w.coin("OIMAJ", "CRYPTO", [("hyperliquid", {"vol": 5e8, "oi": 8e9})])            # 16x: a liquid major
        w.coin("MOVE", "CRYPTO", [("hyperliquid", {"vol": 5e6})], h1={"r24": -0.2})
        w.coin("CALM", "CRYPTO", [("hyperliquid", {"price": 1.0, "vol": 5e6, "oi": 1e6, "fund": 0.0009}),
                                  ("aster", {"price": 1.019, "fund": 0.0006})], h1={"r24": 0.149})
        r = recs(w.build()[0])
        self.assertIn("FUNDING_EXTREME", r["FUND"]["anomaly_flags"])
        self.assertIn("FUNDING_DISAGREEMENT", r["FDIS"]["anomaly_flags"])
        self.assertEqual(r["FDIS"]["funding"]["spread_8h"], 0.0006)
        self.assertIn("PRICE_DISPERSION", r["PDIS"]["anomaly_flags"])
        self.assertIn("OI_HIGH_RELATIVE_TO_VOLUME", r["OIHI"]["anomaly_flags"])
        self.assertEqual((r["OIMIX"]["open_interest"]["oi_to_volume"], r["OIMIX"]["open_interest"]["oi_to_volume_venues"],
                          r["OIMIX"]["open_interest"]["basis"]), (30, 1, "PARTIAL_SUM"))
        self.assertIn("OI_HIGH_RELATIVE_TO_VOLUME", r["OIMIX"]["anomaly_flags"])
        self.assertNotIn("OI_HIGH_RELATIVE_TO_VOLUME", r["OIMAJ"]["anomaly_flags"])
        self.assertIn("STAGE1_EXTREME", r["MOVE"]["anomaly_flags"])
        self.assertEqual(r["CALM"]["anomaly_flags"], ["MULTI_VENUE"])           # every value just under its threshold
        self.assertEqual(r["OIHI"]["anomaly_flags"], ["SINGLE_VENUE", "OI_HIGH_RELATIVE_TO_VOLUME"])

    def test_11_lanes(self):
        w = World()
        w.coin("CORE1", "CRYPTO", [("hyperliquid", {"vol": 5e6}), ("aster", {})])
        w.coin("ANOM", "CRYPTO", [("hyperliquid", {"vol": 5e6, "fund": 0.002})])
        w.coin("THIN", "CRYPTO", [("hyperliquid", {"vol": 5e5, "fund": 0.002})], code="DEX_VOLUME_BELOW_LEGACY_MIN")
        w.coin("FRESH", "CRYPTO", [("hyperliquid", {"vol": 5e6, "first": TS - DAY})])
        r = recs(w.build()[0])
        self.assertEqual({t: x["priority_lane"] for t, x in r.items()},
                         {"CORE1": DS.CORE, "ANOM": DS.STRUCTURAL_ANOMALY, "THIN": DS.EMERGING, "FRESH": DS.EMERGING})
        self.assertIn("FUNDING_EXTREME", r["THIN"]["anomaly_flags"])            # emerging wins; the flag is kept

    def test_12_decision_trace(self):
        r = recs(mixed().build()[0])
        for t, x in r.items():
            tr = x["decision_trace"]
            self.assertEqual([s[0] for s in tr], list(DS.TRACE_RULES), t)
            for step, inp, rule, result, effect in tr:
                self.assertIn(rule, DS.TRACE_RULES)
                self.assertTrue(inp and result and effect, (t, step))
        self.assertEqual(r["ILLQ"]["decision_trace"][7][3:], ["GATES_BLOCKED",
                                                              "no new entry: EXECUTION_LIQUIDITY_BELOW_MIN"])
        self.assertEqual(r["BTC"]["decision_trace"][8][3], T.REJECTED)

    def test_13_accounting_is_complete(self):
        doc, s = mixed().build()
        a = doc["accounting"]
        n = a["discovery_assets"]
        for k in ("by_stage", "by_deep_reason", "by_lane", "by_final_disposition"):
            self.assertEqual(sum(a[k].values()), n, k)
        self.assertEqual(a["canonical_assets"], n + a["registry_only_assets"])
        self.assertEqual(a["problems"], [])
        self.assertEqual(s["stages"], a["by_stage"])
        self.assertEqual(sum(s["visibility"][k] for k in ("radar_published_table", "discovery_only")), n)

    def test_14_deterministic_and_without_authority(self):
        a, _ = mixed().build()
        b, _ = mixed().build()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual((a["provenance"]["authority"], a["provenance"]["network_requests_added"]), ("NONE", 0))
        for f in ("scanner.py", "quant.py", "picks.py", "smart.py", "dashboard.py", "analyze.js",
                  *glob.glob(os.path.join(ROOT, "v8", "*.py"))):
            p = f if os.path.isabs(f) else os.path.join(ROOT, f)
            if os.path.basename(p) in ("discovery.py", "snapshot.py", "audit_radar.py", "provenance.py"):
                continue
            with open(p) as fh:
                src = fh.read()
            self.assertIsNone(re.search(r"^\s*(from\s+(v8|\.)\s+import\s+discovery|import\s+v8\.discovery|"
                                        r"from\s+v8\.discovery|from\s+\.discovery)", src, re.M), p)
            self.assertNotIn("discovery.json", src.split('"""', 2)[-1] if p.endswith(".py") else src, p)
        words = json.dumps(a["vocabulary"]).lower()
        for w in ("alpha", "edge", "confidence"):
            self.assertIsNone(re.search(rf"\b{w}\b", words), w)

    def test_15_stage_from_the_final_ledger_record(self):
        w = World()
        for t, code, st in (("PICK", "RADAR_PICK", "publish"), ("WATCH", "RADAR_WATCH", "publish"),
                            ("BLOCK", "STRATEGY_NOT_PASSED", "block"), ("CUT", "OUTPUT_TOP_N_CUTOFF", "publish"),
                            ("WIDE", "STOP_TOO_WIDE", "plan"), ("SHORT", "INSUFFICIENT_15M_HISTORY", "deep_dive")):
            w.coin(t, "CRYPTO", [("hyperliquid", {})], stage=st, code=code)
        r = recs(w.build()[0])
        self.assertEqual({t: x["discovery_stage"] for t, x in r.items()},
                         {"PICK": DS.SURFACED, "WATCH": DS.WATCHED, "BLOCK": DS.EXECUTION_BLOCKED,
                          "CUT": DS.STRATEGY_EVALUATED, "WIDE": DS.STRATEGY_EVALUATED, "SHORT": DS.DEEP_RESEARCH})
        self.assertEqual(r["SHORT"]["deep_research_state"]["reason"], DS.DEEP_HISTORY_INSUFFICIENT)
        self.assertEqual(r["PICK"]["final_disposition"], {"engine": "radar", "code": "RADAR_PICK",
                                                          "disposition": T.SURFACED, "stage": "publish"})

    def test_scan_part_and_ledger_must_agree(self):
        w = mixed()
        w.coins["BUDGET"]["deep"] = {"selected": True, "via": "TOP_N", "completed": True}
        doc, s = w.build()
        self.assertTrue(any("BUDGET" in p for p in doc["accounting"]["problems"]))
        self.assertTrue(s["problems"])

    def test_missing_scan_part_still_gives_every_asset_a_record(self):
        doc, _ = mixed().build(scan=False)
        r = recs(doc)
        self.assertEqual(len(r), 9)
        self.assertEqual(r["BTC"]["execution_liquidity"]["state"], DS.NO_COIN_RECORD)
        self.assertEqual(r["BTC"]["price_basis"], "CONTRACT_MEDIAN")
        self.assertEqual(doc["accounting"]["unaccounted"], 0)

    def test_unsupported_active_markets_are_counted_apart(self):
        w = mixed()
        w.registry_only("XYZ:TSLA", "hyperliquid", legacy="HL_BUILDER_MARKET", active=True)
        doc, _ = w.build()
        a = doc["accounting"]
        self.assertEqual(a["active_perps_unsupported"], {"HL_BUILDER_MARKET": 1})
        self.assertEqual(a["active_perps"], a["active_perps_in_denominator"] + 1)
        self.assertEqual(doc["venues"]["hyperliquid"]["active_perps_unsupported"], {"HL_BUILDER_MARKET": 1})
        self.assertEqual(a["unaccounted"], 0)


# --------------------------------------------------------------------------- the shadow deep-research queue
def shadow_world(n_liquid=60):
    w = World()
    for i in range(n_liquid):
        w.coin(f"L{i:02d}", "CRYPTO", [("hyperliquid", {"vol": 2e6 + i * 1e5})],
               stage="signal" if i >= n_liquid - 56 else "stage2")
    w.coin("ZNEW", "CRYPTO", [("hyperliquid", {"vol": 3e5, "first": TS - DAY, "fund": 0.003}),
                              ("aster", {"vol": 1e5, "fund": 0.001})], code="DEX_VOLUME_BELOW_LEGACY_MIN")
    w.coin("ZTRADFI", "TRADFI", [("extended", {"vol": 9e9, "fund": 0.01, "first": TS - DAY})])
    return w


class ShadowQueue(unittest.TestCase):
    def test_same_budget_ranked_by_points_then_liquidity(self):
        doc, _ = shadow_world().build()
        q = doc["shadow_queue"]
        self.assertEqual((q["slots"], len(q["entries"]), q["authority"], q["trade_authority"]), (56, 56, "NONE", False))
        self.assertEqual(q["entries"][0]["asset"], "ZNEW")       # NEW_LISTING + FUNDING_EXTREME + MULTI_VENUE
        self.assertNotIn("ZTRADFI", [e["asset"] for e in q["entries"]])         # verified crypto only
        rest = [e for e in q["entries"][1:]]
        self.assertEqual([e["asset"] for e in rest], [f"L{i:02d}" for i in range(59, 4, -1)])

    def test_legacy_vs_shadow(self):
        doc, s = shadow_world().build()
        c = doc["legacy_vs_shadow"]
        self.assertEqual((c["legacy_deep"], c["shadow"], c["overlap"]), (56, 56, 55))
        self.assertEqual(c["legacy_only"], ["L04"])
        self.assertEqual([x["asset"] for x in c["shadow_only"]], ["ZNEW"])
        self.assertEqual(c["shadow_only"][0]["why_not_legacy_deep"], DS.EXECUTION_LIQUIDITY_BELOW_MIN)
        self.assertEqual(c["resource"]["shadow_requests_made"], 0)
        self.assertTrue(c["resource"]["within_budget"])
        self.assertEqual(s["legacy_vs_shadow"]["shadow_only"], 1)

    def test_shadow_never_changes_a_disposition(self):
        doc, _ = shadow_world().build()
        r = recs(doc)["ZNEW"]
        self.assertEqual((r["final_disposition"]["code"], r["discovery_stage"], r["deep_research_state"]["selected"]),
                         ("DEX_VOLUME_BELOW_LEGACY_MIN", DS.CHARTED_1H, False))
        self.assertFalse(r["execution_state"]["new_entry_executable"])
        self.assertEqual(r["research_priority"]["authority"], "NONE")

    def test_emerging_census(self):
        doc, s = mixed().build()
        e = doc["emerging"]
        self.assertEqual(e["trade_promotion"], "NONE")
        self.assertEqual(e["verified_crypto"]["assets"], 4)          # ILLQ NOVOL OFFDEX + NOHIST (single venue)
        self.assertEqual((e["verified_crypto"]["below_min"], e["verified_crypto"]["liquidity_missing"],
                          e["verified_crypto"]["not_on_trade_dex"]), (1, 1, 1))
        self.assertEqual(e["unverified"]["assets"], 2)               # MYST, AMBI (below the minimum)
        self.assertNotIn("top_by_points", json.dumps(s["emerging"]))


# --------------------------------------------------------------------------- the bounded quant-audit fix
COIN = {"t": "HBAR", "venues": {"hyperliquid": {"dex": "hyperliquid", "sym": "HBAR"}}, "name": "HBAR", "tradfi": False,
        "ref_price": 0.2, "best_vol": 4e5, "tot_vol": 4e5, "trade_vol": 4e5, "identity": ID.VERIFIED_CRYPTO}
OPEN = {"id": "HBAR-TSMOM-1", "s": "TSMOM", "c": "HBAR", "d": 1, "t_sig": 1, "t_in": 1, "stop_pct": 0.1,
        "trail_pct": 0.0, "hold_h": 720, "px": 0.2, "res": {"state": "open", "r": 0.1},
        "identity_state_at_entry": ID.VERIFIED_CRYPTO, "identity_qualified": True, "identity_version": ID.VERSION,
        "identity_scan_id": "gh-1-1"}


def quant(universe, opens=(), new=(), chosen=()):
    return AQ.quant_part(TS, universe, [universe[t] for t in chosen], {}, {}, {}, None, list(new), list(opens))


class QuantLifecycle(unittest.TestCase):
    def test_open_position_below_liquidity_is_surfaced_for_lifecycle_only(self):
        p = quant({"HBAR": COIN}, opens=[OPEN])
        r = {x["a"]: x for x in p["records"]}["HBAR"]
        self.assertEqual((r["d"], r["c"], r["st"]), (T.SURFACED, "QUANT_POSITION_OPEN", "lifecycle"))
        self.assertEqual(r["x"], ["POSITION_LIFECYCLE_ONLY"])
        o = r["o"]
        self.assertEqual((o["action"], o["new_entry_executable"], o["execution_reason"]),
                         ("HOLD / MANAGE EXISTING POSITION", False, "DEX_VOLUME_BELOW_LEGACY_MIN"))
        self.assertEqual(o["liquidity"], {"state": LQ.KNOWN, "trade_vol": 400000, "basis": "OBSERVED"})
        self.assertEqual(r["th"], {"min": 1000000})
        self.assertEqual(o["open"], [["TSMOM", 1, 1]])

    def test_published_equals_ledger(self):
        p = quant({"HBAR": COIN, "XLM": dict(COIN, t="XLM")}, opens=[OPEN, dict(OPEN, c="XLM", id="XLM-1")])
        self.assertEqual(p["problems"], [])
        self.assertEqual({x["a"] for x in p["records"] if x["d"] == T.SURFACED}, {"HBAR", "XLM"})

    def test_journal_is_preserved(self):
        opens = [copy.deepcopy(OPEN)]
        before = copy.deepcopy(opens)
        quant({"HBAR": COIN}, opens=opens)
        self.assertEqual(opens, before)

    def test_missing_volume_and_no_trade_dex_reasons(self):
        p = quant({"HBAR": dict(COIN, trade_vol=None, best_vol=None),
                   "DYX": dict(COIN, t="DYX", venues={"dydx": {"dex": "dydx", "sym": "DYX-USD"}}, trade_vol=None)},
                  opens=[OPEN, dict(OPEN, c="DYX", id="DYX-1")])
        r = {x["a"]: x for x in p["records"]}
        self.assertEqual(r["HBAR"]["o"]["execution_reason"], "DEX_VOLUME_MISSING")
        self.assertEqual(r["DYX"]["o"]["execution_reason"], "NOT_ON_TRADE_DEX")
        self.assertTrue(all(x["d"] == T.SURFACED and x["o"]["new_entry_executable"] is False for x in r.values()))

    def test_new_signal_on_an_illiquid_coin_stays_not_executable(self):
        p = quant({"HBAR": COIN}, new=[{"c": "HBAR", "s": "TSMOM", "d": 1}])
        r = {x["a"]: x for x in p["records"]}["HBAR"]
        self.assertEqual((r["d"], r["c"]), (T.NOT_EXECUTABLE, "DEX_VOLUME_BELOW_LEGACY_MIN"))
        self.assertTrue(any("new quant signal" in x for x in p["problems"]))

    def test_no_position_no_lifecycle(self):
        r = {x["a"]: x for x in quant({"HBAR": COIN})["records"]}["HBAR"]
        self.assertEqual((r["d"], r["c"]), (T.NOT_EXECUTABLE, "DEX_VOLUME_BELOW_LEGACY_MIN"))
        self.assertNotIn("x", r)

    def test_step_is_in_the_taxonomy(self):
        self.assertIn("POSITION_LIFECYCLE_ONLY", T.STEPS)
        with open(os.path.join(ROOT, "docs", "v8", "disposition-taxonomy.md")) as fh:
            self.assertIn("POSITION_LIFECYCLE_ONLY", fh.read())


# --------------------------------------------------------------------------- versions
class Versions(unittest.TestCase):
    def test_identity_is_not_bumped(self):
        self.assertEqual(ID.VERSION, "v8.identity/4")
        self.assertEqual(provenance.identity_config_hash(), IDENTITY_CONFIG_HASH)

    def test_discovery_and_audit_versions(self):
        from v8 import ENGINE_VERSION, SCHEMA
        self.assertEqual((DS.VERSION, SCHEMA, ENGINE_VERSION), ("v8.discovery/1", "v8.audit/5", "v8-phase7.0"))
        self.assertEqual(provenance.engine_version("discovery"), "v8.discovery/1")


# --------------------------------------------------------------------------- the scheduled-scan gate
class ScanGateInvariants(unittest.TestCase):
    """Critical Phase 7 invariants, cheap enough for every scan."""

    def test_every_active_perp_of_a_healthy_venue_is_visible(self):
        doc, _ = mixed().build()
        self.assertEqual(doc["accounting"]["unaccounted"], 0)
        self.assertEqual(doc["accounting"]["active_perps_in_denominator"], doc["accounting"]["active_perps_in_discovery"])

    def test_identity_and_liquidity_do_not_gate_visibility(self):
        r = recs(mixed().build()[0])
        self.assertTrue({"AAPL", "MYST", "AMBI", "ILLQ", "NOVOL", "NOHIST"} <= set(r))

    def test_failed_venue_is_degraded_and_fallback_is_not_full(self):
        w = World()
        w.coin("BTC", "CRYPTO", [("hyperliquid", {})], stage="signal")
        w.down("edgex")
        doc, _ = w.build()
        self.assertEqual(doc["venues"]["edgex"]["health"], DS.DATA_DEGRADED)
        w.fallback = True
        self.assertFalse(w.build()[0]["provenance"]["full_discovery_qualified"])

    def test_research_flags_have_no_authority(self):
        doc, _ = shadow_world().build()
        self.assertEqual((doc["shadow_queue"]["trade_authority"], doc["legacy_vs_shadow"]["resource"]
                          ["shadow_requests_made"]), (False, 0))

    def test_quant_lifecycle_position_is_surfaced_without_new_entry(self):
        p = quant({"HBAR": COIN}, opens=[OPEN])
        r = p["records"][0]
        self.assertEqual((r["d"], r["o"]["new_entry_executable"], p["problems"]), (T.SURFACED, False, []))


# --------------------------------------------------------------------------- end to end on the parity fixture
class PipelineDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import legacy_parity as LP
        from v8 import snapshot as SN
        cls.LP = LP
        cls.tmp = tempfile.mkdtemp(prefix="v8p7")
        cls.out = os.path.join(cls.tmp, "site")
        LP.run_pipeline(cls.out)
        cls.summary = LP.summary(cls.out)
        cls.snap, _, _, _ = SN.write(cls.out, keep_parts=True)
        with open(os.path.join(cls.out, "data", "v8", "discovery.json")) as fh:
            cls.doc = json.load(fh)
        cls.r = recs(cls.doc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_legacy_outputs_unchanged(self):
        for g in ("legacy_parity_golden_phase7.json", "legacy_parity_golden_phase6.json"):
            with open(os.path.join(HERE, "fixtures", "v8", g)) as fh:
                golden = json.load(fh)
            self.assertEqual(self.LP.compare(golden, self.summary), [], g)
        with open(os.path.join(HERE, "fixtures", "v8", "phase7_expected_deltas.json")) as fh:
            man = json.load(fh)
        self.assertEqual((man["base"]["sha"], man["base"]["tree"]),
                         ("61960d97a0e27f1bec8c83aee0f2a90b5019fd02", "5d3c62204d875fc63641362685498972aeafd0a1"))
        self.assertEqual((man["universe"], man["dex_status"], man["code"], man["decisions"], man["files"]),
                         ([], [], [], [], []))
        self.assertEqual(man["notes"], {"removed": [], "added": []})
        self.assertIn("data/v8/parts/discovery.json", self.summary["audit_files"])

    def test_every_universe_coin_and_active_perp_is_in_discovery(self):
        radar = {x["a"] for x in self.snap["dispositions"]["radar"]}
        self.assertEqual(set(self.r), radar)
        a = self.doc["accounting"]
        self.assertEqual(a["unaccounted"], 0)
        self.assertEqual(a["problems"], [])
        self.assertEqual(a["canonical_assets"], len(self.snap["registry"]["assets"]))
        self.assertTrue(self.doc["provenance"]["full_discovery_qualified"])
        self.assertEqual(self.snap["data_health"]["audit_problems"], {})

    def test_stages_follow_the_radar_ledger(self):
        led = {x["a"]: x for x in self.snap["dispositions"]["radar"]}
        for t, x in self.r.items():
            self.assertEqual(x["final_disposition"]["code"], led[t]["c"], t)
        st = self.snap["coverage"]["engines"]["radar"]["stages"]
        charted = sum(1 for x in self.r.values() if x["discovery_stage"] not in (DS.DISCOVERED, DS.LIGHT_ONLY))
        self.assertEqual(charted, st["stage1_charted"])
        self.assertEqual(sum(1 for x in self.r.values() if x["deep_research_state"]["selected"]),
                         st["stage2_selected"] + st["stage2_extras"])

    def test_snapshot_section_and_provenance(self):
        s = self.snap["discovery"]
        self.assertEqual((s["schema"], s["status"], s["unaccounted"]), ("v8.discovery/1", "OK", 0))
        for k in ("coverage", "venues", "stages", "identity_breakdown", "liquidity_breakdown", "priority_lanes",
                  "anomaly_flags", "shadow_queue", "legacy_vs_shadow", "unaccounted"):
            self.assertIn(k, s)
        m = self.snap["manifest"]
        self.assertEqual(m["discovery_version"], "v8.discovery/1")
        with open(os.path.join(self.out, "data", "v8", "discovery.json"), "rb") as fh:
            import hashlib
            self.assertEqual(m["discovery_file"]["sha256"], hashlib.sha256(fh.read()).hexdigest())
        p = self.doc["provenance"]
        self.assertEqual((p["identity_version"], p["scan_id"], p["identity_config_hash"]),
                         ("v8.identity/4", m["scan_id"], m["identity_config_hash"]))
        self.assertEqual(s["requests"]["discovery_extra"], 0)
        self.assertEqual(self.snap["schema"], "v8.audit/5")

    def test_records_are_compact(self):
        for x in self.doc["assets"]:
            self.assertLess(len(json.dumps(x)), 6000, x["asset"])


if __name__ == "__main__":
    unittest.main()
