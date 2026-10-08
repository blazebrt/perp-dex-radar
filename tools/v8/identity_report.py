"""Universe identity report from an audit snapshot (v8 Phase 2; Phase 3: identity coverage).

    python tools/v8/identity_report.py out_new/data/v8/audit_latest.json [--json research_identity.json]
        [--base-out out_base]

Phase 2 part: for every ticker whose own markets disagree (a collision), every market: venue, raw symbol, price per 1
coin, 24h volume, its own classification and reason, its exposure and the exposure's class, and whether it reached
the crypto universe; then the ticker's decision before (Phase 1 ticker-level OR) and now. Also the headline counts
and every coin excluded for a missing 24h volume.

Phase 3 part:
* the four identity states, discovery vs execution identity, and every state change against the Phase 2 identity
  on the same market lists;
* the default-crypto inventory: every asset Phase 2 admitted (partly or only) because no evidence said otherwise,
  and what it is now;
* every UNVERIFIED asset: venues, raw symbols, prices, volumes, evidence, why it is unresolved, parsed-symbol links,
  the raw venue identity fields, and whether the $1M liquidity gate would pass for it;
* the venue field census: every identity-relevant raw field each venue sent, with its values counted per identity
  state of the contract's own exposure, so a later phase can decide - from data - whether a field is reliable evidence;
* smart money under the identity gate: rows by identity state, crowds blocked only by identity, actionable signals;
* with --base-out (the phase base's engines run on the same live data minutes apart): every production output
  (radar pick or watch, quant signal or position, swing or day listing) the base published that this run did not,
  and the other way round, each with the asset's identity state now - the identity gate's effect on production.

Reads files only; changes nothing."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from v8 import snapshot as SN  # noqa: E402

MIN_DEX_VOL = 1_000_000


def load(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def _contract_view(c):
    return {"contract": c.get("id"), "venue": c.get("venue"), "raw": c.get("raw"), "active": c.get("active"),
            "price": c.get("price"), "npx": c.get("npx"), "vol": c.get("vol"), "class": c.get("cls"),
            "reason": c.get("cls_reason"), "exposure": c.get("exposure"), "exposure_state": c.get("exp_state"),
            "exposure_reason": c.get("exp_reason"), "state": c.get("legacy"), "evidence": c.get("evidence"),
            "parsed": c.get("parsed"), "link": c.get("link"), "venue_fields": c.get("vmeta"), "meta": c.get("meta")}


def report(snap, base_out=None, head_out=None):
    reg = snap.get("registry") or {}
    counts = reg.get("counts") or {}
    assets = reg.get("assets") or {}
    by_id = {c["id"]: c for c in SN.contract_records(snap)}
    recs = {e: {r["a"]: r for r in (snap.get("dispositions") or {}).get(e, [])} for e in ("radar", "quant", "swing")}
    out = {"scan_id": (snap.get("manifest") or {}).get("scan_id"),
           "git_sha": (snap.get("manifest") or {}).get("git_sha"),
           "identity_version": (snap.get("manifest") or {}).get("identity_version"),
           "identity_config_hash": (snap.get("manifest") or {}).get("identity_config_hash"),
           "counts": {k: counts.get(k) for k in (
               "raw_contracts", "active_perps", "canonical_assets", "assets_by_legacy", "assets_by_identity",
               "phase1_crypto", "phase1_excluded", "now_crypto", "now_excluded", "now_unverified", "changed_vs_phase1",
               "tradfi_collisions", "crypto_exposure_selected", "ambiguous", "by_contract_class", "by_exposure_class",
               "adapter_mismatches", "identity_states", "discovery_visible_assets", "discovery_visible_contracts",
               "execution_identity_eligible", "phase2_states", "changed_vs_phase2_detail", "parsed_symbol_links")},
           "unaccounted": ((snap.get("coverage") or {}).get("summary") or {}).get("unaccounted"),
           "identity_summary": ((snap.get("coverage") or {}).get("summary") or {}).get("identity"),
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
            "ticker": t, "phase1": ident.get("phase1"), "phase2": ident.get("phase2"), "now": a.get("legacy"),
            "identity_state": ident.get("state"), "decision": ident.get("decision"),
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
    out.update(phase3(snap, assets, by_id, counts))
    out["smart"] = smart_identity(snap, head_out)
    if base_out and head_out:
        out["production"] = production_diff(base_out, head_out, assets)
    return out


# --------------------------------------------------------------------------- Phase 3
def _asset_row(t, a, by_id):
    ident = a.get("identity") or {}
    cs = [by_id.get(cid) or {} for cid in a.get("contracts") or []]
    live = [c for c in cs if c.get("legacy") in ("SELECTED", "DUPLICATE_NOT_SELECTED", "PRICE_CONFLICT_DROPPED",
                                                  "EXPOSURE_NOT_ADMITTED", "UNVERIFIED_EXPOSURE_NOT_ADMITTED")]
    in_record = [c for c in live if c.get("in_record")]
    best = max([c.get("vol") or 0 for c in in_record] or [0])
    return {"ticker": t, "state": ident.get("state"), "phase2": ident.get("phase2"),
            "phase2_reasons": ident.get("phase2_reasons"), "decision": ident.get("decision"),
            "reason": ident.get("reason"), "authority": ident.get("authority"), "venues": a.get("venues"),
            "raw_symbols": [c.get("id") for c in live], "best_vol": best,
            "liquidity_gate_would_pass": best >= MIN_DEX_VOL,
            "evidence": ident.get("evidence"), "links": ident.get("links"),
            "why_unresolved": ("no venue asset-class label, no known-crypto or tradfi list entry, no tradfi name, no "
                               "verified exposure linked by price or symbol") if ident.get("state") == "UNVERIFIED"
            else None,
            "promotion": ident.get("promotion"),
            "contracts": [_contract_view(c) for c in live]}


def phase3(snap, assets, by_id, counts):
    inv = {}
    for t in counts.get("phase2_default_crypto_any") or []:
        a = assets.get(t) or {}
        inv[t] = _asset_row(t, a, by_id)
    unver = {t: _asset_row(t, a, by_id) for t, a in sorted(assets.items())
             if (a.get("identity") or {}).get("state") == "UNVERIFIED"}
    census = {}
    for c in SN.contract_records(snap):
        if c.get("legacy") not in ("SELECTED", "DUPLICATE_NOT_SELECTED", "PRICE_CONFLICT_DROPPED",
                                   "EXPOSURE_NOT_ADMITTED", "UNVERIFIED_EXPOSURE_NOT_ADMITTED"):
            continue
        # the contract's own exposure state (an RWA market under a crypto ticker counts as tradfi, not crypto)
        st = c.get("exp_state") or ((assets.get(c.get("asset")) or {}).get("identity") or {}).get("state") or "NONE"
        for k, v in (c.get("vmeta") or {}).items():
            if k in ("description", "name", "baseAsset", "assetName"):      # free text: count presence only
                v = "<text>"
            key = json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else str(v)
            cell = census.setdefault(c["venue"], {}).setdefault(k, {}).setdefault(key, {})
            cell[st] = cell.get(st, 0) + 1
    by_bucket = {}
    for t, r in inv.items():
        by_bucket.setdefault(r["state"], []).append(t)
    only = set(counts.get("phase2_default_crypto_only") or [])
    return {"default_crypto_inventory": {
                "base_count_any": len(inv), "base_count_only": len(only),
                "now": {k: len(v) for k, v in sorted(by_bucket.items())},
                "now_tickers": {k: sorted(v) for k, v in sorted(by_bucket.items())},
                "partly_default": sorted(set(inv) - only),
                "assets": [inv[t] for t in sorted(inv, key=lambda x: -(inv[x]["best_vol"] or 0))]},
            "unverified": [unver[t] for t in sorted(unver, key=lambda x: -(unver[x]["best_vol"] or 0))],
            "unverified_liquid": sorted(t for t, r in unver.items() if r["liquidity_gate_would_pass"]),
            "venue_field_census": census}


def smart_identity(snap, head_out):
    """Smart money under the identity gate (v8 Phase 3 closure): every row's identity state (all rows, from the smart
    part's stages), the crowds blocked only by identity (each blocked row keeps the crowd it would have been), the
    actionable signals left, and the authority the engine used. Verified-crypto rows are unchanged by construction
    (proven by the differential parity), so the blocked crowds are the whole difference."""
    st = (((snap.get("coverage") or {}).get("engines") or {}).get("smart") or {}).get("stages") or {}
    sm = {}
    if head_out:
        try:
            with open(os.path.join(head_out, "data", "smart.json")) as fh:
                sm = json.load(fh)
        except (OSError, ValueError):
            sm = {}
    rows = sm.get("coins") or []
    blocked = [{"coin": r["coin"], "identity": r.get("identity"), "reason": (r.get("identity_block") or {}).get("reason"),
                "would_have_been": "signal" if (r.get("identity_block") or {}).get("crowd_signal") else "info",
                "side": (r.get("identity_block") or {}).get("crowd_side"), "traders": r.get("traders"),
                "new_long": r.get("new_long"), "new_short": r.get("new_short")}
               for r in rows if r.get("identity_block")]
    return {"authority": sm.get("identity_authority"), "rows_by_identity": st.get("identity"),
            "rows": st.get("rows"), "identity_blocked_all": st.get("identity_blocked"),
            "blocked_crowds_published": blocked,
            "blocked_signals": sum(1 for b in blocked if b["would_have_been"] == "signal"),
            "blocked_info": sum(1 for b in blocked if b["would_have_been"] == "info"),
            "actionable_signals": [[r["coin"], r.get("side"), r.get("identity")] for r in rows if r.get("signal")],
            "info_crowds": [[r["coin"], r.get("side"), r.get("identity")] for r in rows if r.get("info")],
            "published_rows": len(rows),
            # the smart journal's evidence boundary (final closure): only qualified trades are in the live record
            "journal_evidence": (sm.get("accuracy") or {}).get("evidence"),
            "live": (sm.get("accuracy") or {}).get("live"), "live_info": (sm.get("accuracy") or {}).get("live_info"),
            "legacy_unqualified": (sm.get("accuracy") or {}).get("legacy_unqualified"),
            "verdict": (sm.get("accuracy") or {}).get("verdict"),
            "unqualified_trades": ((((snap.get("coverage") or {}).get("engines") or {}).get("smart") or {})
                                   .get("journal") or {}).get("unqualified_trades"),
            "published_by_identity": {k: sum(1 for r in rows if (r.get("identity") or "NONE") == k)
                                      for k in sorted({r.get("identity") or "NONE" for r in rows})}}


def _published(out_dir):
    """Every production output of one run: (engine, ticker, detail)."""
    def ld(n):
        try:
            with open(os.path.join(out_dir, "data", n)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    L, Q, P = ld("latest.json"), ld("quant.json"), ld("picks.json")
    got = set()
    for p in L.get("picks") or []:
        got.add(("radar_pick", p.get("coin"), p.get("sid")))
    for p in L.get("watch") or []:
        got.add(("radar_watch", p.get("coin"), p.get("sid")))
    for t in Q.get("signals") or []:
        got.add(("quant_signal", t.get("c"), t.get("s")))
    for t in Q.get("open") or []:
        got.add(("quant_open", t.get("c"), t.get("s")))
    for k, name in (("swing", "swing"), ("daytrade", "day")):
        for r in (P.get(k) or {}).get("all") or []:
            if isinstance(r, dict):
                got.add((name, r.get("coin"), r.get("side")))
    return got, {"radar_ok": bool(L), "quant_ok": bool(Q), "picks_ok": bool(P)}


def production_diff(base_out, head_out, assets):
    b, bok = _published(base_out)
    h, hok = _published(head_out)
    st = lambda t: ((assets.get(t) or {}).get("identity") or {}).get("state")  # noqa: E731
    removed = [{"engine": e, "ticker": t, "detail": d, "identity_state": st(t),
                "blocked_by_identity": st(t) != "VERIFIED_CRYPTO"} for e, t, d in sorted(b - h, key=str)]
    added = [{"engine": e, "ticker": t, "detail": d, "identity_state": st(t)} for e, t, d in sorted(h - b, key=str)]
    return {"base_runs": bok, "head_runs": hok, "base_outputs": len(b), "head_outputs": len(h),
            "removed": removed, "added": added,
            "removed_by_identity": [r for r in removed if r["blocked_by_identity"]],
            "note": "The base engines ran on the same live data a few minutes apart: differences not explained by "
                    "identity (blocked_by_identity false) can come from market moves between the two runs or from "
                    "the cross-sectional ranks changing once unverified coins left the universe."}


def text(rep):
    L = [f"scan {rep['scan_id']}  commit {str(rep['git_sha'])[:12]}  {rep['identity_version']}  "
         f"config {str(rep.get('identity_config_hash'))[:12]}", ""]
    for k, v in rep["counts"].items():
        if k not in ("changed_vs_phase2_detail",):
            L.append(f"{k}: {v}")
    L.append(f"unaccounted: {rep['unaccounted']}")
    L.append("")
    inv = rep.get("default_crypto_inventory") or {}
    L.append(f"== default-crypto inventory (Phase 2 admitted with DEFAULT_CRYPTO): {inv.get('base_count_any')} assets "
             f"({inv.get('base_count_only')} only by default); now {inv.get('now')}")
    for k, v in (inv.get("now_tickers") or {}).items():
        L.append(f"   {k}: {', '.join(v)}")
    L.append("")
    L.append(f"== UNVERIFIED assets ({len(rep.get('unverified') or [])}); liquid enough for the $1M gate: "
             f"{rep.get('unverified_liquid')}")
    for r in rep.get("unverified") or []:
        L.append(f"   {r['ticker']:<14} vol {r['best_vol']:>14,.0f}  {', '.join(r['raw_symbols'])}")
        for c in r["contracts"]:
            L.append(f"      {c['contract']:<30} px {c['price']!s:<14} vol {c['vol']!s:<14} {c['exposure_state']!s:<16} "
                     f"fields {c['venue_fields']} parsed {c['parsed']} link {(c['link'] or {}).get('coherent_exposure')}")
    L.append("")
    L.append("== venue field census (raw identity fields x identity state)")
    for v, fields in sorted((rep.get("venue_field_census") or {}).items()):
        for k, vals in sorted(fields.items()):
            L.append(f"   {v}.{k}: " + "; ".join(f"{val} {cnt}" for val, cnt in sorted(vals.items())[:40]))
    smr = rep.get("smart") or {}
    L.append("")
    L.append(f"== smart money identity: authority {(smr.get('authority') or {}).get('why')} "
             f"({(smr.get('authority') or {}).get('coins')} coins); rows by identity {smr.get('rows_by_identity')} "
             f"of {smr.get('rows')}; published {smr.get('published_by_identity')}")
    L.append(f"   crowds blocked by identity: {smr.get('identity_blocked_all')} (would-be signals "
             f"{smr.get('blocked_signals')}, information crowds {smr.get('blocked_info')})")
    L.append(f"   actionable smart signals: {smr.get('actionable_signals')}; information crowds: {smr.get('info_crowds')}")
    L.append(f"   journal evidence: {smr.get('journal_evidence')}")
    L.append(f"   live record (qualified only): {smr.get('live')}; info {smr.get('live_info')}; verdict {smr.get('verdict')}")
    L.append(f"   legacy without entry-time identity proof (kept, never counted): {smr.get('legacy_unqualified')}")
    if rep.get("production"):
        p = rep["production"]
        L.append("")
        L.append(f"== production outputs: base {p['base_outputs']} ({p['base_runs']}), this run {p['head_outputs']} "
                 f"({p['head_runs']})")
        for r in p["removed"]:
            L.append(f"   REMOVED {r['engine']:<13} {r['ticker']:<12} {r['detail']!s:<10} identity {r['identity_state']}"
                     + ("  <- identity gate" if r["blocked_by_identity"] else ""))
        for r in p["added"]:
            L.append(f"   ADDED   {r['engine']:<13} {r['ticker']:<12} {r['detail']!s:<10} identity {r['identity_state']}")
    L.append("")
    for c in rep["collisions"]:
        L.append(f"== {c['ticker']}: Phase 1 {c['phase1']} -> Phase 2 {c['phase2']} -> now {c['identity_state']} "
                 f"({c['decision']}); ticker list {c['ticker_list']}; engines {c['engines']}")
        for r in c["contracts"]:
            L.append(f"   {r['contract']:<28} px {r['price']!s:<14} per coin {r['npx']!s:<14} vol {r['vol']!s:<12} "
                     f"{r['class']!s:<9} {r['reason']!s:<28} {r['exposure']!s:<11} {r['exposure_class']!s:<10} "
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
    ap.add_argument("--base-out", default=None, help="the phase base's run on the same live data (comparison)")
    ap.add_argument("--head-out", default=None, help="this run's output folder (default: next to the snapshot)")
    a = ap.parse_args(argv)
    head_out = a.head_out or os.path.abspath(os.path.join(os.path.dirname(a.snapshot), "..", ".."))
    rep = report(load(a.snapshot), base_out=a.base_out, head_out=head_out)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True)
    print(text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
