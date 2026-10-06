"""Assemble the versioned audit snapshot after every engine of a scan has run.

    python -m v8.snapshot --out site [--pages-url URL] [--archive-dir DIR]

Reads data/v8/parts/*.json (written by each engine), the legacy output files (hashed, never changed) and the
previous scan's first-seen map, and writes
    data/v8/audit_latest.json      the snapshot (manifest, registry, data_health, dispositions, coverage,
                                   legacy_output_refs, storage)
    data/v8/audit_latest.json.gz   the same, gzip (deterministic: no file name or time in the header)
    data/v8/first_seen.json        contract id -> [first seen, last seen], carried from scan to scan via the site
With --archive-dir the gzip copy is also appended to a bounded archive (an Actions artifact with a retention
period in the Scan workflow); nothing is stored permanently and no external service is used.

The snapshot is deterministic for the same inputs: sorted keys, no wall-clock values except the scan's own."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request

from . import ENGINE_VERSION, SCHEMA
from . import ledger as LG
from . import parts as PT
from . import taxonomy as T

ENGINES = ("universe", "radar", "quant", "swing", "day", "smart")
LEGACY_FILES = ("latest.json", "journal.json", "journal.csv", "quant.json", "quant_journal.json", "picks.json",
                "picks_journal.json", "smart.json", "smart_journal.json", "dashboard.json")
FIRST_SEEN_KEEP_S = 400 * 86400


def _load_json_url(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "perp-dex-radar-v8", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_first_seen(out_dir, pages_url=None, path=None):
    """The previous scan's first-seen map: an explicit file, else the published one, else empty."""
    if path:
        try:
            with open(path) as fh:
                return json.load(fh), "file"
        except (OSError, ValueError):
            return {}, "missing"
    if pages_url:
        try:
            d = _load_json_url(pages_url.rstrip("/") + "/data/v8/first_seen.json")
            return (d if isinstance(d, dict) else {}), "site"
        except Exception:  # noqa: BLE001 - the first scan with v8 has none
            return {}, "unavailable"
    return {}, "none"


def file_ref(path, rel):
    with open(path, "rb") as fh:
        b = fh.read()
    return {"path": rel, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}


def _smart_fill(smart, registry):
    """Registry assets the smart-money engine never saw: not held, or not on Hyperliquid at all."""
    if not smart or not registry:
        return
    recs = {r["a"]: r for r in smart.get("records") or []}
    hl = {c["asset"] for c in registry["contracts"] if c["venue"] == "hyperliquid" and c["legacy"] == "SELECTED"}
    L = LG.Ledger("smart")
    for t in sorted(registry["assets"]):
        if t in recs:
            continue
        if t in hl:
            L.final(t, "SMART_NOT_HELD", "snapshot", k=[c for c in registry["assets"][t]["contracts"]
                                                         if c.startswith("hyperliquid:")])
        else:
            L.final(t, "SMART_VENUE_NOT_COVERED", "snapshot", o={"venues": registry["assets"][t]["venues"]})
    add = list(L.records.values())
    smart["records"] = sorted((smart.get("records") or []) + add, key=lambda r: r["a"])
    cov = smart.setdefault("coverage", {})
    cov["filled_at_snapshot"] = len(add)
    by_d = {d: 0 for d in T.DISPOSITIONS}
    by_c = {}
    for r in smart["records"]:
        by_d[r["d"]] += 1
        by_c[r["c"]] = by_c.get(r["c"], 0) + 1
    cov.update(input=cov.get("input", 0) + len(add), disposed=len(smart["records"]), by_disposition=by_d,
               by_reason=dict(sorted(by_c.items())))


def build(out_dir, pages_url=None, first_seen_path=None):
    data = os.path.join(out_dir, "data")
    P = {e: PT.read(out_dir, e) for e in ENGINES}
    uni = P.get("universe") or {}
    reg = uni.get("registry") if uni.get("ok") else None
    hdr = (uni.get("header") or (P.get("radar") or {}).get("header") or {})
    ts = hdr.get("ts")
    # first seen, from our own registry history
    prev, fs_src = load_first_seen(out_dir, pages_url, first_seen_path)
    fs = {}
    if reg:
        for c in reg["contracts"]:
            old = prev.get(c["id"]) if isinstance(prev.get(c["id"]), list) else None
            first = old[0] if old else ts
            c["first_seen"] = first
            fs[c["id"]] = [first, ts]
        for cid, v in prev.items():        # keep markets not returned this scan for a while (they may come back)
            if cid not in fs and isinstance(v, list) and len(v) == 2 and ts and ts - (v[1] or 0) <= FIRST_SEEN_KEEP_S:
                fs[cid] = v
    _smart_fill(P.get("smart"), reg)
    # dispositions and coverage
    dispositions, coverage, problems = {}, {}, {}
    for e in ENGINES:
        p = P.get(e)
        if not p:
            coverage[e] = {"status": "MISSING_PART"}
            continue
        if not p.get("ok"):
            coverage[e] = {"status": "AUDIT_FAILED", "error": p.get("error")}
            continue
        dispositions[e] = p.get("records") or []
        coverage[e] = dict(p.get("coverage") or {}, status="OK", stages=p.get("stages"))
        if p.get("problems"):
            problems[e] = p["problems"]
    radar_in = {r["a"] for r in dispositions.get("radar", [])}
    uni_final = {r["a"] for r in dispositions.get("universe", [])}
    reg_assets = set((reg or {}).get("assets") or {})
    universe_unaccounted = sorted(reg_assets - radar_in - uni_final)
    # engines that build their own universe (quant, picks) fetch the market lists again minutes later
    diffs = {}
    for e in ("quant", "swing", "smart"):
        got = {r["a"] for r in dispositions.get(e, [])}
        if e == "smart":
            got = got & reg_assets
            diffs[e] = {"registry_assets_without_record": len(reg_assets - got)}
            continue
        diffs[e] = {"in_scanner_universe_only": sorted(radar_in - got)[:50],
                    "in_engine_universe_only": sorted(got - radar_in)[:50],
                    "n_scanner_only": len(radar_in - got), "n_engine_only": len(got - radar_in)}
    rc = uni.get("registry_counts") or {}
    rstages = (P.get("radar") or {}).get("stages") or {}

    def n_disp(e, d):
        return ((coverage.get(e) or {}).get("by_disposition") or {}).get(d, 0)

    def n_code(e, *codes):
        br = (coverage.get(e) or {}).get("by_reason") or {}
        return sum(br.get(c, 0) for c in codes)

    summary = {
        "raw_contracts": rc.get("raw_contracts"), "active_perps": rc.get("active_perps"),
        "canonical_assets": rc.get("canonical_assets"), "legacy_universe": rstages.get("universe"),
        "legacy_crypto": rstages.get("crypto"),
        "tradfi_exclusions": n_code("radar", "TRADFI_CLASSIFIED", "TRADFI_TICKER_COLLISION"),
        "tradfi_collisions": n_code("radar", "TRADFI_TICKER_COLLISION"),
        "universe_exclusions": len(uni_final),
        "no_data_exclusions_radar": n_disp("radar", T.INSUFFICIENT_DATA),
        "scanner_stage1": rstages.get("stage1_charted"), "scanner_stage2": rstages.get("stage2_selected"),
        "scanner_extras": rstages.get("stage2_extras"), "scanner_deep_dives": rstages.get("deep_dives"),
        "quant_eligible": ((P.get("quant") or {}).get("stages") or {}).get("eligible_latest_day"),
        "swing_eligible": ((P.get("swing") or {}).get("stages") or {}).get("swing_checked"),
        "smart_represented": ((P.get("smart") or {}).get("stages") or {}).get("rows"),
        "dispositions": {e: (coverage.get(e) or {}).get("by_disposition") for e in ENGINES},
        "unaccounted": {"registry_assets": len(universe_unaccounted),
                        **{e: (coverage.get(e) or {}).get("unaccounted") for e in ENGINES}},
        "unaccounted_registry_assets": universe_unaccounted[:50],
        "engine_universe_differences": diffs,
    }
    # data health
    by_venue = {}
    vals = {"price": {}, "vol": {}, "oi": {}, "fund8h": {}}
    for c in (reg or {}).get("contracts") or []:
        v = by_venue.setdefault(c["venue"], {s: 0 for s in T.HEALTH})
        v[c["health"]] += 1
        for f in vals:
            b = (c.get("basis") or {}).get(f, "OBSERVED")
            vals[f][b] = vals[f].get(b, 0) + 1
    rec_health = {}
    for e, recs in dispositions.items():
        h = {s: 0 for s in T.HEALTH}
        for r in recs:
            h[r.get("h", T.HEALTHY)] = h.get(r.get("h", T.HEALTHY), 0) + 1
        rec_health[e] = h
    steps = {}
    for e, recs in dispositions.items():
        for r in recs:
            for x in r.get("x") or []:
                steps.setdefault(e, {})[x] = steps.setdefault(e, {}).get(x, 0) + 1
    legacy_cov = {}
    try:
        with open(os.path.join(data, "latest.json")) as fh:
            lc = json.load(fh).get("coverage") or {}
        legacy_cov = {"candle_sources": lc.get("sources"), "dex_ok": lc.get("dex_ok"),
                      "dexes": {k: {"ok": v.get("ok"), "markets": v.get("markets")}
                                for k, v in (lc.get("dexes") or {}).items()}}
    except (OSError, ValueError, AttributeError):
        legacy_cov = {"status": "latest.json unreadable"}
    data_health = {"contracts_by_venue": dict(sorted(by_venue.items())), "value_basis": vals,
                   "records_by_engine": rec_health, "steps": steps, "sources": legacy_cov,
                   "registry_venues": (reg or {}).get("venues"), "first_seen_source": fs_src,
                   "audit_problems": problems}
    # legacy output references (hashes of the files the engines wrote; the audit never changes them)
    refs = []
    for name in LEGACY_FILES:
        p = os.path.join(data, name)
        if os.path.exists(p):
            refs.append(file_ref(p, f"data/{name}"))
    manifest = {
        "schema": SCHEMA, "audit_version": ENGINE_VERSION, "scan_id": hdr.get("scan_id"), "ts": ts,
        "repo": hdr.get("repo"), "ref": hdr.get("git_ref"), "git_sha": hdr.get("git_sha"),
        "engine_versions": {e: ((P.get(e) or {}).get("header") or {}).get("engine_version") for e in ENGINES},
        "config_hashes": {e: ((P.get(e) or {}).get("header") or {}).get("config_hash") for e in ENGINES},
        "parts": {e: ("ok" if (P.get(e) or {}).get("ok") else "failed" if P.get(e) else "missing") for e in ENGINES},
        "scan_ids_consistent": len({((P.get(e) or {}).get("header") or {}).get("scan_id") for e in ENGINES
                                    if P.get(e)}) <= 1,
        "registry_contracts": rc.get("raw_contracts"),
        "dispositions": sum(len(v) for v in dispositions.values()),
        "data_sources": {"dex_market_lists": {k: (v or {}).get("ok") for k, v in ((reg or {}).get("venues") or {}).items()},
                         "fallback_universe": bool(uni.get("fallback"))},
        "legacy_output_hashes": {r["path"]: r["sha256"] for r in refs},
    }
    snap = {"schema": SCHEMA, "manifest": manifest, "coverage": {"summary": summary, "engines": coverage},
            "registry": {"counts": rc, "contracts": (reg or {}).get("contracts") or [],
                         "assets": (reg or {}).get("assets") or {}, "events": (reg or {}).get("events") or []},
            "data_health": data_health, "dispositions": dispositions,
            "reasons": {k: {"disposition": v[0], "text": v[1]} for k, v in T.REASONS.items()},
            "steps": T.STEPS, "legacy_output_refs": refs}
    return snap, fs


def dumps(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()


def gz(b):
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as fh:
        fh.write(b)
    return buf.getvalue()


def storage(snap_bytes, gz_bytes, snap):
    """Measured sizes of this snapshot and what keeping every one would cost."""
    sec = {k: len(dumps(v)) for k, v in snap.items() if k != "storage"}
    per_day = {"nominal_72_per_day": 72, "hourly_24_per_day": 24, "observed_4_per_day": 4}
    proj = {}
    for name, n in per_day.items():
        proj[name] = {"day_gz": gz_bytes * n, "30d_gz": gz_bytes * n * 30, "1y_gz": gz_bytes * n * 365,
                      "day_raw": snap_bytes * n, "30d_raw": snap_bytes * n * 30, "1y_raw": snap_bytes * n * 365}
    return {"uncompressed_bytes": snap_bytes, "gzip_bytes": gz_bytes, "sections_bytes": sec, "projection": proj,
            "note": "Sizes of this scan's snapshot; the projection multiplies by scans per day. The Scan workflow "
                    "is scheduled 72 times a day but GitHub runs it far less often (about 4 a day observed)."}


class ArchiveDir:
    """Append-only, bounded history: one gzip file per scan id in a directory the Scan workflow uploads as an
    Actions artifact with a retention period. Never overwrites an existing scan's file."""

    def __init__(self, path):
        self.path = path

    def append(self, scan_id, gz_bytes):
        os.makedirs(self.path, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(scan_id))
        p = os.path.join(self.path, f"audit_{safe}.json.gz")
        if os.path.exists(p):
            return None
        with open(p, "xb") as fh:
            fh.write(gz_bytes)
        return p


def write(out_dir, pages_url=None, first_seen_path=None, archive_dir=None, keep_parts=False):
    snap, fs = build(out_dir, pages_url, first_seen_path)
    raw = dumps({k: v for k, v in snap.items()})
    z = gz(raw)
    snap["storage"] = storage(len(raw), len(z), snap)
    raw = dumps(snap)
    z = gz(raw)
    d = os.path.join(out_dir, "data", "v8")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "audit_latest.json"), "wb") as fh:
        fh.write(raw)
    with open(os.path.join(d, "audit_latest.json.gz"), "wb") as fh:
        fh.write(z)
    with open(os.path.join(d, "first_seen.json"), "wb") as fh:
        fh.write(dumps(fs))
    arch = ArchiveDir(archive_dir).append(snap["manifest"]["scan_id"] or "unknown", z) if archive_dir else None
    if not keep_parts:
        shutil.rmtree(os.path.join(out_dir, PT.PART_DIR), ignore_errors=True)
    return snap, len(raw), len(z), arch


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble the v8 audit snapshot from this scan's engine parts")
    ap.add_argument("--out", default="site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"))
    ap.add_argument("--first-seen", default=None, help="previous first_seen.json (default: read from the site)")
    ap.add_argument("--archive-dir", default=None, help="append the gzip snapshot to this bounded archive folder")
    ap.add_argument("--keep-parts", action="store_true")
    a = ap.parse_args(argv)
    snap, n, z, arch = write(a.out, a.pages_url, a.first_seen, a.archive_dir, a.keep_parts)
    s = snap["coverage"]["summary"]
    print(f"[v8] audit snapshot {snap['manifest']['scan_id']}: {s['raw_contracts']} contracts, "
          f"{s['canonical_assets']} assets, {snap['manifest']['dispositions']} dispositions, unaccounted "
          f"{s['unaccounted']}, {n} bytes ({z} gzip)" + (f", archived {os.path.basename(arch)}" if arch else ""),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
