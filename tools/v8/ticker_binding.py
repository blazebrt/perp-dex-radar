"""Known-crypto ticker authority vs exposure binding (v8 Phase 6, Stage A and its proof). Read-only.

    python tools/v8/ticker_binding.py SNAPSHOT [SNAPSHOT ...] [--outputs DIR] [--json out.json]

SNAPSHOT is a v8 audit snapshot (data/v8/audit_latest.json, or a Research run's .json.gz). --outputs is a folder with
the production files of a scan (the journal-data branch: latest.json, quant.json, quant_journal.json, picks.json,
picks_journal.json, smart.json, smart_journal.json, journal.csv), used to list the open positions and published
outputs an identity change would touch.

The repository's known-crypto list (scanner.KNOWN_CRYPTO) is ticker-level knowledge: one crypto asset exists under
the ticker. The universe is exposure-level: one ticker can carry several price-coherent exposures (v8.identity rule
2). Under v8.identity/3 the list verifies EVERY otherwise-unlabeled priced exposure of a listed ticker. This tool:

1. Census. Every known-crypto ticker of the snapshot, resolved under v8.identity/3 (rules=3, the Phase 5 production
   rules, exactly reproduced first): its state, every priced and unpriced exposure with its contracts, venues, price
   per coin, direct economic evidence, wrapper evidence, exposure-check states, class, reason and authority, and
   whether the ticker list is what verifies it. Each ticker gets one category (CATEGORIES, first match wins) and the
   flags of all that apply.
2. Binding candidates. A priced exposure of a known-crypto ticker that the ticker list alone decides: no contract
   evidence (not TRADFI, not AMBIGUOUS, not direct CRYPTO), not blocked by a failed exposure check (Phase 5:
   EXPOSURE_CHECK_UNAVAILABLE), not an unpriced contract. Under v8.identity/3 these are exactly the exposures with
   reason TICKER_KNOWN_CRYPTO.
3. Models, on the same contracts:
     model 1  v8.identity/3: the list verifies every candidate (Phase 5 production)
     model 2  exposure-local single-candidate binding (v8.identity/4): exactly one candidate -> CRYPTO
              (TICKER_KNOWN_CRYPTO_BOUND); more than one -> every candidate UNVERIFIED (TICKER_CRYPTO_EXPOSURE_UNBOUND);
              a direct-crypto exposure present -> candidates UNVERIFIED (the ticker's crypto asset is the directly
              evidenced one); none -> nothing to bind. Computed here independently of v8.identity (from the model 1
              exposure classes), and - when this checkout has rules=4 - compared with v8.identity's own resolution.
     model 3  heuristic winner (evaluated, never implemented): of several candidates, pick one by volume, venue count,
              open interest or presence on Hyperliquid. Shown to disagree with itself and, on the tickers whose
              non-crypto exposure is known from negative evidence, to be able to pick that exposure when the negative
              evidence is withheld - liquidity and popularity are not identity.
4. Impact. State counts under each model and every asset that changes state, with its exposures, prices, contracts,
   venues, the reason the list verified it, why model 2 cannot bind it, liquidity, open positions and outputs.
5. Known-crypto list audit (observability only; the list is not changed): entries, entries with a live market, with
   one / several priced exposures, entries whose live exposures are all tradfi, entries with no live market.

Nothing is written except --json; no network."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import candidate_census as CC  # noqa: E402
import exposure_safety as ES  # noqa: E402
import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402

SCHEMA = "v8.ticker-binding/1"
TICKER_REASON = "TICKER_KNOWN_CRYPTO"                    # v8.identity/3: the list verifies the exposure
BOUND_REASON = "TICKER_KNOWN_CRYPTO_BOUND"              # v8.identity/4: the list was bound to this one exposure
UNBOUND_REASON = "TICKER_CRYPTO_EXPOSURE_UNBOUND"       # v8.identity/4: the list could not be bound to it
UNPRICED_REASON = "UNPRICED_NO_CONTRACT_EVIDENCE"
BOUND, UNBOUND_MULTI, UNBOUND_DIRECT, NO_CANDIDATE = ("BOUND", "UNBOUND_MULTIPLE_CANDIDATES",
                                                      "UNBOUND_DIRECT_CRYPTO_EVIDENCE", "NO_BINDABLE_EXPOSURE")
CATEGORIES = ("unpriced_only", "direct_positive_crypto_evidence", "multiple_unlabeled_exposures",
              "crypto_plus_explicit_tradfi_collision", "crypto_plus_unavailable_check_collision",
              "multiple_priced_exposures", "single_priced_exposure", "other")
HEURISTICS = ("highest_volume", "most_venues", "highest_open_interest", "on_hyperliquid")


def lists():
    return ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME)


def resolve(rows, rules):
    """The resolution of the given rules version on these contracts (v8.identity/3 = rules 3)."""
    return ID._resolve(ES.with_checks(rows), sc.DEXES, lists(), sc.in_my_dexes, None, rules=rules,
                       before_after=False)


def has_rules4():
    return getattr(ID, "RULES", 3) >= 4


# --------------------------------------------------------------------------- 1. census
def exposure_details(res, rows):
    """{ticker: {exposure id: {"contracts": [...], "vol", "oi", "venues"}}} from the per-contract identity rows."""
    out = collections.defaultdict(dict)
    for dex, lst in rows.items():
        for i, r in enumerate(lst or []):
            info = res.rows.get((dex, i))
            if info is None:
                continue
            x = out[r["t"]].setdefault(info["exp"], {"contracts": [], "vol": 0.0, "oi": 0.0, "venues": set()})
            x["contracts"].append({
                "contract": f"{dex}:{r.get('sym')}", "venue": dex, "price_per_coin": ID._r(info["npx"]),
                "vol": r.get("vol"), "oi": r.get("oi"), "contract_class": info["cls"], "evidence": info["evidence"],
                "wrapper": info["wrapper"], "exposure_check": info["xcheck"], "legacy": info["state"]})
            x["vol"] += r.get("vol") or 0.0
            x["oi"] += r.get("oi") or 0.0       # as each venue reports it: the units are not uniform across venues
            x["venues"].add(dex)
    return out


def candidates_of(a):
    """The ticker-list binding candidates of an asset resolved under v8.identity/3 (see the module docstring)."""
    return [g["id"] for g in a["exposures"] if g["priced"] and g["reason"] == TICKER_REASON]


def census_ticker(t, a, det):
    exps = a["exposures"]
    priced = [g for g in exps if g["priced"]]
    unpriced = [g for g in exps if not g["priced"]]
    cands = candidates_of(a)
    direct = [g["id"] for g in priced if g["class"] == ID.CRYPTO and g["reason"] != TICKER_REASON]
    tradfi = [g["id"] for g in priced if g["class"] == ID.TRADFI]
    ambiguous = [g["id"] for g in priced if g["class"] == ID.AMBIGUOUS]
    blocked = [g["id"] for g in priced if g["reason"] == ID.R_CHECK_UNAVAILABLE]
    other_unver = [g["id"] for g in priced if g["class"] == ID.UNVERIFIED and g["reason"] != ID.R_CHECK_UNAVAILABLE]
    flags = {"multiple_priced_exposures": len(priced) > 1, "explicit_tradfi_collision": bool(tradfi),
             "ambiguous_exposure": bool(ambiguous), "unavailable_check_collision": bool(blocked),
             "multiple_unlabeled_exposures": len(cands) > 1, "direct_positive_crypto_evidence": bool(direct),
             "unpriced_contracts": bool(unpriced)}
    if not priced:
        cat = "unpriced_only"
    elif direct:
        cat = "direct_positive_crypto_evidence"
    elif len(cands) > 1:
        cat = "multiple_unlabeled_exposures"
    elif len(priced) > 1 and tradfi:
        cat = "crypto_plus_explicit_tradfi_collision"
    elif len(priced) > 1 and blocked:
        cat = "crypto_plus_unavailable_check_collision"
    elif len(priced) > 1:
        cat = "multiple_priced_exposures"
    elif len(priced) == 1:
        cat = "single_priced_exposure"
    else:
        cat = "other"
    admitted = [g for g in exps if g["admitted"]]
    needs_list = a["state"] == ID.VERIFIED_CRYPTO and all(g["authority"] == ID.TICKER_LIST for g in admitted)
    xs = []
    for g in exps:
        d = det.get(g["id"]) or {}
        xs.append({"id": g["id"], "priced": g["priced"], "class": g["class"], "reason": g["reason"],
                   "authority": g["authority"], "anchor_price": g["anchor_price"], "price_range": g["price_range"],
                   "admitted": g["admitted"], "wrapper": g.get("wrapper"),
                   "venues": sorted(d.get("venues") or ()), "vol": round(d.get("vol") or 0.0, 2),
                   "oi_reported": round(d.get("oi") or 0.0, 2), "contracts": d.get("contracts") or [],
                   "binding_candidate": g["id"] in cands})
    return {"ticker": t, "state": a["state"], "decision": a["decision"], "reason": a.get("reason"),
            "authority": a.get("authority"), "category": cat, "flags": flags,
            "priced_exposures": len(priced), "unpriced_exposures": len(unpriced),
            "binding_candidates": cands, "direct_crypto_exposures": direct, "tradfi_exposures": tradfi,
            "ambiguous_exposures": ambiguous, "check_blocked_exposures": blocked,
            "other_unverified_exposures": other_unver,
            "known_crypto_needed": needs_list, "exposures": xs}


# --------------------------------------------------------------------------- 2/3. models
def model2(c):
    """(result, selected exposure, {exposure id: (class, reason)} changes) of single-candidate binding for one
    census row; computed from the v8.identity/3 exposure classes only."""
    cands = c["binding_candidates"]
    # an unpriced exposure the list verified under /3 (a ticker without any priced contract) cannot be bound
    unpriced = {x["id"]: (ID.UNVERIFIED, UNPRICED_REASON) for x in c["exposures"]
                if not x["priced"] and x["reason"] == TICKER_REASON}
    if c["direct_crypto_exposures"] and cands:
        return UNBOUND_DIRECT, None, unpriced | {x: (ID.UNVERIFIED, UNBOUND_REASON) for x in cands}
    if len(cands) == 1:
        return BOUND, cands[0], unpriced | {cands[0]: (ID.CRYPTO, BOUND_REASON)}
    if len(cands) > 1:
        return UNBOUND_MULTI, None, unpriced | {x: (ID.UNVERIFIED, UNBOUND_REASON) for x in cands}
    return NO_CANDIDATE, None, unpriced


def projected_state(a, changes):
    """The asset state of rule 5 after the exposure classes in `changes` are applied."""
    lead = [(g["id"], changes.get(g["id"], (g["class"], g["reason"]))[0]) for g in a["exposures"]
            if "#u" not in g["id"]]          # unpriced single contracts never decide the state
    classes = [c for _, c in lead]
    if ID.CRYPTO in classes:
        return ID.VERIFIED_CRYPTO
    if ID.UNVERIFIED in classes:
        return ID.UNVERIFIED
    if ID.AMBIGUOUS in classes:
        return ID.AMBIGUOUS
    return ID.VERIFIED_TRADFI if classes else a["state"]


def model3(c):
    """What each heuristic would pick among the binding candidates (and, for an explicit tradfi collision, among the
    candidates plus the tradfi exposures as if their negative evidence were withheld). Never used as a rule."""
    by_id = {x["id"]: x for x in c["exposures"]}

    def pick(ids, h):
        xs = [by_id[i] for i in ids]
        if not xs:
            return None
        if h == "highest_volume":
            return max(xs, key=lambda x: x["vol"])["id"]
        if h == "most_venues":
            return max(xs, key=lambda x: len(x["venues"]))["id"]
        if h == "highest_open_interest":
            return max(xs, key=lambda x: x["oi_reported"])["id"]
        on = [x for x in xs if "hyperliquid" in x["venues"]]
        return on[0]["id"] if len(on) == 1 else None
    out = {"candidates": {h: pick(c["binding_candidates"], h) for h in HEURISTICS}}
    if c["tradfi_exposures"] and len(c["binding_candidates"]) == 1:
        pool = c["binding_candidates"] + c["tradfi_exposures"]
        picks = {h: pick(pool, h) for h in HEURISTICS}
        out["negative_evidence_withheld"] = picks
        out["would_pick_tradfi"] = sorted(h for h, p in picks.items() if p in c["tradfi_exposures"])
        out["negative_evidence_withheld_disagree"] = len({p for p in picks.values() if p}) > 1
    vals = {p for p in out["candidates"].values() if p}
    out["heuristics_disagree"] = len(vals) > 1
    return out


# --------------------------------------------------------------------------- 4. impact
def impact(census, base, out_idx):
    moves = []
    states = collections.Counter(a["state"] for a in base.assets.values())
    proj = collections.Counter()
    for t, a in base.assets.items():
        c = census.get(t)
        st = a["state"]
        if c is not None:
            _, _, ch = model2(c)
            st = projected_state(a, ch)
        proj[st] += 1
        if c is not None and st != a["state"]:
            coin = base.coins.get(t) or {}
            moves.append({"asset": t, "from": a["state"], "to": st, "result": model2(c)[0],
                          "exposures": [{k: x[k] for k in ("id", "class", "reason", "anchor_price", "venues", "vol")}
                                        | {"contracts": [y["contract"] for y in x["contracts"]],
                                           "prices": [y["price_per_coin"] for y in x["contracts"]]}
                                        for x in c["exposures"]],
                          "v3_reason": a.get("reason"), "v3_authority": a.get("authority"),
                          "why_unbound": why_unbound(c),
                          "best_vol": coin.get("best_vol"), "trade_vol": coin.get("trade_vol"),
                          "liquid_1m": (coin.get("trade_vol") or 0) >= 1_000_000,
                          "open_positions": sorted(o for o in out_idx.get(t, ()) if o.endswith("_open")),
                          "outputs": sorted(out_idx.get(t, ()))})
    kinds = collections.Counter(f"{m['from']}->{m['to']}" for m in moves)
    return {"current": dict(sorted(states.items())), "projected": dict(sorted(proj.items())),
            "transitions": dict(sorted(kinds.items())), "moves": moves}


def why_unbound(c):
    r = model2(c)[0]
    if r == UNBOUND_MULTI:
        return (f"{len(c['binding_candidates'])} price-separated exposures ({', '.join(c['binding_candidates'])}) carry "
                "no economic evidence; the ticker list names one crypto asset and cannot tell which exposure it is")
    if r == UNBOUND_DIRECT:
        return "the ticker's crypto asset is the directly evidenced exposure; the list cannot verify a second one"
    return None


# --------------------------------------------------------------------------- 5. list audit
def list_audit(census, base):
    present = sorted(t for t in sc.KNOWN_CRYPTO if t in base.assets)
    absent = sorted(t for t in sc.KNOWN_CRYPTO if t not in base.assets)
    one = sorted(t for t in present if census[t]["priced_exposures"] == 1)
    many = sorted(t for t in present if census[t]["priced_exposures"] > 1)
    all_tradfi = sorted(t for t in present if census[t]["exposures"] and
                        all(x["class"] == ID.TRADFI for x in census[t]["exposures"]))
    return {"entries": len(sc.KNOWN_CRYPTO), "in_live_universe": len(present), "one_priced_exposure": len(one),
            "multiple_priced_exposures": len(many), "multiple_priced_exposure_entries": many,
            "unpriced_only": sorted(t for t in present if census[t]["priced_exposures"] == 0),
            "all_live_exposures_tradfi": all_tradfi, "no_live_market": len(absent), "no_live_market_entries": absent,
            "also_on_tradfi_list": sorted(set(sc.KNOWN_CRYPTO) & set(sc.TRADFI))}


# --------------------------------------------------------------------------- the v4 cross-check
def v4_check(census, base, rows):
    """When this checkout resolves rules=4: v8.identity/4 must give exactly the model 2 projection."""
    if not has_rules4():
        return None
    v4 = resolve(rows, 4)
    diffs = []
    for t, a in v4.assets.items():
        b = base.assets[t]
        c = census.get(t)
        want_state = projected_state(b, model2(c)[2]) if c is not None else b["state"]
        ch = model2(c)[2] if c is not None else {}
        want = {g["id"]: ch.get(g["id"], (g["class"], g["reason"])) for g in b["exposures"]}
        got = {g["id"]: (g["class"], g["reason"]) for g in a["exposures"]}
        if a["state"] != want_state or got != want:
            diffs.append({"asset": t, "want_state": want_state, "got_state": a["state"], "want": want, "got": got})
        ta = a.get("ticker_authority")
        if c is not None and (ta is None or ta.get("result") != model2(c)[0]):
            diffs.append({"asset": t, "ticker_authority": ta, "want_result": model2(c)[0]})
    return {"identity_version": ID.VERSION, "differences": diffs,
            "states": dict(sorted(collections.Counter(a["state"] for a in v4.assets.values()).items()))}


# --------------------------------------------------------------------------- report
def report(paths, outputs=None):
    out_idx = ES.outputs_index(outputs)
    obs = []
    for p in paths:
        o = CC.observation(p)
        rows = CC.rows_with_vmeta(o["snap"])
        recorded = (o["snap"].get("manifest") or {}).get("identity_version")
        rules = ID.VERSION_RULES.get(recorded, ID.RULES)      # reproduced by the rules that recorded it
        same = resolve(rows, rules)
        repro = sorted(t for t, a in same.assets.items() if o["astate"](t) != a["state"])
        base = resolve(rows, 3)
        det = exposure_details(base, rows)
        census = {t: census_ticker(t, a, det[t]) for t, a in sorted(base.assets.items()) if t in sc.KNOWN_CRYPTO}
        cats = collections.Counter(c["category"] for c in census.values())
        multi = [c for c in census.values() if c["priced_exposures"] > 1]
        results = {t: model2(c) for t, c in census.items()}
        counts = {
            "known_crypto_tickers": len(census),
            "single_exposure_crypto": sum(1 for c in census.values() if c["priced_exposures"] == 1
                                          and c["state"] == ID.VERIFIED_CRYPTO),
            "multi_exposure": len(multi),
            "multi_exposure_crypto": sum(1 for c in multi if c["state"] == ID.VERIFIED_CRYPTO),
            "multi_exposure_with_explicit_tradfi": sum(1 for c in multi if c["tradfi_exposures"]),
            "multi_exposure_with_unverified_or_unchecked": sum(
                1 for c in multi if c["check_blocked_exposures"] or c["other_unverified_exposures"]),
            "multi_exposure_with_more_than_one_bindable": sum(1 for c in multi if len(c["binding_candidates"]) > 1),
            "unpriced_only": cats.get("unpriced_only", 0),
            "known_crypto_needed": sum(1 for c in census.values() if c["known_crypto_needed"])}
        m3 = {t: model3(c) for t, c in census.items() if len(c["binding_candidates"]) > 1 or c["tradfi_exposures"]}
        obs.append({
            "observation": o["meta"], "recorded_identity_version": recorded, "reproduced_with_rules": rules,
            "reproduction_differences": repro,
            "counts": counts, "categories": {k: cats.get(k, 0) for k in CATEGORIES},
            "category_members": {k: sorted(t for t, c in census.items() if c["category"] == k) for k in CATEGORIES},
            "more_than_one_bindable": sorted(t for t, c in census.items() if len(c["binding_candidates"]) > 1),
            "multi_exposure": {c["ticker"]: {k: c[k] for k in ("state", "category", "binding_candidates",
                                                               "tradfi_exposures", "ambiguous_exposures",
                                                               "check_blocked_exposures",
                                                               "other_unverified_exposures",
                                                               "direct_crypto_exposures")}
                               | {"model2": results[c["ticker"]][0], "selected": results[c["ticker"]][1]}
                               for c in multi},
            "model2_results": dict(sorted(collections.Counter(r[0] for r in results.values()).items())),
            "model3": m3,
            "model3_unsafe": sorted(t for t, v in m3.items() if v.get("would_pick_tradfi")
                                    or v.get("heuristics_disagree")),
            "impact_model2": impact(census, base, out_idx),
            "list_audit": list_audit(census, base),
            "v4_check": v4_check(census, base, rows),
            "census": census})
    return {"schema": SCHEMA, "identity_version": ID.VERSION, "outputs_folder": outputs, "observations": obs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--outputs", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rep = report(a.snapshots, a.outputs)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True, default=sorted, ensure_ascii=False)
    short = {"identity_version": rep["identity_version"], "observations": [
        {k: v for k, v in o.items() if k not in ("census", "multi_exposure", "model3", "category_members")}
        | {"impact_model2": {k: v for k, v in o["impact_model2"].items() if k != "moves"}
           | {"moved": [m["asset"] for m in o["impact_model2"]["moves"]]},
           "v4_check": None if o["v4_check"] is None else {"differences": len(o["v4_check"]["differences"]),
                                                           "states": o["v4_check"]["states"]},
           "list_audit": {k: v for k, v in o["list_audit"].items() if k != "no_live_market_entries"}}
        for o in rep["observations"]]}
    print(json.dumps(short, indent=1, sort_keys=True, default=sorted, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
