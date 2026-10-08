"""Re-resolve the universe identity of an earlier scan's market lists with this checkout's v8.identity (v8 Phase 3).

    python tools/v8/rescore_identity.py research_audit_latest.json.gz [--json out.json]

An audit snapshot keeps every contract the adapters kept (venue, raw symbol, ticker, multiplier, price, 24h volume,
the raw metadata Aster and Extended send, and the classification reason). This tool rebuilds the adapter rows in
market-list order and runs v8.identity.resolve() on them, so the identity states of a past scan can be computed
without a network: the Phase 3 inventory of the Phase 2 live scan is reproduced this way.

A Phase 3 snapshot also keeps the raw venue fields (Variational name, Aster underlyingSubType), which are used. For an
older snapshot without them, the market's display name is rebuilt from the recorded reason: a contract whose reason
was a tradfi name pattern gets a name carrying the same pattern word, so the same rule decides. Reads
the snapshot only; changes nothing."""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import snapshot as SN  # noqa: E402

KEPT = ("SELECTED", "DUPLICATE_NOT_SELECTED", "PRICE_CONFLICT_DROPPED", "EXPOSURE_NOT_ADMITTED",
        "UNVERIFIED_EXPOSURE_NOT_ADMITTED")


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def rows_of(snap):
    """{dex: adapter-shaped rows} in market-list order, from the snapshot's contract registry."""
    out = {d: [] for d in sc.DEXES}
    for c in SN.contract_records(snap):
        if c.get("legacy") not in KEPT:
            continue
        meta = c.get("meta") or {}
        why = c.get("cls_reason") or ""
        name = None
        if why.startswith("NAME_PATTERN:"):
            name = f"{c['asset']} {why.split(':', 1)[1]}"
        r = {"t": c["asset"], "dex": c["venue"], "sym": c["raw"], "mult": c["mult"], "price": c["price"],
             "vol": c["vol"], "oi": c.get("oi"), "funding8h": c.get("fund8h"), "tradfi": c.get("tradfi"),
             "name": name}
        r.update(meta)
        vm = c.get("vmeta") or {}            # Phase 3 snapshots keep the raw venue fields
        if c["venue"] == "aster" and isinstance(vm.get("underlyingSubType"), list) and vm["underlyingSubType"]:
            r["subtypes"] = list(vm["underlyingSubType"])
        if c["venue"] == "variational" and vm.get("name"):
            r["name"] = vm["name"]
        out[c["venue"]].append(r)
    return out


def rescore(snap):
    rows = rows_of(snap)
    res = ID.resolve(rows, sc.DEXES, ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME),
                     sc.in_my_dexes)
    states = collections.Counter(a["state"] for a in res.assets.values())
    p2 = collections.Counter(a["phase2"]["state"] for a in res.assets.values())
    default_any = sorted(t for t, a in res.assets.items()
                         if a["phase2"]["state"] == "CRYPTO" and "DEFAULT_CRYPTO" in a["phase2"]["reasons"])
    default_only = sorted(t for t in default_any if res.assets[t]["phase2"]["reasons"] == ["DEFAULT_CRYPTO"])
    now = collections.defaultdict(list)
    for t in default_any:
        now[res.assets[t]["state"]].append(t)
    p2map = {"CRYPTO": ID.VERIFIED_CRYPTO, "TRADFI": ID.VERIFIED_TRADFI, "AMBIGUOUS": ID.AMBIGUOUS}
    changed = {t: [a["phase2"]["state"], a["state"]] for t, a in res.assets.items()
               if p2map[a["phase2"]["state"]] != a["state"]}
    by_venue = collections.Counter()
    for (dex, i), info in res.rows.items():
        if res.coins.get(rows[dex][i]["t"], {}).get("identity") == ID.UNVERIFIED and info["in_record"]:
            by_venue[dex] += 1
    unver = []
    for t, a in res.assets.items():
        if a["state"] != ID.UNVERIFIED:
            continue
        c = res.coins.get(t) or {}
        unver.append({"ticker": t, "venues": sorted(c.get("venues") or {}), "best_vol": c.get("best_vol"),
                      "trade_vol": c.get("trade_vol"), "ref_price": c.get("ref_price"),
                      "symbols": [f"{d}:{v.get('sym')}" for d, v in (c.get("venues") or {}).items()],
                      "liquid_1m": (c.get("trade_vol") or 0) >= 1_000_000, "links": a.get("links")})
    unver.sort(key=lambda r: -(r["best_vol"] or 0))
    return {"identity_version": ID.VERSION, "source_scan": (snap.get("manifest") or {}).get("scan_id"),
            "source_commit": (snap.get("manifest") or {}).get("git_sha"),
            "raw_contracts": len(SN.contract_records(snap)), "adapter_rows": sum(len(v) for v in rows.values()),
            "assets_resolved": len(res.assets), "coins": len(res.coins),
            "states": {s: states.get(s, 0) for s in ID.STATES}, "phase2_states": dict(p2),
            "phase2_default_crypto_any": len(default_any), "phase2_default_crypto_only": len(default_only),
            "phase2_default_partly": sorted(set(default_any) - set(default_only)),
            "default_now": {k: sorted(v) for k, v in sorted(now.items())},
            "default_now_counts": {k: len(v) for k, v in sorted(now.items())},
            "changed_vs_phase2": dict(sorted(changed.items())),
            "unverified_contracts_by_venue": dict(sorted(by_venue.items())),
            "unverified": unver, "unverified_liquid_1m": [r["ticker"] for r in unver if r["liquid_1m"]],
            "execution_identity_eligible": sum(1 for c in res.coins.values() if ID.execution_identity_eligible(c)),
            "discovery_visible_coins": sum(1 for c in res.coins.values() if ID.discovery_eligible(c))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snapshot")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rep = rescore(load(a.snapshot))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True)
    short = {k: v for k, v in rep.items() if k not in ("unverified", "changed_vs_phase2", "default_now")}
    print(json.dumps(short, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
