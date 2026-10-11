"""Full-universe discovery report (v8 Phase 7). Read-only.

    python tools/v8/discovery_report.py OBS [OBS ...] [--quant-part PATH] [--json OUT]

Each OBS is either
  * a discovery file (data/v8/discovery.json, schema v8.discovery/1): coverage, venues, accounting, stages, deep-research
    reasons, lanes, flags, the emerging census, the shadow deep-research queue against the legacy stage 2; or
  * an audit snapshot (data/v8/audit_latest.json[.gz], any v8.audit schema): the coverage census the snapshot alone can
    give (Stage A of Phase 7: venues, contracts, identity, liquidity buckets, the radar's pipeline counts, what the
    published radar table cannot show, an emerging census from the registry). For a snapshot that has no discovery
    file yet (production before Phase 7) this is the baseline.
--quant-part: a quant audit part (data/v8/parts/quant.json) - its consistency problems and the open positions recorded
for their lifecycle only (Phase 7's bounded quant-audit fix).

Nothing here decides anything or makes a request."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

TRADE = ("hyperliquid", "lighter", "aster", "variational")      # scanner CFG["trade_dexes"] (unchanged)
MIN_VOL = 1_000_000


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as fh:
        return json.load(fh)


def count(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: str(kv[0])))


def bucket(v):
    if v is None:
        return "MISSING"
    return ">=5M" if v >= 5e6 else "1M-5M" if v >= 1e6 else "100k-1M" if v >= 1e5 else "<100k"


# --------------------------------------------------------------------------- a discovery file
def discovery(doc):
    p, a = doc["provenance"], doc["accounting"]
    rs = doc["assets"]
    out = {"kind": "discovery", "provenance": p, "venues": doc["venues"], "accounting": a,
           "identity": count(r["identity"] or "NONE" for r in rs),
           "liquidity": count(r["execution_liquidity"]["state"] if r["execution_liquidity"]["observed_value"] is None
                              else bucket(r["execution_liquidity"]["observed_value"]) for r in rs),
           "flags": count(f for r in rs for f in r["anomaly_flags"]),
           "visibility": {"radar_table": sum(1 for r in rs if r["discovery_stage"] not in ("DISCOVERED", "LIGHT_ONLY")),
                          "discovery_only": count((r["identity"] or "NONE") for r in rs
                                                  if r["discovery_stage"] in ("DISCOVERED", "LIGHT_ONLY"))},
           "emerging": doc["emerging"], "shadow_top": doc["shadow_queue"]["entries"][:20],
           "legacy_vs_shadow": doc["legacy_vs_shadow"],
           "lanes_top": {ln: [[r["asset"], r["research_priority"]["points"], r["anomaly_flags"]]
                              for r in sorted((r for r in rs if r["priority_lane"] == ln),
                                              key=lambda r: (-r["research_priority"]["points"], r["asset"]))[:12]]
                         for ln in sorted({r["priority_lane"] for r in rs})}}
    return out


def print_discovery(o, name):
    p, a = o["provenance"], o["accounting"]
    print(f"== discovery {name}: {p['schema']} scan {p['scan_id']} git {str(p['git_sha'])[:12]} identity "
          f"{p['identity_version']} {str(p['identity_config_hash'])[:12]}")
    print(f"   coverage {p['coverage_state']}  full_discovery_qualified {p['full_discovery_qualified']}  fallback "
          f"{p['fallback_universe']}  venues ok {p['venues_ok']}/{p['venues_expected']} failed {p['venues_failed_names']}")
    print(f"   contracts {a['registry_contracts']}  active perps {a['active_perps']}  in denominator "
          f"{a['active_perps_in_denominator']}  in discovery {a['active_perps_in_discovery']}  unsupported "
          f"{a['active_perps_unsupported']}  on unavailable venues {a['active_perps_on_unavailable_venues']}")
    print(f"   assets {a['canonical_assets']} = discovery {a['discovery_assets']} + registry-only "
          f"{a['registry_only_assets']} {a['registry_only_by_reason']}")
    print(f"   UNACCOUNTED {a['unaccounted']} {a['unaccounted_by_scope']}  problems {len(a['problems'])}")
    print("   venues: " + ", ".join(f"{v} {x['state']} {x['active_perps']}" for v, x in o["venues"].items()))
    print(f"   identity {o['identity']}")
    print(f"   execution liquidity {o['liquidity']}")
    print(f"   stages {a['by_stage']}")
    print(f"   deep research {a['by_deep_reason']}")
    print(f"   lanes {a['by_lane']}")
    print(f"   final dispositions {a['by_final_disposition']}")
    print(f"   flags {o['flags']}")
    print(f"   visibility: radar table {o['visibility']['radar_table']}, discovery-only {o['visibility']['discovery_only']}")
    for k, v in o["emerging"].items():
        if isinstance(v, dict):
            print(f"   emerging {k}: " + ", ".join(f"{kk} {vv}" for kk, vv in v.items() if kk != "top_by_points"))
            print("      top: " + "; ".join(f"{t} {pt} {' '.join(f)}" for t, pt, f in v["top_by_points"][:12]))
    c = o["legacy_vs_shadow"]
    print(f"   legacy deep {c['legacy_deep']} vs shadow {c['shadow']}: overlap {c['overlap']}, legacy-only "
          f"{len(c['legacy_only'])} {c['legacy_only'][:20]}, shadow-only {len(c['shadow_only'])} "
          f"{c['shadow_only_by_reason']}  resource {c['resource']}  authority {c['authority']}")
    for x in c["shadow_only"][:20]:
        print(f"      shadow-only {x['asset']}: {' '.join(x['flags'])} | {x['lane']} | {x['why_not_legacy_deep']} | "
              f"{x['liquidity']}")
    print("   shadow top 20: " + "; ".join(f"{e['rank']} {e['asset']} {e['points']}" for e in o["shadow_top"]))
    for ln, xs in o["lanes_top"].items():
        print(f"   lane {ln}: " + "; ".join(f"{t} {pt}" for t, pt, _ in xs))


# --------------------------------------------------------------------------- an audit snapshot (Stage A census)
def census(s):
    from v8 import snapshot as SN
    cs = SN.contract_records(s)
    A = s["registry"]["assets"]
    R = {r["a"]: r for r in (s.get("dispositions") or {}).get("radar") or []}
    ts = s["manifest"]["ts"]
    act = [c for c in cs if c.get("type") == "perp" and c.get("active")]
    sel = {}
    for c in act:
        if c.get("legacy") == "SELECTED":
            sel.setdefault(c["asset"], []).append(c)

    def tvol(t):
        v = [c["vol"] for c in sel.get(t, []) if c.get("vol") is not None and c["venue"] in TRADE]
        return max(v) if v else None
    state = {t: ((A.get(t) or {}).get("identity") or {}).get("state") for t in R}
    fs = [c["first_seen"] for c in cs if c.get("first_seen")]
    since = min(fs) if fs else None
    first = {t: min((c["first_seen"] for c in sel.get(t, []) if c.get("first_seen")), default=None) for t in R}
    new = sorted(t for t, f in first.items() if f and since and f > since and ts - f <= 7 * 86400)
    nven = {t: len({c["venue"] for c in sel.get(t, [])}) for t in R}
    deep = {t for t, r in R.items() if r["st"] in ("deep_dive", "signal", "plan", "block", "publish")}
    charted = {t for t, r in R.items() if r["st"] not in ("universe", "stage1")}
    cr = [t for t, x in state.items() if x == "VERIFIED_CRYPTO"]
    em = [t for t in cr if t not in deep and ((tvol(t) or 0) < MIN_VOL or nven[t] == 1 or t in new)]
    uv = [t for t, x in state.items() if x in ("UNVERIFIED", "AMBIGUOUS")]
    rad = (s["coverage"]["engines"].get("radar") or {}).get("stages") or {}
    return {"kind": "census", "manifest": {k: s["manifest"].get(k) for k in ("schema", "audit_version", "scan_id",
                                                                             "git_sha", "identity_version",
                                                                             "identity_config_hash", "ts")},
            "venues": s["data_health"].get("registry_venues"),
            "contracts": {"raw": len(cs), "active_perps": len(act), "by_legacy": count(c["legacy"] for c in act)},
            "assets": {"canonical": len(A), "by_legacy": count(a["legacy"] for a in A.values()),
                       "universe_coins": len(R), "identity": count(state.values())},
            "liquidity_by_identity": {st: count(bucket(tvol(t)) for t, x in state.items() if x == st)
                                      for st in sorted({x for x in state.values() if x})},
            "pipeline": rad, "radar_codes": count(f"{r['st']}:{r['c']}" for r in R.values()),
            "invisible_in_radar_table": count(f"{state[t]}:{R[t]['c']}" for t in R if t not in charted),
            "coverage_of_values": {f: sum(1 for t in R if any(c.get(f) is not None for c in sel.get(t, [])))
                                   for f in ("price", "vol", "oi", "fund8h")},
            "venue_count": count(nven.values()),
            "tracking_since": since, "tracking_days": round((ts - since) / 86400, 2) if since else None,
            "new_listings": new,
            "emerging_verified": {"assets": len(em), "below_min": sum(1 for t in em if tvol(t) is not None
                                                                       and tvol(t) < MIN_VOL),
                                  "missing": sum(1 for t in em if tvol(t) is None),
                                  "single_venue": sum(1 for t in em if nven[t] == 1),
                                  "new": sum(1 for t in em if t in new), "charted": sum(1 for t in em if t in charted)},
            "unverified_or_ambiguous": {"assets": len(uv), "single_venue": sum(1 for t in uv if nven[t] == 1),
                                        "new": sum(1 for t in uv if t in new),
                                        "liquidity": count(bucket(tvol(t)) for t in uv)},
            "audit_problems": s["data_health"].get("audit_problems"),
            "discovery_section": s.get("discovery")}


def print_census(o, name):
    m = o["manifest"]
    print(f"== census {name}: {m['schema']} {m['audit_version']} scan {m['scan_id']} git {str(m['git_sha'])[:12]} "
          f"identity {m['identity_version']} {str(m['identity_config_hash'])[:12]}")
    print("   venues: " + ", ".join(f"{v} {'ok' if x.get('ok') else 'FAILED'} raw {x.get('raw')} kept {x.get('kept')}"
                                    for v, x in sorted((o["venues"] or {}).items())))
    print(f"   contracts {o['contracts']}")
    print(f"   assets {o['assets']}")
    for st, b in o["liquidity_by_identity"].items():
        print(f"   liquidity {st}: {b}")
    print(f"   radar pipeline {o['pipeline']}")
    print(f"   radar codes {o['radar_codes']}")
    print(f"   not in the published radar table {o['invisible_in_radar_table']}")
    print(f"   values present (universe coins) {o['coverage_of_values']}  venue count {o['venue_count']}")
    print(f"   first-seen tracking since {o['tracking_since']} ({o['tracking_days']} days); new listings "
          f"{o['new_listings']}")
    print(f"   emerging verified crypto {o['emerging_verified']}")
    print(f"   unverified / ambiguous {o['unverified_or_ambiguous']}")
    print(f"   audit problems {o['audit_problems']}")
    if o.get("discovery_section"):
        d = o["discovery_section"]
        print(f"   discovery section: {d.get('status')} assets {(d.get('coverage') or {}).get('discovery_assets')} "
              f"unaccounted {d.get('unaccounted')}")


def quant_part(path):
    q = load(path)
    life = [r for r in q.get("records") or [] if "POSITION_LIFECYCLE_ONLY" in (r.get("x") or [])]
    return {"kind": "quant_part", "ok": q.get("ok"), "problems": q.get("problems") or [],
            "lifecycle": [[r["a"], r["c"], (r.get("o") or {}).get("execution_reason")] for r in life],
            "surfaced": sorted(r["a"] for r in q.get("records") or [] if r["d"] == "SURFACED"),
            "open": (q.get("stages") or {}).get("open"), "blocked_open": (q.get("stages") or {}).get("blocked_open")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("obs", nargs="*")
    ap.add_argument("--quant-part", action="append", default=[])
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    out = {}
    for path in a.obs:
        name = os.path.basename(path)
        try:
            d = load(path)
        except Exception as e:  # noqa: BLE001 - a missing observation is reported, never fatal
            print(f"== {name}: unreadable ({type(e).__name__}: {e})")
            out[name] = {"error": f"{type(e).__name__}: {e}"}
            continue
        if d.get("schema", "").startswith("v8.discovery/"):
            out[name] = discovery(d)
            print_discovery(out[name], name)
        else:
            out[name] = census(d)
            print_census(out[name], name)
    for path in a.quant_part:
        name = "quant_part:" + path
        try:
            out[name] = quant_part(path)
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": f"{type(e).__name__}: {e}"}
        print(f"== {name}: {out[name]}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1, sort_keys=True, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
