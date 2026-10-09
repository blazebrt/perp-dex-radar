"""Economic-exposure safety: who holds crypto authority, and what changes if a wrapper label stops counting
(v8 Phase 5, Stage A). Read-only.

    python tools/v8/exposure_safety.py SNAPSHOT [SNAPSHOT ...] [--outputs DIR] [--json out.json]

SNAPSHOT is a v8 audit snapshot (data/v8/audit_latest.json, or a Research run's .json.gz). --outputs is a folder with
the production files of the same scan (latest.json, quant.json, quant_journal.json, picks.json, picks_journal.json,
smart.json, smart_journal.json, journal.csv: the journal-data branch), used to list the open positions and published
outputs an identity change would touch.

1. Inventory. For every VERIFIED_CRYPTO asset, the authority that verifies it: the repository's known-crypto list,
   Extended `category = Crypto` on a contract of its admitted exposure (directly, or inherited by the other contracts
   of that price-coherent exposure), both, or anything else.
2. Projection. The snapshot's adapter rows (tools/v8/rescore_identity.py; it reproduces every recorded state, which
   is checked first, against the identity version that recorded them) are re-resolved through this checkout's
   v8.identity under three readings of Extended Crypto:
     model 1  economic crypto evidence (v8.identity/2: the rules=2 resolution, no Phase 5 evidence)
     model 2  wrapper evidence only: no economic evidence either way (v8.identity/3, production since Phase 5)
     model 3  wrapper evidence that counts as crypto only when corroborated by an independent crypto authority (the
              known-crypto list, the only other positive crypto authority): v8.identity/3 plus that evidence
   and every asset that changes state from model 1 is listed with its contracts, exposures, old and new authority,
   liquidity, and the production outputs and open paper positions it appears in. A snapshot written before Phase 5
   carries no Lighter token-list data: its Lighter markets are projected as checked with no RWA entry, so the
   projection isolates the wrapper change (the token list's own effect is measured on a Phase 5 scan, which records
   every market's check).
3. Controls. Tokenized RWA and collision controls (PAXG, XAUT, SPY, NVDA, TSLA, XAU, US500, US10Y, BYD, SAMSUNGUSD,
   HYUNDAIUSD, XIAOMI; BTC, ETH, SOL, QNT, PURR, BB) under every model. Controls are reported, never rules.

Nothing is written except --json; no network."""
from __future__ import annotations

import argparse
import collections
import contextlib
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import candidate_census as CC  # noqa: E402
import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402

EXT_CRYPTO = "VENUE_CATEGORY:Crypto"
NEG_CONTROLS = ("PAXG", "XAUT", "SPY", "NVDA", "TSLA", "XAU", "US500", "US10Y", "BYD", "SAMSUNGUSD", "HYUNDAIUSD",
                "XIAOMI")
POS_CONTROLS = ("BTC", "ETH", "SOL", "QNT", "PURR", "BB")
MODELS = {
    "model1": "Extended category=Crypto is economic crypto evidence (v8.identity/2)",
    "model2": "Extended category=Crypto is wrapper evidence only (v8.identity/3, Phase 5 production)",
    "model3": "Extended category=Crypto is wrapper evidence, counted as crypto only with an independent crypto "
              "authority (the known-crypto list)",
}


@contextlib.contextmanager
def model(name):
    """v8.identity/3 under model 3: Extended category=Crypto also counts as crypto evidence when the ticker is on the
    known-crypto list (projection only; restored on exit). Models 1 and 2 need no patch."""
    orig = ID.exposure_field_evidence

    def patched(row):
        ev = orig(row)
        if name == "model3" and ID.wrapper_evidence(row) and row.get("t") in sc.KNOWN_CRYPTO:
            ev = ev + [(ID.CRYPTO, EXT_CRYPTO, ID.VENUE_METADATA)]
        return ev

    ID.exposure_field_evidence = patched
    try:
        yield
    finally:
        ID.exposure_field_evidence = orig


def lists():
    return ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME)


def with_checks(rows):
    """Rows of a snapshot written before Phase 5 carry no token-list check: project them as checked, no RWA entry."""
    if any("xcheck" in r for r in rows.get("lighter") or []):
        return rows
    out = dict(rows)
    out["lighter"] = [dict(r, xcheck=ID.XCHECK_OK) for r in rows.get("lighter") or []]
    return out


def resolve(rows, name):
    if name == "model1":
        return ID._resolve(rows, sc.DEXES, lists(), sc.in_my_dexes, None, rules=2)
    with model(name):
        return ID.resolve(with_checks(rows), sc.DEXES, lists(), sc.in_my_dexes)


# --------------------------------------------------------------------------- 1. inventory
def authority(res, t, rows):
    """How a VERIFIED_CRYPTO asset is verified: known list, Extended Crypto (direct / inherited), both, other."""
    a = res.assets[t]
    known = t in sc.KNOWN_CRYPTO
    admitted = [g for g in a["exposures"] if g["admitted"]]
    members = {m for g in admitted for m in g["members"]}
    ext_direct = sorted(m for m in members if m.startswith("extended:") and
                        any(e[2] == EXT_CRYPTO for e in a["evidence"] if e[0] == m))
    inherited = sorted(m for m in members if ext_direct and m not in ext_direct)
    reasons = sorted({g["reason"] for g in admitted})
    if known and ext_direct:
        cls = "known_and_extended"
    elif known:
        cls = "known_only"
    elif ext_direct:
        cls = "extended_only"
    else:
        cls = "other"
    return {"class": cls, "known_crypto": known, "extended_crypto_contracts": ext_direct,
            "inheriting_contracts": inherited if not known else [], "admitted_exposures": [g["id"] for g in admitted],
            "reasons": reasons}


def inventory(res, rows):
    out = {}
    for t, a in sorted(res.assets.items()):
        if a["state"] == ID.VERIFIED_CRYPTO:
            out[t] = authority(res, t, rows)
    counts = collections.Counter(v["class"] for v in out.values())
    return {"total": len(out), "counts": {k: counts.get(k, 0) for k in
                                           ("known_only", "extended_only", "known_and_extended", "other")},
            "extended_only_assets": sorted(t for t, v in out.items() if v["class"] == "extended_only"),
            "extended_only_with_inheritance": sorted(t for t, v in out.items()
                                                     if v["class"] == "extended_only" and v["inheriting_contracts"]),
            "other_assets": sorted(t for t, v in out.items() if v["class"] == "other"),
            "assets": out}


# --------------------------------------------------------------------------- 2. projection
def outputs_index(folder):
    """{asset: [where it appears]} over the published outputs and open paper positions of one scan."""
    idx = collections.defaultdict(set)
    if not folder or not os.path.isdir(folder):
        return idx

    def load(n):
        try:
            with open(os.path.join(folder, n)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    L, Q, P, S = load("latest.json"), load("quant.json"), load("picks.json"), load("smart.json")
    QJ, PJ, SJ = load("quant_journal.json"), load("picks_journal.json"), load("smart_journal.json")
    for p in L.get("picks") or []:
        idx[p.get("coin")].add("radar_pick")
    for p in L.get("watch") or []:
        idx[p.get("coin")].add("radar_watch")
    for r in L.get("table") or []:
        idx[r[1]].add("radar_table")
    for o in Q.get("open") or []:
        idx[o.get("c")].add("quant_actionable_open")
    for o in Q.get("blocked_open") or []:
        idx[o.get("c")].add("quant_blocked_open")
    for t in QJ.get("open") or []:
        idx[t.get("c")].add("quant_journal_open")
    for k, name in (("swing", "swing_list"), ("daytrade", "day_list")):
        for r in (P.get(k) or {}).get("all") or []:
            if isinstance(r, dict):
                idx[r.get("coin")].add(name)
    for t in PJ.get("open") or []:
        idx[t.get("c") or t.get("coin")].add("picks_journal_open")
    for r in S.get("coins") or []:
        if r.get("signal"):
            idx[r["coin"]].add("smart_signal")
        elif r.get("info"):
            idx[r["coin"]].add("smart_info")
        else:
            idx[r["coin"]].add("smart_row")
    for t in SJ.get("open") or []:
        idx[t.get("coin")].add("smart_journal_open")
    try:
        with open(os.path.join(folder, "journal.csv")) as fh:
            for r in csv.DictReader(fh):
                if r.get("status_at_scan") == "open":
                    idx[r["coin"]].add("radar_journal_open")
    except OSError:
        pass
    return idx


def transitions(base, after, out_idx, inv):
    moves = []
    for t, a in sorted(after.assets.items()):
        b = base.assets.get(t) or {}
        if b.get("state") == a["state"]:
            continue
        coin = base.coins.get(t) or {}
        moves.append({"asset": t, "from": b.get("state"), "to": a["state"], "decision": a["decision"],
                      "old_authority": (inv["assets"].get(t) or {}).get("class"),
                      "old_reasons": (inv["assets"].get(t) or {}).get("reasons"),
                      "new_reason": a.get("reason"),
                      "contracts": [f"{d}:{v.get('sym')}" for d, v in (coin.get("venues") or {}).items()],
                      "exposures": [[g["id"], g["class"], g["anchor_price"], g["members"]] for g in a["exposures"]],
                      "best_vol": coin.get("best_vol"), "trade_vol": coin.get("trade_vol"),
                      "liquid_1m": (coin.get("trade_vol") or 0) >= 1_000_000,
                      "outputs": sorted(out_idx.get(t, ()))})
    kinds = collections.Counter(f"{m['from']}->{m['to']}" for m in moves)
    return {"moves": moves, "transitions": dict(sorted(kinds.items())),
            "states": dict(sorted(collections.Counter(a["state"] for a in after.assets.values()).items())),
            "touching_outputs": [m["asset"] for m in moves if m["outputs"]]}


def controls(res):
    out = {}
    for t in NEG_CONTROLS + POS_CONTROLS:
        a = res.assets.get(t)
        out[t] = None if a is None else {
            "state": a["state"], "decision": a["decision"], "reason": a.get("reason"),
            "exposures": [[g["id"], g["class"], g["reason"], g["anchor_price"], g["members"]] for g in a["exposures"]]}
    return out


def extended_crypto_contracts(res, rows):
    """Every kept Extended contract labelled category=Crypto, with its asset's state and how else it is known."""
    out = []
    for i, r in enumerate(rows.get("extended") or []):
        if r.get("category") != "Crypto":
            continue
        a = res.assets.get(r["t"]) or {}
        info = res.rows.get(("extended", i)) or {}
        out.append({"contract": f"extended:{r['sym']}", "asset": r["t"], "asset_state": a.get("state"),
                    "exposure": info.get("exp"), "exposure_class": info.get("exp_cls"),
                    "known_crypto": r["t"] in sc.KNOWN_CRYPTO, "tradfi_list": r["t"] in sc.TRADFI,
                    "price": r.get("price"), "vol": r.get("vol")})
    return out


def known_crypto_audit():
    """Repository known-crypto entries that are also on the tradfi list, or that look like tokenized RWA names."""
    both = sorted(set(sc.KNOWN_CRYPTO) & set(sc.TRADFI))
    rwa_like = sorted(t for t in sc.KNOWN_CRYPTO if any(k in t for k in ("PAXG", "XAU", "GOLD", "XAG", "USDY",
                                                                         "OUSG", "BUIDL", "TSLA", "NVDA", "SPY")))
    return {"size": len(sc.KNOWN_CRYPTO), "also_on_tradfi_list": both, "rwa_like_names": rwa_like}


# --------------------------------------------------------------------------- report
def report(paths, outputs=None):
    out_idx = outputs_index(outputs)
    obs = []
    for p in paths:
        o = CC.observation(p)
        rows = CC.rows_with_vmeta(o["snap"])
        res = {m: resolve(rows, m) for m in MODELS}
        recorded = (o["snap"].get("manifest") or {}).get("identity_version")
        same = res["model1"] if recorded == ID.PREVIOUS_VERSION else res["model2"]   # the rules that recorded it
        diff = sorted(t for t, a in same.assets.items() if o["astate"](t) != a["state"])
        inv = inventory(res["model1"], rows)
        obs.append({"observation": o["meta"], "recorded_identity_version": recorded,
                    "reproduction_differences": diff, "inventory": inv,
                    "token_list_recorded": any("xcheck" in r for r in rows.get("lighter") or []),
                    "extended_crypto_contracts": extended_crypto_contracts(res["model1"], rows),
                    "projection": {m: transitions(res["model1"], res[m], out_idx, inv) for m in ("model2", "model3")},
                    "controls": {m: controls(res[m]) for m in MODELS}})
    return {"schema": "v8.exposure-safety/2", "identity_version": ID.VERSION, "models": MODELS,
            "outputs_folder": outputs, "known_crypto_audit": known_crypto_audit(), "observations": obs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--outputs", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rep = report(a.snapshots, a.outputs)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True, default=str, ensure_ascii=False)
    short = {"known_crypto_audit": rep["known_crypto_audit"], "observations": [
        {"observation": o["observation"], "recorded_identity_version": o["recorded_identity_version"],
         "token_list_recorded": o["token_list_recorded"],
         "reproduction_differences": len(o["reproduction_differences"]),
         "inventory": {k: v for k, v in o["inventory"].items() if k != "assets"},
         "projection": {m: {"transitions": p["transitions"], "states": p["states"],
                            "touching_outputs": p["touching_outputs"]} for m, p in o["projection"].items()}}
        for o in rep["observations"]]}
    print(json.dumps(short, indent=1, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
