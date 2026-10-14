"""Assemble the versioned audit snapshot after every engine of a scan has run.

    python -m v8.snapshot --out site [--pages-url URL] [--archive-dir DIR]

Reads data/v8/parts/*.json (written by each engine), the legacy output files (hashed, never changed) and the
previous scan's first-seen map, and writes
    data/v8/audit_latest.json      the snapshot (manifest, registry, data_health, dispositions, coverage,
                                   legacy_output_refs, storage)
    data/v8/audit_latest.json.gz   the same, gzip (deterministic: no file name or time in the header)
    data/v8/first_seen.json        contract id -> [first seen, last seen], carried from scan to scan via the site
    data/v8/identity_state.json    asset -> [identity state, since] (v8 Phase 3), carried the same way; state changes
                                   since the previous scan are listed in the snapshot (coverage.summary.identity)
    data/v8/discovery.json         v8 Phase 7: one discovery record per asset with an active perpetual on a healthy
                                   venue (v8.discovery/1); its summary is the snapshot's `discovery` section
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
from .liquidity import VERSION as LIQUIDITY_VERSION
from . import decision as DEC
from . import discovery as DS
from . import history as HI
from . import ledger as LG
from . import parts as PT
from . import provenance
from . import taxonomy as T

ENGINES = ("universe", "radar", "quant", "swing", "day", "smart")
CONTRACT_FIELDS = ("id", "venue", "raw", "norm", "asset", "mult", "canon", "type", "active", "status", "tradfi",
                   "tradfi_reason", "price", "vol", "oi", "fund8h", "fund_iv_h", "src_ts", "rcv_ts", "first_seen",
                   "health", "basis", "legacy",
                   # v8 Phase 2 identity (v8.identity; None for markets the adapters skip)
                   "cls", "cls_reason", "cls_auth", "npx", "exposure", "exp_class", "exp_reason", "admitted",
                   "inherited_from", "meta",
                   # v8 Phase 3 identity (exposure state, in the coin record, evidence, parsed symbol and its link, raw
                   # venue identity fields)
                   "exp_state", "in_record", "evidence", "parsed", "link", "vmeta",
                   # v8 Phase 4: observed candidate evidence (never authority)
                   "candidate",
                   # v8 Phase 5: wrapper evidence (never decides) and the venue's economic-exposure check
                   "wrapper", "xcheck")
LEGACY_FILES = ("latest.json", "journal.json", "journal.csv", "quant.json", "quant_journal.json", "picks.json",
                "picks_journal.json", "smart.json", "smart_journal.json", "dashboard.json")
FIRST_SEEN_KEEP_S = 400 * 86400
IDENTITY_FILE = "identity_state.json"     # asset -> [identity state, since ts], carried from scan to scan via the site


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


def load_identity_state(pages_url=None, path=None):
    """The previous scan's identity states (asset -> [state, since]): an explicit file, else the published one."""
    if path:
        try:
            with open(path) as fh:
                d = json.load(fh)
            return (d if isinstance(d, dict) else {}), "file"
        except (OSError, ValueError):
            return {}, "missing"
    if pages_url:
        try:
            d = _load_json_url(pages_url.rstrip("/") + "/data/v8/" + IDENTITY_FILE)
            return (d if isinstance(d, dict) else {}), "site"
        except Exception:  # noqa: BLE001 - the first scan with Phase 3 has none
            return {}, "unavailable"
    return {}, "none"


def identity_transitions(assets, prev, ts):
    """(new map, transitions): every asset's identity state now, carried 'since' when unchanged, and every state
    change against the previous scan. Each scan records what was known then; nothing earlier is rewritten."""
    now, moves = {}, []
    for t, a in sorted((assets or {}).items()):
        st = (a.get("identity") or {}).get("state")
        if not st:
            continue
        old = prev.get(t) if isinstance(prev.get(t), list) and len(prev.get(t)) == 2 else None
        if old and old[0] == st:
            now[t] = [st, old[1]]
        else:
            now[t] = [st, ts]
            if old:
                moves.append({"asset": t, "from": old[0], "to": st, "prev_since": old[1], "ts": ts})
    for t, v in prev.items():          # keep assets not seen this scan for a while (they may come back)
        if t not in now and isinstance(v, list) and len(v) == 2 and ts and ts - (v[1] or 0) <= FIRST_SEEN_KEEP_S:
            now[t] = v
    return now, moves


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


def load_previous_decision(pages_url=None, path=None):
    """The previous scan's Phase 11 decision document: an explicit file, else the published one, else none."""
    if path:
        try:
            with open(path) as fh:
                d = json.load(fh)
            return (d if isinstance(d, dict) else None), "file"
        except (OSError, ValueError):
            return None, "missing"
    if pages_url:
        try:
            d = _load_json_url(pages_url.rstrip("/") + "/" + DEC.FILE)
            return (d if isinstance(d, dict) else None), "site"
        except Exception:  # noqa: BLE001 - the first Phase 11 scan has none
            return None, "unavailable"
    return None, "none"


def decision_as_of(ts, discovery_generated_at, quant_as_of, portfolio_as_of, contracts):
    """The decision time: the latest knowledge time among this scan's inputs (the scanner's header time, discovery,
    the quant run, the portfolio, the latest contract receipt). Every input is then at or before it, so the engine's
    freshness and signal-age gates never see a future input, and nothing later than the scan is used."""
    times = [t for t in (ts, discovery_generated_at, quant_as_of, portfolio_as_of) if isinstance(t, int)
             and not isinstance(t, bool)]
    times += [c.get("rcv_ts") for c in contracts or [] if isinstance(c.get("rcv_ts"), int)
              and not isinstance(c.get("rcv_ts"), bool)]
    return max(times) if times else None


def _decision(P, reg, disc_bytes, hdr, ts, pages_url, decision_path):
    """(decision.json bytes or None, snapshot decision section). v8 Phase 11. Never raises: a failure is a named gap."""
    try:
        import quant as q
        from . import strategy_authority as SA
        from . import strategy_policy as SP
        qp = P.get("quant") or {}
        di = qp.get("decision_inputs") or {}
        if not qp.get("ok") or not di or di.get("error"):
            raise ValueError("quant decision inputs unavailable: " + str(di.get("error") or "quant part not ok"))
        if disc_bytes is None:
            raise ValueError("discovery unavailable")
        disc = json.loads(disc_bytes)
        policy = SP.load(q.STRATS)
        rows = {r["strategy_id"]: r for r in policy["strategies"]}
        strategies = {sid: dict((di.get("strategies") or {}).get(sid) or {}, deployment_state=r["deployment_state"],
                                research_state=r["research_state"]) for sid, r in rows.items()}
        for sid, r in rows.items():      # v9: the bound probation terms of an ACTIVE_PROBATION row (validated at load)
            terms = SP.probation_terms(r)
            if terms:
                strategies[sid]["probation"] = terms
        prev, prev_src = load_previous_decision(pages_url, decision_path)
        contracts = [{k: c.get(k) for k in ("id", "venue", "asset", "type", "active", "price", "npx", "vol", "fund8h",
                                            "fund_iv_h", "src_ts", "rcv_ts", "health", "admitted", "legacy")}
                     for c in (reg or {}).get("contracts") or []]
        auth = {"identity_version": (disc.get("provenance") or {}).get("identity_version"),
                "identity_config_hash": hdr.get("identity_config_hash"),
                "discovery_schema": disc.get("schema"), "discovery_document_hash": hashlib.sha256(disc_bytes).hexdigest(),
                "strategy_policy_schema": SP.VERSION, "strategy_policy_hash": SP.digest(policy),
                "strategy_runtime_implementation_hash": SP.runtime_implementation_hash(),
                "phase9_authority": {"version": SA.VERSION, "gate_hash": SP.digest(SA.GATE),
                                     "implementation_hash": provenance.file_sha(os.path.join(provenance.ROOT, "v8",
                                                                                             "strategy_authority.py"))}}
        inputs_as_of = {"discovery": (disc.get("provenance") or {}).get("generated_at"), "quant": di.get("as_of"),
                        "portfolio": (di.get("portfolio") or {}).get("as_of")}
        as_of = decision_as_of(ts, inputs_as_of["discovery"], inputs_as_of["quant"], inputs_as_of["portfolio"],
                               contracts)
        snapshot = {"as_of": as_of, "discovery": {"assets": disc.get("assets") or [],
                                                    "provenance": disc.get("provenance") or {},
                                                    "venues": disc.get("venues") or {}},
                    "contracts": contracts, "trade_dexes": di.get("trade_dexes") or [], "signals": di.get("signals") or {},
                    "strategies": strategies, "portfolio": di.get("portfolio"), "sizing": di.get("sizing"),
                    "forward_tests": di.get("forward_tests") or {},
                    "phase10_state": (qp.get("portfolio_risk") or {}).get("state"),
                    "inputs_as_of": inputs_as_of,
                    "authorities": auth, "previous": prev,
                    "input_provenance": {"discovery": DS.FILE, "registry_contracts": len(contracts),
                                         "quant_part": "data/v8/parts/quant.json decision_inputs",
                                         "signals_source": "quant.py strategy functions at the latest closed bar",
                                         "previous_decision": prev_src, "scan_id": hdr.get("scan_id"),
                                         "decision_as_of_rule": "latest knowledge time among this scan's inputs",
                                         "scan_header_ts": ts}}
        doc = DEC.build(snapshot)
        b = dumps(doc)
        s = DEC.summary(doc)
        s.update(file={"path": DEC.FILE, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)},
                 previous_decision_source=prev_src)
        return b, s
    except Exception as e:  # noqa: BLE001 - the decision engine must never stop the snapshot
        return None, {"schema": DEC.VERSION, "status": "FAILED", "error": f"{type(e).__name__}: {e}"[:500]}


def build(out_dir, pages_url=None, first_seen_path=None, identity_path=None, decision_path=None):
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
    prev_id, id_src = load_identity_state(pages_url, identity_path)
    id_map, id_moves = identity_transitions((reg or {}).get("assets"), prev_id, ts)
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
        if p.get("journal"):       # v8 Phase 3: the smart journal's evidence state (qualified vs legacy trades)
            coverage[e]["journal"] = p["journal"]
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
        "tradfi_exclusions": n_code("radar", "TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED"),
        "ambiguous_exclusions": n_code("radar", "AMBIGUOUS_EXPOSURE"),
        "tradfi_collisions": len(rc.get("tradfi_collisions") or []),
        "collisions": rc.get("tradfi_collisions") or [],
        "crypto_exposure_selected": rc.get("crypto_exposure_selected") or [],
        "assets_by_identity": rc.get("assets_by_identity"),
        "universe_exclusions": len(uni_final),
        "no_data_exclusions_radar": n_disp("radar", T.INSUFFICIENT_DATA),
        "scanner_stage1": rstages.get("stage1_charted"), "scanner_stage2": rstages.get("stage2_selected"),
        "scanner_extras": rstages.get("stage2_extras"), "scanner_deep_dives": rstages.get("deep_dives"),
        "quant_eligible": ((P.get("quant") or {}).get("stages") or {}).get("eligible_latest_day"),
        "swing_eligible": ((P.get("swing") or {}).get("stages") or {}).get("swing_checked"),
        "smart_represented": ((P.get("smart") or {}).get("stages") or {}).get("rows"),
        "dispositions": {e: (coverage.get(e) or {}).get("by_disposition") for e in ENGINES},
        "dispositions_total": {d: sum(((coverage.get(e) or {}).get("by_disposition") or {}).get(d, 0) for e in ENGINES)
                               for d in T.DISPOSITIONS},
        "unaccounted": {"registry_assets": len(universe_unaccounted),
                        **{e: (coverage.get(e) or {}).get("unaccounted") for e in ENGINES}},
        "unaccounted_registry_assets": universe_unaccounted[:50],
        # v8 Phase 3: identity states, discovery vs execution identity, transitions since the previous scan
        "identity": {"states": rc.get("identity_states"), "discovery_visible_assets": rc.get("discovery_visible_assets"),
                     "discovery_visible_contracts": rc.get("discovery_visible_contracts"),
                     "execution_identity_eligible": rc.get("execution_identity_eligible"),
                     "unverified_exclusions_radar": n_code("radar", "IDENTITY_UNVERIFIED"),
                     "unverified_exclusions": {e: n_code(e, "IDENTITY_UNVERIFIED") for e in ("radar", "quant", "swing", "day")},
                     "unverified_assets": rc.get("unverified_assets") or [],
                     "phase2_states": rc.get("phase2_states"), "changed_vs_phase2": rc.get("changed_vs_phase2") or [],
                     "phase2_default_crypto_only": len(rc.get("phase2_default_crypto_only") or []),
                     "phase2_default_crypto_any": len(rc.get("phase2_default_crypto_any") or []),
                     "phase2_default_crypto_now": {k: len(v) for k, v in (rc.get("phase2_default_crypto_now") or {}).items()},
                     "transitions": id_moves, "transitions_source": id_src,
                     # v8 Phase 5: wrapper vs economic exposure, and the before/after against the previous version
                     "exposure_safety": {k: (v if isinstance(v, (int, str)) else (len(v) if isinstance(v, list) else v))
                                         for k, v in (rc.get("exposure_safety") or {}).items()
                                         if k not in ("changed_vs_previous_detail",)},
                     # v8 Phase 6: the known-crypto list bound to at most one exposure per ticker (unaccounted 0)
                     "ticker_authority": {k: v for k, v in (rc.get("ticker_authority") or {}).items()
                                          if k not in ("multi_exposure",)}},
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
                   "exposure_metadata": (reg or {}).get("exposure_metadata"),
                   "audit_problems": problems}
    # legacy output references (hashes of the files the engines wrote; the audit never changes them)
    refs = []
    for name in LEGACY_FILES:
        p = os.path.join(data, name)
        if os.path.exists(p):
            refs.append(file_ref(p, f"data/{name}"))
    manifest = {
        "schema": SCHEMA, "audit_version": ENGINE_VERSION, "identity_version": rc.get("identity_version"),
        "identity_config_hash": hdr.get("identity_config_hash"),
        "liquidity_version": LIQUIDITY_VERSION, "scan_id": hdr.get("scan_id"), "ts": ts,
        "repo": hdr.get("repo"), "ref": hdr.get("git_ref"), "git_sha": hdr.get("git_sha"),
        "engine_versions": {e: ((P.get(e) or {}).get("header") or {}).get("engine_version") for e in ENGINES},
        "config_hashes": {e: ((P.get(e) or {}).get("header") or {}).get("config_hash") for e in ENGINES},
        "parts": {e: ("ok" if (P.get(e) or {}).get("ok") else "failed" if P.get(e) else "missing") for e in ENGINES},
        "scan_ids_consistent": len({((P.get(e) or {}).get("header") or {}).get("scan_id") for e in ENGINES
                                    if P.get(e)}) <= 1,
        "registry_contracts": rc.get("raw_contracts"),
        "dispositions": sum(len(v) for v in dispositions.values()),
        "data_sources": {"dex_market_lists": {k: (v or {}).get("ok") for k, v in ((reg or {}).get("venues") or {}).items()},
                         "exposure_metadata": {k: (v or {}).get("state")
                                               for k, v in ((reg or {}).get("exposure_metadata") or {}).items()},
                         "fallback_universe": bool(uni.get("fallback"))},
        "legacy_output_hashes": {r["path"]: r["sha256"] for r in refs},
        "strategy_authority": provenance.strategy_authority(),
    }
    data_health["strategy_authority"] = manifest["strategy_authority"]["health"]
    from . import shadow_ledger as SL
    manifest["strategy_authority"]["shadow_ledger"] = SL.summary(os.path.join(provenance.ROOT, SL.DIR))
    if "STRATEGY_POLICY_INVALID" in data_health["strategy_authority"]:
        problems["strategy_authority"] = [manifest["strategy_authority"].get("error")]
    # v8 Phase 10: the governed portfolio-risk authority (the full result and its trace are in the quant part)
    from . import portfolio_risk as PRISK
    manifest["portfolio_risk"] = dict(provenance.portfolio_risk_authority(),
                                      evaluation=PRISK.audit_summary((P.get("quant") or {}).get("portfolio_risk")))
    data_health["portfolio_risk"] = [manifest["portfolio_risk"]["evaluation"]["state"]]
    if manifest["portfolio_risk"].get("health") == "PORTFOLIO_RISK_POLICY_INVALID":
        problems["portfolio_risk"] = [manifest["portfolio_risk"].get("error")]
    # v8 Phase 7: full-universe discovery (observational; data/v8/discovery.json, summary in the snapshot)
    disc_bytes, disc_sum = _discovery(out_dir, reg, dispositions, hdr, fs, fs_src, ts)
    manifest["discovery_version"] = DS.VERSION
    manifest["discovery_file"] = ({"path": DS.FILE.replace(os.sep, "/"), "sha256": hashlib.sha256(disc_bytes).hexdigest(),
                                   "bytes": len(disc_bytes)} if disc_bytes is not None else None)
    manifest["parts"]["discovery"] = disc_sum.get("part")
    # v8 Phase 11: the unified decision engine (data/v8/decision.json; summary here)
    dec_bytes, manifest["decision"] = _decision(P, reg, disc_bytes, hdr, ts, pages_url, decision_path)
    data_health["decision"] = [manifest["decision"].get("status")]
    if manifest["decision"].get("status") != "OK":
        problems["decision"] = [manifest["decision"].get("error") or manifest["decision"].get("status")]
    if disc_sum.get("status") != "OK":
        problems["discovery"] = [disc_sum.get("error") or disc_sum.get("status")]
    elif disc_sum.get("problems"):
        problems["discovery"] = disc_sum["problems"]
    snap = {"schema": SCHEMA, "manifest": manifest, "coverage": {"summary": summary, "engines": coverage},
            "registry": {"counts": rc, "contracts": columns((reg or {}).get("contracts") or []),
                         "assets": (reg or {}).get("assets") or {}, "events": (reg or {}).get("events") or []},
            "data_health": data_health, "dispositions": dispositions,
            "reasons": {k: {"disposition": v[0], "text": v[1]} for k, v in T.REASONS.items()},
            "steps": T.STEPS, "legacy_output_refs": refs, "discovery": disc_sum,
            # v8 Phase 10: the full portfolio-risk result with its INPUT -> RULE -> RESULT -> EFFECT trace
            "portfolio_risk": (P.get("quant") or {}).get("portfolio_risk")}
    return snap, fs, id_map, disc_bytes, dec_bytes


def _discovery(out_dir, reg, dispositions, hdr, fs, fs_src, ts):
    """(discovery.json bytes or None, snapshot discovery section). Never raises: a failure is a named gap."""
    part = PT.read(out_dir, "discovery")
    pstate = "ok" if (part or {}).get("ok") else "failed" if part else "missing"
    if not reg:
        return None, {"schema": DS.VERSION, "status": "NO_REGISTRY", "part": pstate}
    try:
        since = min((v[0] for v in fs.values() if isinstance(v, list) and v and v[0] is not None), default=None)
        doc, s = DS.build(reg, part if pstate == "ok" else None, dispositions, hdr,
                          {"since": since, "source": fs_src}, ts)
        doc["provenance"]["scan_part"] = pstate
        s["part"] = pstate
        if pstate != "ok":
            s["problems"] = (s.get("problems") or []) + [f"discovery scan part {pstate}: light records without "
                                                          f"the coin records' liquidity and stage-1 metrics"]
        return dumps(doc), s
    except Exception as e:  # noqa: BLE001 - discovery must never stop the snapshot
        return None, {"schema": DS.VERSION, "status": "FAILED", "part": pstate,
                      "error": f"{type(e).__name__}: {e}"[:500]}


def columns(contracts):
    """Registry contracts as one field list and one row per contract (the field names are not repeated ten
    thousand times). contract_records() turns them back into dicts."""
    return {"fields": list(CONTRACT_FIELDS), "rows": [[c.get(f) for f in CONTRACT_FIELDS] for c in contracts]}


def contract_records(snap):
    """The registry contracts of a snapshot as dicts."""
    c = (snap.get("registry") or {}).get("contracts") or {}
    if isinstance(c, list):
        return c
    return [dict(zip(c.get("fields") or [], row)) for row in c.get("rows") or []]


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


def write(out_dir, pages_url=None, first_seen_path=None, archive_dir=None, keep_parts=False, identity_path=None,
          history_branch=None, history_backfill=False, history_repo=None, history_store=None, decision_path=None):
    built = build(out_dir, pages_url, first_seen_path, identity_path, decision_path)
    snap, fs, id_map, disc = built[:4]
    dec = built[4] if len(built) > 4 else None      # v8 Phase 11 decision bytes (an older 4-value build has none)
    # v8 Phase 8: append this scan's point-in-time observation to the history branch (only when the Scan workflow
    # asks for it). capture() never raises; a failure is HISTORY_CAPTURE_DEGRADED here and never stops the files below.
    if history_branch or history_store is not None:
        snap["history"] = HI.capture(snap, repo=os.getcwd(), branch=history_branch or HI.BRANCH,
                                     backfill=history_backfill, repo_slug=history_repo, store=history_store)
    else:
        snap["history"] = HI.status_template(snap, None)
    if snap["history"].get("persistence_state") == HI.DEGRADED:
        snap["data_health"].setdefault("audit_problems", {})["history"] = [snap["history"].get("reason")]
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
    with open(os.path.join(d, IDENTITY_FILE), "wb") as fh:
        fh.write(dumps(id_map))
    if disc is not None:      # v8 Phase 7: written whole or not at all
        tmp = os.path.join(out_dir, DS.FILE) + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(disc)
        os.replace(tmp, os.path.join(out_dir, DS.FILE))
    elif os.path.exists(os.path.join(out_dir, DS.FILE)):       # never leave another scan's discovery beside this one
        os.remove(os.path.join(out_dir, DS.FILE))
    if dec is not None:       # v8 Phase 11: written whole or not at all, never another scan's beside this one
        tmp = os.path.join(out_dir, DEC.FILE) + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(dec)
        os.replace(tmp, os.path.join(out_dir, DEC.FILE))
    elif os.path.exists(os.path.join(out_dir, DEC.FILE)):
        os.remove(os.path.join(out_dir, DEC.FILE))
    arch = ArchiveDir(archive_dir).append(snap["manifest"]["scan_id"] or "unknown", z) if archive_dir else None
    if not keep_parts:
        shutil.rmtree(os.path.join(out_dir, PT.PART_DIR), ignore_errors=True)
    return snap, len(raw), len(z), arch


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble the v8 audit snapshot from this scan's engine parts")
    ap.add_argument("--out", default="site")
    ap.add_argument("--pages-url", default=os.environ.get("PAGES_URL"))
    ap.add_argument("--first-seen", default=None, help="previous first_seen.json (default: read from the site)")
    ap.add_argument("--identity-state", default=None,
                    help="previous identity_state.json (default: read from the site)")
    ap.add_argument("--archive-dir", default=None, help="append the gzip snapshot to this bounded archive folder")
    ap.add_argument("--keep-parts", action="store_true")
    ap.add_argument("--decision-previous", default=None,
                    help="previous data/v8/decision.json (default: read from the site; v8 Phase 11)")
    ap.add_argument("--history-branch", default=None,
                    help="append this scan's point-in-time observation to this branch (v8 Phase 8; Scan workflow)")
    ap.add_argument("--history-backfill", action="store_true",
                    help="also append archived v8-audit-* scan artifacts not yet in the history (needs gh, GH_TOKEN)")
    ap.add_argument("--history-repo", default=os.environ.get("GITHUB_REPOSITORY"),
                    help="owner/name of the repository whose artifacts are backfilled")
    a = ap.parse_args(argv)
    snap, n, z, arch = write(a.out, a.pages_url, a.first_seen, a.archive_dir, a.keep_parts, a.identity_state,
                             a.history_branch, a.history_backfill, a.history_repo, decision_path=a.decision_previous)
    s = snap["coverage"]["summary"]
    print(f"[v8] audit snapshot {snap['manifest']['scan_id']}: {s['raw_contracts']} contracts, "
          f"{s['canonical_assets']} assets, {snap['manifest']['dispositions']} dispositions, unaccounted "
          f"{s['unaccounted']}, {n} bytes ({z} gzip)" + (f", archived {os.path.basename(arch)}" if arch else ""),
          flush=True)
    d = snap.get("discovery") or {}
    cov = d.get("coverage") or {}
    print(f"[v8] discovery {d.get('status')}: {cov.get('discovery_assets')} assets "
          f"({cov.get('active_perps_in_denominator')} active perps on {cov.get('venues_ok')} healthy venues, "
          f"{cov.get('venues_failed')} unavailable), stages {d.get('stages')}, unaccounted {d.get('unaccounted')}",
          flush=True)
    h = snap.get("history") or {}
    print(f"[v8] history {h.get('persistence_state')}: branch {h.get('branch')}, commit {h.get('history_branch_commit')}, "
          f"integrity {h.get('append_integrity')}, observation {(h.get('observation') or {}).get('seq')}, "
          f"storage {h.get('storage_size')}, backfill {h.get('backfill')}" + (f", reason {h.get('reason')}"
                                                                              if h.get('reason') else ""), flush=True)
    if h.get("persistence_state") == HI.DEGRADED:       # visible in the Actions run summary; the scan carries on
        print(f"::warning title=v8 history::{HI.DEGRADED}: {h.get('reason')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
