"""Point-in-time view of the v8 history (v8 Phase 8). RESEARCH ONLY: no live engine imports this module.

    Historical research may use only information that was actually knowable at that historical time.

`History` reads a verified v8.history/1 chain (v8.history) and answers, for any time t, only from observations with
observed_at <= t that are at most MAX_STALENESS_S old:

    universe_at(t)     every asset the history had seen by t: KNOWN_ACTIVE (an active perpetual on a venue whose
                       market list loaded), KNOWN_INACTIVE (seen before, and every venue it was seen on loaded and
                       no longer lists it as active) or UNKNOWN (no observation fresh enough, a venue it was seen on
                       was unavailable, the fallback universe, a broken chain). UNKNOWN is never False or zero.
                       An asset first observed after t is absent: a future listing never leaks back.
    identity_at(t, a)  the identity state, decision, version and config hash recorded then (never today's); an
                       observation older than the identity states (v8.audit/1 and /2) leaves it unknown
    liquidity_at(t, a) the execution liquidity recorded then (KNOWN / MISSING / NOT_ON_TRADE_DEX with the trade-DEX
                       volume), or LIQUIDITY_HISTORY_UNKNOWN when no liquidity observation is fresh enough
    intervals(a)       listing intervals: eligible_from = first observed active; last observed active and first
                       observed inactive; a gap or an outage ends an interval as UNKNOWN, never as a delisting;
                       a re-listing opens a new interval
    exposure_at(t, c)  a contract's asset and price-coherent exposure as recorded then

Staleness: production scans have been observed up to ~7.3 hours apart (GitHub schedules are best effort), so
MAX_STALENESS_S is 12 hours: an observation older than that answers nothing (PIT_UNIVERSE_GAP). The same bound applies
to liquidity, recorded about every 4 hours (v8.history.LIQUIDITY_EVERY_S).

A chain that fails verification answers nothing (HISTORY_INTEGRITY_FAILED): research fails closed."""
from __future__ import annotations

import bisect
from collections import OrderedDict

from . import history as H

VERSION = "v8.pit/1"
MAX_STALENESS_S = 12 * 3600
LIQUIDITY_MAX_STALENESS_S = 12 * 3600
KNOWN_ACTIVE, KNOWN_INACTIVE, UNKNOWN = "KNOWN_ACTIVE", "KNOWN_INACTIVE", "UNKNOWN"
PIT_UNIVERSE_OK, PIT_UNIVERSE_GAP = "PIT_UNIVERSE_OK", "PIT_UNIVERSE_GAP"
LIQUIDITY_HISTORY_OK, LIQUIDITY_HISTORY_GAP = "LIQUIDITY_HISTORY_OK", "LIQUIDITY_HISTORY_GAP"
LIQUIDITY_HISTORY_UNKNOWN = "LIQUIDITY_HISTORY_UNKNOWN"
HISTORY_INTEGRITY_FAILED, HISTORY_EMPTY = "HISTORY_INTEGRITY_FAILED", "HISTORY_EMPTY"
BEFORE_HISTORY, STALE, VENUE_UNAVAILABLE, FALLBACK = "BEFORE_HISTORY", "STALE", "VENUE_UNAVAILABLE", \
    "FALLBACK_UNIVERSE"
OBSERVED_ACTIVE, OBSERVED_NOT_TRADING, OBSERVED_ABSENT = "OBSERVED_ACTIVE", "OBSERVED_NOT_TRADING", \
    "OBSERVED_ABSENT"
VERIFIED_CRYPTO = "VERIFIED_CRYPTO"


def _loaded(ob, venue):
    """Whether this observation saw the venue's market list (OK, or loaded with no or no active markets). A venue
    that failed, or that the observation does not mention, says nothing about the assets listed there."""
    return ob.venues.get(venue) in ("OK", "NO_MARKETS", "ZERO_ACTIVE_MARKETS")


class _Obs:
    __slots__ = ("seq", "scan_id", "observed_at", "venues", "fallback", "versions", "source", "liquidity")

    def __init__(self, o):
        self.seq, self.scan_id, self.observed_at = o["seq"], o["scan_id"], o["observed_at"]
        self.venues = o.get("venues") or {}
        self.fallback = bool((o.get("coverage") or {}).get("fallback_universe"))
        self.versions = o.get("versions") or {}
        self.source = (o.get("source") or {}).get("type")
        self.liquidity = o.get("liquidity") is not None


class History:
    """A verified history, indexed in observation-time order. `assets` limits what is kept (memory) to those
    tickers; the universe of other assets is then not answered."""

    def __init__(self, store, assets=None, max_staleness_s=MAX_STALENESS_S,
                 liquidity_max_staleness_s=LIQUIDITY_MAX_STALENESS_S, cutoff=None):
        self.cutoff = cutoff                 # observations observed after the cutoff are not used
        self.report = H.verify(store)
        self.ok = bool(self.report["ok"]) and self.report["observations"] > 0
        self.max_staleness_s = max_staleness_s
        self.liq_max_staleness_s = liquidity_max_staleness_s
        self.keep = set(assets) if assets is not None else None
        self.obs = []                    # _Obs in observation-time order
        self.times = []
        self._asset = {}                 # asset -> ([obs index], [point]) run-length, observation-time order
        self._ident = {}                 # asset -> ([obs index], [identity row]) run-length
        self._liq = {}                   # asset -> ([observed_at], [(state, value)]) every liquidity observation
        self._contract = {}              # contract -> ([obs index], [row or None]) run-length
        self.status = (PIT_UNIVERSE_OK if self.ok else
                       HISTORY_EMPTY if self.report["observations"] == 0 else HISTORY_INTEGRITY_FAILED)
        if self.ok:
            self._build(store)

    # ------------------------------------------------------------------ indexing
    def _build(self, store):
        heads = []
        for p in store.paths():
            o = H.decode(store.read_bytes(p))
            heads.append((o["observed_at"], o["seq"], p, o.get("state_mode"), (o.get("base") or {}).get("seq")))
        paths_by_seq = {s: p for _, s, p, _, _ in heads}       # every observation (a delta's base may be later)
        heads = sorted(h for h in heads if self.cutoff is None or h[0] <= self.cutoff)
        cache = OrderedDict()                       # base checkpoint states (LRU)

        def base_state(seq):
            if seq in cache:
                cache.move_to_end(seq)
                return cache[seq]
            st = H.full_state(H.decode(store.read_bytes(paths_by_seq[seq])))
            cache[seq] = st
            if len(cache) > 4:
                cache.popitem(last=False)
            return st

        seen_venues = {}                            # asset -> venues it was seen listed on, up to this observation
        prev_point, prev_ident, prev_contract = {}, {}, {}
        for i, (t, seq, p, mode, bseq) in enumerate(heads):
            o = H.decode(store.read_bytes(p))
            state = base_state(seq) if mode == H.CHECKPOINT else H.full_state(o, base_state(bseq))
            ob = _Obs(o)
            self.obs.append(ob)
            self.times.append(t)
            by_asset = {}
            for row in state["contracts"].values():
                cid, venue, asset, active = row[0], row[1], row[2], row[3]
                if not isinstance(asset, str) or (self.keep is not None and asset not in self.keep):
                    continue
                by_asset.setdefault(asset, []).append(row)
                crow = tuple(row)
                if prev_contract.get(cid) != crow:
                    self._rl(self._contract, cid, i, crow)
                    prev_contract[cid] = crow
            for cid in [c for c in prev_contract if c not in state["contracts"] and prev_contract[c] is not None]:
                self._rl(self._contract, cid, i, None)       # absent this observation (venue may be unavailable)
                prev_contract[cid] = None
            for a, rows in by_asset.items():
                seen_venues.setdefault(a, set()).update(r[1] for r in rows)
            for a in seen_venues:
                pt = self._point(ob, by_asset.get(a) or [], seen_venues[a])
                if prev_point.get(a) != pt:
                    self._rl(self._asset, a, i, pt)
                    prev_point[a] = pt
            for a, row in state["assets"].items():
                if self.keep is not None and a not in self.keep:
                    continue
                r = tuple(row)
                if prev_ident.get(a) != r:
                    self._rl(self._ident, a, i, r)
                    prev_ident[a] = r
            if o.get("liquidity") is not None:
                for row in o["liquidity"]["rows"]:
                    if self.keep is not None and row[0] not in self.keep:
                        continue
                    ts, vs = self._liq.setdefault(row[0], ([], []))
                    ts.append(t)
                    vs.append((row[1], row[2]))
        for ts, vs in self._liq.values():           # observation-time order (a backfill may arrive late)
            order = sorted(range(len(ts)), key=lambda k: ts[k])
            ts[:], vs[:] = [ts[k] for k in order], [vs[k] for k in order]

    @staticmethod
    def _rl(index, key, i, value):
        ix, vs = index.setdefault(key, ([], []))
        ix.append(i)
        vs.append(value)

    @staticmethod
    def _point(ob, rows, seen):
        """(state, reason, active venues, exposures) of one asset in one observation."""
        if ob.fallback:
            return (UNKNOWN, FALLBACK, (), ())
        ok_rows = [r for r in rows if _loaded(ob, r[1])]
        act = sorted({r[1] for r in ok_rows if r[3]})
        if act:
            return (KNOWN_ACTIVE, OBSERVED_ACTIVE, tuple(act),
                    tuple(sorted({r[5] for r in ok_rows if r[3] and r[5]})))
        down = sorted(v for v in seen if not _loaded(ob, v))
        if down:
            return (UNKNOWN, VENUE_UNAVAILABLE, (), ())
        return (KNOWN_INACTIVE, OBSERVED_NOT_TRADING if rows else OBSERVED_ABSENT, (), ())

    # ------------------------------------------------------------------ lookups
    def _at(self, t):
        """(index of the latest observation with observed_at <= t, why not usable or None)."""
        if not self.ok:
            return None, self.status
        if not self.times:
            return None, HISTORY_EMPTY
        i = bisect.bisect_right(self.times, t) - 1
        if i < 0:
            return None, BEFORE_HISTORY
        if t - self.times[i] > self.max_staleness_s:
            return i, STALE
        return i, None

    @staticmethod
    def _lookup(index, key, i):
        ix, vs = index.get(key, ((), ()))
        k = bisect.bisect_right(ix, i) - 1
        return vs[k] if k >= 0 else None

    def observation_at(self, t):
        i, why = self._at(t)
        if i is None:
            return {"state": PIT_UNIVERSE_GAP, "reason": why, "observation": None}
        ob = self.obs[i]
        return {"state": PIT_UNIVERSE_GAP if why else PIT_UNIVERSE_OK, "reason": why,
                "observation": {"scan_id": ob.scan_id, "seq": ob.seq, "observed_at": ob.observed_at,
                                "age_s": t - ob.observed_at, "source": ob.source, "fallback": ob.fallback,
                                "venues": dict(ob.venues), "identity_version": ob.versions.get("identity"),
                                "identity_config_hash": ob.versions.get("identity_config_hash")}}

    def asset_at(self, t, asset):
        """{state, reason, venues, exposures, observed_at} of one asset at t, or None when the history had not seen
        it by then (unknown to the past)."""
        i, why = self._at(t)
        if i is None and why != BEFORE_HISTORY:
            return {"state": UNKNOWN, "reason": why}
        if i is None:
            return None
        pt = self._lookup(self._asset, asset, i)
        if pt is None:
            return None
        if why:
            return {"state": UNKNOWN, "reason": why, "observed_at": self.obs[i].observed_at}
        return {"state": pt[0], "reason": pt[1], "venues": list(pt[2]), "exposures": list(pt[3]),
                "observed_at": self.obs[i].observed_at}

    def identity_at(self, t, asset):
        i, why = self._at(t)
        if i is None or why:
            return {"state": UNKNOWN, "reason": why or BEFORE_HISTORY}
        r = self._lookup(self._ident, asset, i)
        if r is None:
            return None
        ob = self.obs[i]
        return {"universe": r[1], "identity": r[2], "decision": r[3], "reason": r[4], "authority": r[5],
                "identity_version": ob.versions.get("identity"),
                "identity_config_hash": ob.versions.get("identity_config_hash"), "observed_at": ob.observed_at}

    def crypto_identity_at(self, t, asset):
        """True / False when the identity recorded at t is / is not verified crypto; None when unknown (no fresh
        observation, or an observation made before the audit recorded identity states - v8.audit/1 and /2)."""
        r = self.identity_at(t, asset)
        if r is None or r.get("state") == UNKNOWN or r.get("identity") is None:
            return None
        return r["identity"] == VERIFIED_CRYPTO and r["universe"] == "CRYPTO"

    def liquidity_at(self, t, asset):
        """{state, value, observed_at, age_s, health} of the latest liquidity observation at or before t."""
        if not self.ok:
            return {"state": LIQUIDITY_HISTORY_UNKNOWN, "value": None, "health": LIQUIDITY_HISTORY_GAP,
                    "reason": self.status}
        ts, vs = self._liq.get(asset, ((), ()))
        k = bisect.bisect_right(ts, t) - 1
        if k < 0:
            return {"state": LIQUIDITY_HISTORY_UNKNOWN, "value": None, "health": LIQUIDITY_HISTORY_GAP,
                    "reason": BEFORE_HISTORY}
        if t - ts[k] > self.liq_max_staleness_s:
            return {"state": LIQUIDITY_HISTORY_UNKNOWN, "value": None, "health": LIQUIDITY_HISTORY_GAP,
                    "reason": STALE, "observed_at": ts[k], "age_s": t - ts[k]}
        st, v = vs[k]
        return {"state": st, "value": v, "observed_at": ts[k], "age_s": t - ts[k], "health": LIQUIDITY_HISTORY_OK,
                "reason": None}

    def exposure_at(self, t, contract_id):
        i, why = self._at(t)
        if i is None or why:
            return {"state": UNKNOWN, "reason": why or BEFORE_HISTORY}
        r = self._lookup(self._contract, contract_id, i)
        if r is None:
            ix = self._contract.get(contract_id, ((),))[0]
            return None if not ix or ix[0] > i else {"state": UNKNOWN, "reason": "ABSENT_THIS_OBSERVATION"}
        return {"venue": r[1], "asset": r[2], "active": bool(r[3]), "legacy": r[4], "exposure": r[5],
                "exp_state": r[6], "observed_at": self.obs[i].observed_at}

    def universe_at(self, t, min_vol=None):
        """The point-in-time universe: every asset seen by t with its state, identity and liquidity then, and
        `research_eligible` (True / False / None=unknown): KNOWN_ACTIVE, verified crypto identity and, when min_vol
        is given, a KNOWN trade-DEX volume of at least min_vol from a fresh liquidity observation."""
        head = self.observation_at(t)
        out = {}
        i, why = self._at(t)
        if i is None:
            return {"t": t, "header": head, "assets": out}
        for a in sorted(self._asset):
            ast = self.asset_at(t, a)
            if ast is None:
                continue
            ident = self.identity_at(t, a)
            liq = self.liquidity_at(t, a)
            out[a] = {"state": ast["state"], "reason": ast["reason"], "venues": ast.get("venues"),
                      "identity": None if ident is None else ident.get("identity"),
                      "liquidity": {"state": liq["state"], "value": liq["value"], "health": liq["health"]},
                      "research_eligible": eligible(ast, ident, liq, min_vol)}
        return {"t": t, "header": head, "assets": out}

    def intervals(self, asset):
        """Listing intervals of one asset in observation time: {first_observed_active (= eligible_from),
        listing_known (an earlier observation that covered it saw it inactive or absent), last_observed_active,
        first_observed_inactive, end: DELISTED_OR_HALTED_OBSERVED | UNKNOWN_GAP | OPEN}."""
        if not self.ok:
            return []
        ix, vs = self._asset.get(asset, ((), ()))
        out, cur, prev_known_inactive = [], None, False
        # walk every observation from the asset's first point (run-length expanded where staleness matters)
        if not ix:
            return []
        for i in range(ix[0], len(self.obs)):
            pt = self._lookup(self._asset, asset, i)
            t = self.times[i]
            gap = cur is not None and i > 0 and t - self.times[i - 1] > self.max_staleness_s
            if gap:
                cur.update(end="UNKNOWN_GAP")
                out.append(cur)
                cur = None
            st = pt[0]
            if st == KNOWN_ACTIVE:
                if cur is None:
                    cur = {"first_observed_active": t, "eligible_from": t, "listing_known": prev_known_inactive,
                           "last_observed_active": t, "first_observed_inactive": None, "end": "OPEN"}
                else:
                    cur["last_observed_active"] = t
                prev_known_inactive = False
            elif st == KNOWN_INACTIVE:
                if cur is not None:
                    cur.update(first_observed_inactive=t, end="DELISTED_OR_HALTED_OBSERVED")
                    out.append(cur)
                    cur = None
                prev_known_inactive = True
            else:       # UNKNOWN: an outage or the fallback universe - neither listed nor delisted
                prev_known_inactive = False
        if cur is not None:
            if self.times and self.times[-1] - cur["last_observed_active"] > self.max_staleness_s:
                cur["end"] = "UNKNOWN_GAP"
            out.append(cur)
        return out

    def gaps(self):
        """Windows with no observation fresh enough (PIT_UNIVERSE_GAP), in observation time."""
        out = []
        for a, b in zip(self.times, self.times[1:]):
            if b - a > self.max_staleness_s:
                out.append({"from": a + self.max_staleness_s, "to": b, "seconds": b - a - self.max_staleness_s})
        return out

    def window(self):
        """The point-in-time window this history supports (observation time)."""
        if self.ok and not self.obs:
            return {"status": HISTORY_EMPTY, "start": None, "end": None, "observations": 0, "cutoff": self.cutoff}
        if not self.ok:
            return {"status": self.status, "start": None, "end": None, "observations": self.report["observations"]}
        return {"status": PIT_UNIVERSE_OK, "start": self.times[0], "end": self.times[-1] + self.max_staleness_s,
                "last_observation": self.times[-1], "observations": len(self.obs),
                "liquidity_observations": sum(1 for o in self.obs if o.liquidity),
                "backfilled": sum(1 for o in self.obs if o.source == H.ARTIFACT), "gaps": self.gaps(),
                "cutoff": self.cutoff}


def eligible(asset_point, ident, liq, min_vol=None):
    """research_eligible at one time: True / False when every input was known then, None when any was unknown."""
    if asset_point is None or asset_point.get("state") == UNKNOWN:
        return None
    if asset_point["state"] == KNOWN_INACTIVE:
        return False
    if ident is None or ident.get("state") == UNKNOWN or ident.get("identity") is None:
        return None              # identity not recorded then (before v8.audit/3): unknown, never "not crypto"
    if not (ident.get("identity") == VERIFIED_CRYPTO and ident.get("universe") == "CRYPTO"):
        return False
    if min_vol is None:
        return True
    if liq is None or liq.get("state") == LIQUIDITY_HISTORY_UNKNOWN:
        return None
    if liq["state"] != "KNOWN":
        return False if liq["state"] == "NOT_ON_TRADE_DEX" else None
    return liq["value"] >= min_vol
