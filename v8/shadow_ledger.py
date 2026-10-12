"""Shadow experiment ledger (v8.shadow-ledger/1, v8 Phase 8): pre-registration for research, with no trade authority.

An experiment is registered BEFORE it is evaluated: what is tested (name, parameters and their hash, the code and its
hash, the commit it was registered from), on which data (the cutoff, the evaluation window - forward from the
registration only - the universe-history and cost-model versions), what would count (hypothesis, primary and
secondary metrics, the pass and the fail rule) and how many variants of the same idea were tried before it (so a
later deflated-Sharpe, PBO, SPA or FDR correction knows the number of trials).

The ledger is a folder of canonical JSON records in the repository (research/shadow-ledger/), one file per record,
`<seq:06d>-<kind>-<experiment_id>.json`, chained by `prev_hash`. Files are only ever added (CI checks it with
tools/v8/ledger_guard.py): a registration is never edited - changed parameters are a new experiment id, and a status
change (RUNNING, PASSED, FAILED, RETIRED, INVALIDATED) is a new STATUS record. There is no FINAL, LIVE or PROMOTED
status and every record's authority is NONE: nothing here can reach a live engine."""
from __future__ import annotations

import hashlib
import json
import os
import re

VERSION = "v8.shadow-ledger/1"
DIR = os.path.join("research", "shadow-ledger")
GENESIS, REGISTRATION, STATUS = "GENESIS", "REGISTRATION", "STATUS"
STATUSES = ("REGISTERED", "RUNNING", "PASSED", "FAILED", "RETIRED", "INVALIDATED")
FORBIDDEN_STATUSES = ("FINAL", "LIVE", "PROMOTED", "ACTIVE", "TRADING")
REGISTRATION_FIELDS = ("experiment_id", "registered_at", "registration_commit", "name", "params", "param_hash",
                       "code_files", "code_hash", "data_cutoff", "evaluation_start", "evaluation_end",
                       "universe_history_version", "cost_model_version", "hypothesis", "primary_metric",
                       "secondary_metrics", "pass_rule", "fail_rule", "status", "authority", "multiple_testing")
MULTIPLE_TESTING_FIELDS = ("family", "variants_tried_before_registration", "variant_ids", "selection",
                           "corrections_planned")
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{2,63}$")
NAME_RE = re.compile(r"^(\d{6})-(GENESIS|REGISTRATION|STATUS)-([A-Za-z0-9_.-]+)\.json$")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def param_hash(params):
    return sha(canonical(params))


def files_hash(root, files):
    h = hashlib.sha256()
    for f in sorted(files):
        with open(os.path.join(root, f), "rb") as fh:
            h.update(f.encode() + b"\0" + sha(fh.read()).encode() + b"\n")
    return h.hexdigest()


def load(folder):
    """[(file name, record, raw bytes)] in seq order."""
    out = []
    if not os.path.isdir(folder):
        return out
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(folder, f), "rb") as fh:
            raw = fh.read()
        out.append((f, json.loads(raw.decode()), raw))
    return out


def validate(folder):
    """Every rule of the ledger. Returns a list of problems (empty: valid)."""
    problems, prev_raw, regs = [], None, {}
    recs = load(folder)
    if not recs:
        return ["the ledger is empty (no genesis record)"]
    for n, (f, r, raw) in enumerate(recs, 1):
        m = NAME_RE.match(f)
        if not m:
            problems.append(f"{f}: file name is not <seq>-<kind>-<id>.json")
            continue
        if int(m.group(1)) != n or r.get("seq") != n:
            problems.append(f"{f}: seq {r.get('seq')} at position {n}")
        if r.get("kind") != m.group(2):
            problems.append(f"{f}: kind {r.get('kind')} does not match the file name")
        if r.get("schema") != VERSION:
            problems.append(f"{f}: schema {r.get('schema')!r}")
        if raw != canonical(r):
            problems.append(f"{f}: not in canonical form")
        if r.get("prev_hash") != (sha(prev_raw) if prev_raw is not None else None):
            problems.append(f"{f}: prev_hash does not link to the previous record")
        if r.get("authority") != "NONE":
            problems.append(f"{f}: authority must be NONE")
        if n == 1 and r.get("kind") != GENESIS:
            problems.append(f"{f}: the first record must be the genesis")
        if n > 1 and r.get("kind") == GENESIS:
            problems.append(f"{f}: a second genesis")
        if r.get("kind") == REGISTRATION:
            problems += [f"{f}: {p}" for p in check_registration(r)]
            eid = r.get("experiment_id")
            if eid in regs:
                problems.append(f"{f}: experiment id {eid} registered twice (changed parameters need a new id)")
            if m.group(3) != eid:
                problems.append(f"{f}: file name id differs from the experiment id")
            regs[eid] = r
        elif r.get("kind") == STATUS:
            eid = r.get("experiment_id")
            if m.group(3) != eid:       # the append-only file name is the permanent attribution of the record
                problems.append(f"{f}: file name id {m.group(3)} differs from the experiment id {eid}")
            if eid not in regs:
                problems.append(f"{f}: status for unregistered experiment {eid}")
            if r.get("status") not in STATUSES or r.get("status") == "REGISTERED":
                problems.append(f"{f}: status {r.get('status')!r} is not a status change")
        prev_raw = raw
    return problems


def check_registration(r):
    p = [f"missing field {k}" for k in REGISTRATION_FIELDS if k not in r]
    if p:
        return p
    if not ID_RE.match(str(r["experiment_id"])):
        p.append("experiment id must be 3-64 characters A-Z 0-9 _ . -")
    if r["status"] != "REGISTERED":
        p.append("a registration's status is REGISTERED")
    if r["status"] in FORBIDDEN_STATUSES:
        p.append("no FINAL / LIVE status in the shadow ledger")
    if r["param_hash"] != param_hash(r["params"]):
        p.append("param_hash does not match params")
    if not re.match(r"^[0-9a-f]{40}$", str(r["registration_commit"])):
        p.append("registration_commit must be a full commit sha")
    for k in ("registered_at", "data_cutoff", "evaluation_start"):
        if not isinstance(r[k], int):
            p.append(f"{k} must be a unix time")
    if not p:
        if r["data_cutoff"] > r["registered_at"]:
            p.append("data_cutoff after registration")
        if r["evaluation_start"] < r["registered_at"]:
            p.append("evaluation must start after registration (forward only)")
        if r["evaluation_end"] is not None and r["evaluation_end"] <= r["evaluation_start"]:
            p.append("evaluation_end before evaluation_start")
    mt = r.get("multiple_testing") or {}
    p += [f"multiple_testing missing {k}" for k in MULTIPLE_TESTING_FIELDS if k not in mt]
    return p


def record(kind, seq, prev_raw, **fields):
    r = {"schema": VERSION, "kind": kind, "seq": seq, "prev_hash": sha(prev_raw) if prev_raw is not None else None,
         "authority": "NONE"}
    r.update(fields)
    return r


def file_name(r):
    rid = r.get("experiment_id") or "ledger"
    return f"{r['seq']:06d}-{r['kind']}-{rid}.json"


def append(folder, kind, **fields):
    """Add one record (exclusive create; never overwrites). Returns (file name, record)."""
    recs = load(folder)
    prev = recs[-1][2] if recs else None
    r = record(kind, len(recs) + 1, prev, **fields)
    if kind == REGISTRATION:
        bad = check_registration(r)
        if bad:
            raise ValueError("; ".join(bad))
        if any(x[1].get("experiment_id") == r["experiment_id"] for x in recs):
            raise ValueError("experiment id already registered: changed parameters need a new id")
    os.makedirs(folder, exist_ok=True)
    name = file_name(r)
    with open(os.path.join(folder, name), "xb") as fh:
        fh.write(canonical(r))
    return name, r


def _attributed(f, r):
    """Whether a record's experiment id is the one its permanent file name attributes it to."""
    m = NAME_RE.match(f)
    return bool(m) and m.group(3) == r.get("experiment_id")


def summary(folder):
    """Ledger state. A registration or status record whose file name attributes it to another experiment never
    updates any experiment (it is also a validation problem)."""
    recs = load(folder)
    problems = validate(folder)
    regs = [r for f, r, _ in recs if r.get("kind") == REGISTRATION and _attributed(f, r)]
    status = {}
    for f, r, _ in recs:
        if r.get("kind") == REGISTRATION and _attributed(f, r):
            status[r["experiment_id"]] = r["status"]
        elif r.get("kind") == STATUS and _attributed(f, r) and r.get("experiment_id") in status:
            status[r["experiment_id"]] = r["status"]
    return {"version": VERSION, "records": len(recs), "experiments": len(regs), "status": status,
            "valid": not problems, "problems": problems[:20],
            "head_hash": sha(recs[-1][2]) if recs else None}
