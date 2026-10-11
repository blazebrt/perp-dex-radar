"""v8 Phase 8: point-in-time history and research correctness.

    Historical research may use only information that was actually knowable at that historical time.

Standard library only, except the classes marked NUMPY (the research cost and simulation modules), which run where
numpy and numba are installed (the CI research-checks job runs this module there too)."""
from __future__ import annotations

import copy
import glob
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from v8 import history as H  # noqa: E402
from v8 import pit as P  # noqa: E402
from v8 import shadow_ledger as SL  # noqa: E402

try:
    import numpy as np  # noqa: F401
    import numba  # noqa: F401
    HAVE_NUMPY = True
except ImportError:          # the unit-test job has no numpy; the research-checks job runs these
    HAVE_NUMPY = False

T0 = 1_791_000_000          # a fixed observation time (UTC)
HOUR = 3600
VENUES_OK = {"hyperliquid": {"ok": True, "raw": 10}, "lighter": {"ok": True, "raw": 10},
             "aster": {"ok": True, "raw": 10}, "edgex": {"ok": True, "raw": 10}}


def contract(cid, asset, active=True, legacy="SELECTED", vol=5e6, exposure=None, exp_state="VERIFIED_CRYPTO"):
    venue = cid.split(":")[0]
    return {"id": cid, "venue": venue, "asset": asset, "type": "perp", "active": active, "legacy": legacy,
            "vol": vol, "exposure": exposure or f"{asset}#1", "exp_state": exp_state}


def asset(state="VERIFIED_CRYPTO", legacy="CRYPTO"):
    return {"legacy": legacy, "identity": {"state": state, "decision": "CRYPTO" if "CRYPTO" in state else "TRADFI",
                                           "reason": "TEST", "authority": "TICKER_LIST"}}


def snapshot(ts, scan_id, contracts, assets=None, venues=None, fallback=False, columns=True):
    """A minimal audit snapshot with what the history reads."""
    assets = assets if assets is not None else {c["asset"]: asset() for c in contracts}
    venues = copy.deepcopy(venues if venues is not None else VENUES_OK)
    if columns:
        fields = ["id", "venue", "asset", "type", "active", "legacy", "vol", "exposure", "exp_state"]
        reg_c = {"fields": fields, "rows": [[c.get(f) for f in fields] for c in contracts]}
    else:
        reg_c = contracts
    return {"schema": "v8.audit/6",
            "manifest": {"schema": "v8.audit/6", "audit_version": "v8-phase8.0", "identity_version": "v8.identity/4",
                         "identity_config_hash": "96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c",
                         "discovery_version": "v8.discovery/1", "liquidity_version": "v8.liquidity/1",
                         "scan_id": scan_id, "ts": ts, "git_sha": "a" * 40, "config_hashes": {},
                         "data_sources": {"fallback_universe": fallback,
                                          "dex_market_lists": {k: v["ok"] for k, v in venues.items()}}},
            "registry": {"contracts": reg_c, "assets": assets},
            "data_health": {"registry_venues": venues}}


def base_contracts():
    return [contract("hyperliquid:BTC", "BTC", vol=5e8), contract("lighter:BTC", "BTC", vol=1e8),
            contract("hyperliquid:ETH", "ETH", vol=2e8), contract("aster:OLDCOIN", "OLDCOIN", vol=3e6),
            contract("edgex:EDGEONLY", "EDGEONLY", vol=2e6), contract("hyperliquid:SMALL", "SMALL", vol=150_000)]


def append(store, snap, now=None, **kw):
    return H.append(store, H.scan_content(snap), H.state_from_snapshot(snap), now=now or snap["manifest"]["ts"], **kw)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v8p8_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def store(self, name="h"):
        return H.DirStore(os.path.join(self.tmp, name))


def world(tmp):
    """A history of six scans 4 hours apart: OLDCOIN delisted at scan 3, NEWCOIN listed at scan 4, MAYBE's identity
    upgraded at scan 4, edgex unavailable at scan 5 (EDGEONLY unknown, not delisted), RELIST off at 2 and back at 5."""
    st = H.DirStore(os.path.join(tmp, "world"))
    cs = base_contracts() + [contract("lighter:MAYBE", "MAYBE", vol=4e6), contract("aster:RELIST", "RELIST", vol=2e6)]
    for k in range(6):
        c = copy.deepcopy(cs)
        assets = {x["asset"]: asset() for x in c}
        assets["MAYBE"] = asset("UNVERIFIED", "UNVERIFIED") if k < 3 else asset()
        venues = copy.deepcopy(VENUES_OK)
        if k >= 2:
            c = [x for x in c if x["asset"] != "OLDCOIN"] + [contract("aster:OLDCOIN", "OLDCOIN", active=False,
                                                                       legacy="DELISTED", vol=None)]
        if k >= 3:
            c.append(contract("hyperliquid:NEWCOIN", "NEWCOIN", vol=9e6))
            assets["NEWCOIN"] = asset()
        if k == 4:
            venues["edgex"] = {"ok": False, "raw": 0}
            c = [x for x in c if x["venue"] != "edgex"]
        if k in (1, 2, 3):
            c = [x for x in c if x["asset"] != "RELIST"]
        assets = {a: v for a, v in assets.items() if any(x["asset"] == a for x in c)}
        r = append(st, snapshot(T0 + k * 4 * HOUR, f"gh-{k}-1", c, assets, venues))
        assert r[0] == H.PERSISTED, r
    return st


# --------------------------------------------------------------------------- the history (append-only, chained)
class HistoryStore(Tmp):
    def test_checkpoint_then_deltas_and_verify(self):
        st = self.store()
        s0 = snapshot(T0, "gh-1-1", base_contracts())
        self.assertEqual(append(st, s0)[0], H.PERSISTED)
        c = base_contracts()
        c[2]["active"] = False
        s1 = snapshot(T0 + 1200, "gh-2-1", c)
        r, obs, path = append(st, s1)
        self.assertEqual((r, obs["state_mode"]), (H.PERSISTED, H.DELTA))
        self.assertEqual([x[0] for x in obs["contracts"]["set"]], ["hyperliquid:ETH"])
        self.assertEqual(obs["base"]["seq"], 1)
        self.assertIsNone(obs["liquidity"])                 # less than LIQUIDITY_EVERY_S after the last one
        rep = H.verify(st)
        self.assertTrue(rep["ok"], rep)
        self.assertEqual((rep["observations"], rep["checkpoints"], rep["liquidity_observations"]), (2, 1, 1))
        self.assertTrue(path.startswith("obs/") and path.endswith("00000002-gh-2-1.json.gz"))

    def test_deterministic_serialization(self):
        a, b = self.store("a"), self.store("b")
        for st in (a, b):
            append(st, snapshot(T0, "gh-1-1", base_contracts()), now=T0 + 5)
        pa, pb = a.paths()[0], b.paths()[0]
        self.assertEqual(a.read_bytes(pa), b.read_bytes(pb))
        o = H.decode(a.read_bytes(pa))
        self.assertEqual(H.canonical(o), gzip.decompress(a.read_bytes(pa)))

    def test_provenance_on_every_observation(self):
        st = self.store()
        append(st, snapshot(T0, "gh-1-1", base_contracts()))
        o = H.decode(st.read_bytes(st.paths()[0]))
        for k in ("scan_id", "observed_at", "git_sha", "source", "versions", "venues", "coverage", "seq", "prev_hash",
                  "content_hash", "liquidity_content_hash", "record_hash", "appended_at", "stored_bytes_before"):
            self.assertIn(k, o)
        self.assertEqual(o["versions"]["identity"], "v8.identity/4")
        self.assertEqual(o["versions"]["identity_config_hash"],
                         "96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c")
        self.assertEqual(o["source"], {"type": H.SCAN, "backfill": False})

    def test_idempotent_replay_and_conflict(self):
        st = self.store()
        s0 = snapshot(T0, "gh-1-1", base_contracts())
        append(st, s0)
        self.assertEqual(append(st, s0)[0], H.REPLAY)
        changed = snapshot(T0, "gh-1-1", base_contracts()[:-1])
        self.assertEqual(append(st, changed)[0], H.CONFLICT)
        self.assertEqual(len(st.paths()), 1)

    def test_never_overwrites(self):
        st = self.store()
        append(st, snapshot(T0, "gh-1-1", base_contracts()))
        p = st.paths()[0]
        with self.assertRaises(FileExistsError):
            st.write(p, b"x")

    def test_tamper_is_detected(self):
        for how in ("modify", "delete", "reorder"):
            st = self.store(how)
            for k in range(4):
                c = base_contracts()
                c[0]["vol"] = 1e8 + k
                c[1]["active"] = bool(k % 2)
                append(st, snapshot(T0 + k * 5 * HOUR, f"gh-{k}-1", c))
            self.assertTrue(H.verify(st)["ok"])
            ps = st.paths()
            full = [os.path.join(st.root, p) for p in ps]
            if how == "modify":
                o = H.decode(st.read_bytes(ps[1]))
                o["observed_at"] += 1
                with open(full[1], "wb") as fh:
                    fh.write(H.gz(H.canonical(o)))
            elif how == "delete":
                os.remove(full[2])
            else:                                     # swap two observations' contents
                a, b = st.read_bytes(ps[1]), st.read_bytes(ps[2])
                with open(full[1], "wb") as fh:
                    fh.write(b)
                with open(full[2], "wb") as fh:
                    fh.write(a)
            self.assertFalse(H.verify(st)["ok"], how)
            self.assertFalse(P.History(st).ok, how)

    def test_broken_tail_appends_nothing(self):
        st = self.store()
        append(st, snapshot(T0, "gh-1-1", base_contracts()))
        append(st, snapshot(T0 + HOUR, "gh-2-1", base_contracts()))
        p = os.path.join(st.root, st.paths()[-1])
        with open(p, "rb") as fh:
            o = H.decode(fh.read())
        o["prev_hash"] = "0" * 64
        with open(p, "wb") as fh:
            fh.write(H.gz(H.canonical(o)))
        self.assertEqual(H.Chain(st).integrity, "BROKEN")
        self.assertEqual(append(st, snapshot(T0 + 2 * HOUR, "gh-3-1", base_contracts()))[0], H.INTEGRITY_BROKEN)
        self.assertEqual(len(st.paths()), 2)

    def test_checkpoint_cadence_and_liquidity_cadence(self):
        st = self.store()
        modes, liq = [], []
        for k in range(10):                       # one scan every 3 hours for 30 hours
            r, o, _ = append(st, snapshot(T0 + k * 3 * HOUR, f"gh-{k}-1", base_contracts()))
            modes.append(o["state_mode"])
            liq.append(o["liquidity"] is not None)
        self.assertEqual(modes[0], H.CHECKPOINT)
        self.assertIn(H.CHECKPOINT, modes[8:])     # a new checkpoint after 24 hours
        self.assertEqual(liq[:4], [True, False, True, False])     # every 4 hours or more
        self.assertTrue(H.verify(st)["ok"])

    def test_storage_bytes_add_up(self):
        st = self.store()
        for k in range(3):
            append(st, snapshot(T0 + k * HOUR, f"gh-{k}-1", base_contracts()))
        total = sum(len(st.read_bytes(p)) for p in st.paths())
        self.assertEqual(H.Chain(st).stored_bytes, total)
        self.assertEqual(H.verify(st)["bytes"], total)

    def test_older_snapshot_schemas(self):
        """Archived snapshots of earlier audit schemas (contract list, no registry venue detail) still record."""
        s = snapshot(T0, "gh-9-1", base_contracts(), columns=False)
        del s["data_health"]["registry_venues"]
        s["manifest"]["schema"] = "v8.audit/2"
        c = H.scan_content(s)
        self.assertEqual(c["venues"]["edgex"], "OK")
        self.assertEqual(len(H.state_from_snapshot(s)["contracts"]), 6)

    def test_venue_states_match_discovery(self):
        from v8 import discovery as DS
        cs = base_contracts() + [contract("aster:OFF", "OFF", active=False, legacy="NOT_TRADING")]
        rv = {"hyperliquid": {"ok": True, "raw": 5}, "lighter": {"ok": False, "raw": 0},
              "aster": {"ok": True, "raw": 3}, "edgex": {"ok": True, "raw": 0},
              "dydx": {"ok": True, "raw": 4}, "paradex": {"ok": True, "raw": 2, "error": "x"}}
        self.assertEqual(H.venue_states(cs, rv),
                         {v: x["state"] for v, x in DS.venue_table({"contracts": cs, "venues": rv}).items()})

    def test_liquidity_semantics(self):
        cs = base_contracts() + [contract("dydx:NOTRADE", "NOTRADE", vol=9e9),
                                 contract("hyperliquid:NOVOL", "NOVOL", vol=None),
                                 contract("hyperliquid:ZERO", "ZERO", vol=0.0)]
        liq = H.state_from_snapshot(snapshot(T0, "x", cs))["liquidity"]
        self.assertEqual(liq["BTC"], ["BTC", "KNOWN", 500_000_000])          # the largest trade-DEX volume
        self.assertEqual(liq["NOTRADE"][1], "NOT_ON_TRADE_DEX")
        self.assertEqual(liq["NOVOL"], ["NOVOL", "MISSING", None])            # missing is never 0
        self.assertEqual(liq["ZERO"], ["ZERO", "KNOWN", 0])                    # an observed 0 is 0
        self.assertNotIn("EDGEONLY", [a for a, r in liq.items() if r[1] == "KNOWN"])


class HistoryIntegrity(Tmp):
    """Full observed scan identity and self-verifying records, including the unlinked head."""

    def btc(self, ts=T0, sid="gh-1-1", vol=5_000_000):
        return snapshot(ts, sid, [contract("hyperliquid:BTC", "BTC", vol=vol)])

    def rewrite(self, st, obs):
        with open(os.path.join(st.root, st.paths()[-1]), "wb") as fh:
            fh.write(H.gz(H.canonical(obs)))

    def assert_broken(self, st):
        rep = H.verify(st)
        self.assertFalse(rep["ok"], rep)
        self.assertEqual(H.Chain(st).integrity, "BROKEN")
        hist = P.History(st)
        self.assertFalse(hist.ok)
        self.assertEqual(hist.status, P.HISTORY_INTEGRITY_FAILED)
        self.assertEqual(append(st, self.btc(T0 + 10 * HOUR, "gh-next-1"))[0], H.INTEGRITY_BROKEN)

    def test_same_scan_liquidity_conflict(self):
        st = self.store()
        original, changed = self.btc(), self.btc(vol=100_000)
        before, after = H.state_from_snapshot(original), H.state_from_snapshot(changed)
        self.assertEqual(H.scan_content(original), H.scan_content(changed))
        self.assertEqual(before["contracts"], after["contracts"])
        self.assertEqual(before["assets"], after["assets"])
        self.assertEqual(append(st, original)[0], H.PERSISTED)
        stored = st.read_bytes(st.paths()[0])
        self.assertEqual(append(st, changed)[0], H.CONFLICT)
        self.assertEqual(len(st.paths()), 1)
        self.assertEqual(st.read_bytes(st.paths()[0]), stored)
        self.assertTrue(H.verify(st)["ok"])

    def test_omitted_liquidity_still_conflicts_and_exact_retry_replays(self):
        st = self.store()
        append(st, self.btc())
        s = self.btc(T0 + 1200, "gh-2-1")
        _, obs, path = append(st, s)
        self.assertIsNone(obs["liquidity"])
        self.assertEqual(obs["liquidity_content_hash"], H.liquidity_hash(H.state_from_snapshot(s)["liquidity"]))
        stored = st.read_bytes(path)
        self.assertEqual(append(st, copy.deepcopy(s), now=T0 + HOUR)[0], H.REPLAY)
        self.assertEqual(append(st, self.btc(T0 + 1200, "gh-2-1", 100_000))[0], H.CONFLICT)
        self.assertEqual(len(st.paths()), 2)
        self.assertEqual(st.read_bytes(path), stored)
        self.assertTrue(H.verify(st)["ok"])

    def test_exact_retry_and_different_provenance_replay(self):
        st = self.store()
        s = self.btc()
        _, obs, path = append(st, s)
        stored = st.read_bytes(path)
        self.assertEqual(append(st, copy.deepcopy(s), now=T0 + HOUR)[0], H.REPLAY)
        source = {"type": H.ARTIFACT, "backfill": True, "artifact": {"id": 42, "digest": "other-source"}}
        self.assertEqual(H.append(st, H.scan_content(s, source), H.state_from_snapshot(s), now=T0 + 2 * HOUR)[0],
                         H.REPLAY)
        self.assertEqual(len(st.paths()), 1)
        self.assertEqual(st.read_bytes(path), stored)
        self.assertEqual(obs["record_hash"], H.obs_hash(obs))

    def test_liquidity_digest_is_order_independent_and_covers_every_row(self):
        s = snapshot(T0, "gh-1-1", base_contracts())
        state = H.state_from_snapshot(s)
        reordered = {k: dict(reversed(list(v.items()))) for k, v in state.items()}
        self.assertEqual(H.content_hash(H.scan_content(s), state), H.content_hash(H.scan_content(s), reordered))
        for key in state["liquidity"]:
            changed = copy.deepcopy(state)
            changed["liquidity"][key][1] = "MISSING"
            self.assertNotEqual(H.content_hash(H.scan_content(s), state), H.content_hash(H.scan_content(s), changed))

    def test_other_observed_authority_changes_conflict(self):
        for field in ("scan_id", "observed_at", "git_sha", "versions", "venues", "coverage", "trade_dexes",
                      "contracts", "assets"):
            with self.subTest(field=field):
                st = self.store(field)
                s = self.btc()
                append(st, s)
                content, state = H.scan_content(s), H.state_from_snapshot(s)
                old_hash = H.content_hash(content, state)
                if field == "contracts":
                    state[field]["hyperliquid:BTC"][3] = 0
                elif field == "assets":
                    state[field]["BTC"][2] = "UNVERIFIED"
                elif field == "versions":
                    content[field]["identity_config_hash"] = "changed"
                elif field == "venues":
                    content[field]["hyperliquid"] = H.VENUE_UNAVAILABLE
                elif field == "coverage":
                    content[field]["fallback_universe"] = True
                elif field == "trade_dexes":
                    content[field] = []
                else:
                    content[field] = content[field] + 1 if field == "observed_at" else "changed"
                self.assertNotEqual(old_hash, H.content_hash(content, state))
                if field != "scan_id":
                    self.assertEqual(H.append(st, content, state, now=T0)[0], H.CONFLICT)
                    self.assertEqual(len(st.paths()), 1)

    def test_head_liquidity_tamper_fails_closed(self):
        for mode in (H.CHECKPOINT, H.DELTA):
            for index, value in ((0, "ETH"), (1, "MISSING"), (2, 100_000)):
                with self.subTest(mode=mode, index=index):
                    st = self.store(f"{mode}-{index}")
                    append(st, self.btc())
                    _, obs, _ = append(st, self.btc(T0 + 4 * HOUR, "gh-2-1"),
                                       force_checkpoint=mode == H.CHECKPOINT)
                    self.assertEqual(obs["state_mode"], mode)
                    self.assertIsNotNone(obs["liquidity"])
                    earlier = st.read_bytes(st.paths()[0])
                    obs["liquidity"]["rows"][0][index] = value
                    self.rewrite(st, obs)
                    self.assert_broken(st)
                    self.assertEqual(st.read_bytes(st.paths()[0]), earlier)

    def test_liquidity_payload_checked_independently_of_record_hash(self):
        st = self.store()
        _, obs, _ = append(st, self.btc())
        obs["liquidity"]["rows"][0][2] = 100_000
        obs["record_hash"] = H.obs_hash(obs)
        self.rewrite(st, obs)
        self.assert_broken(st)
        self.assertTrue(any("liquidity payload" in p for p in H.verify(st)["problems"]))

    def test_backfilled_head_source_tamper(self):
        for field in ("id", "digest", "file_sha256", "run_id"):
            with self.subTest(field=field):
                st = self.store(field)
                append(st, self.btc())
                s = self.btc(T0 + HOUR, "gh-2-1")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as zf:
                    zf.writestr("audit.json.gz", H.gz(H.canonical(s)))
                content, state = H.artifact_observations(buf.getvalue(),
                                                       {"id": 42, "digest": "sha256:original", "run_id": 2})[0]
                _, obs, _ = H.append(st, content, state, now=T0 + HOUR, force_checkpoint=True)
                self.assertTrue(H.verify(st)["ok"])
                semantic = obs["content_hash"]
                earlier = st.read_bytes(st.paths()[0])
                obs["source"]["artifact"][field] = "tampered"
                self.assertEqual(H.content_hash(obs, H.full_state(obs)), semantic)
                self.rewrite(st, obs)
                self.assert_broken(st)
                self.assertEqual(st.read_bytes(st.paths()[0]), earlier)

    def test_every_persisted_head_field_has_record_integrity(self):
        changes = {"content_hash": "0" * 64, "liquidity_content_hash": "0" * 64,
                   "source": {"type": H.ARTIFACT, "backfill": True}, "seq": 3, "prev_hash": "0" * 64,
                   "state_mode": H.CHECKPOINT, "stored_bytes_before": 0,
                   "base": {"seq": 1, "hash": "0" * 64},
                   "last_liquidity": {"seq": 1, "observed_at": T0 + 1},
                   "appended_at": T0 + HOUR + 1, "record_hash": "0" * 64}
        for field, value in changes.items():
            with self.subTest(field=field):
                st = self.store(field)
                append(st, self.btc())
                _, obs, _ = append(st, self.btc(T0 + HOUR, "gh-2-1"))
                self.assertIsNone(obs["liquidity"])
                obs[field] = value
                self.rewrite(st, obs)
                # Self-integrity itself must reject these fields before any chain/state interpretation.
                self.assertTrue(H.record_problems(obs))
                self.assertEqual(H.Chain(st).integrity, "BROKEN")
                self.assertFalse(H.verify(st)["ok"])

    def test_chain_and_base_use_one_record_hash_authority(self):
        st = self.store()
        _, first, _ = append(st, self.btc())
        _, second, _ = append(st, self.btc(T0 + HOUR, "gh-2-1"))
        self.assertEqual(second["prev_hash"], first["record_hash"])
        self.assertEqual(second["base"]["hash"], first["record_hash"])
        self.assertEqual(H.verify(st)["head_hash"], second["record_hash"])
        self.assertTrue(H.verify(st)["ok"])

    def test_defective_dryrun_format_is_rejected(self):
        st = self.store()
        _, obs, _ = append(st, self.btc())
        del obs["record_hash"]
        del obs["liquidity_content_hash"]
        self.rewrite(st, obs)
        self.assert_broken(st)


# --------------------------------------------------------------------------- the git branch writer
def _git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True).stdout.decode().strip()


class GitBranch(Tmp):
    def setUp(self):
        super().setUp()
        self.bare = os.path.join(self.tmp, "remote.git")
        _git("init", "-q", "--bare", self.bare)
        self.work = os.path.join(self.tmp, "work")
        _git("init", "-q", self.work)
        _git("remote", "add", "origin", self.bare, cwd=self.work)

    def snap(self, k, n=None):
        return snapshot(T0 + k * HOUR, f"gh-{k}-1", base_contracts()[:n] if n else base_contracts())

    def test_genesis_append_and_fast_forward_only(self):
        st = H.capture(self.snap(0), repo=self.work, now=T0 + 10)
        self.assertEqual(st["persistence_state"], H.PERSISTED, st)
        self.assertEqual(st["append_integrity"], "EMPTY")
        head1 = _git("rev-parse", "refs/heads/v8-history", cwd=self.bare)
        self.assertEqual(st["history_branch_commit"], head1)
        st2 = H.capture(self.snap(1), repo=self.work, now=T0 + HOUR + 10)
        self.assertEqual((st2["persistence_state"], st2["append_integrity"]), (H.PERSISTED, "VERIFIED_TAIL"))
        head2 = _git("rev-parse", "refs/heads/v8-history", cwd=self.bare)
        self.assertEqual(_git("rev-parse", head2 + "^", cwd=self.bare), head1)       # appended, history kept
        files = _git("ls-tree", "-r", "--name-only", head2, cwd=self.bare).split("\n")
        self.assertIn("README.md", files)
        self.assertEqual(len([f for f in files if f.endswith(".json.gz")]), 2)
        self.assertEqual(st2["storage_size"]["observations"], 2)
        # the same scan again: nothing new
        st3 = H.capture(self.snap(1), repo=self.work, now=T0 + 2 * HOUR)
        self.assertEqual(st3["persistence_state"], H.REPLAY)
        self.assertEqual(_git("rev-parse", "refs/heads/v8-history", cwd=self.bare), head2)
        # the checkout's own origin is left alone
        self.assertEqual(_git("remote", "get-url", "origin", cwd=self.work), self.bare)

    def test_rewritten_remote_is_never_overwritten(self):
        H.capture(self.snap(0), repo=self.work, now=T0)
        # someone else appends first (another clone)
        other = os.path.join(self.tmp, "other")
        _git("init", "-q", other)
        _git("remote", "add", "origin", self.bare, cwd=other)
        H.capture(self.snap(1), repo=other, now=T0 + HOUR)
        head = _git("rev-parse", "refs/heads/v8-history", cwd=self.bare)
        # a stale writer that does not refetch is rejected by git (no --force), never overwrites
        gs = H.GitStore(self.work)
        gs.head = _git("rev-parse", head + "^", cwd=self.bare)
        _git("fetch", "-q", self.bare, "refs/heads/v8-history", cwd=self.work)
        gs._paths = None
        gs.pending = [("obs/2099/01/01/00000002-stale.json.gz", b"x")]
        with self.assertRaises(H.PushRejected):
            gs.commit_and_push("stale")
        self.assertEqual(_git("rev-parse", "refs/heads/v8-history", cwd=self.bare), head)
        # capture refetches and appends on top
        st = H.capture(self.snap(2), repo=self.work, now=T0 + 2 * HOUR)
        self.assertEqual(st["persistence_state"], H.PERSISTED)
        self.assertEqual(st["observation"]["seq"], 3)

    def test_rejected_push_is_retried_from_a_fresh_fetch(self):
        H.capture(self.snap(0), repo=self.work, now=T0)
        orig, calls = H.GitStore.commit_and_push, []

        def flaky(gs, message):
            calls.append(message)
            if len(calls) == 1:
                raise H.PushRejected("! [rejected] (fetch first)")
            return orig(gs, message)
        H.GitStore.commit_and_push = flaky
        try:
            st = H.capture(self.snap(1), repo=self.work, now=T0 + HOUR)
        finally:
            H.GitStore.commit_and_push = orig
        self.assertEqual((st["persistence_state"], len(calls)), (H.PERSISTED, 2))
        self.assertIn("retried", st["reason"])
        self.assertEqual(st["observation"]["seq"], 2)

    def test_failure_is_degraded_never_raised(self):
        bad = os.path.join(self.tmp, "nogit")
        os.makedirs(bad)
        st = H.capture(self.snap(0), repo=bad, now=T0)
        self.assertEqual(st["persistence_state"], H.DEGRADED)
        self.assertTrue(st["reason"])

    def test_snapshot_write_unaffected_by_history_failure(self):
        """The snapshot step writes the same files whether the history is persisted, degraded or not configured."""
        from v8 import snapshot as SN
        orig = SN.build

        def fake_build(*a, **k):
            return (copy.deepcopy(self.snap(0)) | {"coverage": {"summary": {}}, "discovery": {}}, {}, {}, None)
        SN.build = fake_build
        try:
            outs = {}
            for mode in ("none", "degraded", "persisted"):
                d = os.path.join(self.tmp, "site_" + mode)
                kw = {}
                if mode == "degraded":
                    kw = {"history_store": object()}            # not a store: capture fails inside
                elif mode == "persisted":
                    kw = {"history_store": H.DirStore(os.path.join(self.tmp, "hs"))}
                snap, _, _, _ = SN.write(d, **kw)
                outs[mode] = snap
                self.assertTrue(os.path.exists(os.path.join(d, "data", "v8", "audit_latest.json")))
            self.assertEqual(outs["none"]["history"]["persistence_state"], H.NOT_CONFIGURED)
            self.assertEqual(outs["degraded"]["history"]["persistence_state"], H.DEGRADED)
            self.assertIn("history", outs["degraded"]["data_health"]["audit_problems"])
            self.assertEqual(outs["persisted"]["history"]["persistence_state"], H.PERSISTED)
            strip = [{k: v for k, v in s.items() if k not in ("history", "data_health", "storage")}
                     for s in outs.values()]
            self.assertEqual(strip[0], strip[1])
            self.assertEqual(strip[0], strip[2])
        finally:
            SN.build = orig


# --------------------------------------------------------------------------- backfill from archived scan artifacts
def artifact_zip(snaps):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for s in snaps:
            zf.writestr(f"audit_{s['manifest']['scan_id']}.json.gz", H.gz(H.canonical(s)))
    return buf.getvalue()


class Backfill(Tmp):
    def test_backfill_cites_the_artifact_and_is_idempotent(self):
        st = self.store()
        snaps = {f"gh-{k}-1": snapshot(T0 + k * HOUR, f"gh-{k}-1", base_contracts()) for k in (3, 1, 2)}
        arts = [{"id": 100 + k, "name": f"v8-audit-{k}-1", "created_at": f"2026-10-0{k}T00:00:00Z",
                 "digest": f"sha256:{k}", "workflow_run": {"id": k}} for k in (3, 1, 2)]
        zips = {100 + k: artifact_zip([snaps[f"gh-{k}-1"]]) for k in (1, 2, 3)}
        cur = snapshot(T0 + 5 * HOUR, "gh-5-1", base_contracts())
        st_ = H.capture(cur, store=st, backfill=True, repo_slug="o/r", now=T0 + 6 * HOUR,
                        lister=lambda slug: arts, downloader=lambda slug, i: zips[i])
        self.assertEqual(st_["persistence_state"], H.PERSISTED, st_)
        self.assertEqual(st_["backfill"]["appended"], 3)
        obs = [H.decode(st.read_bytes(p)) for p in st.paths()]
        self.assertEqual([o["scan_id"] for o in obs], ["gh-1-1", "gh-2-1", "gh-3-1", "gh-5-1"])   # observed order
        for o in obs[:3]:
            self.assertEqual(o["state_mode"], H.CHECKPOINT)
            self.assertEqual(o["source"]["type"], H.ARTIFACT)
            a = o["source"]["artifact"]
            self.assertTrue(a["zip_sha256"] and a["file_sha256"] and a["name"].startswith("v8-audit-"))
            self.assertIsNotNone(o["liquidity"])
        self.assertEqual(obs[3]["source"]["type"], H.SCAN)
        self.assertTrue(H.verify(st)["ok"])
        # again: everything already recorded, nothing downloaded
        calls = []
        st2 = H.capture(snapshot(T0 + 6 * HOUR, "gh-6-1", base_contracts()), store=st, backfill=True, repo_slug="o/r",
                        now=T0 + 7 * HOUR, lister=lambda slug: arts,
                        downloader=lambda slug, i: calls.append(i) or zips[i])
        self.assertEqual((st2["backfill"]["appended"], st2["backfill"]["already_recorded"], calls), (0, 3, []))

    def test_live_and_backfilled_copies_of_one_scan_are_the_same_observation(self):
        st = self.store()
        s = snapshot(T0, "gh-1-1", base_contracts())
        append(st, s)
        z = artifact_zip([s])
        (c, state), = H.artifact_observations(z, {"name": "v8-audit-1-1"})
        self.assertEqual(H.append(st, c, state, now=T0 + 99)[0], H.REPLAY)


# --------------------------------------------------------------------------- point-in-time queries
class PointInTime(Tmp):
    def setUp(self):
        super().setUp()
        self.h = P.History(world(self.tmp))

    def at(self, k, extra=0):
        return T0 + k * 4 * HOUR + extra

    def test_no_look_ahead(self):
        u = self.h.universe_at(self.at(0, 60))
        self.assertNotIn("NEWCOIN", u["assets"])                       # listed at scan 3: unknown to scan 0
        self.assertEqual(u["header"]["observation"]["scan_id"], "gh-0-1")
        self.assertIsNone(self.h.asset_at(self.at(0) - 1, "BTC"))        # before the history: not known at all
        self.assertEqual(self.h.identity_at(self.at(0) - 1, "BTC")["state"], P.UNKNOWN)

    def test_delisted_asset_is_kept_in_its_past(self):
        self.assertEqual(self.h.asset_at(self.at(1, 1), "OLDCOIN")["state"], P.KNOWN_ACTIVE)
        self.assertEqual(self.h.asset_at(self.at(2, 1), "OLDCOIN")["state"], P.KNOWN_INACTIVE)
        iv = self.h.intervals("OLDCOIN")
        self.assertEqual(len(iv), 1)
        self.assertEqual((iv[0]["eligible_from"], iv[0]["last_observed_active"], iv[0]["first_observed_inactive"],
                          iv[0]["end"]), (self.at(0), self.at(1), self.at(2), "DELISTED_OR_HALTED_OBSERVED"))
        self.assertFalse(iv[0]["listing_known"])                        # active in the first observation

    def test_future_listing_does_not_leak_back(self):
        for k in range(3):
            self.assertIsNone(self.h.asset_at(self.at(k, 100), "NEWCOIN"))
        self.assertEqual(self.h.asset_at(self.at(3, 1), "NEWCOIN")["state"], P.KNOWN_ACTIVE)
        self.assertEqual(self.h.intervals("NEWCOIN")[0]["eligible_from"], self.at(3))

    def test_identity_is_not_rewritten(self):
        self.assertEqual(self.h.identity_at(self.at(1, 5), "MAYBE")["identity"], "UNVERIFIED")
        self.assertFalse(self.h.crypto_identity_at(self.at(1, 5), "MAYBE"))
        self.assertEqual(self.h.identity_at(self.at(4, 5), "MAYBE")["identity"], "VERIFIED_CRYPTO")
        self.assertEqual(self.h.identity_at(self.at(1, 5), "MAYBE")["identity_version"], "v8.identity/4")
        u = self.h.universe_at(self.at(1, 5), min_vol=1e6)
        self.assertFalse(u["assets"]["MAYBE"]["research_eligible"])

    def test_venue_outage_is_not_a_delisting(self):
        a = self.h.asset_at(self.at(4, 1), "EDGEONLY")
        self.assertEqual((a["state"], a["reason"]), (P.UNKNOWN, P.VENUE_UNAVAILABLE))
        self.assertEqual(self.h.asset_at(self.at(5, 1), "EDGEONLY")["state"], P.KNOWN_ACTIVE)
        iv = self.h.intervals("EDGEONLY")
        self.assertEqual(len(iv), 1)                  # the outage neither closed nor reopened the interval
        self.assertIsNone(iv[0]["first_observed_inactive"])
        u = self.h.universe_at(self.at(4, 1), min_vol=1e6)
        self.assertIsNone(u["assets"]["EDGEONLY"]["research_eligible"])          # unknown, never False
        self.assertEqual(self.h.exposure_at(self.at(4, 1), "edgex:EDGEONLY")["reason"], "ABSENT_THIS_OBSERVATION")

    def test_relisting_opens_a_new_interval(self):
        iv = self.h.intervals("RELIST")
        self.assertEqual(len(iv), 2)
        self.assertEqual((iv[0]["first_observed_inactive"], iv[1]["eligible_from"]), (self.at(1), self.at(4)))
        self.assertTrue(iv[1]["listing_known"])

    def test_staleness(self):
        last = self.at(5)
        self.assertEqual(self.h.asset_at(last + P.MAX_STALENESS_S, "BTC")["state"], P.KNOWN_ACTIVE)
        a = self.h.asset_at(last + P.MAX_STALENESS_S + 1, "BTC")
        self.assertEqual((a["state"], a["reason"]), (P.UNKNOWN, P.STALE))
        liq = self.h.liquidity_at(last + P.LIQUIDITY_MAX_STALENESS_S + 1, "BTC")
        self.assertEqual((liq["state"], liq["health"]), (P.LIQUIDITY_HISTORY_UNKNOWN, P.LIQUIDITY_HISTORY_GAP))
        self.assertEqual(self.h.observation_at(last + P.MAX_STALENESS_S + 1)["state"], P.PIT_UNIVERSE_GAP)

    def test_liquidity_at_is_point_in_time(self):
        self.assertEqual(self.h.liquidity_at(self.at(0, 60), "BTC")["value"], 500_000_000)
        self.assertEqual(self.h.liquidity_at(self.at(0, 60), "SMALL")["value"], 150_000)
        u = self.h.universe_at(self.at(0, 60), min_vol=1e6)
        self.assertFalse(u["assets"]["SMALL"]["research_eligible"])
        self.assertTrue(u["assets"]["BTC"]["research_eligible"])

    def test_identity_not_recorded_then_is_unknown_not_false(self):
        """Archived snapshots of v8.audit/1 and /2 carry no identity state: eligibility then is unknown."""
        st = self.store("old")
        old = snapshot(T0, "gh-1-1", base_contracts())
        for a in old["registry"]["assets"].values():
            a["identity"] = {}
        append(st, old)
        append(st, snapshot(T0 + 4 * HOUR, "gh-2-1", base_contracts()))
        h = P.History(st)
        self.assertIsNone(h.identity_at(T0 + 60, "BTC")["identity"])
        self.assertIsNone(h.crypto_identity_at(T0 + 60, "BTC"))
        self.assertIsNone(h.universe_at(T0 + 60, min_vol=1e6)["assets"]["BTC"]["research_eligible"])
        self.assertTrue(h.universe_at(T0 + 4 * HOUR + 60, min_vol=1e6)["assets"]["BTC"]["research_eligible"])
        if HAVE_NUMPY:
            import pit_sim as PS
            u = PS.universe_panel(h, [T0 + 60, T0 + 4 * HOUR + 60], ["BTC"], 1e6)
            self.assertEqual(list(u["crypto"][:, 0]), [-1, 1])
            self.assertEqual(list(u["code"][:, 0]), [-1, 1])

    def test_fallback_universe_is_unknown(self):
        st = self.store("fb")
        append(st, snapshot(T0, "gh-1-1", base_contracts()))
        append(st, snapshot(T0 + HOUR, "gh-2-1", [contract("hyperliquid:BTC", "BTC")], fallback=True))
        h = P.History(st)
        self.assertEqual(h.asset_at(T0 + HOUR + 1, "BTC")["state"], P.UNKNOWN)
        self.assertEqual(h.asset_at(T0 + HOUR + 1, "ETH")["reason"], P.FALLBACK)

    def test_broken_chain_fails_closed(self):
        st = world(self.tmp + "/b")
        p = os.path.join(st.root, st.paths()[2])
        os.remove(p)
        h = P.History(st)
        self.assertFalse(h.ok)
        self.assertEqual(h.status, P.HISTORY_INTEGRITY_FAILED)
        self.assertEqual(h.asset_at(T0 + 1, "BTC")["state"], P.UNKNOWN)
        self.assertEqual(h.universe_at(T0 + 1)["assets"], {})
        self.assertEqual(h.liquidity_at(T0 + 1, "BTC")["state"], P.LIQUIDITY_HISTORY_UNKNOWN)

    def test_cutoff(self):
        st = world(self.tmp + "/c")
        h = P.History(st, cutoff=self.at(2))
        self.assertEqual(h.window()["observations"], 3)
        self.assertIsNone(h.asset_at(self.at(5), "NEWCOIN"))             # observed after the cutoff: never used
        self.assertEqual(h.asset_at(self.at(2, 1), "OLDCOIN")["state"], P.KNOWN_INACTIVE)

    def test_backfilled_observation_out_of_append_order(self):
        """A late-appended archived scan sits at its own observation time."""
        st = self.store("late")
        append(st, snapshot(T0, "gh-1-1", base_contracts()))
        append(st, snapshot(T0 + 8 * HOUR, "gh-3-1", base_contracts()))
        late = snapshot(T0 + 4 * HOUR, "gh-2-1", [x for x in base_contracts() if x["asset"] != "ETH"]
                        + [contract("hyperliquid:ETH", "ETH", active=False, legacy="NOT_TRADING")])
        H.append(st, H.scan_content(late, {"type": H.ARTIFACT, "backfill": True}), H.state_from_snapshot(late),
                 now=T0 + 9 * HOUR, force_checkpoint=True)
        append(st, snapshot(T0 + 10 * HOUR, "gh-4-1", base_contracts()), now=T0 + 10 * HOUR)
        self.assertTrue(H.verify(st)["ok"])
        h = P.History(st)
        self.assertEqual(h.asset_at(T0 + 5 * HOUR, "ETH")["state"], P.KNOWN_INACTIVE)
        self.assertEqual(h.asset_at(T0 + 9 * HOUR, "ETH")["state"], P.KNOWN_ACTIVE)
        self.assertEqual(h.window()["backfilled"], 1)


# --------------------------------------------------------------------------- the shadow experiment ledger
def registration(**over):
    params = {"look": 30}
    r = {"experiment_id": "TSMOM-PIT-001", "registered_at": T0, "registration_commit": "b" * 40, "name": "TSMOM",
         "params": params, "param_hash": SL.param_hash(params), "code_files": ["tools/research/qstrat.py"],
         "code_hash": "c" * 64, "data_cutoff": T0, "evaluation_start": T0 + 1, "evaluation_end": None,
         "universe_history_version": "v8.history/1", "cost_model_version": "v8.pit-cost/1",
         "hypothesis": "h", "primary_metric": "avg net R of fully qualified trades",
         "secondary_metrics": ["win rate"], "pass_rule": "p", "fail_rule": "f", "status": "REGISTERED",
         "multiple_testing": {"family": "trend", "variants_tried_before_registration": 4, "variant_ids": [],
                              "selection": "s", "corrections_planned": ["DSR", "PBO", "SPA", "FDR"]}}
    r.update(over)
    return r


class ShadowLedger(Tmp):
    def test_committed_ledger_is_valid_and_has_no_authority(self):
        folder = os.path.join(ROOT, SL.DIR)
        self.assertEqual(SL.validate(folder), [])
        for _, r, _ in SL.load(folder):
            self.assertEqual(r["authority"], "NONE")
            self.assertNotIn(r.get("status"), SL.FORBIDDEN_STATUSES)

    def test_registration_rules(self):
        d = os.path.join(self.tmp, "ledger")
        SL.append(d, SL.GENESIS, created_at=T0)
        SL.append(d, SL.REGISTRATION, **registration())
        self.assertEqual(SL.validate(d), [])
        with self.assertRaises(ValueError):                          # same id again (changed params need a new id)
            SL.append(d, SL.REGISTRATION, **registration(params={"look": 31},
                                                         param_hash=SL.param_hash({"look": 31})))
        for bad in (dict(param_hash="0" * 64), dict(evaluation_start=T0 - 1), dict(data_cutoff=T0 + 5),
                    dict(status="FINAL"), dict(status="LIVE"), dict(experiment_id="x"),
                    dict(registration_commit="abc")):
            reg = registration(experiment_id="TSMOM-PIT-002")
            reg.update(bad)
            with self.assertRaises(ValueError, msg=str(bad)):
                SL.append(d, SL.REGISTRATION, **reg)
        SL.append(d, SL.REGISTRATION, **registration(experiment_id="TSMOM-PIT-002", params={"look": 31},
                                                     param_hash=SL.param_hash({"look": 31})))
        SL.append(d, SL.STATUS, experiment_id="TSMOM-PIT-001", status="RETIRED", at=T0 + 9)
        self.assertEqual(SL.validate(d), [])
        self.assertEqual(SL.summary(d)["status"], {"TSMOM-PIT-001": "RETIRED", "TSMOM-PIT-002": "REGISTERED"})

    def test_edits_are_detected(self):
        d = os.path.join(self.tmp, "ledger")
        SL.append(d, SL.GENESIS, created_at=T0)
        name, _ = SL.append(d, SL.REGISTRATION, **registration())
        p = os.path.join(d, name)
        with open(p) as fh:
            r = json.load(fh)
        r["params"] = {"look": 99}
        with open(p, "wb") as fh:
            fh.write(SL.canonical(r))
        self.assertTrue(SL.validate(d))

    def test_guard_rejects_modifications(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(repo, "tools", "v8"))
        shutil.copytree(os.path.join(ROOT, "v8"), os.path.join(repo, "v8"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(ROOT, "tools", "v8", "ledger_guard.py"), os.path.join(repo, "tools", "v8"))
        d = os.path.join(repo, SL.DIR)
        SL.append(d, SL.GENESIS, created_at=T0)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        for a in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
            subprocess.run(["git", *a], cwd=repo, check=True, env=env, capture_output=True)
        base = _git("rev-parse", "HEAD", cwd=repo)
        guard = [sys.executable, os.path.join(repo, "tools", "v8", "ledger_guard.py"), "--base", base]
        SL.append(d, SL.REGISTRATION, **registration())
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "add"], cwd=repo, check=True, env=env)
        self.assertEqual(subprocess.run(guard, cwd=repo, capture_output=True).returncode, 0)
        g = os.path.join(d, sorted(os.listdir(d))[0])
        with open(g, "ab") as fh:
            fh.write(b" ")
        subprocess.run(["git", "commit", "-qam", "edit"], cwd=repo, check=True, env=env)
        r = subprocess.run(guard, cwd=repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("append-only", r.stdout)


# --------------------------------------------------------------------------- versions and live isolation
class VersionsAndIsolation(unittest.TestCase):
    def test_versions(self):
        from v8 import ENGINE_VERSION, SCHEMA, discovery as DS, identity as ID, provenance
        self.assertEqual((SCHEMA, ENGINE_VERSION), ("v8.audit/6", "v8-phase8.0"))
        self.assertEqual((H.VERSION, P.VERSION, SL.VERSION), ("v8.history/1", "v8.pit/1", "v8.shadow-ledger/1"))
        self.assertEqual((ID.VERSION, DS.VERSION), ("v8.identity/4", "v8.discovery/1"))
        self.assertEqual(provenance.identity_config_hash(),
                         "96a10dc22e22d0bcf2c6ed1970ea1de72307426dfad2b53020a2b998c125d12c")

    def test_no_live_engine_reads_history_or_research(self):
        pat = re.compile(r"^\s*(from\s+(v8|\.)\s+import\s+[^\n]*\b(history|pit|shadow_ledger)\b|import\s+v8\.(history|pit|"
                         r"shadow_ledger)|from\s+v8\.(history|pit|shadow_ledger)|from\s+\.(history|pit|shadow_ledger)"
                         r"|import\s+(pit_cost|pit_sim|pit_research)|from\s+(pit_cost|pit_sim|pit_research))", re.M)
        live = ["scanner.py", "quant.py", "picks.py", "smart.py", "dashboard.py"]
        live += [f for f in glob.glob(os.path.join(ROOT, "v8", "*.py"))
                 if os.path.basename(f) not in ("snapshot.py", "history.py", "pit.py", "shadow_ledger.py")]
        for f in live:
            p = f if os.path.isabs(f) else os.path.join(ROOT, f)
            with open(p) as fh:
                self.assertIsNone(pat.search(fh.read()), p)
        with open(os.path.join(ROOT, "v8", "snapshot.py")) as fh:
            src = fh.read()
        self.assertNotRegex(src, r"import\s+[^\n]*\bpit\b")

    def test_history_holds_no_secret(self):
        s = snapshot(T0, "gh-1-1", base_contracts())
        blob = json.dumps(H.scan_content(s)) + json.dumps(H.state_from_snapshot(s))
        for w in ("token", "secret", "password", "api_key", "authorization"):
            self.assertNotIn(w, blob.lower())

    def test_legacy_research_files_untouched(self):
        out = subprocess.run(["git", "diff", "--name-only", "1609e2cf7c95abe9f1c0d7d4df92a5dfcef40280", "--",
                              "quant_research.json", "picks_research.json", "tools/research/qsim.py",
                              "tools/research/qstrat.py", "tools/research/qexport.py", "tools/research/pk_trades.py"],
                             cwd=ROOT, capture_output=True, text=True)
        if out.returncode == 0:
            self.assertEqual(out.stdout.strip(), "")

    def test_storage_projection_runs(self):
        snap = snapshot(T0, "gh-1-1", base_contracts())
        r = H.project(snap, days=1, scans_per_day=6)
        self.assertTrue(r["chain_verified"])
        for k in ("observation_bytes_mean", "observations_per_day", "projected_30d_bytes", "projected_1y_bytes",
                  "projected_3y_bytes", "git_packed_bytes", "fetch_tree_bytes_per_scan_after_3y"):
            self.assertIn(k, r)
        self.assertEqual(r["observations_simulated"], 6)


class ScanGateInvariants(unittest.TestCase):
    """Critical Phase 8 invariants, cheap enough for every scan: an unconfigured or failing history never changes
    the scan's outputs, a degraded capture is visible, the history is append-only and verified, unknown is never
    false, and no live engine imports the research view."""

    def test_capture_never_raises(self):
        st = H.capture({"manifest": {}}, store=object())
        self.assertEqual(st["persistence_state"], H.DEGRADED)

    def test_unknown_is_never_false(self):
        self.assertIsNone(P.eligible({"state": P.UNKNOWN}, None, None, 1e6))
        self.assertIsNone(P.eligible({"state": P.KNOWN_ACTIVE}, {"identity": "VERIFIED_CRYPTO", "universe": "CRYPTO"},
                                     {"state": P.LIQUIDITY_HISTORY_UNKNOWN}, 1e6))

    def test_isolation(self):
        VersionsAndIsolation("test_no_live_engine_reads_history_or_research").test_no_live_engine_reads_history_or_research()


# --------------------------------------------------------------------------- research costs (NUMPY)
if HAVE_NUMPY:
    sys.path.insert(0, os.path.join(ROOT, "tools", "research"))


def synthetic_md(folder, coins, t0, hours, trade_vol=None, funding=None, seed=3):
    """A small market-data export: universe.json, h1 and h4 gzip CSVs, MEXC funding."""
    import numpy as np
    rng = np.random.default_rng(seed)
    for sub in ("h1", "h4", "fund_mexc"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    uni = {"time": t0 + hours * HOUR, "min_vol": 300_000, "trade_dexes": ["hyperliquid"], "dex_status": {},
           "coins": [{"t": c, "trade_vol": (trade_vol or {}).get(c, 5e6)} for c in coins]}
    with open(os.path.join(folder, "universe.json"), "w") as fh:
        json.dump(uni, fh)
    for j, c in enumerate(coins):
        px = 100.0 * np.exp(np.cumsum(rng.normal(0.0004 * (1 if j % 2 else -1), 0.01, hours)))
        rows = []
        for i in range(hours):
            o = px[i - 1] if i else px[0]
            cl = px[i]
            rows.append((t0 + i * HOUR, o, max(o, cl) * 1.002, min(o, cl) * 0.998, cl, 2e6))
        for sub, bar in (("h1", 1), ("h4", 4)):
            with gzip.open(os.path.join(folder, sub, f"{c}.csv.gz"), "wt") as fh:
                fh.write("t,o,h,l,c,v\n")
                for k in range(0, hours - bar + 1, bar):
                    seg = rows[k:k + bar]
                    fh.write(f"{seg[0][0]},{seg[0][1]},{max(x[2] for x in seg)},{min(x[3] for x in seg)},"
                             f"{seg[-1][4]},{sum(x[5] for x in seg)}\n")
        ser = (funding or {}).get(c)
        if ser is not None:
            with gzip.open(os.path.join(folder, "fund_mexc", f"{c}.csv.gz"), "wt") as fh:
                fh.write("t,rate,cycle_h\n")
                for t, r, cyc in ser:
                    fh.write(f"{t},{r},{cyc}\n")


@unittest.skipUnless(HAVE_NUMPY, "numpy and numba (the CI research-checks job runs these)")
class ResearchCosts(Tmp):
    def test_tiers_unchanged(self):
        import pit_cost as PC
        self.assertEqual([PC.tier(v) for v in (5e6, 1e6, 999_999, 2e5, 199_999, 0)],
                         [0.0005, 0.0005, 0.001, 0.001, 0.002, 0.002])
        self.assertEqual(PC.SLIP_TIERS, ((1_000_000.0, 0.0005), (200_000.0, 0.001), (0.0, 0.002)))

    def test_slippage_is_time_varying_and_today_never_changes_the_past(self):
        import numpy as np
        import pit_cost as PC
        st = self.store()
        for k, vol in enumerate((5e6, 500_000, 100_000)):
            append(st, snapshot(T0 + k * 5 * HOUR, f"gh-{k}-1", [contract("hyperliquid:X", "X", vol=vol)]))
        h = P.History(st)
        times = [T0 + 60, T0 + 5 * HOUR + 60, T0 + 10 * HOUR + 60, T0 - 1, T0 + 10 * HOUR + 13 * HOUR]
        vol, state, slip = PC.liquidity_panel(h, times, ["X", "Y"])
        self.assertEqual(list(slip[:3, 0]), [0.0005, 0.001, 0.002])
        self.assertTrue(np.isnan(slip[3, 0]) and np.isnan(slip[4, 0]))           # before / stale: unknown
        self.assertEqual(state[3, 0], PC.L_UNKNOWN)
        self.assertTrue(np.isnan(slip[:, 1]).all())                               # never observed: unknown
        # a new observation today does not change the cost of an old trade
        append(st, snapshot(T0 + 20 * HOUR, "gh-9-1", [contract("hyperliquid:X", "X", vol=9e9)]))
        _, _, slip2 = PC.liquidity_panel(P.History(st), times[:3], ["X"])
        self.assertEqual(list(slip2[:, 0]), [0.0005, 0.001, 0.002])
        self.assertEqual(list(PC.legacy_slip([5e6, 5e5, 1e5])), [0.0005, 0.001, 0.002])

    def test_funding_states(self):
        import numpy as np
        import pit_cost as PC
        t = np.arange(T0, T0 + 48 * HOUR, HOUR)
        ser = [(T0 + 8 * HOUR, 0.0002, 8), (T0 + 16 * HOUR, 0.0, 8), (T0 + 40 * HOUR, 0.0001, 8)]
        rate, state = PC.funding_panel_from_series(t, ser)
        self.assertTrue((state[:8] == PC.F_MISSING).all())                      # before the first settlement
        self.assertEqual(state[8], PC.F_OBSERVED)
        self.assertEqual(state[16], PC.F_OBSERVED_ZERO)
        self.assertTrue((state[9:16] == PC.F_NOT_DUE).all())
        self.assertTrue((state[24:40] == PC.F_MISSING).all())                    # the gap: 24h and 32h never came
        self.assertEqual(state[40], PC.F_OBSERVED)
        self.assertTrue((state[41:48] == PC.F_NOT_DUE).all())
        self.assertAlmostEqual(rate.sum(), 0.0003)
        self.assertEqual(rate[24:40].sum(), 0.0)                                  # never filled with 0.01% / 8h
        scen = PC.scenario_funding(t, state[:, None])
        self.assertAlmostEqual(scen[:, 0].sum(), 0.0001 * 3)                       # 0h, 24h, 32h: scenario only
        r2, s2 = PC.funding_panel_from_series(t, [])
        self.assertTrue((s2 == PC.F_MISSING).all() and r2.sum() == 0)

    def test_trade_costs(self):
        import numpy as np
        import pit_cost as PC
        T, N = 10, 2
        slip = np.full((T, N), 0.001)
        slip[6, 0] = np.nan
        fr = np.zeros((T, N))
        fr[3, 0] = 0.0005
        fs = np.zeros((T, N), dtype=np.int8)
        fs[8, 1] = PC.F_MISSING
        c = PC.trade_costs([1, 1, 1], [4, 6, 9], [0, 0, 1], [1, -1, 1], [False, True, False], slip, fr, fs)
        self.assertAlmostEqual(c["cost"][0], 0.00045 * 2 + 0.002 + 0.0005)
        self.assertAlmostEqual(c["cost"][1], 0.00045 + 0.00015 + 0.001 - 0.0005)    # take-profit: maker, no exit slip
        self.assertTrue(c["liquidity_known"][1])
        self.assertFalse(c["funding_known"][2])
        c2 = PC.trade_costs([1], [6], [0], [1], [False], slip, fr, fs)
        self.assertFalse(c2["liquidity_known"][0])
        self.assertNotAlmostEqual(c["cost"][0], 0.0019)


@unittest.skipUnless(HAVE_NUMPY, "numpy, numba and pandas (the CI research-checks job runs these)")
class CorrectedResearch(Tmp):
    def test_end_to_end(self):
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas")
        import pit_research as PR
        coins = ["BTC"] + [f"C{k:02d}" for k in range(11)]
        hours = 24 * 160
        t0 = T0 - 150 * 24 * HOUR
        fund = {c: [(t0 + k * 8 * HOUR, 0.0001, 8) for k in range(hours // 8)] for c in coins}
        md = os.path.join(self.tmp, "md")
        synthetic_md(md, coins, t0, hours, funding=fund)
        st = self.store("hist")
        cs = [contract(f"hyperliquid:{c}", c, vol=5e6) for c in coins]
        for k in range(0, 150 * 6):                              # every 4 hours for the last 150 days
            ts = t0 + 10 * 24 * HOUR + k * 4 * HOUR
            if ts > t0 + hours * HOUR:
                break
            append(st, snapshot(ts, f"gh-{k}-1", cs))
        cutoff = t0 + (hours - 1) * HOUR
        out = PR.run(md, st.root, cutoff=cutoff)
        q = out["qualified_window"]
        self.assertGreater(q["hours"], 0)
        for sid, r in out["quant"].items():
            self.assertEqual(r["legacy"]["label"], PR.LEGACY)
            self.assertEqual(r["scenario"]["label"], PR.SCENARIO)
            c = r["corrected"]
            self.assertEqual(c["fully_qualified"], c["components"].get("fully_qualified_closed", 0))
            if c["fully_qualified"]:
                self.assertEqual(c["authoritative"]["n"], c["fully_qualified"])
        self.assertTrue(any(r["corrected"]["fully_qualified"] for r in out["quant"].values()), out["quant"])
        self.assertEqual(out["promotion"].split(":")[0], "NONE")
        # parity: with full coverage and the same inputs as the legacy run (today's volume equal to the recorded
        # one, observed funding everywhere) the point-in-time re-costing reproduces qsim's result exactly
        for sid, r in out["quant"].items():
            self.assertEqual(r["corrected"]["authoritative"]["n"], r["legacy"]["trades"], sid)
            self.assertAlmostEqual(r["corrected"]["authoritative"]["avg_R"], r["legacy"]["avg_R"], places=3, msg=sid)
        # today's volume changes the legacy result, never the point-in-time one
        with open(os.path.join(md, "universe.json")) as fh:
            u = json.load(fh)
        for c in u["coins"]:
            c["trade_vol"] = 50_000.0
        with open(os.path.join(md, "universe.json"), "w") as fh:
            json.dump(u, fh)
        out3 = PR.run(md, st.root, cutoff=cutoff)
        for sid in out["quant"]:
            self.assertEqual(out3["quant"][sid]["corrected"]["authoritative"],
                             out["quant"][sid]["corrected"]["authoritative"], sid)
            self.assertLess(out3["quant"][sid]["legacy"]["avg_R"], out["quant"][sid]["legacy"]["avg_R"], sid)
        # no history: nothing qualifies, legacy still labelled
        out2 = PR.run(md, os.path.join(self.tmp, "nohist"), cutoff=cutoff)
        for r in out2["quant"].values():
            self.assertEqual(r["corrected"]["fully_qualified"], 0)
            self.assertEqual(r["corrected"]["authoritative"], {"n": 0})
        self.assertEqual(out2["qualified_window"]["hours"], 0)
