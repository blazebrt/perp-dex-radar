"""Differential qualification of an intentional behaviour change (v8 Phase 2; Phase 3: identity states).

Phase 1's parity check proved that the legacy outputs did not change at all. Phase 2 changes them on purpose, in a
narrow, approved scope (universe identity, missing-vs-zero liquidity). This tool proves that every difference from
the base commit is one of the approved ones, and fails on any other:

    BASE  = the base commit (main at the start of the phase), on the parity fixture
    HEAD  = this checkout, on the same fixture
    CF    = the counterfactual: BASE's code, with every build_universe() answered by HEAD's universe

    1. BASE reproduces its committed golden digests              (the base really is the base)
    2. BASE with its own universe injected reproduces them too   (injecting a universe changes nothing else)
    3. HEAD reproduces its committed golden digests              (no drift on this branch)
    4. universe delta  BASE -> HEAD   == manifest "universe", "dex_status", "notes"   (exactly; nothing more, nothing less)
       and every HEAD coin's identity state == manifest "identity_states" (when the manifest has it; Phase 3)
    5. code delta      CF   -> HEAD   == manifest "code" (and "decisions")           (exactly)

Phase 3 (manifest schema v8.delta/2) adds two things. The derived universe field `execution_identity` - whether a
coin may reach a crypto engine: `not tradfi` for a coin record without an identity (Phase 2 and earlier), and
`identity == VERIFIED_CRYPTO and not tradfi` with one - is compared like a coin field, so every coin that loses or
gains crypto execution authority is a listed delta. And the counterfactual expresses HEAD's identity gate in the only
exclusion the base code has: every HEAD coin without execution identity is handed to the base code with tradfi=True
(projection "exclude_without_execution_identity"). Then CF -> HEAD isolates what HEAD's changed code does beyond
that gate (the published lists that tell tradfi from unverified), and every other engine difference is the unchanged
engine logic responding to the identity gate. Code deltas may be "kind": "set": the list at that path is compared
as a set (base items -> head items), its elements are not diffed one by one.

4 isolates what the new identity and volume semantics decide; 5 isolates what the changed engine code does with the
same universe. Every other output difference between BASE and HEAD is then the unchanged legacy logic responding to
the approved universe change: it is reported (step 6) but needs no entry of its own.

    python tools/v8/delta_parity.py --base-root /tmp/base --manifest tests/fixtures/v8/phase2_expected_deltas.json \\
        --work /tmp/delta [--write-report /tmp/delta/report.json]

--base-root is a checkout of the manifest's base commit (git worktree add --detach /tmp/base <sha>); this file's
legacy_parity.py is copied into it, so both sides run the same fixture."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import legacy_parity as LP  # noqa: E402

COIN_FIELDS = ("t", "name", "tradfi", "ref_price", "best_vol", "tot_vol", "trade_vol", "execution_identity")
VERIFIED_CRYPTO = "VERIFIED_CRYPTO"


def execution_identity(coin):
    """Whether a coin record may reach a crypto engine, in the semantics of the code that built it: a record without
    an identity (Phase 2 and earlier) is admitted when not tradfi; with one, only VERIFIED_CRYPTO (v8.identity)."""
    if "identity" not in coin:
        return not coin.get("tradfi")
    return (not coin.get("tradfi")) and coin.get("identity") == VERIFIED_CRYPTO


def project(u, projection):
    """The universe handed to the base code for the counterfactual. "exclude_without_execution_identity": every
    coin without execution identity gets tradfi=True (the base code's only exclusion); nothing else changes."""
    if not projection:
        return u
    if projection != "exclude_without_execution_identity":
        raise SystemExit(f"unknown counterfactual projection {projection!r}")
    out = json.loads(json.dumps(u))
    for c in out["coins"].values():
        if not execution_identity(c):
            c["tradfi"] = True
    return out


# --------------------------------------------------------------------------- running both sides
def run(root, args, log):
    r = subprocess.run([sys.executable, os.path.join(root, "tools", "v8", "legacy_parity.py"), *args], cwd=root,
                       capture_output=True, text=True, timeout=1800)
    log.append(f"$ ({os.path.basename(root) or root}) legacy_parity.py {' '.join(args)}\n{r.stdout[-1500:]}"
               f"{r.stderr[-1500:]}")
    return r.returncode, r.stdout


def summary_of(out):
    return LP.summary(out)


# --------------------------------------------------------------------------- diffs
def json_diff(a, b, path=()):
    """[(path tuple, a value, b value)] for every leaf that differs; missing keys are '<absent>'."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append((path + (k,), a.get(k, "<absent>"), b.get(k, "<absent>")))
            else:
                out += json_diff(a[k], b[k], path + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path + ("#len",), len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += json_diff(x, y, path + (i,))
    elif type(a) is not type(b) or a != b:
        out.append((path, a, b))
    return out


def load_norm(path):
    raw = LP.normalized_bytes(path)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def universe_delta(ub, uh):
    """Observed universe differences: per coin field, venue set, presence and order; DEX status; notes."""
    out = []
    cb, ch = ub["coins"], uh["coins"]
    for t in sorted(set(cb) | set(ch)):
        a, b = cb.get(t), ch.get(t)
        if a is None or b is None:
            out.append({"ticker": t, "field": "present", "base": a is not None, "head": b is not None})
            continue
        for f in COIN_FIELDS:
            x, y = (execution_identity(a), execution_identity(b)) if f == "execution_identity" else (a.get(f), b.get(f))
            if x != y or type(x) is not type(y):
                out.append({"ticker": t, "field": f, "base": x, "head": y})
        if "identity" in a and a.get("identity") != b.get("identity"):     # both sides know identity states
            out.append({"ticker": t, "field": "identity", "base": a.get("identity"), "head": b.get("identity")})
        va = {d: v.get("sym") for d, v in (a.get("venues") or {}).items()}
        vb = {d: v.get("sym") for d, v in (b.get("venues") or {}).items()}
        if va != vb or list(va) != list(vb):
            out.append({"ticker": t, "field": "venues", "base": va, "head": vb})
        else:
            for d in va:   # the same markets must carry the same values (the adapters did not change)
                ra, rb = dict(a["venues"][d]), dict(b["venues"][d])
                for k in ("underlying", "category", "subtypes"):   # raw metadata HEAD's adapters now pass on
                    if k not in ra:
                        rb.pop(k, None)
                if ra != rb:
                    out.append({"ticker": t, "field": f"venues.{d}", "base": ra, "head": rb})
    order = [t for t in cb if t in ch] == [t for t in ch if t in cb]
    st = []
    for d in sorted(set(ub["status"]) | set(uh["status"])):
        for k in sorted(set(ub["status"].get(d) or {}) | set(uh["status"].get(d) or {})):
            x, y = (ub["status"].get(d) or {}).get(k), (uh["status"].get(d) or {}).get(k)
            if x != y:
                st.append({"dex": d, "field": k, "base": x, "head": y})
    notes = {"removed": [n for n in ub["notes"] if n not in uh["notes"]],
             "added": [n for n in uh["notes"] if n not in ub["notes"]]}
    return out, st, notes, order, ub["ok"] == uh["ok"]


def resolve_path(doc, spec):
    """A manifest path -> a concrete path in doc. An element {"match": [i, value]} selects the list item whose item
    i equals value (a table row by its ticker), {"key": [k, value]} the item whose dict key k equals value."""
    cur, out = doc, []
    for p in spec:
        if isinstance(p, dict):
            if "match" in p:
                i, v = p["match"]
                hit = [n for n, row in enumerate(cur) if isinstance(row, list) and len(row) > i and row[i] == v]
            else:
                k, v = p["key"]
                hit = [n for n, row in enumerate(cur) if isinstance(row, dict) and row.get(k) == v]
            if len(hit) != 1:
                return None
            p = hit[0]
        out.append(p)
        try:
            cur = cur[p]
        except (KeyError, IndexError, TypeError):
            return None
    return tuple(out)


def same(x, y):
    if isinstance(x, float) and isinstance(y, float):
        return x == y or abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))
    return x == y and type(x) is type(y)


def check(manifest, ub, uh, cf_out, head_out):
    """Compare the observed deltas with the manifest. Returns (report dict, list of failures)."""
    fails = []
    uni, st, notes, order, ok_same = universe_delta(ub, uh)
    if not order:
        fails.append("the coin order of the universe changed")
    if not ok_same:
        fails.append("the universe ok flag changed")
    # 4a. coins
    want = {(e["ticker"], e["field"]): e for e in manifest["universe"]}
    seen = set()
    for d in uni:
        key = (d["ticker"], d["field"])
        e = want.get(key)
        if e is None:
            fails.append(f"UNEXPECTED universe delta {key}: {d['base']!r} -> {d['head']!r}")
            continue
        if not (_eq(e["base"], d["base"]) and _eq(e["head"], d["head"])):
            fails.append(f"universe delta {key} differs from the manifest: {d['base']!r} -> {d['head']!r} "
                         f"(manifest {e['base']!r} -> {e['head']!r})")
        seen.add(key)
    for key in want:
        if key not in seen:
            fails.append(f"expected universe delta not observed: {key}")
    # 4b. DEX status
    want_s = {(e["dex"], e["field"]): e for e in manifest["dex_status"]}
    seen_s = set()
    for d in st:
        key = (d["dex"], d["field"])
        e = want_s.get(key)
        if e is None or not (_eq(e["base"], d["base"]) and _eq(e["head"], d["head"])):
            fails.append(f"UNEXPECTED DEX status delta {key}: {d['base']!r} -> {d['head']!r}")
        seen_s.add(key)
    for key in want_s:
        if key not in seen_s:
            fails.append(f"expected DEX status delta not observed: {key}")
    # 4c. notes
    for side in ("removed", "added"):
        if sorted(notes[side]) != sorted(manifest["notes"][side]):
            fails.append(f"notes {side} differ from the manifest: {notes[side]}")
    # 4d. identity states of every HEAD coin (Phase 3 manifests)
    if "identity_states" in manifest:
        got = {t: c.get("identity") for t, c in uh["coins"].items()}
        want = manifest["identity_states"]
        for t in sorted(set(got) | set(want)):
            if got.get(t) != want.get(t):
                fails.append(f"identity state of {t}: HEAD {got.get(t)!r}, manifest {want.get(t)!r}")
    # 5. code deltas, counterfactual vs head
    cf_sum, head_sum = summary_of(cf_out), summary_of(head_out)
    files = sorted(set(cf_sum["files"]) | set(head_sum["files"]))
    want_c = {}
    for e in manifest["code"]:
        want_c.setdefault(e["file"], []).append(e)
    code_seen = []
    for f in files:
        if cf_sum["files"].get(f) == head_sum["files"].get(f):
            if f in want_c:
                fails.append(f"expected code delta not observed: {f}")
            continue
        a, b = load_norm(os.path.join(cf_out, f)), load_norm(os.path.join(head_out, f))
        if not isinstance(a, (dict, list)) or not isinstance(b, (dict, list)):
            fails.append(f"UNEXPECTED code delta in non-JSON file {f}")
            continue
        code_seen += match_deltas(f, a, b, want_c.get(f, []), fails)
    want_d = manifest.get("decisions") or []
    if cf_sum["decisions"] != head_sum["decisions"] or want_d:
        code_seen += match_deltas("decisions", cf_sum["decisions"], head_sum["decisions"], want_d, fails)
    report = {"universe": uni, "dex_status": st, "notes": notes, "code": code_seen}
    return report, fails


def match_deltas(f, a, b, entries, fails):
    """Every difference between a (counterfactual) and b (HEAD) must be one of the manifest entries for f, and every
    entry must occur. A "kind": "set" entry compares the list at its path as a set and hides its elements from the
    element-by-element diff. Returns the matched deltas; appends failures."""
    seen, allowed = [], {}
    a, b = json.loads(json.dumps(a)), json.loads(json.dumps(b))
    for e in entries:
        if e.get("kind") == "set":
            pa, pb = resolve_path(a, e["path"]), resolve_path(b, e["path"])
            va = _get(a, pa) if pa is not None else "<absent>"
            vb = _get(b, pb) if pb is not None else "<absent>"
            sa = sorted(va) if isinstance(va, list) else va
            sb = sorted(vb) if isinstance(vb, list) else vb
            if not (_eq(sorted(e["base"]) if isinstance(e["base"], list) else e["base"], sa)
                    and _eq(sorted(e["head"]) if isinstance(e["head"], list) else e["head"], sb)):
                fails.append(f"set delta {f} {'/'.join(map(str, e['path']))} differs from the manifest: "
                             f"{sa!r} -> {sb!r} (manifest {e['base']!r} -> {e['head']!r})")
            elif sa == sb:
                fails.append(f"expected set delta not observed: {f} {'/'.join(map(str, e['path']))}")
            else:
                seen.append({"file": f, "path": "/".join(map(str, e["path"])), "kind": "set",
                             "removed": sorted(set(sa or []) - set(sb or [])),
                             "added": sorted(set(sb or []) - set(sa or [])), "rule": e["rule"]})
            for doc, p in ((a, pa), (b, pb)):        # hide the compared list from the element diff
                if p is not None:
                    _set(doc, p, "<set>")
            continue
        p = resolve_path(b, e["path"])
        if p is None:
            fails.append(f"manifest code path not found in {f}: {e['path']}")
            continue
        allowed[p] = e
    got = {d[0]: d for d in json_diff(a, b)}
    for p, (_, x, y) in got.items():
        e = allowed.get(p)
        if e is None:
            fails.append(f"UNEXPECTED code delta {f} {'/'.join(map(str, p))}: {x!r} -> {y!r}")
        elif not (_eq(e["base"], x) and _eq(e["head"], y)):
            fails.append(f"code delta {f} {'/'.join(map(str, p))} differs from the manifest: {x!r} -> {y!r}")
        else:
            seen.append({"file": f, "path": "/".join(map(str, p)), "base": x, "head": y, "rule": e["rule"]})
    for p in allowed:
        if p not in got:
            fails.append(f"expected code delta not observed: {f} {'/'.join(map(str, p))}")
    return seen


def _get(doc, path):
    for p in path:
        doc = doc[p]
    return doc


def _set(doc, path, v):
    for p in path[:-1]:
        doc = doc[p]
    doc[path[-1]] = v


def _eq(x, y):
    if isinstance(x, dict) and isinstance(y, dict):
        return set(x) == set(y) and all(_eq(x[k], y[k]) for k in x) and list(x) == list(y)
    if isinstance(x, list) and isinstance(y, list):
        return len(x) == len(y) and all(_eq(a, b) for a, b in zip(x, y))
    return same(x, y)


def overall(base_out, head_out):
    """Step 6, information only: which legacy files and decisions differ between BASE and HEAD."""
    bs, hs = summary_of(base_out), summary_of(head_out)
    files = {}
    for f in sorted(set(bs["files"]) | set(hs["files"])):
        if bs["files"].get(f) != hs["files"].get(f):
            try:
                n = len(json_diff(load_norm(os.path.join(base_out, f)), load_norm(os.path.join(head_out, f))))
            except Exception:  # noqa: BLE001
                n = None
            files[f] = n
    dec = json_diff(bs["decisions"], hs["decisions"])
    return {"changed_files": files, "unchanged_files": len(bs["files"]) - len(files),
            "decision_changes": [["/".join(map(str, p)), a, b] for p, a, b in dec]}


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-root", required=True, help="checkout of the manifest's base commit")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--write-report", default=None)
    a = ap.parse_args(argv)
    with open(a.manifest) as fh:
        man = json.load(fh)
    base_root = os.path.abspath(a.base_root)
    os.makedirs(a.work, exist_ok=True)
    W = lambda *p: os.path.join(os.path.abspath(a.work), *p)  # noqa: E731
    shutil.copyfile(os.path.join(HERE, "legacy_parity.py"), os.path.join(base_root, "tools", "v8", "legacy_parity.py"))
    base_golden = os.path.join(ROOT, man["base"]["golden"])
    head_golden = os.path.join(ROOT, man["head_golden"])
    log, fails = [], []

    def step(name, rc_ok):
        print(("ok    " if rc_ok else "FAIL  ") + name, flush=True)
        if not rc_ok:
            fails.append(name)

    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=base_root, capture_output=True, text=True).stdout.strip()
    step(f"base checkout is the manifest base {man['base']['sha'][:12]} (got {sha[:12]})", sha == man["base"]["sha"])
    rc, _ = run(base_root, ["--out", W("base"), "--check", base_golden], log)
    step("1 BASE reproduces its golden digests", rc == 0)
    rc, _ = run(base_root, ["--dump-universe", W("u_base.json")], log)
    step("  BASE universe dumped", rc == 0)
    rc, _ = run(base_root, ["--out", W("base_inj"), "--universe-from", W("u_base.json"), "--check", base_golden], log)
    step("2 BASE with its own universe injected reproduces its golden digests", rc == 0)
    rc, _ = run(ROOT, ["--out", W("head"), "--check", head_golden], log)
    step("3 HEAD reproduces its golden digests", rc == 0)
    rc, _ = run(ROOT, ["--dump-universe", W("u_head.json")], log)
    step("  HEAD universe dumped", rc == 0)
    with open(W("u_head.json")) as fh:
        u_cf = project(json.load(fh), man.get("counterfactual_projection"))
    with open(W("u_cf.json"), "w") as fh:
        json.dump(u_cf, fh)
    rc, _ = run(base_root, ["--out", W("cf"), "--universe-from", W("u_cf.json")], log)
    step("  counterfactual (BASE code, HEAD universe" + (f", {man['counterfactual_projection']}"
                                                         if man.get("counterfactual_projection") else "") + ") ran",
         rc == 0)
    report = {}
    if not fails:
        with open(W("u_base.json")) as fh:
            ub = json.load(fh)
        with open(W("u_head.json")) as fh:
            uh = json.load(fh)
        report, f45 = check(man, ub, uh, W("cf"), W("head"))
        for f in f45:
            print("FAIL  " + f)
        fails += f45
        print(("ok    " if not f45 else "FAIL  ") + "4+5 every BASE -> HEAD delta is in the manifest, and every "
              "manifest delta occurred")
        report["overall"] = overall(W("base"), W("head"))
    report["failures"] = fails
    report["manifest"] = os.path.relpath(os.path.abspath(a.manifest), ROOT)
    if a.write_report:
        with open(a.write_report, "w") as fh:
            json.dump(report, fh, indent=1, sort_keys=True, default=str)
    with open(W("delta_parity.log"), "w") as fh:
        fh.write("\n".join(log))
    if fails:
        print(f"DELTA PARITY FAILED ({len(fails)} problem(s)); log: {W('delta_parity.log')}")
        return 1
    u, c = report.get("universe") or [], report.get("code") or []
    ov = report.get("overall") or {}
    print(f"DELTA PARITY OK: {len(u)} universe deltas, {len(report.get('dex_status') or [])} DEX status deltas, "
          f"{len(report['notes']['removed']) + len(report['notes']['added'])} note deltas and {len(c)} code deltas, "
          f"all in the manifest; 0 unexpected. BASE -> HEAD changed files: "
          + (", ".join(f"{k} ({v} values)" for k, v in sorted(ov.get("changed_files", {}).items())) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
