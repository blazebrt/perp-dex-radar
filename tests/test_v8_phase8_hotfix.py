"""v8 Phase 8 post-merge hotfix (v8-phase8.1): the four findings of the post-merge review, fixed and pinned.

    1. P1 day-pick research qualifies the day-pick selection authority itself (pk_day.surfaces), not every eligible row
    2. P1 a research cutoff before the first history observation is an empty view (BEFORE_PIT_HISTORY), never a crash
    3. P2 liquidity is recorded without whole-dollar rounding (v8.history/2); the immutable v8.history/1 records keep
       their bytes and hashes, and their rounded KNOWN liquidity never decides a threshold or a slippage tier
    4. P2 a STATUS record's file name and experiment id must agree in the shadow ledger

Standard library only, except the classes marked NUMPY (the CI research-checks job runs this module with numpy, numba
and pandas)."""
from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from v8 import history as H  # noqa: E402
from v8 import pit as P  # noqa: E402
from v8 import shadow_ledger as SL  # noqa: E402

import test_v8_phase8 as B  # noqa: E402  (the Phase 8 fixtures: snapshot(), contract(), append(), synthetic_md())

HAVE_NUMPY = B.HAVE_NUMPY
try:
    import pandas  # noqa: F401
    HAVE_PANDAS = True
except ImportError:
    HAVE_PANDAS = False
if HAVE_NUMPY:
    sys.path.insert(0, os.path.join(ROOT, "tools", "research"))

T0, HOUR = B.T0, B.HOUR
V1_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "v8", "history_v1_chain")
ORACLE = os.path.join(ROOT, "tests", "fixtures", "v8", "research_oracle")
BOUNDARY = (199999.4, 199999.6, 200000.0, 999999.4, 999999.6, 1000000.0)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8p81_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def store(self, name="h"):
        return H.DirStore(os.path.join(self.tmp, name))

    def v1_copy(self, name="mixed"):
        """A copy of the frozen v8.history/1 chain (written by the production v1 writer of main f142bb1)."""
        root = os.path.join(self.tmp, name)
        shutil.copytree(os.path.join(V1_FIXTURE, "obs"), os.path.join(root, "obs"))
        return H.DirStore(root)


def boundary_contracts(vols):
    return ([B.contract("hyperliquid:BTC", "BTC", vol=5e8)]
            + [B.contract(f"hyperliquid:L{k}", f"L{k}", vol=v) for k, v in enumerate(vols)])


# --------------------------------------------------------------------------- finding 3: liquidity precision, versions
class LiquidityPrecision(Tmp):
    def test_writer_persists_the_recorded_value_without_rounding(self):
        st = self.store()
        r, obs, path = B.append(st, B.snapshot(T0, "gh-1-1", boundary_contracts(BOUNDARY)))
        self.assertEqual((r, obs["schema"]), (H.PERSISTED, "v8.history/2"))
        raw = json.loads(gzip.decompress(st.read_bytes(path)))
        rows = {x[0]: x for x in raw["liquidity"]["rows"]}
        for k, v in enumerate(BOUNDARY):
            self.assertEqual(rows[f"L{k}"], [f"L{k}", "KNOWN", v])                # exactly as recorded, not rounded
        self.assertEqual(raw["liquidity_precision"], H.LIQUIDITY_PRECISION)
        self.assertTrue(H.verify(st)["ok"])

    def test_decides_each_boundary_value(self):
        exact = P.PRECISION_REGISTRY_8SIG
        expect_200k = {199999.4: False, 199999.6: False, 200000.0: None, 999999.4: True, 999999.6: True,
                       1000000.0: True}
        expect_1m = {199999.4: False, 199999.6: False, 200000.0: False, 999999.4: False, 999999.6: False,
                     1000000.0: None}
        for v in BOUNDARY:
            self.assertIs(P.decides(v, exact, 200_000), expect_200k[v], v)
            self.assertIs(P.decides(v, exact, 1_000_000), expect_1m[v], v)
            self.assertIsNone(P.decides(v, P.PRECISION_LOST_V1, 1_000_000), v)      # a v1 value never decides
        # the registry keeps 8 significant digits: a value recorded exactly on a threshold may stand for a scan value
        # just below it (999,999.996 is recorded as 1,000,000.0), so it decides nothing; just off it, it decides
        self.assertIs(P.decides(1000000.1, exact, 1_000_000), True)
        self.assertIs(P.decides(999999.99, exact, 1_000_000), False)
        self.assertIs(P.decides(200000.01, exact, 200_000), True)

    def test_historical_eligibility_at_each_boundary(self):
        st = self.store()
        B.append(st, B.snapshot(T0, "gh-1-1", boundary_contracts(BOUNDARY)))
        h = P.History(st)
        u = h.universe_at(T0 + 60, min_vol=1_000_000)["assets"]
        got = {v: u[f"L{k}"]["research_eligible"] for k, v in enumerate(BOUNDARY)}
        self.assertEqual(got, {199999.4: False, 199999.6: False, 200000.0: False, 999999.4: False, 999999.6: False,
                               1000000.0: None})
        self.assertTrue(u["BTC"]["research_eligible"])
        u2 = h.universe_at(T0 + 60, min_vol=200_000)["assets"]
        self.assertEqual({v: u2[f"L{k}"]["research_eligible"] for k, v in enumerate(BOUNDARY)},
                         {199999.4: False, 199999.6: False, 200000.0: None, 999999.4: True, 999999.6: True,
                          1000000.0: True})

    def test_missing_volume_is_a_known_fail_like_the_live_gate(self):
        st = self.store()
        cs = [B.contract("hyperliquid:BTC", "BTC", vol=5e8), B.contract("hyperliquid:NOVOL", "NOVOL", vol=None)]
        B.append(st, B.snapshot(T0, "gh-1-1", cs))
        h = P.History(st)
        self.assertEqual(h.liquidity_at(T0 + 60, "NOVOL")["state"], "MISSING")
        u = h.universe_at(T0 + 60, min_vol=200_000)["assets"]
        self.assertIs(u["NOVOL"]["research_eligible"], False)  # v8.liquidity.passes never passes a missing volume
        self.assertIs(u["BTC"]["research_eligible"], True)
        late = T0 + P.LIQUIDITY_MAX_STALENESS_S + 120          # no fresh record any more: unknown, not a fail
        self.assertIsNone(P.eligible({"state": P.KNOWN_ACTIVE}, h.identity_at(T0 + 60, "NOVOL"),
                                     h.liquidity_at(late, "NOVOL"), 200_000))

    def test_today_never_alters_an_old_exact_observation(self):
        st = self.store()
        B.append(st, B.snapshot(T0, "gh-1-1", boundary_contracts(BOUNDARY)))
        before = P.History(st).liquidity_at(T0 + 60, "L1")
        B.append(st, B.snapshot(T0 + 5 * HOUR, "gh-2-1", boundary_contracts([5e9] * len(BOUNDARY))))
        after = P.History(st).liquidity_at(T0 + 60, "L1")
        self.assertEqual(before, after)
        self.assertEqual((after["value"], after["precision"]), (199999.6, P.PRECISION_REGISTRY_8SIG))


@unittest.skipUnless(HAVE_NUMPY, "numpy and numba (the CI research-checks job runs these)")
class LiquidityPrecisionCosts(Tmp):
    def test_slippage_tier_at_each_boundary(self):
        import numpy as np
        import pit_cost as PC
        st = self.store()
        B.append(st, B.snapshot(T0, "gh-1-1", boundary_contracts(BOUNDARY + (1000000.1,))))
        h = P.History(st)
        coins = [f"L{k}" for k in range(len(BOUNDARY) + 1)]
        vol, state, slip, gate = PC.liquidity_panel(h, [T0 + 60], coins, 1_000_000)
        tiers = dict(zip(BOUNDARY + (1000000.1,), slip[0]))
        self.assertEqual(tiers[199999.4], 0.002)
        self.assertEqual(tiers[199999.6], 0.002)
        self.assertEqual(tiers[999999.4], 0.001)
        self.assertEqual(tiers[999999.6], 0.001)
        self.assertEqual(tiers[1000000.1], 0.0005)
        for v in (200000.0, 1000000.0):           # recorded on a tier threshold: no tier (precision cannot decide it)
            j = (BOUNDARY + (1000000.1,)).index(v)
            self.assertTrue(np.isnan(slip[0, j]))
            self.assertEqual(state[0, j], PC.L_PRECISION)
        self.assertEqual(list(gate[0]), [0, 0, 0, 0, 0, -1, 1])
        # the governed tiers themselves are unchanged
        self.assertEqual([PC.tier(v) for v in (1_000_000, 200_000, 199_999.99)], [0.0005, 0.001, 0.002])

    def test_missing_volume_gate_is_zero_in_the_vectorised_panels(self):
        import numpy as np
        import pit_cost as PC
        import pit_sim as PS
        st = self.store()
        cs = [B.contract("hyperliquid:BTC", "BTC", vol=5e8), B.contract("hyperliquid:NOVOL", "NOVOL", vol=None)]
        B.append(st, B.snapshot(T0, "gh-1-1", cs))
        h = P.History(st)
        vol, state, slip, gate = PC.liquidity_panel(h, [T0 + 60], ["BTC", "NOVOL"], 200_000)
        self.assertEqual((int(state[0, 1]), int(gate[0, 1])), (PC.L_MISSING, 0))
        self.assertTrue(np.isnan(slip[0, 1]) and np.isnan(vol[0, 1]))       # no cost is ever taken from it
        uni = PS.universe_panel(h, [T0 + 60], ["BTC", "NOVOL"], 200_000)
        self.assertEqual((int(uni["code"][0, 0]), int(uni["code"][0, 1])), (1, 0))
        self.assertEqual(PS.liquidity_reason(0, PC.L_MISSING, PC.L_MISSING),
                         "BELOW_GATE_MISSING_OR_NOT_ON_TRADE_DEX_THEN")


class MixedChain(Tmp):
    def test_frozen_v1_fixture_is_byte_identical_and_verifies(self):
        with open(os.path.join(V1_FIXTURE, "MANIFEST.json")) as fh:
            man = json.load(fh)
        st = H.DirStore(V1_FIXTURE)
        self.assertEqual({p: hashlib.sha256(st.read_bytes(p)).hexdigest() for p in st.paths()}, man["files"])
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual((rep["schemas"], rep["head_hash"]), ({"v8.history/1": 3}, man["head_hash"]))
        rows = {r[0]: r for r in H.decode(st.read_bytes(st.paths()[0]))["liquidity"]["rows"]}
        self.assertEqual((rows["EDGE200"][2], rows["EDGE1M"][2]), (200000, 1000000))   # the v1 rounding defect

    def test_v2_appends_to_v1_without_touching_it(self):
        st = self.v1_copy()
        old = {p: st.read_bytes(p) for p in st.paths()}
        head = H.verify(st)["head_hash"]
        cs = boundary_contracts([199999.6, 999999.6])
        r, obs, _ = B.append(st, B.snapshot(T0 + 6 * HOUR, "gh-104-1", cs))
        self.assertEqual((r, obs["schema"], obs["state_mode"]), (H.PERSISTED, "v8.history/2", H.CHECKPOINT))
        self.assertIsNotNone(obs["liquidity"])                 # the first v2 record carries the precise table at once
        self.assertEqual(obs["prev_hash"], head)               # linked to the immutable v1 record hash
        r2, obs2, _ = B.append(st, B.snapshot(T0 + 7 * HOUR, "gh-105-1", cs))
        self.assertEqual((obs2["schema"], obs2["state_mode"], obs2["base"]["seq"]), ("v8.history/2", H.DELTA, 4))
        self.assertEqual({p: st.read_bytes(p) for p in list(old)}, old)       # v1 bytes untouched
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["schemas"], {"v8.history/1": 3, "v8.history/2": 2})
        self.assertEqual(H.Chain(st).integrity, "VERIFIED_TAIL")

    def test_v1_liquidity_is_precision_lost_but_v1_universe_stays_usable(self):
        st = self.v1_copy()
        h = P.History(st)
        liq = h.liquidity_at(T0 + 60, "EDGE200")
        self.assertEqual((liq["state"], liq["value"], liq["precision"]), ("KNOWN", 200000, P.PRECISION_LOST_V1))
        u = h.universe_at(T0 + 60, min_vol=1_000_000)["assets"]
        self.assertIsNone(u["EDGE1M"]["research_eligible"])      # 1,000,000 recorded by v1: cannot decide the gate
        self.assertIsNone(u["BTC"]["research_eligible"])         # even far above it: v1 values never decide
        self.assertFalse(u["EX"]["research_eligible"])           # NOT_ON_TRADE_DEX is a state, not a rounded value
        self.assertEqual(u["BTC"]["state"], P.KNOWN_ACTIVE)      # universe and identity authority stay usable
        self.assertTrue(h.crypto_identity_at(T0 + 60, "BTC"))
        self.assertEqual(h.asset_at(T0 + HOUR + 60, "OLD")["state"], P.KNOWN_INACTIVE)

    def test_no_v1_after_v2_and_no_v2_delta_on_a_v1_checkpoint(self):
        # a v2 delta forged onto the v1 checkpoint (hashes otherwise valid) is rejected
        st = self.v1_copy("forged")
        cs = boundary_contracts([199999.6, 999999.6])
        snap = B.snapshot(T0 + 6 * HOUR, "gh-104-1", cs)
        chain = H.Chain(st)
        obs = H.build_observation(chain, H.scan_content(snap), H.state_from_snapshot(snap), T0 + 6 * HOUR)
        base = chain.base
        obs.update(state_mode=H.DELTA, base={"seq": base["seq"], "hash": H.obs_hash(base)})
        full = H.state_from_snapshot(snap)
        obs["contracts"] = dict(H.delta(chain.base_state["contracts"], full["contracts"]), fields=list(H.CONTRACT_FIELDS))
        obs["assets"] = dict(H.delta(chain.base_state["assets"], full["assets"]), fields=list(H.ASSET_FIELDS))
        obs["record_hash"] = H.obs_hash(obs)
        st.write(H.path_for(obs), H.gz(H.canonical(obs)))
        rep = H.verify(st)
        self.assertFalse(rep["ok"])
        self.assertTrue(any("delta on a v8.history/1 checkpoint" in p for p in rep["problems"]), rep["problems"])
        # a v1 record after a v2 record is rejected
        st2 = self.store("order")
        B.append(st2, B.snapshot(T0, "gh-1-1", cs))
        o = H.decode(st2.read_bytes(st2.paths()[0]))
        o2 = dict(o, seq=2, scan_id="gh-2-1", schema="v8.history/1", prev_hash=H.obs_hash(o), appended_at=T0 + 9,
                  stored_bytes_before=len(st2.read_bytes(st2.paths()[0])))
        o2.pop("liquidity_precision")
        o2["record_hash"] = H.obs_hash(o2)
        st2.write(H.path_for(o2), H.gz(H.canonical(o2)))
        rep2 = H.verify(st2)
        self.assertTrue(any("after a later history schema" in p for p in rep2["problems"]), rep2["problems"])
        # the first v2 record must be a checkpoint carrying the full liquidity table (the writer guarantees it)
        st3 = self.v1_copy("noliq")
        snap3 = B.snapshot(T0 + 6 * HOUR, "gh-104-1", cs)
        obs3 = H.build_observation(H.Chain(st3), H.scan_content(snap3), H.state_from_snapshot(snap3), T0 + 6 * HOUR)
        self.assertEqual((obs3["state_mode"], obs3["liquidity"] is not None), (H.CHECKPOINT, True))
        obs3["liquidity"] = None
        obs3["record_hash"] = H.obs_hash(obs3)
        st3.write(H.path_for(obs3), H.gz(H.canonical(obs3)))
        rep3 = H.verify(st3)
        self.assertFalse(rep3["ok"])
        self.assertTrue(any("first v8.history/2 record must be a checkpoint" in p for p in rep3["problems"]),
                        rep3["problems"])

    def test_v2_record_rules(self):
        st = self.store()
        B.append(st, B.snapshot(T0, "gh-1-1", boundary_contracts([5e6])))
        o = H.decode(st.read_bytes(st.paths()[0]))
        bad = copy.deepcopy(o)
        bad["liquidity"]["rows"][0][2] = None                  # KNOWN without a value
        bad["liquidity_content_hash"] = H.sha(H.canonical(bad["liquidity"]))
        bad["record_hash"] = H.obs_hash(bad)
        self.assertTrue(any("not a finite KNOWN value" in p for p in H.record_problems(bad)))
        bad2 = copy.deepcopy(o)
        bad2.pop("liquidity_precision")
        bad2["record_hash"] = H.obs_hash(bad2)
        self.assertTrue(any("liquidity precision" in p for p in H.record_problems(bad2)))
        bad3 = dict(o, schema="v8.history/9")
        bad3["record_hash"] = H.obs_hash(bad3)
        self.assertTrue(any("unknown history schema" in p for p in H.record_problems(bad3)))

    def test_capture_into_a_mixed_chain_reports_the_writer(self):
        st = self.v1_copy()
        res = H.capture(B.snapshot(T0 + 6 * HOUR, "gh-104-1", boundary_contracts([5e6])), store=st, now=T0 + 6 * HOUR)
        self.assertEqual((res["persistence_state"], res["version"], res["observation"]["schema"]),
                         (H.PERSISTED, "v8.history/2", "v8.history/2"))
        self.assertEqual(res["readable_schemas"], ["v8.history/1", "v8.history/2"])
        self.assertEqual(res["append_integrity"], "VERIFIED_TAIL")


# --------------------------------------------------------------------------- finding 2: cutoff before history
class CutoffViews(Tmp):
    def setUp(self):
        super().setUp()
        self.st = self.store("c")
        for k in range(3):
            B.append(self.st, B.snapshot(T0 + k * 4 * HOUR, f"gh-{k}-1", B.base_contracts()))

    def test_1_cutoff_before_first_observation_is_an_empty_view(self):
        h = P.History(self.st, cutoff=T0 - 1)
        self.assertTrue(h.ok)                                   # the chain itself verifies: not corrupted
        self.assertFalse(h.usable)
        self.assertEqual(h.view_status, (P.HISTORY_EMPTY, P.BEFORE_PIT_HISTORY))
        w = h.window()
        self.assertEqual((w["status"], w["reason"], w["observations"]), (P.HISTORY_EMPTY, P.BEFORE_PIT_HISTORY, 0))
        self.assertIsNone(h.asset_at(T0 + 60, "BTC"))           # unknown to that past
        self.assertEqual(h.identity_at(T0 + 60, "BTC")["state"], P.UNKNOWN)
        self.assertEqual(h.liquidity_at(T0 + 60, "BTC")["state"], P.LIQUIDITY_HISTORY_UNKNOWN)
        self.assertEqual(h.universe_at(T0 + 60, min_vol=1e6)["assets"], {})
        self.assertEqual(h.observation_at(T0 + 60)["state"], P.PIT_UNIVERSE_GAP)
        self.assertEqual(h.intervals("BTC"), [])
        self.assertEqual(h.gaps(), [])

    def test_2_cutoff_exactly_at_first_observation(self):
        h = P.History(self.st, cutoff=T0)
        self.assertTrue(h.usable)
        self.assertEqual(len(h.times), 1)
        self.assertEqual(h.asset_at(T0, "BTC")["state"], P.KNOWN_ACTIVE)

    def test_3_cutoff_between_observations(self):
        h = P.History(self.st, cutoff=T0 + 5 * HOUR)
        self.assertEqual(len(h.times), 2)
        self.assertEqual(h.observation_at(T0 + 9 * HOUR)["observation"]["scan_id"], "gh-1-1")

    def test_4_cutoff_after_final_observation(self):
        h = P.History(self.st, cutoff=T0 + 99 * HOUR)
        self.assertEqual((len(h.times), h.view_status[0]), (3, P.PIT_UNIVERSE_OK))

    def test_5_structurally_broken_history(self):
        os.remove(os.path.join(self.st.root, self.st.paths()[1]))
        h = P.History(self.st, cutoff=T0 - 1)
        self.assertFalse(h.ok)
        self.assertEqual(h.view_status, (P.HISTORY_INTEGRITY_FAILED, P.HISTORY_INTEGRITY_FAILED))
        self.assertEqual(h.asset_at(T0 + 60, "BTC")["state"], P.UNKNOWN)

    def test_6_truly_empty_store(self):
        h = P.History(self.store("empty"))
        self.assertFalse(h.ok)
        self.assertEqual(h.view_status, (P.HISTORY_EMPTY, P.HISTORY_EMPTY))
        self.assertEqual(h.universe_at(T0)["assets"], {})


@unittest.skipUnless(HAVE_NUMPY, "numpy and numba (the CI research-checks job runs these)")
class CutoffVectorised(Tmp):
    def test_every_vectorised_caller_fails_closed(self):
        import numpy as np
        import pit_cost as PC
        import pit_sim as PS
        st = self.store("c")
        for k in range(3):
            B.append(st, B.snapshot(T0 + k * 4 * HOUR, f"gh-{k}-1", B.base_contracts()))
        broken_dir = os.path.join(self.tmp, "broken")
        shutil.copytree(st.root, broken_dir)
        os.remove(os.path.join(broken_dir, H.DirStore(broken_dir).paths()[1]))
        views = {"none": None, "before": P.History(st, cutoff=T0 - 1), "broken": P.History(H.DirStore(broken_dir)),
                 "empty": P.History(self.store("empty"))}
        times = np.array([T0 + 60, T0 + 5 * HOUR])
        for name, h in views.items():
            u = PS.universe_panel(h, times, ["BTC", "ETH"], 1e6)              # no IndexError
            self.assertTrue((u["code"] == PS.U_UNKNOWN).all(), name)
            self.assertFalse(u["complete"].any(), name)
            vol, state, slip, gate = PC.liquidity_panel(h, times, ["BTC"], 1e6)
            self.assertTrue(np.isnan(slip).all() and (gate == -1).all(), name)
            i, fresh = PS._obs_index(h, times)
            self.assertFalse(fresh.any(), name)
        self.assertEqual(PS.view_reason(views["before"]), P.BEFORE_PIT_HISTORY)
        self.assertEqual(PS.view_reason(views["broken"]), P.HISTORY_INTEGRITY_FAILED)
        self.assertEqual(PS.view_reason(views["none"]), "NO_HISTORY")


# --------------------------------------------------------------------------- findings 1 and 2: corrected research
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(HAVE_NUMPY and HAVE_PANDAS, "numpy, numba and pandas (the CI research-checks job runs these)")
class DayPickAuthority(unittest.TestCase):
    """A synthetic full-authority dataset: 34 coins, 160 days (long enough for finite swing scores, so the swing
    score's 25 day-score points, the day 80+ bands and the swing bands are exercised), every coin active, verified
    crypto and $5M a day in the
    point-in-time history every 4 hours (v8.history/2), funding observed at 0 every 8 hours: the historical costs
    equal the legacy assumptions (0.045% taker and 0.05% slippage each way, no funding)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="v8p81_day_")
        cls.coins = ["BTC"] + [f"C{k:02d}" for k in range(33)]
        cls.hours = 24 * 160
        cls.t0 = T0 - 170 * 24 * HOUR
        cls.md = os.path.join(cls.tmp, "md")
        zero = {c: [(cls.t0 + k * 8 * HOUR, 0.0, 8) for k in range(cls.hours // 8 + 2)] for c in cls.coins}
        B.synthetic_md(cls.md, cls.coins, cls.t0, cls.hours, funding=zero, seed=11)
        cls.hist_dir = os.path.join(cls.tmp, "hist")
        st = H.DirStore(cls.hist_dir)
        cs = [B.contract(f"hyperliquid:{c}", c, vol=5e6) for c in cls.coins]
        for k in range(cls.hours // 4 + 1):
            ts = cls.t0 + k * 4 * HOUR
            B.append(st, B.snapshot(ts, f"gh-{k}-1", cs))
        cls.cutoff = cls.t0 + cls.hours * HOUR
        cls.hist = P.History(st, cutoff=cls.cutoff)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def swing_inputs(self, md):
        import pit_research as PR
        from pk_data import factors, regimes
        from pk_score import scores
        _, d = PR._daily_panel(md, self.cutoff)
        SL_, SS_, _, _ = scores(factors(d), regimes(d)[0])
        return d, SL_, SS_

    def test_refactored_pk_day_reproduces_the_frozen_legacy_exactly(self):
        import numpy as np
        import pk_day
        oracle = _load("pk_day_oracle_f142bb1", os.path.join(ORACLE, "pk_day_f142bb1.py"))
        from pk_data import daily_panel, factors, regimes
        from pk_score import scores
        _, d = daily_panel(self.md)
        SL_, SS_, _, _ = scores(factors(d), regimes(d)[0])
        new = pk_day.run(self.md, d["t"], d["coins"], SL_, SS_)
        old = oracle.run(self.md, d["t"], d["coins"], SL_, SS_)
        self.assertEqual(json.dumps(new, sort_keys=True), json.dumps(old, sort_keys=True))
        self.assertGreater(new["long"]["top5"]["n"], 50)
        self.assertTrue(new["long"]["bands"] and new["short"]["bands"])
        # the swing score reaches the day score (its 25 points: the other checks add up to 75 at most)
        p, F, x = pk_day.hourly(self.md)
        surf = pk_day.surfaces(p, F, x, d["t"], d["coins"], SL_, SS_)
        self.assertTrue(any((surf[side]["score"][surf[side]["base"]] > 75).any() for side in ("long", "short")))
        # picks_export's band masks were extracted, not changed
        pe_old = _load("picks_export_oracle_f142bb1", os.path.join(ORACLE, "picks_export_f142bb1.py"))
        import picks_export as pe_new
        rng = np.random.default_rng(5)
        sc = rng.uniform(0, 100, (60, 9))
        sc[rng.random((60, 9)) < 0.1] = np.nan
        R = rng.normal(0, 1, (60, 9))
        R[rng.random((60, 9)) < 0.1] = np.nan
        RET = R / 20
        fw = {"max30": np.where(rng.random((60, 9)) < 0.1, np.nan, rng.normal(0.1, 0.3, (60, 9))),
              "min30": rng.normal(-0.1, 0.2, (60, 9))}
        elig = rng.random((60, 9)) < 0.8
        years = np.repeat(np.array([2024, 2025, 2026]), 20)
        self.assertEqual(json.dumps(pe_new.band_stats(sc, R, RET, fw, elig, years, ((0, 40), (40, 70), (70, 101))),
                                    sort_keys=True),
                         json.dumps(pe_old.band_stats(sc, R, RET, fw, elig, years, ((0, 40), (40, 70), (70, 101))),
                                    sort_keys=True))

    def test_corrected_day_selection_is_exactly_pk_day_and_costs_match_legacy(self):
        import numpy as np
        import pit_research as PR
        import pk_day
        d, SL_, SS_ = self.swing_inputs(self.md)
        rep, surf_l, surf_p, quals = PR.day_research(self.md, self.hist, self.cutoff, d["t"], d["coins"], SL_, SS_)
        for side in ("long", "short"):
            L, Pp = surf_l[side], surf_p[side]
            np.testing.assert_array_equal(L["score"], Pp["score"])                     # scoring
            np.testing.assert_array_equal(L["base"], Pp["base"])                       # 4-hour sample, eligibility
            self.assertEqual([(lo, hi) for lo, hi, _ in L["bands"]], [(lo, hi) for lo, hi, _ in Pp["bands"]])
            for (_, _, ml), (_, _, mp) in zip(L["bands"], Pp["bands"]):
                np.testing.assert_array_equal(ml, mp)                                    # band membership
            self.assertEqual([(k, list(pk)) for k, pk, _ in L["top"]],
                             [(k, list(pk)) for k, pk, _ in Pp["top"]])                  # Top 5 and its ranking
            r = rep[side]
            self.assertEqual(r["base"]["label"], PR.DIAGNOSTIC)
            K = L["R"].shape[0]
            for b in r["bands"]:
                if b["legacy"].get("n", 0) >= 30:
                    q = quals[(side, "band", b["lo"], b["hi"])]
                    comp, auth = b["corrected"]["components"], b["corrected"]["authoritative"]
                    self.assertEqual(comp["n"], b["legacy"]["n"])                        # the same rows, re-costed
                    self.assertTrue(q["fully_qualified"].all())
                    # a row still open at the data end (pk_trades.sim marks it at the last close) is never authoritative
                    opn = ~q["closed"]
                    self.assertTrue((q["k"][opn] + pk_day.HOLD > K - 1).all())
                    self.assertEqual(auth["n"], b["legacy"]["n"] - int(opn.sum()))
                    self.assertEqual(comp["open_at_data_end"], int(opn.sum()))
                    closed_legacy = L["R"][q["k"][~opn], q["j"][~opn]]
                    self.assertAlmostEqual(auth["avg_R"], float(np.mean(closed_legacy)), places=3)
                    np.testing.assert_allclose(q["net_R"], L["R"][q["k"], q["j"]], rtol=0, atol=1e-9)
            t5 = r["top5"]
            self.assertEqual(t5["corrected"]["qualified_samples"], t5["legacy"]["n"])
            self.assertAlmostEqual(t5["corrected"]["authoritative"]["avg_R"], t5["legacy"]["R"], places=3)
            # every selected row: corrected net R equals pk_day's own R (costs equal the legacy assumptions)
            q = quals[(side, "top5")]
            self.assertTrue(q["fully_qualified"].all() and q["closed"].all())          # sampled 24h+ before the end
            np.testing.assert_allclose(q["net_R"], L["R"][q["k"], q["j"]], rtol=0, atol=1e-9)
        # the dataset does reach the data end inside a band: the open-row rule is exercised
        self.assertGreater(sum(int((~q["closed"]).sum()) for key, q in quals.items() if key[1] == "band" and q.get("n")),
                           0)

    def test_swing_bands_are_the_picks_export_surfaces(self):
        import pit_research as PR
        out = PR.picks(self.md, self.hist, self.cutoff)
        reported = closed_only = 0
        for side in ("long", "short"):
            o = out["swing"][side]
            self.assertEqual(o["base"]["label"], PR.SWING_DIAGNOSTIC)
            self.assertNotIn("authoritative", o["base"]["corrected"])               # a diagnostic aggregate only
            self.assertEqual([(b["lo"], b["hi"]) for b in o["bands"]][-1], PR.READY_BAND)
            for b in o["bands"]:
                lg, co = b["legacy"], b["corrected"]
                self.assertEqual(lg["reported_by_picks_export"], lg.get("n", 0) >= 30)
                if lg.get("n", 0) >= 30:                    # full authority: the same rows, re-costed
                    reported += 1
                    comp = co["components"]
                    self.assertEqual((comp["n"], comp["fully_qualified"]), (lg["n"], lg["n"]))
                    # a trade still open at the data end (max30 needs only one later day) is never authoritative
                    self.assertEqual(co["authoritative"]["n"], lg["n"] - comp["open_at_data_end"])
                    if comp["open_at_data_end"] == 0:
                        closed_only += 1
                        self.assertAlmostEqual(co["authoritative"]["avg_R"], lg["R"], places=3)
                else:                                       # picks_export would not report it: never authoritative
                    self.assertEqual(co["authoritative"], {"n": 0})
        self.assertGreater(reported, 1)
        self.assertGreater(closed_only, 1)
        # the ready band repeats the 80-90 and 90+ rows: it is never counted twice in the qualified window
        win = PR.qualified_window({"picks": out, "market_data_1h": {"start": 1, "end": 2}}, {"start": 1, "end": 2})
        expect = sum(b["corrected"]["authoritative"].get("n", 0) for side in ("long", "short")
                     for b in out["swing"][side]["bands"] if (b["lo"], b["hi"]) != PR.READY_BAND)
        expect += sum(b["corrected"]["authoritative"].get("n", 0) for side in ("long", "short")
                      for b in out["day"][side]["bands"])
        self.assertEqual(win["qualified_pick_band_rows"], expect)

    def test_cost_requalification_changes_costs_never_the_selection(self):
        import numpy as np
        import pit_research as PR
        md2 = os.path.join(self.tmp, "md_funded")
        if not os.path.isdir(md2):
            shutil.copytree(self.md, md2)
            for c in self.coins:              # observed funding of 0.03% every 8 hours instead of 0
                with gzip.open(os.path.join(md2, "fund_mexc", f"{c}.csv.gz"), "wt") as fh:
                    fh.write("t,rate,cycle_h\n")
                    for k in range(self.hours // 8 + 2):
                        fh.write(f"{self.t0 + k * 8 * HOUR},0.0003,8\n")
        d, SL_, SS_ = self.swing_inputs(self.md)
        _, sl0, sp0, q0 = PR.day_research(self.md, self.hist, self.cutoff, d["t"], d["coins"], SL_, SS_)
        _, sl1, sp1, q1 = PR.day_research(md2, self.hist, self.cutoff, d["t"], d["coins"], SL_, SS_)
        for side, sgn in (("long", 1), ("short", -1)):
            self.assertEqual([(k, list(pk)) for k, pk, _ in sp0[side]["top"]],
                             [(k, list(pk)) for k, pk, _ in sp1[side]["top"]])
            np.testing.assert_array_equal(sp0[side]["base"], sp1[side]["base"])
            a, b = q0[(side, "top5")], q1[(side, "top5")]
            np.testing.assert_array_equal(a["k"], b["k"])
            np.testing.assert_array_equal(a["j"], b["j"])
            self.assertTrue((sgn * (b["funding"] - a["funding"]) >= 0).all())            # longs pay, shorts receive
            self.assertTrue((np.abs(b["net_R"] - a["net_R"]) > 0).any())

    def test_research_end_to_end_reports_the_governed_surfaces(self):
        import pit_research as PR
        out = PR.run(self.md, self.hist_dir, cutoff=self.cutoff)
        self.assertEqual(out["schema"], "v8.pit-research/2")
        for side in ("long", "short"):
            r = out["picks"]["day"][side]
            self.assertEqual(r["base"]["label"], PR.DIAGNOSTIC)
            self.assertTrue(all(b["label"] == "DAY STRATEGY SURFACE" for b in r["bands"]))
            self.assertGreater(r["top5"]["corrected"]["qualified_samples"], 0)
            self.assertEqual(out["picks"]["swing"][side]["base"]["label"], PR.SWING_DIAGNOSTIC)
        self.assertEqual(out["promotion"].split(":")[0], "NONE")
        self.assertEqual(out["history"]["view_status"], P.PIT_UNIVERSE_OK)

    def test_research_cutoff_before_history_reports_zero_and_never_crashes(self):
        """The production shape: market data up to the cutoff, every history observation after it."""
        import pit_research as PR
        late = os.path.join(self.tmp, "hist_late")
        if not os.path.isdir(late):
            st = H.DirStore(late)
            cs = [B.contract(f"hyperliquid:{c}", c, vol=5e6) for c in self.coins]
            for k in range(3):
                B.append(st, B.snapshot(self.cutoff + (2 + k) * 24 * HOUR, f"gh-late-{k}", cs))
        out = PR.run(self.md, late, cutoff=self.cutoff)
        self.assertEqual((out["history"]["view_status"], out["history"]["view_reason"]),
                         (P.HISTORY_EMPTY, P.BEFORE_PIT_HISTORY))
        self.assertEqual(out["qualified_window"]["qualified_quant_trades"], 0)
        self.assertEqual(out["qualified_window"]["qualified_day_top5_samples"], 0)
        self.assertEqual(out["qualified_window"]["hours"], 0)
        self.assertEqual(out["promotion"].split(":")[0], "NONE")
        for r in out["quant"].values():
            self.assertEqual(r["corrected"]["fully_qualified"], 0)
            self.assertIn(P.BEFORE_PIT_HISTORY, r["legacy"]["why_not_qualified"]["universe"])


# --------------------------------------------------------------------------- finding 4: shadow ledger STATUS provenance
def _reg(eid, **over):
    params = {"look": 30, "id": eid}
    r = {"experiment_id": eid, "registered_at": T0, "registration_commit": "b" * 40, "name": "TSMOM",
         "params": params, "param_hash": SL.param_hash(params), "code_files": ["tools/research/qstrat.py"],
         "code_hash": "c" * 64, "data_cutoff": T0, "evaluation_start": T0 + 1, "evaluation_end": None,
         "universe_history_version": "v8.history/2", "cost_model_version": "v8.pit-cost/2",
         "hypothesis": "h", "primary_metric": "m", "secondary_metrics": [], "pass_rule": "p", "fail_rule": "f",
         "status": "REGISTERED",
         "multiple_testing": {"family": "trend", "variants_tried_before_registration": 1, "variant_ids": [],
                              "selection": "s", "corrections_planned": ["DSR"]}}
    r.update(over)
    return r


def _forge(folder, fname, kind, **fields):
    """Write a record by hand under an arbitrary (possibly lying) file name, chained correctly."""
    recs = SL.load(folder)
    r = SL.record(kind, len(recs) + 1, recs[-1][2] if recs else None, **fields)
    with open(os.path.join(folder, fname), "xb") as fh:
        fh.write(SL.canonical(r))


class ShadowStatusProvenance(Tmp):
    def ledger(self):
        d = os.path.join(self.tmp, "ledger")
        SL.append(d, SL.GENESIS, created_at=T0)
        SL.append(d, SL.REGISTRATION, **_reg("EXP_A"))
        SL.append(d, SL.REGISTRATION, **_reg("EXP_B"))
        return d

    def test_matching_status_passes(self):
        d = self.ledger()
        SL.append(d, SL.STATUS, experiment_id="EXP_A", status="RETIRED", at=T0 + 9)
        self.assertEqual(SL.validate(d), [])
        self.assertEqual(SL.summary(d)["status"], {"EXP_A": "RETIRED", "EXP_B": "REGISTERED"})

    def test_mismatched_status_fails_and_never_reassigns(self):
        d = self.ledger()
        _forge(d, "000004-STATUS-EXP_A.json", SL.STATUS, experiment_id="EXP_B", status="FAILED", at=T0 + 9)
        probs = SL.validate(d)
        self.assertTrue(any("file name id EXP_A differs from the experiment id EXP_B" in p for p in probs), probs)
        self.assertEqual(SL.summary(d)["status"], {"EXP_A": "REGISTERED", "EXP_B": "REGISTERED"})

    def test_retired_experiment_cannot_be_revived_through_a_mismatched_name(self):
        d = self.ledger()
        SL.append(d, SL.STATUS, experiment_id="EXP_B", status="RETIRED", at=T0 + 5)
        _forge(d, "000005-STATUS-EXP_A.json", SL.STATUS, experiment_id="EXP_B", status="RUNNING", at=T0 + 9)
        self.assertTrue(SL.validate(d))
        self.assertEqual(SL.summary(d)["status"]["EXP_B"], "RETIRED")

    def test_unregistered_and_registration_mismatch_still_fail(self):
        d = self.ledger()
        SL.append(d, SL.STATUS, experiment_id="EXP_A", status="RUNNING", at=T0 + 5)
        _forge(d, "000005-STATUS-EXP_C.json", SL.STATUS, experiment_id="EXP_C", status="RUNNING", at=T0 + 9)
        self.assertTrue(any("unregistered experiment EXP_C" in p for p in SL.validate(d)))
        d2 = os.path.join(self.tmp, "ledger2")
        SL.append(d2, SL.GENESIS, created_at=T0)
        _forge(d2, "000002-REGISTRATION-EXP_X.json", SL.REGISTRATION, **_reg("EXP_Y"))
        self.assertTrue(any("file name id differs from the experiment id" in p for p in SL.validate(d2)))
        self.assertEqual(SL.summary(d2)["experiments"], 0)

    def test_guard_rejects_the_bad_commit(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "tools", "v8"))
        shutil.copytree(os.path.join(ROOT, "v8"), os.path.join(repo, "v8"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(ROOT, "tools", "v8", "ledger_guard.py"), os.path.join(repo, "tools", "v8"))
        d = os.path.join(repo, SL.DIR)
        SL.append(d, SL.GENESIS, created_at=T0)
        SL.append(d, SL.REGISTRATION, **_reg("EXP_A"))
        SL.append(d, SL.REGISTRATION, **_reg("EXP_B"))
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        for a in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *a], cwd=repo, check=True, env=env, capture_output=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        guard = [sys.executable, os.path.join(repo, "tools", "v8", "ledger_guard.py"), "--base", base]
        _forge(d, "000004-STATUS-EXP_A.json", SL.STATUS, experiment_id="EXP_B", status="FAILED", at=T0 + 9)
        for a in (["add", "-A"], ["commit", "-qm", "bad status"]):
            subprocess.run(["git", *a], cwd=repo, check=True, env=env, capture_output=True)
        r = subprocess.run(guard, cwd=repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("differs from the experiment id", r.stdout)


# --------------------------------------------------------------------------- versions and isolation
class Versions(unittest.TestCase):
    def test_versions(self):
        from v8 import ENGINE_VERSION, SCHEMA, discovery as DS, identity as ID, provenance
        self.assertEqual((SCHEMA, ENGINE_VERSION), ("v8.audit/7", "v8-phase8.1"))
        self.assertEqual((H.VERSION, H.SCHEMAS, P.VERSION), ("v8.history/2", ("v8.history/1", "v8.history/2"),
                                                             "v8.pit/2"))
        self.assertEqual((ID.VERSION, DS.VERSION, SL.VERSION), ("v8.identity/4", "v8.discovery/1",
                                                               "v8.shadow-ledger/1"))
        self.assertEqual(provenance.identity_config_hash(),
                         "96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c")

    @unittest.skipUnless(HAVE_NUMPY, "numpy")
    def test_research_versions(self):
        import pit_cost as PC
        import pit_sim as PS
        self.assertEqual((PC.VERSION, PS.VERSION), ("v8.pit-cost/2", "v8.pit-research/2"))


class ScanGateInvariants(unittest.TestCase):
    """Critical hotfix invariants, cheap enough for every scan: the writer is v8.history/2 and never rounds liquidity,
    a v1 value never decides a threshold, an empty view is not an error."""

    def test_writer_keeps_precision(self):
        st = H.state_from_snapshot(B.snapshot(T0, "gh-1-1", boundary_contracts([199999.6])))
        self.assertEqual(st["liquidity"]["L0"], ["L0", "KNOWN", 199999.6])
        self.assertEqual(H.VERSION, "v8.history/2")

    def test_v1_never_decides(self):
        self.assertIsNone(P.decides(5e8, P.PRECISION_LOST_V1, 1e6))

    def test_empty_view_is_not_an_error(self):
        h = P.History(H.DirStore(tempfile.mkdtemp(prefix="v8p81_e_")))
        self.assertEqual(h.universe_at(T0)["assets"], {})


if __name__ == "__main__":
    unittest.main()
