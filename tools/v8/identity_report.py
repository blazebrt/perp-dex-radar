"""Universe identity report from an audit snapshot (v8 Phase 2): the collision matrix and the missing-volume cases.

    python tools/v8/identity_report.py out_new/data/v8/audit_latest.json [--json research_identity.json]

For every ticker whose own markets disagree (a collision), every market: venue, raw symbol, price per 1 coin,
24h volume, its own classification and reason, its exposure and the exposure's class, and whether it reached the
crypto universe; then the ticker's decision before (Phase 1 ticker-level OR) and now. Also the headline counts and
every coin excluded for a missing 24h volume. Reads the snapshot only; changes nothing."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from v8 import snapshot as SN  # noqa: E402


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def report(snap):
    reg = snap.get("registry") or {}
    counts = reg.get("counts") or {}
    assets = reg.get("assets") or {}
    by_id = {c["id"]: c for c in SN.contract_records(snap)}
    recs = {e: {r["a"]: r for r in (snap.get("dispositions") or {}).get(e, [])} for e in ("radar", "quant", "swing")}
    out = {"scan_id": (snap.get("manifest") or {}).get("scan_id"),
           "git_sha": (snap.get("manifest") or {}).get("git_sha"),
           "identity_version": (snap.get("manifest") or {}).get("identity_version"),
           "counts": {k: counts.get(k) for k in (
               "raw_contracts", "active_perps", "canonical_assets", "assets_by_legacy", "assets_by_identity",
               "phase1_crypto", "phase1_excluded", "now_crypto", "now_excluded", "changed_vs_phase1",
               "tradfi_collisions", "crypto_exposure_selected", "ambiguous", "by_contract_class", "by_exposure_class",
               "adapter_mismatches")},
           "unaccounted": ((snap.get("coverage") or {}).get("summary") or {}).get("unaccounted"),
           "collisions": [], "missing_volume": []}
    for t in counts.get("tradfi_collisions") or []:
        a = assets.get(t) or {}
        ident = a.get("identity") or {}
        rows = []
        for cid in a.get("contracts") or []:
            c = by_id.get(cid) or {}
            rows.append({"contract": cid, "venue": c.get("venue"), "active": c.get("active"), "price": c.get("price"),
                         "npx": c.get("npx"), "vol": c.get("vol"), "class": c.get("cls"),
                         "reason": c.get("cls_reason"), "meta": c.get("meta"), "exposure": c.get("exposure"),
                         "exposure_class": c.get("exp_class"), "exposure_reason": c.get("exp_reason"),
                         "inherited_from": c.get("inherited_from"), "state": c.get("legacy"),
                         "crypto_universe": bool(c.get("admitted")) if c.get("admitted") is not None else None})
        out["collisions"].append({
            "ticker": t, "phase1": ident.get("phase1"), "now": a.get("legacy"), "decision": ident.get("decision"),
            "ticker_list": ident.get("ticker_list"), "exposures": ident.get("exposures"), "contracts": rows,
            "engines": {e: [recs[e][t]["d"], recs[e][t]["c"]] for e in recs if t in recs[e]}})
    for t, r in sorted(recs["radar"].items()):
        if r["c"] in ("DEX_VOLUME_MISSING",):
            out["missing_volume"].append({"ticker": t, "radar": r["c"], "venues": (r.get("o") or {}).get("venues"),
                                          "quant": (recs["quant"].get(t) or {}).get("c"),
                                          "swing": (recs["swing"].get(t) or {}).get("c")})
    zero = sorted(t for t, r in recs["quant"].items() if r["c"] == "DEX_VOLUME_BELOW_LEGACY_MIN"
                  and (r.get("o") or {}).get("basis") == "OBSERVED_ZERO")
    out["observed_zero_volume"] = zero
    out["missing_volume_quant"] = sorted(t for t, r in recs["quant"].items() if r["c"] == "DEX_VOLUME_MISSING")
    return out


def text(rep):
    L = [f"scan {rep['scan_id']}  commit {str(rep['git_sha'])[:12]}  {rep['identity_version']}", ""]
    for k, v in rep["counts"].items():
        L.append(f"{k}: {v}")
    L.append(f"unaccounted: {rep['unaccounted']}")
    L.append("")
    for c in rep["collisions"]:
        L.append(f"== {c['ticker']}: Phase 1 {c['phase1']} -> now {c['now']} ({c['decision']}); ticker list "
                 f"{c['ticker_list']}; engines {c['engines']}")
        for r in c["contracts"]:
            L.append(f"   {r['contract']:<28} px {r['price']!s:<14} per coin {r['npx']!s:<14} vol {r['vol']!s:<12} "
                     f"{r['class']!s:<9} {r['reason']!s:<28} {r['exposure']!s:<11} {r['exposure_class']!s:<9} "
                     f"{r['exposure_reason']!s:<34} {r['state']!s:<22} crypto={r['crypto_universe']}")
    L.append("")
    L.append(f"missing 24h volume (radar): {rep['missing_volume']}")
    L.append(f"missing 24h volume (quant): {rep['missing_volume_quant']}")
    L.append(f"observed zero volume (quant): {rep['observed_zero_volume']}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snapshot")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rep = report(load(a.snapshot))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True)
    print(text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
