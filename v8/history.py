"""Durable point-in-time history (v8 Phase 8): an append-only record of what each production scan observed.

    Historical research may use only information that was actually knowable at that historical time.

What is kept, per scan, is only what research needs to know the past truthfully: which perpetual contracts each venue
listed and whether they were active, how each contract mapped to its asset and price-coherent exposure, the asset's
identity as it was decided then (with the identity version and config hash), each venue's health (an unavailable
market list is not a delisting), and - at a governed cadence - each asset's execution liquidity (trade-DEX volume).
Nothing else: no prices, signals or scores, and never a multi-megabyte audit snapshot.

Storage: the `v8-history` branch, separate from the code. One gzip JSON file per observation,
    obs/<YYYY>/<MM>/<DD>/<seq:08d>-<scan_id>.json.gz      (the UTC day the observation was appended)
written with git plumbing and pushed without --force. A file is never modified or deleted.

An observation is a CHECKPOINT (the full contract and asset state) or a DELTA (the rows that differ from its base: the
newest checkpoint before it, named by seq and hash). A checkpoint is written at genesis, for every backfilled
observation, when the newest checkpoint is older than CHECKPOINT_EVERY_S and whenever the chain end cannot be
checked. Appending reads at most three observations (the last, the one before it, the base checkpoint), so a scan's
cost does not grow with the history. Liquidity is recorded when the last liquidity observation is LIQUIDITY_EVERY_S
or more away from this one (and in every backfilled observation).

Integrity: every observation carries `seq` (append order), `record_hash` (sha256 of every persisted field except
itself), `prev_hash` (the previous record hash) and `content_hash` (its full scan authority, including a digest of
the complete liquidity state on every scan, even when its table is omitted). Rewriting, removing or reordering any
observation breaks the chain and `verify()` reports it. This makes retroactive edits detectable; it does not make
them impossible (the branch is ordinary git; a repository rule protecting it is recommended).

Versions (one append-only chain, never migrated): `v8.history/1` observations (the first production records, up to
the Phase 8 post-merge hotfix) stored each liquidity value rounded to a whole dollar, which can cross the $200k and
$1M thresholds (199,999.6 became 200,000): their KNOWN liquidity is PRECISION_LOST for cost authority (v8.pit), while
their contracts, assets, identity and venue health stay usable. `v8.history/2` (the writer since the hotfix) stores
the finite value exactly as the audit registry recorded it (8 significant digits, `liquidity_precision`). Records
are verified under their own schema; a v2 record links to the previous record's hash whatever its version, a v2
delta's base is a v2 checkpoint (the first v2 observation is a checkpoint with liquidity), and no v1 record may
follow a v2 record.

Backfill: only from a genuinely contemporaneous record - an archived production audit snapshot (the 14-day
`v8-audit-*` Actions artifacts) whose manifest names its own scan id and commit. Each backfilled observation cites
the artifact (id, name, run, created_at, digest) and is a checkpoint. Nothing is reconstructed from today's state.

A capture failure never touches the scan's published outputs: capture() never raises and reports
HISTORY_CAPTURE_DEGRADED, and research treats the missing interval as unknown (v8.pit staleness)."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import zipfile

V1, V2 = "v8.history/1", "v8.history/2"
VERSION = V2                       # what this writer appends
SCHEMAS = (V1, V2)                 # what the verifier accepts, in this order only (never v1 after v2)
# the precision of a v2 liquidity value: the audit registry stores every contract's volume with 8 significant
# digits (v8.registry._r); v2 keeps exactly that value (no further rounding). v1 rounded it to a whole dollar.
LIQUIDITY_PRECISION = {"source": "audit registry contract volume", "significant_digits": 8, "rounding": "NONE"}
BRANCH = "v8-history"
CHECKPOINT_EVERY_S = 24 * 3600
LIQUIDITY_EVERY_S = 4 * 3600
OBS_DIR = "obs"
PERSISTED, REPLAY, DEGRADED, NOT_CONFIGURED = "PERSISTED", "IDEMPOTENT_REPLAY", "HISTORY_CAPTURE_DEGRADED", \
    "NOT_CONFIGURED"
SCAN, ARTIFACT = "SCAN", "ARCHIVED_SCAN_ARTIFACT"
CHECKPOINT, DELTA = "CHECKPOINT", "DELTA"
CONTRACT_FIELDS = ("id", "venue", "asset", "active", "state", "exposure", "exp_state")
ASSET_FIELDS = ("asset", "universe", "identity", "decision", "reason", "authority")
LIQUIDITY_FIELDS = ("asset", "state", "trade_vol")
TRADE_DEXES = ("hyperliquid", "lighter", "aster", "variational")     # scanner CFG["trade_dexes"] (unchanged)
README = """# v8-history (v8.history/1, then v8.history/2)

Append-only point-in-time history written by the production Scan workflow (`python -m v8.snapshot
--history-branch v8-history`). One gzip JSON observation per scan under `obs/<YYYY>/<MM>/<DD>/`, chained by
`prev_hash`. Never force-pushed, never rewritten, never deleted. See docs/v8/phase8-point-in-time-research.md on main.
Verify: `python -m v8.history verify --dir <checkout of this branch>`.
"""


# --------------------------------------------------------------------------- canonical bytes and hashes
def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def gz(b):
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as fh:
        fh.write(b)
    return buf.getvalue()


# how an observation was appended and encoded (not what the scan saw); `source` (how the record reached the history:
# live from the scan, or backfilled from an archived artifact) is provenance, also outside the content hash so that
# the same scan recorded twice is recognised as the same observation
CHAIN_KEYS = ("seq", "prev_hash", "appended_at", "stored_bytes_before", "content_hash", "state_mode", "base",
              "last_liquidity", "contracts", "assets", "liquidity", "liquidity_content_hash", "record_hash")
NOT_CONTENT = CHAIN_KEYS + ("source",)


def content_hash(content, state):
    """Full scan authority, independent of provenance and checkpoint/liquidity storage cadence.

    Appends/retries hash the full input liquidity; verification uses its persisted digest when rebuilding the
    contract/asset state. A stored liquidity table is independently checked against that digest.
    """
    head = {k: v for k, v in content.items() if k not in NOT_CONTENT}
    head["liquidity_content_hash"] = (liquidity_hash(state["liquidity"]) if "liquidity" in state
                                      else content.get("liquidity_content_hash"))
    return sha(canonical(dict(head, state={"contracts": state["contracts"], "assets": state["assets"]})))


def obs_hash(obs):
    """Governed record hash: every persisted field except the self-verifying record_hash itself.

    The same value is used for record integrity, chain links, checkpoint references and the reported head hash.
    """
    return sha(canonical({k: v for k, v in obs.items() if k != "record_hash"}))


def liquidity_hash(rows):
    """Deterministic digest of the complete liquidity authority from state_from_snapshot()."""
    return sha(canonical(_table(LIQUIDITY_FIELDS, rows)))


def record_problems(obs):
    """Self-verification, including the head and any liquidity payload that is actually stored."""
    problems = []
    if obs.get("record_hash") != obs_hash(obs):
        problems.append("record hash does not match the persisted observation")
    digest = obs.get("liquidity_content_hash")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        problems.append("missing or invalid liquidity content hash")
    if obs.get("liquidity") is not None and sha(canonical(obs["liquidity"])) != digest:
        problems.append("liquidity payload does not match its content hash")
    return problems + schema_problems(obs)


def schema_problems(obs):
    """What each history schema requires of its own record (a v1 record is judged by v1 rules, never migrated)."""
    sch = obs.get("schema")
    if sch not in SCHEMAS:
        return [f"unknown history schema {sch!r}"]
    if sch == V1:
        return []
    problems = []
    if obs.get("liquidity_precision") != LIQUIDITY_PRECISION:
        problems.append("v8.history/2 record without its liquidity precision")
    for row in (obs.get("liquidity") or {}).get("rows") or []:
        ok = len(row) == 3 and ((row[1] == "KNOWN" and _finite(row[2])) or
                                (row[1] in ("MISSING", "NOT_ON_TRADE_DEX") and row[2] is None))
        if not ok:
            problems.append(f"v8.history/2 liquidity row {row!r} is not a finite KNOWN value or a stateful None")
            break
    return problems


# --------------------------------------------------------------------------- what a scan observed
def _contract_records(snap):
    c = (snap.get("registry") or {}).get("contracts") or {}
    if isinstance(c, list):
        return c
    return [dict(zip(c.get("fields") or [], row)) for row in c.get("rows") or []]


# the venue states of v8.discovery.venue_table (Phase 7), computed here without importing discovery (it has no
# authority and only the observational modules may read it); tests/test_v8_phase8.py keeps the two in step
VENUE_OK, VENUE_UNAVAILABLE, NO_MARKETS, ZERO_ACTIVE_MARKETS = "OK", "VENUE_UNAVAILABLE", "NO_MARKETS", \
    "ZERO_ACTIVE_MARKETS"
UNSUPPORTED = ("EMPTY_SYMBOL", "HL_BUILDER_MARKET", "DELISTED", "NOT_PERPETUAL", "NOT_TRADING", "ADAPTER_FAILED")


def venue_states(contracts, registry_venues):
    """{venue: state}: VENUE_UNAVAILABLE (the market list failed or was unreadable), NO_MARKETS (it loaded and
    listed nothing), ZERO_ACTIVE_MARKETS (no active supported perpetual) or OK."""
    out = {}
    for v, vi in sorted((registry_venues or {}).items()):
        vi = vi or {}
        if not vi.get("ok") or vi.get("error"):
            out[v] = VENUE_UNAVAILABLE
        elif not vi.get("raw"):
            out[v] = NO_MARKETS
        elif not any(c.get("venue") == v and c.get("type") == "perp" and c.get("active")
                     and c.get("legacy") not in UNSUPPORTED for c in contracts):
            out[v] = ZERO_ACTIVE_MARKETS
        else:
            out[v] = VENUE_OK
    return out


def _venues(snap, contracts):
    """Each venue's market-list state this scan. A snapshot older than the registry venue detail falls back to the
    manifest's per-venue ok flag: unavailable, or OK."""
    rv = (snap.get("data_health") or {}).get("registry_venues")
    if rv:
        return venue_states(contracts, rv)
    lists = ((snap.get("manifest") or {}).get("data_sources") or {}).get("dex_market_lists") or {}
    return {v: (VENUE_OK if ok else VENUE_UNAVAILABLE) for v, ok in sorted(lists.items())}


def state_from_snapshot(snap):
    """{contracts: {id: row}, assets: {asset: row}, liquidity: {asset: row}} from an audit snapshot (any v8.audit
    schema). Only perpetual contracts are kept; an older snapshot's missing field stays None."""
    cs = _contract_records(snap)
    contracts = {}
    for c in cs:
        cid = c.get("id")
        if c.get("type") != "perp" or not isinstance(cid, str) or not cid:
            continue
        # active: the venue's own listing flag (1 listed and trading, 0 listed but not trading / delisted);
        # state: what the registry made of the contract this scan (SELECTED, NOT_TRADING, DELISTED, ...)
        contracts[cid] = [cid, c.get("venue"), c.get("asset"), 1 if c.get("active") else 0, c.get("legacy"),
                          c.get("exposure"), c.get("exp_state")]
    assets = {}
    for t, a in sorted(((snap.get("registry") or {}).get("assets") or {}).items()):
        if not isinstance(t, str) or not t:
            continue
        ib = a.get("identity") or {}
        assets[t] = [t, a.get("legacy"), ib.get("state"), ib.get("decision"), ib.get("reason"), ib.get("authority")]
    # execution liquidity as the coin record held it: the largest 24h volume reported by the asset's selected
    # markets on the trade DEXs (KNOWN, an observed 0 included), MISSING when none of them reported one,
    # NOT_ON_TRADE_DEX when it has no selected market on a trade DEX (v8.liquidity semantics)
    by = {}
    for c in cs:
        if c.get("type") == "perp" and c.get("legacy") == "SELECTED" and isinstance(c.get("asset"), str):
            by.setdefault(c["asset"], []).append(c)
    liquidity = {}
    for t, rows in sorted(by.items()):
        mine = [r for r in rows if r.get("venue") in TRADE_DEXES]
        vols = [float(r["vol"]) for r in mine if _finite(r.get("vol"))]
        if vols:
            liquidity[t] = [t, "KNOWN", max(vols)]            # v8.history/2: the recorded value, never rounded
        elif mine:
            liquidity[t] = [t, "MISSING", None]
        else:
            liquidity[t] = [t, "NOT_ON_TRADE_DEX", None]
    return {"contracts": contracts, "assets": assets, "liquidity": liquidity}


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def scan_content(snap, source=None):
    """The header of an observation from a snapshot: what scan, when, by which code and rules, and each venue's
    market-list state (an unavailable venue's contracts are absent from the state: unknown, never delisted)."""
    m = snap.get("manifest") or {}
    contracts = _contract_records(snap)
    venues = _venues(snap, contracts)
    failed = sorted(v for v, s in venues.items() if s == "VENUE_UNAVAILABLE")
    fallback = bool((m.get("data_sources") or {}).get("fallback_universe"))
    return {"schema": VERSION, "kind": "observation", "scan_id": m.get("scan_id"), "observed_at": m.get("ts"),
            "git_sha": m.get("git_sha"),
            "versions": {"history": VERSION, "audit_schema": m.get("schema"), "audit_version": m.get("audit_version"),
                         "identity": m.get("identity_version"), "identity_config_hash": m.get("identity_config_hash"),
                         "discovery": m.get("discovery_version"), "liquidity": m.get("liquidity_version"),
                         "config_hashes": m.get("config_hashes")},
            "venues": dict(sorted(venues.items())),
            "coverage": {"venues_expected": len(venues), "venues_ok": sum(1 for s in venues.values() if s == "OK"),
                         "venues_failed": len(failed), "venues_failed_names": failed, "fallback_universe": fallback},
            "trade_dexes": list(TRADE_DEXES), "liquidity_precision": dict(LIQUIDITY_PRECISION),
            "source": source or {"type": SCAN, "backfill": False}}


def _table(fields, rows):
    return {"fields": list(fields), "rows": [rows[k] for k in sorted(rows)]}


def _rows(tbl):
    return {r[0]: r for r in (tbl or {}).get("rows") or []}


def delta(prev, cur):
    """Rows of `cur` that are new or changed against `prev`, and the keys `prev` had that `cur` lacks."""
    return {"set": [cur[k] for k in sorted(cur) if prev.get(k) != cur[k]],
            "removed": sorted(k for k in prev if k not in cur)}


def apply_delta(prev, d):
    out = dict(prev)
    for k in d.get("removed") or []:
        out.pop(k, None)
    for r in d.get("set") or []:
        out[r[0]] = r
    return out


def full_state(obs, base_state=None):
    """The full contract and asset state one observation records: a checkpoint carries it whole; a delta carries
    the rows that differ from its base checkpoint (the newest checkpoint before it in append order)."""
    if obs.get("state_mode") == CHECKPOINT:
        return {"contracts": _rows(obs["contracts"]), "assets": _rows(obs["assets"])}
    if base_state is None:
        raise ValueError("delta without its base checkpoint")
    return {"contracts": apply_delta(base_state["contracts"], obs["contracts"]),
            "assets": apply_delta(base_state["assets"], obs["assets"])}


# --------------------------------------------------------------------------- stores
def safe_id(scan_id):
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(scan_id))


def _seq_of(path):
    name = path.rsplit("/", 1)[-1]
    try:
        return int(name.split("-", 1)[0])
    except ValueError:
        return -1


def _scan_of(path):
    name = path.rsplit("/", 1)[-1]
    return name.split("-", 1)[1][:-len(".json.gz")] if "-" in name else None


def decode(b):
    return json.loads(gzip.decompress(b).decode())


class DirStore:
    """Observations as files in a directory (an export of the history branch, or a test folder). Writes create new
    files only (exclusive create); nothing is ever overwritten or removed."""

    def __init__(self, root):
        self.root = root

    def paths(self):
        out = []
        base = os.path.join(self.root, OBS_DIR)
        for d, _, fs in os.walk(base):
            for f in fs:
                if f.endswith(".json.gz"):
                    out.append(os.path.relpath(os.path.join(d, f), self.root).replace(os.sep, "/"))
        return sorted(out, key=lambda p: (_seq_of(p), p))

    def read_bytes(self, path):
        with open(os.path.join(self.root, path), "rb") as fh:
            return fh.read()

    def write(self, path, data):
        p = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "xb") as fh:        # FileExistsError rather than an overwrite
            fh.write(data)


class Chain:
    """The end of an observation chain, read from a store with at most three observations: the last one, the one
    before it (its prev_hash link) and the base checkpoint of the last one. Gives what the next append needs - seq,
    prev_hash, the base checkpoint and its state, when liquidity was last recorded, the bytes held - and checks the
    links it read (VERIFIED_TAIL) or reports BROKEN. The whole chain is checked by verify()."""

    def __init__(self, store):
        self.store = store
        self.paths = store.paths()
        self.by_seq = {_seq_of(p): p for p in self.paths}
        self.scans = {_scan_of(p): p for p in self.paths}
        self.last = self.base = self.state = self.base_state = None
        self.last_checkpoint_at = self.last_liquidity_at = self.last_liquidity_schema = None
        self.stored_bytes = 0
        self.integrity = "EMPTY"
        if not self.paths:
            return
        self.integrity = "BROKEN"
        last_path = self.paths[-1]
        raw = store.read_bytes(last_path)
        last = decode(raw)
        self.last = last
        if record_problems(last):
            return
        self.stored_bytes = (last.get("stored_bytes_before") or 0) + len(raw)
        n = last.get("seq")
        if n != _seq_of(last_path) or n != len(self.paths) or sorted(self.by_seq) != list(range(1, n + 1)):
            return
        if n > 1:
            prev = decode(store.read_bytes(self.by_seq[n - 1]))
            if record_problems(prev) or last.get("prev_hash") != obs_hash(prev):
                return
        elif last.get("prev_hash") is not None:
            return
        if last.get("state_mode") == CHECKPOINT:
            base = last
        else:
            b = last.get("base") or {}
            if b.get("seq") not in self.by_seq:
                return
            base = decode(store.read_bytes(self.by_seq[b["seq"]]))
            if (record_problems(base) or base.get("state_mode") != CHECKPOINT
                    or obs_hash(base) != b.get("hash")):
                return
        self.base, self.base_state = base, full_state(base)
        self.state = full_state(last, self.base_state)
        if last.get("content_hash") != content_hash(last, self.state):
            return
        self.last_checkpoint_at = base.get("appended_at")
        if last.get("liquidity") is not None:
            self.last_liquidity_at, self.last_liquidity_schema = last.get("observed_at"), last.get("schema")
        else:
            ll = last.get("last_liquidity") or {}
            self.last_liquidity_at, self.last_liquidity_schema = ll.get("observed_at"), ll.get("schema")
        self.integrity = "VERIFIED_TAIL"


def build_observation(chain, content, state, now, force_checkpoint=False):
    """The next observation of the chain for one scan (content: scan_content(); state: state_from_snapshot())."""
    last = chain.last
    seq = (last or {}).get("seq", 0) + 1
    mode = CHECKPOINT
    if (not force_checkpoint and chain.integrity == "VERIFIED_TAIL" and chain.base is not None
            and chain.last_checkpoint_at is not None and now - chain.last_checkpoint_at < CHECKPOINT_EVERY_S
            and (chain.base.get("versions") or {}).get("history") == VERSION):
        mode = DELTA
    observed = content.get("observed_at") or 0
    # liquidity is also due when the last recorded table was written by another schema (the first v2 observation
    # after v1 records the precise table at once)
    due = (bool(content["source"].get("backfill")) or chain.last_liquidity_at is None
           or chain.last_liquidity_schema != VERSION
           or abs(observed - chain.last_liquidity_at) >= LIQUIDITY_EVERY_S)
    if last is None:
        last_liq = None
    elif last.get("liquidity") is not None:
        last_liq = {"seq": last["seq"], "observed_at": last.get("observed_at"), "schema": last.get("schema")}
    else:
        last_liq = last.get("last_liquidity")
    obs = dict(content)
    obs.update(seq=seq, prev_hash=obs_hash(last) if last is not None else None, appended_at=int(now),
               stored_bytes_before=chain.stored_bytes, state_mode=mode, last_liquidity=last_liq)
    if mode == CHECKPOINT:
        obs["base"] = None
        obs["contracts"] = _table(CONTRACT_FIELDS, state["contracts"])
        obs["assets"] = _table(ASSET_FIELDS, state["assets"])
    else:
        obs["base"] = {"seq": chain.base["seq"], "hash": obs_hash(chain.base)}
        obs["contracts"] = dict(delta(chain.base_state["contracts"], state["contracts"]), fields=list(CONTRACT_FIELDS))
        obs["assets"] = dict(delta(chain.base_state["assets"], state["assets"]), fields=list(ASSET_FIELDS))
    obs["liquidity"] = _table(LIQUIDITY_FIELDS, state["liquidity"]) if due else None
    obs["liquidity_content_hash"] = liquidity_hash(state["liquidity"])
    obs["content_hash"] = content_hash(content, state)
    obs["record_hash"] = obs_hash(obs)
    return obs


def path_for(obs):
    t = time.gmtime(obs["appended_at"])
    return f"{OBS_DIR}/{t.tm_year:04d}/{t.tm_mon:02d}/{t.tm_mday:02d}/{obs['seq']:08d}-{safe_id(obs['scan_id'])}.json.gz"


def same_scan(store, path, content, state):
    """Whether the recorded observation of this scan id carries exactly this scan's content (idempotent replay)."""
    return decode(store.read_bytes(path)).get("content_hash") == content_hash(content, state)


INTEGRITY_BROKEN, INVALID, CONFLICT = "INTEGRITY_BROKEN", "INVALID_OBSERVATION", "CONFLICTING_SCAN_ID"


def append(store, content, state, now=None, force_checkpoint=False, chain=None):
    """Append one observation. Returns (status, observation or None, path or None): PERSISTED (a new file),
    IDEMPOTENT_REPLAY (this scan is already recorded with identical content: nothing written), CONFLICTING_SCAN_ID
    (recorded with different content: nothing written), INTEGRITY_BROKEN or INVALID_OBSERVATION (nothing written)."""
    now = int(now if now is not None else time.time())
    chain = chain or Chain(store)
    if chain.integrity == "BROKEN":
        return INTEGRITY_BROKEN, None, None
    sid = content.get("scan_id")
    if not sid or not isinstance(content.get("observed_at"), (int, float)):
        return INVALID, None, None
    if safe_id(sid) in chain.scans:
        path = chain.scans[safe_id(sid)]
        if record_problems(decode(store.read_bytes(path))):
            return INTEGRITY_BROKEN, None, path
        return (REPLAY if same_scan(store, path, content, state) else CONFLICT), None, path
    obs = build_observation(chain, content, state, now, force_checkpoint)
    path = path_for(obs)
    store.write(path, gz(canonical(obs)))
    return PERSISTED, obs, path


# --------------------------------------------------------------------------- verification
def verify(store):
    """Walk the whole chain: seq contiguous from 1, every prev_hash links to the observation before it, every delta
    names the newest checkpoint before it as its base (by seq and hash), every record validates itself (including
    the head and provenance), every stored liquidity table matches its digest, every content hash matches the
    rebuilt state and full liquidity digest, every scan id is unique, stored_bytes_before adds up; each record by its
    own schema (v8.history/1 or /2, never a v1 after a v2, a delta on a checkpoint of its own schema). Returns a
    report (ok, problems, counts per schema, observed window, head hash)."""
    problems, prev, base, base_state = [], None, None, None
    seen, n, ckpt, liq, total, backfilled = set(), 0, 0, 0, 0, 0
    first_obs = last_obs = None
    schemas, rank = {}, 0
    for p in store.paths():
        n += 1
        try:
            raw = store.read_bytes(p)
            o = decode(raw)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{p}: unreadable ({type(e).__name__})")
            prev = None
            continue
        sch = o.get("schema")
        schemas[sch] = schemas.get(sch, 0) + 1
        if sch in SCHEMAS:
            if SCHEMAS.index(sch) < rank:
                problems.append(f"{p}: {sch} after a later history schema")
            rank = max(rank, SCHEMAS.index(sch))
        problems.extend(f"{p}: {problem}" for problem in record_problems(o))
        if o.get("seq") != n or _seq_of(p) != n:
            problems.append(f"{p}: seq {o.get('seq')} at position {n}")
        if o.get("prev_hash") != (obs_hash(prev) if prev is not None else None):
            problems.append(f"{p}: prev_hash does not link to the previous observation")
        if o.get("stored_bytes_before") != total:
            problems.append(f"{p}: stored_bytes_before {o.get('stored_bytes_before')} != {total}")
        if o.get("scan_id") in seen or _scan_of(p) != safe_id(o.get("scan_id")):
            problems.append(f"{p}: duplicate or mismatched scan id {o.get('scan_id')}")
        seen.add(o.get("scan_id"))
        total += len(raw)
        prev = o
        try:
            if o.get("state_mode") == CHECKPOINT:
                base, base_state = o, full_state(o)
                state = base_state
                ckpt += 1
            else:
                b = o.get("base") or {}
                if base is None or b.get("seq") != base.get("seq") or b.get("hash") != obs_hash(base):
                    problems.append(f"{p}: delta base is not the newest checkpoint before it")
                    continue
                if base.get("schema") != sch:
                    problems.append(f"{p}: {sch} delta on a {base.get('schema')} checkpoint")
                    continue
                state = full_state(o, base_state)
        except (ValueError, KeyError, TypeError) as e:
            problems.append(f"{p}: {type(e).__name__}: {e}")
            continue
        if o.get("content_hash") != content_hash(o, state):
            problems.append(f"{p}: content hash does not match the rebuilt state")
        liq += o.get("liquidity") is not None
        backfilled += bool((o.get("source") or {}).get("backfill"))
        ts = o.get("observed_at")
        first_obs = ts if first_obs is None else min(first_obs, ts)
        last_obs = ts if last_obs is None else max(last_obs, ts)
    return {"ok": not problems, "observations": n, "schemas": dict(sorted((str(k), v) for k, v in schemas.items())),
            "checkpoints": ckpt, "liquidity_observations": liq,
            "backfilled": backfilled, "bytes": total, "first_observed_at": first_obs, "last_observed_at": last_obs,
            "problems": problems[:50], "problem_count": len(problems),
            "head_hash": obs_hash(prev) if prev is not None else None}


# --------------------------------------------------------------------------- the git branch (production)
GIT_TIMEOUT = 120


def _git(args, cwd, env=None, input_=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, input=input_, env=env, timeout=GIT_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {r.stderr.decode(errors='replace').strip()[-300:]}")
    return r.stdout


class PushRejected(RuntimeError):
    pass


class GitStore:
    """The history branch read and written through git plumbing in an existing repository (the Scan checkout).

    Reads: a depth-1, blob-less fetch of the branch under its own remote name (so the checkout's `origin` is left
    as it was): the head tree lists every observation and only the blobs that are read are downloaded (the chain
    tail), so a scan's network cost stays flat as the history grows. Writes: new blobs in a temporary index on top
    of the fetched head, one commit, `git push` without --force (a non-fast-forward is rejected by git itself)."""

    REMOTE = "v8-history"

    def __init__(self, repo, branch=BRANCH, url=None, remote_name=None):
        self.repo, self.branch = repo, branch
        self.url = url
        if remote_name:
            self.REMOTE = remote_name
        self.ref = f"refs/v8-history/{branch}"
        self.head = None
        self._paths = None
        self.pending = []

    def _remote(self):
        url = self.url or _git(["remote", "get-url", "origin"], self.repo).decode().strip()
        have = _git(["remote"], self.repo).decode().split()
        if self.REMOTE not in have:
            _git(["remote", "add", "--no-tags", self.REMOTE, url], self.repo)
        else:
            _git(["remote", "set-url", self.REMOTE, url], self.repo)

    def fetch(self):
        self._remote()
        self.pending = []
        self._paths = None
        out = _git(["ls-remote", "--heads", self.REMOTE, f"refs/heads/{self.branch}"], self.repo).decode().split()
        if not out:
            self.head = None          # genesis: the branch does not exist yet
            return None
        _git(["fetch", "--no-tags", "--depth=1", "--filter=blob:none", self.REMOTE,
              f"+refs/heads/{self.branch}:{self.ref}"], self.repo)
        self.head = _git(["rev-parse", self.ref], self.repo).decode().strip()
        if self.head != out[0]:
            raise RuntimeError("history head moved during fetch")
        return self.head

    def paths(self):
        if self._paths is None:
            if self.head is None:
                self._paths = []
            else:
                out = _git(["ls-tree", "-r", "--name-only", self.head, "--", OBS_DIR], self.repo).decode().split("\n")
                self._paths = sorted((p for p in out if p.endswith(".json.gz")), key=lambda p: (_seq_of(p), p))
        return list(self._paths) + [p for p, _ in self.pending]

    def read_bytes(self, path):
        for p, b in self.pending:
            if p == path:
                return b
        return _git(["cat-file", "blob", f"{self.head}:{path}"], self.repo)

    def write(self, path, data):
        if path in self.paths():
            raise FileExistsError(path)
        self.pending.append((path, data))

    def commit_and_push(self, message):
        """Commit the pending files on top of the fetched head and push without --force. Returns the commit."""
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "index"),
                       GIT_AUTHOR_NAME="perp-dex-radar", GIT_AUTHOR_EMAIL="actions@users.noreply.github.com",
                       GIT_COMMITTER_NAME="perp-dex-radar", GIT_COMMITTER_EMAIL="actions@users.noreply.github.com")
            if self.head is not None:
                _git(["read-tree", self.head], self.repo, env=env)
            else:
                _git(["read-tree", "--empty"], self.repo, env=env)
                blob = _git(["hash-object", "-w", "--stdin"], self.repo, input_=README.encode()).decode().strip()
                _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},README.md"], self.repo, env=env)
            for path, data in self.pending:
                blob = _git(["hash-object", "-w", "--stdin"], self.repo, input_=data).decode().strip()
                _git(["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"], self.repo, env=env)
            tree = _git(["write-tree", "--missing-ok"], self.repo, env=env).decode().strip()
            args = ["commit-tree", tree, "-m", message] + (["-p", self.head] if self.head else [])
            commit = _git(args, self.repo, env=env).decode().strip()
        r = subprocess.run(["git", "push", "--no-verify", self.REMOTE, f"{commit}:refs/heads/{self.branch}"],
                           cwd=self.repo, capture_output=True, timeout=GIT_TIMEOUT)
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace")
            if "rejected" in err or "fetch first" in err or "non-fast-forward" in err:
                raise PushRejected(err.strip()[-300:])
            raise RuntimeError("history push failed: " + err.strip()[-300:])
        self.head = commit
        self._paths = None
        self.pending = []
        return commit


# --------------------------------------------------------------------------- backfill from archived scan artifacts
def artifact_observations(zip_bytes, meta):
    """(content, state) of every audit snapshot inside one archived `v8-audit-*` artifact zip, citing the artifact
    and the sha256 of the zip and of the snapshot file. A snapshot without its own scan id and time is skipped."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".json.gz"):
                continue
            raw = zf.read(name)
            snap = json.loads(gzip.decompress(raw).decode())
            m = snap.get("manifest") or {}
            if not m.get("scan_id") or not isinstance(m.get("ts"), (int, float)):
                continue
            src = {"type": ARTIFACT, "backfill": True,
                   "artifact": {"id": meta.get("id"), "name": meta.get("name"), "run_id": meta.get("run_id"),
                                "created_at": meta.get("created_at"), "digest": meta.get("digest"),
                                "zip_sha256": sha(zip_bytes), "file": name, "file_sha256": sha(raw)}}
            out.append((scan_content(snap, src), state_from_snapshot(snap)))
    return out


def _gh(args, timeout=120):
    r = subprocess.run(["gh", "api", *args], capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("gh api: " + r.stderr.decode(errors="replace").strip()[-200:])
    return r.stdout


def list_scan_artifacts(repo_slug):
    """Unexpired `v8-audit-*` artifacts of the repository (the Scan workflow's 14-day audit snapshots)."""
    arts, page = [], 1
    while page <= 10:
        d = json.loads(_gh([f"repos/{repo_slug}/actions/artifacts?per_page=100&page={page}"]))
        got = d.get("artifacts") or []
        arts += [a for a in got if str(a.get("name", "")).startswith("v8-audit-") and not a.get("expired")]
        if len(got) < 100:
            break
        page += 1
    return arts


def download_artifact(repo_slug, art_id):
    return _gh([f"repos/{repo_slug}/actions/artifacts/{art_id}/zip"], timeout=300)


def artifact_scan_id(name):
    """`v8-audit-<run_id>-<attempt>` -> the scan id the Scan workflow gave that run (`gh-<run_id>-<attempt>`)."""
    rest = str(name)[len("v8-audit-"):]
    return rest if rest.startswith("gh-") else "gh-" + rest


MAX_BACKFILL_PER_RUN = 60


def backfill_items(chain, current_scan, repo_slug, lister=list_scan_artifacts, downloader=download_artifact):
    """(items, report): the archived scans not yet in the chain, oldest observation first."""
    rep = {"available": 0, "already_recorded": 0, "downloaded": 0, "errors": []}
    arts = lister(repo_slug)
    rep["available"] = len(arts)
    todo = []
    for a in sorted(arts, key=lambda a: str(a.get("created_at"))):
        sid = artifact_scan_id(a.get("name"))
        if safe_id(sid) in chain.scans or sid == current_scan:
            rep["already_recorded"] += 1
            continue
        todo.append(a)
    items = []
    for a in todo[:MAX_BACKFILL_PER_RUN]:
        try:
            z = downloader(repo_slug, a["id"])
            meta = {"id": a.get("id"), "name": a.get("name"), "created_at": a.get("created_at"),
                    "digest": a.get("digest"), "run_id": (a.get("workflow_run") or {}).get("id")}
            items += artifact_observations(z, meta)
            rep["downloaded"] += 1
        except Exception as e:  # noqa: BLE001
            rep["errors"].append(f"{a.get('name')}: {type(e).__name__}: {e}"[:200])
    rep["deferred"] = max(0, len(todo) - MAX_BACKFILL_PER_RUN)
    items.sort(key=lambda x: (x[0]["observed_at"], x[0]["scan_id"]))
    return items, rep


# --------------------------------------------------------------------------- capture (called by v8.snapshot)
def status_template(snap, branch):
    m = snap.get("manifest") or {}
    return {"version": VERSION, "readable_schemas": list(SCHEMAS), "liquidity_precision": dict(LIQUIDITY_PRECISION),
            "branch": branch, "observation_timestamp": m.get("ts"),
            "source_scan": m.get("scan_id"), "source_main_sha": m.get("git_sha"), "persistence_state": NOT_CONFIGURED,
            "history_branch_commit": None, "append_integrity": None, "storage_size": None, "observation": None,
            "backfill": None, "reason": None}


def capture(snap, repo=None, branch=BRANCH, backfill=False, repo_slug=None, now=None, store=None, attempts=3,
            lister=list_scan_artifacts, downloader=download_artifact, url=None, remote_name=None):
    """Append this scan's observation (and, with backfill, every archived scan not yet recorded) to the history.
    Never raises. Returns the `history` section of the audit snapshot:
        persistence_state  PERSISTED | IDEMPOTENT_REPLAY | HISTORY_CAPTURE_DEGRADED
        append_integrity   the chain tail it appended to: EMPTY (genesis) | VERIFIED_TAIL | BROKEN | ...
    A rejected push (another writer appended first) is retried from a fresh fetch up to `attempts` times."""
    now = int(now if now is not None else time.time())
    st = status_template(snap, branch)
    try:
        content = scan_content(snap)
        state = state_from_snapshot(snap)
        for attempt in range(1, attempts + 1):
            if attempt > 1:                     # a fresh status for the retry, keeping why it was retried
                note = st.get("reason")
                st = status_template(snap, branch)
                st["reason"] = note
            s = store or GitStore(repo or os.getcwd(), branch, url=url, remote_name=remote_name)
            if isinstance(s, GitStore):
                s.fetch()
            chain = Chain(s)
            st["append_integrity"] = chain.integrity
            if chain.integrity == "BROKEN":
                st.update(persistence_state=DEGRADED, reason=f"the history chain tail is {chain.integrity}; "
                                                             "nothing was appended")
                return st
            msgs = []
            if backfill and repo_slug:
                try:
                    items, rep = backfill_items(chain, content["scan_id"], repo_slug, lister, downloader)
                    rep["appended"] = 0
                    for c2, s2 in items:
                        r2, _, _ = append(s, c2, s2, now=now, force_checkpoint=True)
                        if r2 == PERSISTED:
                            rep["appended"] += 1
                        elif r2 != REPLAY:
                            rep["errors"].append(f"{c2['scan_id']}: {r2}")
                    if rep["appended"]:
                        msgs.append(f"backfill {rep['appended']} archived scan(s)")
                except Exception as e:  # noqa: BLE001 - backfill is best effort; this scan's own row still counts
                    rep = {"errors": [f"{type(e).__name__}: {e}"[:300]], "appended": 0}
                st["backfill"] = rep
            res, obs, path = append(s, content, state, now=now)
            if res not in (PERSISTED, REPLAY):
                st.update(persistence_state=DEGRADED, reason=res)
            elif res == PERSISTED:
                msgs.append(f"observation {obs['seq']} of scan {content['scan_id']} ({obs['state_mode']})")
                st["observation"] = {"seq": obs["seq"], "schema": obs["schema"], "path": path, "obs_hash": obs_hash(obs),
                                     "state_mode": obs["state_mode"], "liquidity": obs["liquidity"] is not None,
                                     "content_hash": obs["content_hash"]}
            try:
                if isinstance(s, GitStore):
                    st["history_branch_commit"] = (s.commit_and_push("v8 history: " + "; ".join(msgs))
                                                   if s.pending else s.head)
            except PushRejected as e:
                if attempt < attempts and store is None:
                    st["reason"] = f"push rejected, retried ({attempt})"
                    continue
                st.update(persistence_state=DEGRADED, reason=f"push rejected: {e}"[:400])
                return st
            n = len(s.paths())
            stored = (obs["stored_bytes_before"] + len(gz(canonical(obs)))) if res == PERSISTED else None
            st["storage_size"] = {"observations": n, "bytes": stored if stored is not None else Chain(s).stored_bytes}
            if st["persistence_state"] != DEGRADED:
                st["persistence_state"] = PERSISTED if res == PERSISTED else REPLAY
                if res == REPLAY:
                    st["reason"] = "this scan is already recorded with identical content"
            return st
        return st
    except Exception as e:  # noqa: BLE001 - history must never break the scan or its publication
        st.update(persistence_state=DEGRADED, reason=f"{type(e).__name__}: {e}"[:400])
        return st


# --------------------------------------------------------------------------- storage projection (measured)
def project(snap, days=10, scans_per_day=72, change_rate=0.002, seed=7):
    """Measured storage of `days` of history at production scale: one observation per scan from the state of `snap`,
    `change_rate` of contract and asset rows changing per scan and every liquidity value drifting (the worst case:
    liquidity changes every time it is recorded). Every observation becomes its own git commit on the branch (blob,
    trees, commit - written with git fast-import) in a throwaway bare repository that is then garbage-collected, so
    the git size is measured, not estimated."""
    import random
    rnd = random.Random(seed)
    base = state_from_snapshot(snap)
    content = scan_content(snap)
    with tempfile.TemporaryDirectory() as td:
        bare = os.path.join(td, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True, capture_output=True)
        store = DirStore(os.path.join(td, "files"))
        t0 = int(content.get("observed_at") or time.time())
        step = 86400 // scans_per_day
        deltas, fulls, n = [], [], days * scans_per_day
        state = json.loads(json.dumps(base))
        cids, assets = sorted(state["contracts"]), sorted(state["assets"])
        k_c, k_a = max(1, int(len(cids) * change_rate)), max(1, int(len(assets) * change_rate))
        stream = io.BytesIO()
        w = stream.write
        for k in range(n):
            ts = t0 + k * step
            for c in rnd.sample(cids, k_c):
                r = list(state["contracts"][c])
                r[3] = 1 - (r[3] or 0)
                state["contracts"][c] = r
            for a in rnd.sample(assets, k_a):
                r = list(state["assets"][a])
                r[2] = rnd.choice(["VERIFIED_CRYPTO", "UNVERIFIED", "VERIFIED_TRADFI"])
                state["assets"][a] = r
            for a, r in state["liquidity"].items():
                if r[2] is not None:
                    state["liquidity"][a] = [a, r[1], int(max(0, r[2] * (1 + rnd.uniform(-0.2, 0.2))))]
            res, obs, path = append(store, dict(content, scan_id=f"sim-{k}", observed_at=ts), state, now=ts)
            data = store.read_bytes(path)
            (deltas if obs["state_mode"] == DELTA and obs["liquidity"] is None else fulls).append(len(data))
            msg = f"v8 history: observation {k + 1}".encode()
            w(b"commit refs/heads/" + BRANCH.encode() + b"\n")
            w(f"committer perp-dex-radar <actions@users.noreply.github.com> {ts} +0000\n".encode())
            w(b"data %d\n" % len(msg) + msg + b"\n")
            w(f"M 100644 inline {path}\n".encode() + b"data %d\n" % len(data) + data + b"\n")
        subprocess.run(["git", "-C", bare, "fast-import", "--quiet"], input=stream.getvalue(), check=True,
                       capture_output=True)
        # what one scan's blob-less depth-1 fetch transfers: the head commit and every tree (uncompressed)
        trees = subprocess.run(["git", "-C", bare, "ls-tree", "-r", "-t", BRANCH], check=True,
                               capture_output=True).stdout.decode().split("\n")
        shas = [ln.split()[2] for ln in trees if ln.split()[1:2] == ["tree"]]
        root = subprocess.run(["git", "-C", bare, "rev-parse", BRANCH + "^{tree}"], check=True,
                              capture_output=True).stdout.decode().strip()
        chk = subprocess.run(["git", "-C", bare, "cat-file", "--batch-check=%(objectsize)"],
                             input=("\n".join(shas + [root]) + "\n").encode(), check=True, capture_output=True)
        tree_bytes = sum(int(x) for x in chk.stdout.decode().split())
        loose = 0
        for d, _, fs in os.walk(os.path.join(bare, "objects")):
            loose += sum(os.path.getsize(os.path.join(d, f)) for f in fs)
        subprocess.run(["git", "-C", bare, "gc", "-q", "--aggressive", "--prune=now"], check=True, capture_output=True)
        packed = 0
        for d, _, fs in os.walk(os.path.join(bare, "objects")):
            packed += sum(os.path.getsize(os.path.join(d, f)) for f in fs)
        ok = verify(store)["ok"]
    files = deltas + fulls
    per_day = packed / days
    return {"contracts": len(base["contracts"]), "assets": len(base["assets"]), "scans_per_day": scans_per_day,
            "observations_simulated": n, "days_simulated": days, "change_rate_per_scan": change_rate,
            "chain_verified": ok, "observation_bytes_mean": int(sum(files) / len(files)),
            "observation_bytes_max": max(files),
            "delta_bytes_mean": int(sum(deltas) / len(deltas)) if deltas else None,
            "checkpoint_or_liquidity_bytes_mean": int(sum(fulls) / len(fulls)) if fulls else None,
            "observations_per_day": scans_per_day, "file_bytes_per_day": int(sum(files) / days),
            "git_bytes_before_gc": loose, "git_packed_bytes": packed, "git_bytes_per_day": int(per_day),
            "projected_30d_bytes": int(per_day * 30), "projected_1y_bytes": int(per_day * 365),
            "projected_3y_bytes": int(per_day * 365 * 3),
            "fetch_tree_bytes_now": tree_bytes, "fetch_tree_bytes_per_scan_after_1y": int(tree_bytes / days * 365),
            "fetch_tree_bytes_per_scan_after_3y": int(tree_bytes / days * 365 * 3)}


# --------------------------------------------------------------------------- CLI
def _load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v8 point-in-time history (writes v8.history/2; reads /1 and /2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verify an export of the history branch (a folder holding obs/)")
    v.add_argument("--dir", required=True)
    p = sub.add_parser("project", help="measured storage projection at production scale")
    p.add_argument("snapshot")
    p.add_argument("--days", type=int, default=10)
    p.add_argument("--scans-per-day", type=int, default=72)
    p.add_argument("--change-rate", type=float, default=0.002)
    d = sub.add_parser("dryrun", help="capture a snapshot (and backfill) into a throwaway bare repository")
    d.add_argument("--snapshot", required=True)
    d.add_argument("--bare", required=True, help="a bare repository standing in for the remote")
    d.add_argument("--branch", default=BRANCH + "-dryrun")
    d.add_argument("--backfill-repo", default=None, help="owner/name whose v8-audit-* artifacts are backfilled")
    d.add_argument("--json", default=None)
    b = sub.add_parser("backfill", help="append archived scan snapshots (artifact zips or .json.gz) to a folder store")
    b.add_argument("--dir", required=True)
    b.add_argument("inputs", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        rep = verify(DirStore(a.dir))
        print(json.dumps(rep, indent=1, sort_keys=True))
        return 0 if rep["ok"] else 1
    if a.cmd == "project":
        print(json.dumps(project(_load(a.snapshot), a.days, a.scans_per_day, a.change_rate), indent=1, sort_keys=True))
        return 0
    if a.cmd == "dryrun":
        st = capture(_load(a.snapshot), repo=os.getcwd(), branch=a.branch, backfill=bool(a.backfill_repo),
                     repo_slug=a.backfill_repo, url=os.path.abspath(a.bare), remote_name="v8-history-dryrun")
        if a.json:
            with open(a.json, "w") as fh:
                json.dump(st, fh, indent=1, sort_keys=True)
        print(json.dumps({k: st.get(k) for k in ("persistence_state", "append_integrity", "history_branch_commit",
                                                 "storage_size", "backfill", "reason")}, sort_keys=True))
        return 0 if st["persistence_state"] in (PERSISTED, REPLAY) else 1
    if a.cmd == "backfill":
        st = DirStore(a.dir)
        items = []
        for path in a.inputs:
            with open(path, "rb") as fh:
                data = fh.read()
            meta = {"name": os.path.basename(path)}
            if path.endswith(".zip"):
                items += artifact_observations(data, meta)
            else:
                snap = json.loads(gzip.decompress(data).decode())
                src = {"type": ARTIFACT, "backfill": True,
                       "artifact": {"name": meta["name"], "file_sha256": sha(data)}}
                items.append((scan_content(snap, src), state_from_snapshot(snap)))
        items.sort(key=lambda x: (x[0]["observed_at"], x[0]["scan_id"]))
        out = {}
        for c, s in items:
            r, _, _ = append(st, c, s, force_checkpoint=True)
            out[r] = out.get(r, 0) + 1
        print(json.dumps(out, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
