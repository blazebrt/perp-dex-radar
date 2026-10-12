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

    def test_no_v2_delta_on_a_v1_checkpoint_and_v2_after_v1_starts_with_liquidity(self):
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
        self.assertTrue(any("v8.history/2 record after a v8.history/1 record must be a checkpoint carrying the full "
                            "liquidity table" in p for p in rep3["problems"]), rep3["problems"])

    def test_an_old_v1_writer_rerun_after_v2_never_breaks_the_history(self):
        """A re-run of a Scan run that started before the hotfix runs the f142bb1 (v8.history/1) writer and appends a
        v1 record after the v2 ones. The branch is append-only: the record is checked by its own schema and counted,
        its liquidity is precision-unqualified, and the next v2 record starts again from a full checkpoint."""
        with open(os.path.join(V1_FIXTURE, "MANIFEST.json")) as fh:
            man = json.load(fh)
        path = os.path.join(V1_FIXTURE, "writer_f142bb1.py")
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertEqual(hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(), man["writer_blob_sha1"])
        old = _load("history_writer_f142bb1", path)
        st = self.v1_copy("rerun")
        cs = boundary_contracts([199999.6, 999999.6])
        B.append(st, B.snapshot(T0 + 6 * HOUR, "gh-104-1", cs))                        # the hotfix writer: v2
        ostore = old.DirStore(st.root)

        def old_run(ts, scan):
            snap = B.snapshot(ts, scan, cs)
            return old.append(ostore, old.scan_content(snap), old.state_from_snapshot(snap), now=ts)

        # an old run re-run 10 minutes after the v2 record: no liquidity due by its clock, so the exact v2 table stands
        t = T0 + 6 * HOUR + 600
        r, obs, _ = old_run(t, "gh-90-2")
        self.assertEqual((r, obs["schema"], obs["state_mode"], obs["liquidity"]),
                         (H.PERSISTED, "v8.history/1", H.CHECKPOINT, None))
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertEqual((rep["schemas"], rep["schema_regressions"]), ({"v8.history/1": 4, "v8.history/2": 1}, 1))
        h = P.History(st)
        self.assertTrue(h.usable)
        self.assertEqual(h.liquidity_at(t + 60, "L0")["precision"], P.PRECISION_REGISTRY_8SIG)
        # another old run hours later writes its rounded table: from then on that liquidity is unknown, not decided
        t2 = t + H.LIQUIDITY_EVERY_S + 600
        r, obs, _ = old_run(t2, "gh-91-2")
        self.assertEqual((r, obs["schema"]), (H.PERSISTED, "v8.history/1"))
        self.assertIsNotNone(obs["liquidity"])
        self.assertTrue(H.verify(st)["ok"])
        h = P.History(st)
        self.assertEqual(h.liquidity_at(t2 + 60, "L0")["precision"], P.PRECISION_LOST_V1)
        self.assertIsNone(h.universe_at(t2 + 60, min_vol=200_000)["assets"]["L0"]["research_eligible"])
        # the hotfix writer recovers at once: a v2 checkpoint with the full table, then v2 deltas again
        _, o5, _ = B.append(st, B.snapshot(t2 + 600, "gh-105-1", cs))
        self.assertEqual((o5["schema"], o5["state_mode"], o5["liquidity"] is not None),
                         ("v8.history/2", H.CHECKPOINT, True))
        _, o6, _ = B.append(st, B.snapshot(t2 + 1200, "gh-106-1", cs))
        self.assertEqual((o6["schema"], o6["state_mode"]), ("v8.history/2", H.DELTA))
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertEqual((rep["schemas"], rep["schema_regressions"]), ({"v8.history/1": 5, "v8.history/2": 3}, 1))
        liq = P.History(st).liquidity_at(t2 + 660, "L0")
        self.assertEqual((liq["value"], liq["precision"]), (199999.6, P.PRECISION_REGISTRY_8SIG))
        # the common case: an old run re-run right after a v2 DELTA (no table) copies that delta's v2 liquidity
        # pointer into its v1 record; the hotfix writer must still write the full table after it
        t3 = t2 + 1800
        r, obs, _ = old_run(t3, "gh-92-2")
        self.assertEqual((r, obs["schema"], obs["liquidity"]), (H.PERSISTED, "v8.history/1", None))
        self.assertEqual((obs["last_liquidity"] or {}).get("schema"), "v8.history/2")
        _, o8, _ = B.append(st, B.snapshot(t3 + 600, "gh-107-1", cs))
        self.assertEqual((o8["schema"], o8["state_mode"], o8["liquidity"] is not None),
                         ("v8.history/2", H.CHECKPOINT, True))
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep["problems"])
        self.assertEqual((rep["schemas"], rep["schema_regressions"]), ({"v8.history/1": 6, "v8.history/2": 4}, 2))

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
        # this dataset's funding is observed at exactly 0 every 8 hours: the corrected signal is 0.0 (evidence) while
        # the legacy panel reads an all-zero series as none and assumes 0.01% per 8 hours; both pass both funding
        # rules (long <= 0.0001, short >= 0), so the selection coincides on every sampled hour (before the first
        # sample the legacy input is still NaN for a few hours - never sampled)
        F0 = pk_day.FIRST
        _, _, xh = pk_day.hourly(self.md, end=self.cutoff)
        self.assertTrue(np.allclose(xh["funding"][F0:], 0.0001))
        for side in ("long", "short"):
            rows = rep[side]["funding_signal_rows"]
            self.assertEqual((rows["unknown_excluded"], rows["top5_samples_undetermined"]), (0, 0))
            self.assertGreater(rows["observed_settlement"], 0)
        for side in ("long", "short"):
            L, Pp = surf_l[side], surf_p[side]
            np.testing.assert_array_equal(L["score"][F0:], Pp["score"][F0:])           # scoring
            np.testing.assert_array_equal(L["base"], Pp["base"])                       # 4-hour sample, eligibility
            self.assertEqual([(lo, hi) for lo, hi, _ in L["bands"]], [(lo, hi) for lo, hi, _ in Pp["bands"]])
            for (_, _, ml), (_, _, mp) in zip(L["bands"], Pp["bands"]):
                np.testing.assert_array_equal(ml, mp)                                    # band membership
            self.assertEqual([(k, list(pk)) for k, pk, _ in L["top"]],
                             [(k, list(pk)) for k, pk, _ in Pp["top"]])                  # Top 5 and its ranking
            r = rep[side]
            self.assertEqual(r["base"]["label"], PR.DIAGNOSTIC)
            self.assertNotIn("authoritative", r["base"]["corrected"])                  # a diagnostic aggregate only
            for b in r["bands"]:
                if b["legacy"].get("n", 0) >= 30:
                    q = quals[(side, "band", b["lo"], b["hi"])]
                    comp, auth = b["corrected"]["components"], b["corrected"]["authoritative"]
                    self.assertTrue(q["fully_qualified"].all())
                    # the same rows, re-costed; pk_trades.sim leaves no result for a trade still open at the data end,
                    # so every row is a closed trade and the authoritative aggregate is pk_day's own
                    self.assertEqual((comp["n"], auth["n"], comp["open_at_data_end"]), (b["legacy"]["n"],) * 2 + (0,))
                    self.assertAlmostEqual(auth["avg_R"], b["legacy"]["R"], places=3)
                    np.testing.assert_allclose(q["net_R"], L["R"][q["k"], q["j"]], rtol=0, atol=1e-9)
            t5 = r["top5"]
            self.assertEqual(t5["corrected"]["qualified_samples"], t5["legacy"]["n"])
            self.assertAlmostEqual(t5["corrected"]["authoritative"]["avg_R"], t5["legacy"]["R"], places=3)
            # every selected row: corrected net R equals pk_day's own R (costs equal the legacy assumptions)
            q = quals[(side, "top5")]
            self.assertTrue(q["fully_qualified"].all() and q["closed"].all())
            np.testing.assert_allclose(q["net_R"], L["R"][q["k"], q["j"]], rtol=0, atol=1e-9)
        # rows sampled in the last day of data are in the bands (a trade that hit its stop on the last bar is closed)
        K = surf_l["long"]["R"].shape[0]
        self.assertTrue(any((q["k"] + pk_day.HOLD > K - 1).any() for key, q in quals.items()
                            if key[1] == "band" and q.get("n")))

    def test_swing_bands_are_the_picks_export_surfaces(self):
        import pit_research as PR
        out = PR.picks(self.md, self.hist, self.cutoff)
        reported = 0
        for side in ("long", "short"):
            o = out["swing"][side]
            self.assertEqual(o["base"]["label"], PR.SWING_DIAGNOSTIC)
            self.assertNotIn("authoritative", o["base"]["corrected"])               # a diagnostic aggregate only
            self.assertEqual([(b["lo"], b["hi"]) for b in o["bands"]][-1], PR.READY_BAND)
            for b in o["bands"]:
                lg, co = b["legacy"], b["corrected"]
                self.assertEqual(lg["reported_by_picks_export"], lg.get("n", 0) >= 30)
                if lg.get("n", 0) >= 30:                    # full authority: the same rows, re-costed, all closed
                    reported += 1
                    comp = co["components"]
                    self.assertEqual((comp["n"], comp["fully_qualified"], comp["open_at_data_end"]),
                                     (lg["n"], lg["n"], 0))
                    self.assertEqual(co["authoritative"]["n"], lg["n"])
                    self.assertAlmostEqual(co["authoritative"]["avg_R"], lg["R"], places=3)
                else:                                       # picks_export would not report it: never authoritative
                    self.assertEqual(co["authoritative"], {"n": 0})
        self.assertGreater(reported, 1)
        # the ready band repeats the 80-90 and 90+ rows: it is never counted twice in the qualified window
        win = PR.qualified_window({"picks": out, "market_data_1h": {"start": 1, "end": 2}}, {"start": 1, "end": 2})
        expect = sum(b["corrected"]["authoritative"].get("n", 0) for side in ("long", "short")
                     for b in out["swing"][side]["bands"] if (b["lo"], b["hi"]) != PR.READY_BAND)
        expect += sum(b["corrected"]["authoritative"].get("n", 0) for side in ("long", "short")
                      for b in out["day"][side]["bands"])
        self.assertEqual(win["qualified_pick_band_rows"], expect)

    # ------------------------------------------------------------------ the corrected day score's funding input
    RATES = (-0.0002, -0.00005, 0.00005, 0.00015, 0.0003)   # nonzero, on both sides of both funding rules

    def md_variant(self, name, rate_of):
        """This dataset with other funding files: rate_of(j, k) is coin j's k-th 8-hour settlement (None: none
        recorded). Candles and the point-in-time history are unchanged."""
        path = os.path.join(self.tmp, name)
        if not os.path.isdir(path):
            shutil.copytree(self.md, path, ignore=shutil.ignore_patterns("fund_mexc"))
            os.makedirs(os.path.join(path, "fund_mexc"))
            for j, c in enumerate(self.coins):
                with gzip.open(os.path.join(path, "fund_mexc", f"{c}.csv.gz"), "wt") as fh:
                    fh.write("t,rate,cycle_h\n")
                    for k in range(self.hours // 8 + 2):
                        r = rate_of(j, k)
                        if r is not None:
                            fh.write(f"{self.t0 + k * 8 * HOUR},{r!r},8\n")
        return path

    def rate(self, j, k):
        return self.RATES[(7 * j + 3 * k) % 5]

    def signals(self, md):
        """(legacy funding input, corrected signal, known, code) on the research's hourly grid."""
        import pit_cost as PC
        import pit_research as PR
        import pk_day
        ph, _, xh = pk_day.hourly(md, end=self.cutoff)
        self.assertEqual(int(ph.t[0]), self.t0)
        frh, fsh, _ = PC.funding_panel(md, ph.t, ph.coins, cutoff=self.cutoff)
        return (xh["funding"],) + PR.funding_signal(frh, fsh)

    def research(self, md):
        import pit_research as PR
        d, SL_, SS_ = self.swing_inputs(md)
        return PR.day_research(md, self.hist, self.cutoff, d["t"], d["coins"], SL_, SS_)

    def same_selection(self, a, b):
        import numpy as np
        np.testing.assert_array_equal(a["score"], b["score"])
        np.testing.assert_array_equal(a["base"], b["base"])
        self.assertEqual([(lo, hi) for lo, hi, _ in a["bands"]], [(lo, hi) for lo, hi, _ in b["bands"]])
        for (_, _, ma), (_, _, mb) in zip(a["bands"], b["bands"]):
            np.testing.assert_array_equal(ma, mb)
        self.assertEqual([(k, list(pk)) for k, pk, _ in a["top"]], [(k, list(pk)) for k, pk, _ in b["top"]])

    def test_observed_funding_full_authority_reproduces_legacy_selection(self):
        """Every settlement observed, nonzero, from the first hour to the end: the corrected input equals the legacy
        input exactly, so the corrected score, bands and Top 5 are pk_day's own; the costs differ by exactly the
        observed funding."""
        import numpy as np
        import pk_day
        from pk_trades import COST
        md = self.md_variant("md_obs", self.rate)
        legacy, sig, known, _ = self.signals(md)
        self.assertTrue(known.all())
        np.testing.assert_array_equal(sig, legacy)
        self.assertTrue((sig <= 0.0001).any() and (sig > 0.0001).any() and (sig < 0).any())
        rep, surf_l, surf_p, quals = self.research(md)
        _, _, xh = pk_day.hourly(md, end=self.cutoff)
        for side in ("long", "short"):
            self.same_selection(surf_l[side], surf_p[side])
            self.assertEqual(surf_p[side]["undetermined"], [])
            self.assertEqual(rep[side]["funding_signal_rows"]["unknown_excluded"], 0)
            q = quals[(side, "top5")]
            L = surf_l[side]
            np.testing.assert_allclose(q["cost"] - q["funding"], COST, atol=1e-12)           # fees + slippage
            np.testing.assert_allclose(q["net_ret"], L["RET"][q["k"], q["j"]] - q["funding"], atol=1e-12)
            self.assertTrue((q["funding"] != 0).any())
        # the legacy oracle on this dataset is unchanged too
        oracle = _load("pk_day_oracle_obs", os.path.join(ORACLE, "pk_day_f142bb1.py"))
        from pk_data import daily_panel, factors, regimes
        from pk_score import scores
        _, d = daily_panel(md)
        SL_, SS_, _, _ = scores(factors(d), regimes(d)[0])
        self.assertEqual(json.dumps(pk_day.run(md, d["t"], d["coins"], SL_, SS_), sort_keys=True),
                         json.dumps(oracle.run(md, d["t"], d["coins"], SL_, SS_), sort_keys=True))

    def test_funding_before_the_first_observation_is_unknown_and_never_selected(self):
        """Funding recorded only from some hour after the first sample: the legacy input carries the assumed 0.01%
        per 8 hours before it; the corrected input is unknown there, so no corrected base, band or Top-5 row."""
        import numpy as np
        import pk_day
        start_k = (pk_day.FIRST + 240) // 8
        first = start_k * 8                                          # the first observed hour
        md = self.md_variant("md_late", lambda j, k: self.rate(j, k) if k >= start_k else None)
        legacy, sig, known, code = self.signals(md)
        F0 = pk_day.FIRST
        self.assertTrue(np.allclose(legacy[F0:first], 0.0001))                 # LEGACY: the assumption
        self.assertTrue(np.isnan(sig[:first]).all() and not known[:first].any())
        self.assertTrue(known[first:].all())
        np.testing.assert_array_equal(sig[first:], legacy[first:])
        rep, surf_l, surf_p, _ = self.research(md)
        for side in ("long", "short"):
            L, Pp = surf_l[side], surf_p[side]
            self.assertTrue(L["base"][F0:first].any())                         # legacy selects on the assumption
            self.assertFalse(Pp["base"][:first].any())                         # corrected never does
            for _, _, m in Pp["bands"]:
                self.assertFalse(m[:first].any())
            self.assertTrue(all(k >= first for k, _, _ in Pp["top"]))
            before = sorted(k for k, _, _ in L["top"] if k < first)
            self.assertTrue(before)
            self.assertEqual(sorted(k for k in Pp["undetermined"] if k < first), before)
            rows = rep[side]["funding_signal_rows"]
            self.assertGreater(rows["unknown_excluded"], 0)
            self.assertEqual(rows["top5_samples_undetermined"], len(Pp["undetermined"]))
            # after the first observation the corrected selection is pk_day's own again
            np.testing.assert_array_equal(L["base"][first:], Pp["base"][first:])

    def gap_md(self):
        """Coins 0-9: 9 settlements never recorded (a gap); coins 10-14: 6 settlements recorded at exactly 0."""
        import pk_day
        g0 = (pk_day.FIRST + 400) // 8
        g1, z0 = g0 + 9, (pk_day.FIRST + 800) // 8
        z1 = z0 + 6

        def rate_of(j, k):
            if j < 10 and g0 <= k < g1:
                return None
            if 10 <= j < 15 and z0 <= k < z1:
                return 0.0
            return self.rate(j, k)

        return self.md_variant("md_gap", rate_of), (g0, g1, z0, z1)

    def test_funding_gap_is_unknown_until_the_next_settlement_and_zero_is_evidence(self):
        import numpy as np
        md, (g0, g1, z0, z1) = self.gap_md()
        legacy, sig, known, code = self.signals(md)
        a, b = g0 * 8, g1 * 8                                        # the first missed due hour, the next settlement
        for j in range(10):
            self.assertTrue(known[a - 1, j])                         # NOT_DUE before the missed settlement: carried
            self.assertEqual(sig[a - 1, j], self.rate(j, g0 - 1))
            self.assertFalse(known[a:b, j].any())                    # unknown from the missed due time
            self.assertTrue(np.isnan(sig[a:b, j]).all())
            self.assertTrue(np.allclose(legacy[a:b, j], self.rate(j, g0 - 1)))   # LEGACY carries it through the gap
            self.assertTrue(known[b, j])                             # authority resumes at the next settlement
            self.assertEqual(sig[b, j], self.rate(j, g1))
        za, zb = z0 * 8, z1 * 8
        for j in range(10, 15):
            self.assertTrue(known[za:zb, j].all())
            self.assertTrue((sig[za:zb, j] == 0.0).all())            # exactly 0.0, never NaN or the older rate
            self.assertTrue(np.allclose(legacy[za:zb, j], self.rate(j, z0 - 1)))  # LEGACY reads 0 as none
            self.assertEqual(sig[zb, j], self.rate(j, z1))
        rep, surf_l, surf_p, _ = self.research(md)
        for side in ("long", "short"):
            Pp = surf_p[side]
            self.assertFalse(Pp["base"][a:b, :10].any())             # nothing selected on an unknown input
            self.assertTrue(Pp["base"][b:, :10].any())               # selected again after the gap
            self.assertTrue(Pp["base"][za:zb, 10:15].any())          # an observed 0 is a known input
            for k, pk, _ in Pp["top"]:
                if a <= k < b:
                    self.assertFalse(set(int(j) for j in pk) & set(range(10)))
            self.assertGreater(rep[side]["funding_signal_rows"]["unknown_excluded"], 0)

    def test_funding_is_a_selection_input(self):
        """Funding is a day-score input (DAY_W 5 points): observed funding of 0.03% instead of 0 fails the long rule
        (funding <= 0.0001) and moves long rows across score bands; the short rule (funding >= 0) passes both."""
        import numpy as np
        import pk_day
        md2 = self.md_variant("md_funded", lambda j, k: 0.0003)
        _, sp0 = self.research(self.md)[1:3]
        _, sp1 = self.research(md2)[1:3]
        F0 = pk_day.FIRST
        d_long = sp0["long"]["score"][F0:] - sp1["long"]["score"][F0:]
        self.assertTrue(np.allclose(d_long, 5.0))
        np.testing.assert_array_equal(sp0["short"]["score"], sp1["short"]["score"])
        moved = any((m0 != m1).any() for (_, _, m0), (_, _, m1) in zip(sp0["long"]["bands"], sp1["long"]["bands"]))
        self.assertTrue(moved or [x[:2] for x in sp0["long"]["bands"]] != [x[:2] for x in sp1["long"]["bands"]])

    def test_cost_only_change_and_scenario_funding_never_change_the_selection(self):
        """The same observed funding signal, a different cost interpretation (the scenario's assumed 0.01% per 8
        hours where MISSING, added to the cost panel): the corrected score, bands and Top 5 are unchanged; only
        costs differ. Filling the signal itself with the assumption would change the selection."""
        import numpy as np
        from unittest import mock
        import pit_cost as PC
        import pit_research as PR
        import pk_day
        md, _ = self.gap_md()
        real = PC.funding_panel

        def with_scenario(md_, t, coins, bar=3600, cutoff=None):
            rate, state, src = real(md_, t, coins, bar=bar, cutoff=cutoff)
            return rate + PC.scenario_funding(t, state, bar), state, src

        rep0, sl0, sp0, q0 = self.research(md)
        with mock.patch.object(PC, "funding_panel", with_scenario):
            rep1, sl1, sp1, q1 = self.research(md)
        changed = 0
        for side in ("long", "short"):
            self.same_selection(sp0[side], sp1[side])
            self.assertEqual(sp0[side]["undetermined"], sp1[side]["undetermined"])
            for key in q0:
                if key[0] == side and q0[key].get("n"):
                    np.testing.assert_array_equal(q0[key]["k"], q1[key]["k"])
                    np.testing.assert_array_equal(q0[key]["j"], q1[key]["j"])
                    changed += int((q0[key]["funding"] != q1[key]["funding"]).sum())
        self.assertGreater(changed, 0)                                         # the costs did change
        # the counterfactual: an assumption injected into the corrected signal WOULD move the score
        ph, Fh, xh = pk_day.hourly(md, end=self.cutoff)
        rate, state, _ = real(md, ph.t, ph.coins, cutoff=self.cutoff)
        sig, known, _ = PR.funding_signal(rate + PC.scenario_funding(ph.t, state), state)
        sig0, known0, _ = PR.funding_signal(rate, state)
        np.testing.assert_array_equal(sig, sig0)
        np.testing.assert_array_equal(known, known0)
        filled = dict(xh, funding=np.where(known0, sig0, 0.0001))
        d, SL_, SS_ = self.swing_inputs(md)
        naive = pk_day.surfaces(ph, Fh, filled, d["t"], d["coins"], SL_, SS_)
        self.assertTrue((naive["long"]["score"] != sp0["long"]["score"]).any())

    def test_research_end_to_end_reports_the_governed_surfaces(self):
        import pit_research as PR
        out = PR.run(self.md, self.hist_dir, cutoff=self.cutoff)
        self.assertEqual(out["schema"], "v8.pit-research/3")
        fs = out["picks"]["day"]["funding_signal"]
        self.assertEqual((fs["legacy"]["label"], fs["corrected"]["authority"], fs["corrected"]["version"],
                          fs["scenario"]["label"]),
                         (PR.LEGACY, "OBSERVED_SETTLEMENTS_ONLY", "v8.pit-research/3", PR.SCENARIO))
        self.assertIn("picks day funding signal", PR.text(out))
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


# --------------------------------------------------------------------------- the corrected day score's funding input
def fake_day(T, N, funding):
    """Constructed day-pick inputs for pk_day.surfaces: every row eligible with a result; by default each long row
    passes trend1d, trend4h, trend1h, near_edge, no_chase, calm (10 each) and trend30 (5) = 65 points, fails volume,
    no swing score, and its funding check decides 5 more points (long funding <= 0.0001)."""
    import types
    import numpy as np
    full = (lambda v: np.full((T, N), v, dtype=float))
    p = types.SimpleNamespace(t=1_790_006_400 + np.arange(T, dtype=np.int64) * HOUR, c=full(1.0),
                              coins=[f"C{j:02d}" for j in range(N)])
    F = types.SimpleNamespace(elig=np.ones((T, N), dtype=bool))
    x = {"trend1d": full(0.1), "trend4h": full(0.1), "ema9_21": full(0.1), "brk24": full(0.0), "r4h": full(0.0),
         "atrp": full(0.01), "dd30d": full(0.0), "vol24_7d": full(0.5), "dist_low24": full(0.5),
         "funding": np.broadcast_to(np.asarray(funding, dtype=float), (T, N)).copy()}
    R = full(0.1)
    sims = {"long": (R, R / 20, full(1.0)), "short": (R, R / 20, full(1.0))}
    return p, F, x, sims


@unittest.skipUnless(HAVE_NUMPY, "numpy and numba (the CI research-checks job runs these)")
class FundingSignalAuthority(unittest.TestCase):
    """The observed-only funding signal of the corrected day score (pit_research.funding_signal) and the corrected
    selection built on it (pk_day.surfaces with `known`), on constructed inputs."""

    def surfaces(self, p, F, x, sims, known=None, elig=None):
        import numpy as np
        import pk_day
        return pk_day.surfaces(p, F, x, np.array([0]), [], np.zeros((1, 0)), np.zeros((1, 0)), elig=elig,
                               sims=sims, known=known)

    def test_signal_states(self):
        import numpy as np
        import pit_cost as PC
        import pit_research as PR
        t0 = 1_790_006_400                                          # an 8-hour boundary
        t = t0 + np.arange(90) * HOUR
        ser = [(t0 + 16 * HOUR, 0.0002, 8.0), (t0 + 24 * HOUR, 0.0, 8.0), (t0 + 32 * HOUR, -0.0001, 8.0),
               (t0 + 64 * HOUR, 0.00005, 8.0), (t0 + 72 * HOUR, 0.00015, 8.0)]     # 40, 48, 56 never recorded
        rate, state = PC.funding_panel_from_series(t, ser)
        sig, known, code = PR.funding_signal(rate[:, None], state[:, None])
        sig, known, code = sig[:, 0], known[:, 0], code[:, 0]
        expect = {h: np.nan for h in range(90)}
        expect.update({h: 0.0002 for h in range(16, 24)})
        expect.update({h: 0.0 for h in range(24, 32)})
        expect.update({h: -0.0001 for h in range(32, 40)})
        expect.update({h: 0.00005 for h in range(64, 72)})
        expect.update({h: 0.00015 for h in range(72, 80)})
        np.testing.assert_array_equal(sig, np.array([expect[h] for h in range(90)]))
        np.testing.assert_array_equal(known, ~np.isnan(sig))
        self.assertFalse(known[:16].any())                          # before the first observation: unknown
        self.assertTrue(known[24] and sig[24] == 0.0)               # an observed 0 is exactly 0.0 and known
        self.assertFalse(known[40:64].any())                        # from the first missed due hour to the next one
        self.assertFalse(known[80:].any())                          # after the last settlement's cycle
        self.assertEqual([int(h) for h in np.where(code == PR.SIG_OBSERVED)[0]], [16, 24, 32, 64, 72])
        self.assertTrue((code[[17, 23, 25, 39, 65, 79]] == PR.SIG_CARRIED).all())
        # the scenario's assumed 0.01% per 8 hours (only where MISSING) never reaches the signal
        scen = PC.scenario_funding(t, state[:, None])[:, 0]
        self.assertGreater(np.count_nonzero(scen), 0)
        s2, k2, _ = PR.funding_signal((rate + scen)[:, None], state[:, None])
        np.testing.assert_array_equal(s2[:, 0], sig)
        np.testing.assert_array_equal(k2[:, 0], known)

    def test_score_boundary_unknown_funding_never_authoritative(self):
        """The funding check's 5 points move a 65-point long row across the 70 band boundary. LEGACY: the assumed
        0.0001 passes, so every row sits in 70-80. Corrected: an unknown row enters no base or band at all; an
        observed 0.0002 fails (50-70); an observed 0.0 passes (70-80)."""
        import numpy as np
        import pk_day
        T, N = pk_day.FIRST + pk_day.HOLD + 40, 39
        p, F, x, sims = fake_day(T, N, 0.0001)                       # the legacy input: the assumption
        legacy = self.surfaces(p, F, x, sims)["long"]
        self.assertEqual([(lo, hi) for lo, hi, _ in legacy["bands"]], [(70, 80)])
        self.assertTrue(legacy["bands"][0][2][:, :13].any())        # the unknown coins, in 70-80 on the assumption
        sig = np.full((T, N), np.nan)
        sig[:, 13:26], sig[:, 26:] = 0.0002, 0.0                    # coins 0-12 unknown
        known = ~np.isnan(sig)
        corrected = self.surfaces(p, F, dict(x, funding=sig), sims, known=known, elig=F.elig)["long"]
        bands = {(lo, hi): m for lo, hi, m in corrected["bands"]}
        self.assertEqual(sorted(bands), [(50, 70), (70, 80)])
        self.assertFalse(corrected["base"][:, :13].any())
        for m in bands.values():
            self.assertFalse(m[:, :13].any())                       # never an authoritative row
        self.assertTrue(bands[(50, 70)][:, 13:26].any() and not bands[(50, 70)][:, 26:].any())
        self.assertTrue(bands[(70, 80)][:, 26:].any() and not bands[(70, 80)][:, 13:26].any())
        self.assertTrue((corrected["score"][:, 26:] == 70).all())   # the observed 0.0 passes: 65 + 5

    def test_top5_follows_observed_funding_and_unknown_candidates_can_block_it(self):
        import numpy as np
        import pk_day
        T, N = pk_day.FIRST + pk_day.HOLD + 40, 40
        leg = np.full((T, N), 0.0005)
        leg[:, :5] = 0.00005                                         # LEGACY: coins 0-4 pass the long rule
        p, F, x, sims = fake_day(T, N, leg)
        legacy = self.surfaces(p, F, x, sims)["long"]
        obs = np.full((T, N), 0.0005)
        obs[:, 5:10] = 0.0                                           # observed: coins 5-9 pass, 0-4 fail
        known = np.ones((T, N), dtype=bool)
        known[:, 39] = False                                         # unknown, low score: can never reach the Top 5
        x["trend1d"][:, 39] = x["trend4h"][:, 39] = x["ema9_21"][:, 39] = -0.1
        k0 = pk_day.FIRST
        known[k0, 38] = False                                        # unknown at the first sample, high score: 70 + 5
        x["vol24_7d"][k0, 38] = 2.0
        sig = np.where(known, obs, np.nan)
        corrected = self.surfaces(p, F, dict(x, funding=sig), sims, known=known, elig=F.elig)["long"]
        self.assertEqual(corrected["undetermined"], [k0])
        samples = [k for k, _, _ in legacy["top"] if k != k0]
        self.assertTrue(samples)
        for k, pk, _ in legacy["top"]:
            if k != k0:
                self.assertEqual(sorted(int(j) for j in pk), [0, 1, 2, 3, 4])
        self.assertEqual([k for k, _, _ in corrected["top"]], samples)
        for k, pk, _ in corrected["top"]:
            self.assertEqual(sorted(int(j) for j in pk), [5, 6, 7, 8, 9])   # the observed values decide

    def test_fewer_than_five_known_candidates_is_undetermined_and_nan_is_no_evidence(self):
        import numpy as np
        import pit_cost as PC
        import pit_research as PR
        import pk_day
        T, N = pk_day.FIRST + pk_day.HOLD + 40, 40
        p, F, x, sims = fake_day(T, N, 0.0)
        known = np.zeros((T, N), dtype=bool)
        known[:, :4] = True                                          # four known candidates only
        corrected = self.surfaces(p, F, dict(x, funding=np.where(known, 0.0, np.nan)), sims, known=known,
                                  elig=F.elig)["long"]
        self.assertEqual(corrected["top"], [])
        self.assertEqual(corrected["undetermined"], list(range(pk_day.FIRST, T - pk_day.HOLD, pk_day.EVERY)))
        none = self.surfaces(p, F, dict(x, funding=np.full((T, N), np.nan)), sims, known=np.zeros((T, N), bool),
                             elig=F.elig)["long"]
        self.assertEqual((none["top"], none["bands"]), ([], []))
        self.assertFalse(none["base"].any())
        # a recorded rate that is not a number is no evidence
        rate = np.array([[0.0001], [np.nan], [0.0]])
        state = np.array([[PC.F_OBSERVED], [PC.F_OBSERVED], [PC.F_OBSERVED_ZERO]], dtype=np.int8)
        sig, kn, code = PR.funding_signal(rate, state)
        self.assertEqual(kn[:, 0].tolist(), [True, False, True])
        self.assertTrue(np.isnan(sig[1, 0]) and sig[2, 0] == 0.0)
        self.assertEqual(int(code[1, 0]), PR.SIG_UNKNOWN)

    def test_all_known_equals_the_legacy_surfaces(self):
        """Known everywhere and the same input: the corrected path is the legacy selection exactly."""
        import numpy as np
        import pk_day
        T, N = pk_day.FIRST + pk_day.HOLD + 40, 40
        rng = np.random.default_rng(3)
        p, F, x, sims = fake_day(T, N, rng.choice([-0.0002, 0.0, 0.00005, 0.0003], size=(T, N)))
        x["vol24_7d"] = rng.choice([0.5, 2.0], size=(T, N))
        a = self.surfaces(p, F, x, sims)
        b = self.surfaces(p, F, x, sims, known=np.ones((T, N), dtype=bool), elig=F.elig)
        for side in ("long", "short"):
            np.testing.assert_array_equal(a[side]["score"], b[side]["score"])
            np.testing.assert_array_equal(a[side]["base"], b[side]["base"])
            self.assertEqual([(lo, hi) for lo, hi, _ in a[side]["bands"]],
                             [(lo, hi) for lo, hi, _ in b[side]["bands"]])
            self.assertEqual([(k, list(pk)) for k, pk, _ in a[side]["top"]],
                             [(k, list(pk)) for k, pk, _ in b[side]["top"]])
            self.assertEqual(b[side]["undetermined"], [])
            self.assertNotIn("undetermined", a[side])               # the legacy surfaces are unchanged


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
        import pit_research as PR
        self.assertEqual((PC.VERSION, PS.VERSION, PR.VERSION), ("v8.pit-cost/2", "v8.pit-research/3",
                                                                "v8.pit-research/3"))


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
