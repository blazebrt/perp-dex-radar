"""Candidate crypto-identity evidence: census and qualification gate (v8 Phase 4, Stage A). Read-only.

    python tools/v8/candidate_census.py SNAPSHOT [SNAPSHOT ...] [--json out.json]

SNAPSHOT is a v8 audit snapshot (data/v8/audit_latest.json, or the .json.gz a Research run keeps). Every snapshot keeps
every venue contract the adapters kept with the raw identity fields its venue sends (`vmeta`: Aster underlyingType and
underlyingSubType, Lighter strategy_index / market_flags / insurance fund / trading hours, Extended category, the
Variational and Extended names), the contract's own evidence, its price-coherent exposure and the asset's state.

For every candidate field and value it reports, per observation, how the contracts carrying it are classified now
(by exposure state and by asset state), the unique assets and exposures, every contradictory example (a candidate
value on a VERIFIED_TRADFI or AMBIGUOUS exposure) and the negative controls. Then every candidate RULE (a field/value,
or an exact combination) is put through the Phase 4 qualification gate:

  A  deterministic semantics: the venue documents the value as an asset class, or the payload states one
  B  no tradfi contamination: zero selected contracts on a VERIFIED_TRADFI exposure or asset, in every observation
  C  no unresolved conflict: zero selected contracts on an AMBIGUOUS exposure or asset
  D  negative controls: no selected contract carries tradfi evidence of its own, and no VERIFIED_TRADFI / AMBIGUOUS
     asset (stocks, RWA, rates, indices, the named regression controls) would change state
  E  exposure coherence: the projected promotion changes only the selected contracts' own exposures (a separate
     tradfi exposure of the same ticker stays tradfi)
  F  fail closed: an implementation property (a missing or unknown value is no evidence); checked by the tests

A rule qualifies only when A-E hold in every observation. The projection re-resolves each snapshot with this
checkout's v8.identity plus the candidate rule as crypto venue evidence (tools/v8/rescore_identity.py rebuilds the
adapter rows; it reproduces each snapshot's recorded states exactly, which the report checks first), so the impact of
a rule is known before it is made authoritative. Nothing is written except --json; no network."""
from __future__ import annotations

import argparse
import collections
import contextlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import rescore_identity as RS  # noqa: E402
import scanner as sc  # noqa: E402
from v8 import identity as ID  # noqa: E402
from v8 import snapshot as SN  # noqa: E402

KEPT = RS.KEPT
# free text: reported, never a rule (a name is not an asset-class statement)
TEXT_FIELDS = {("aster", "baseAsset"), ("variational", "name"), ("extended", "assetName"),
               ("extended", "description")}
# gate A: what each venue documents about the field (read for Phase 4; see docs/v8/phase4-positive-crypto-evidence.md)
SEMANTICS = {
    ("aster", "underlyingType"): (False, "documented by example only (\"COIN\"); Aster sends COIN for the stocks it "
                                         "lists too, so COIN is no evidence (Phase 2)"),
    ("aster", "underlyingSubType"): (False, "undocumented free-form tag list (the API docs show one example, "
                                            "[\"STORAGE\"]); values mix asset classes (STOCK, ETF), sectors (AI, "
                                            "Semiconductor), themes (Meme), tiers (Top), programmes (AOS2) and listing "
                                            "stages (pre-launch)"),
    ("aster", "quoteAsset"): (False, "settlement currency, not the underlying"),
    ("aster", "marginAsset"): (False, "margin currency, not the underlying"),
    ("lighter", "strategy_index"): (False, "absent from Lighter's OpenAPI schema for orderBookDetails"),
    ("lighter", "insurance_fund_account_index"): (False, "documented as an account index (the insurance fund that "
                                                         "backs the market): a risk pool, not an asset class"),
    ("lighter", "market_flags"): (False, "undocumented bit field"),
    ("lighter", "trading_hours"): (False, "trading hours: excluded by gate A"),
    ("extended", "category"): (True, "Extended's market category (Crypto / RWA): already authority since Phase 2"),
}
# gate A, value level: what a value states by itself. Positive crypto evidence needs a value that states a crypto
# asset class; a sector, theme, tier, programme or listing stage does not (it applies to tokens and companies alike).
VALUE_SEMANTICS = {
    ("aster", "underlyingSubType"): {
        "STOCK": "tradfi asset class (equity)", "ETF": "tradfi asset class (fund)",
        "Commodities": "tradfi asset class (commodity)", "USD1-RWA": "real-world asset",
        "Semiconductor": "industry sector (tradfi evidence since Phase 3)", "AI": "sector / theme tag",
        "Meme": "theme tag", "Top": "tier tag", "AOS2": "programme tag", "pre-launch": "listing stage"},
    ("extended", "category"): {"Crypto": "crypto asset class", "RWA": "real-world asset"},
}
CRYPTO_CLASS_VALUES = {("extended", "category", "Crypto")}
# regression controls (never rules): stocks, RWA, rates, index-like, gold token, ticker collisions
CONTROLS = ("PAXG", "SAMSUNGUSD", "HYUNDAIUSD", "US10Y", "BYD", "XIAOMI", "QNT", "PURR", "BB", "SPY", "XAU", "US500",
            "NVDA", "TSLA", "EURUSD")


# --------------------------------------------------------------------------- observations
def observation(path):
    snap = RS.load(path)
    man = snap.get("manifest") or {}
    contracts = SN.contract_records(snap)
    assets = (snap.get("registry") or {}).get("assets") or {}
    kept = [c for c in contracts if c.get("legacy") in KEPT]

    def astate(t):
        return ((assets.get(t) or {}).get("identity") or {}).get("state")

    return {"path": path, "label": man.get("scan_id") or os.path.basename(path), "snap": snap,
            "meta": {"scan_id": man.get("scan_id"), "git_sha": man.get("git_sha"), "ts": man.get("ts"),
                     "identity_version": man.get("identity_version"), "raw_contracts": len(contracts),
                     "kept_contracts": len(kept)},
            "kept": kept, "assets": assets, "astate": astate}


def values(c, field):
    """The candidate values one contract carries for a field (a list field gives one value per element)."""
    v = (c.get("vmeta") or {}).get(field)
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


# --------------------------------------------------------------------------- 1. the census
def census(obs):
    """{venue: {field: {value: {exp_state: n, asset_state: n, contracts, assets, exposures}}}} for one observation."""
    out = {}
    for c in obs["kept"]:
        for field, v in (c.get("vmeta") or {}).items():
            vals = ["<text>"] if (c["venue"], field) in TEXT_FIELDS else values(c, field)
            if isinstance(v, list) and (c["venue"], field) not in TEXT_FIELDS:
                vals = vals + ["[" + ",".join(str(x) for x in v) + "]"]       # the exact combination too
            for val in vals:
                e = out.setdefault(c["venue"], {}).setdefault(field, {}).setdefault(val, {
                    "contracts": 0, "by_exposure_state": collections.Counter(), "by_asset_state": collections.Counter(),
                    "assets": set(), "exposures": set(), "unpriced": 0})
                e["contracts"] += 1
                e["by_exposure_state"][c.get("exp_state") or "NONE"] += 1
                e["by_asset_state"][obs["astate"](c["asset"]) or "NONE"] += 1
                e["assets"].add(c["asset"])
                e["exposures"].add(c.get("exposure"))
                e["unpriced"] += 0 if c.get("npx") else 1
    for v in out.values():
        for f in v.values():
            for val, e in f.items():
                e["by_exposure_state"] = dict(sorted(e["by_exposure_state"].items()))
                e["by_asset_state"] = dict(sorted(e["by_asset_state"].items()))
                e["assets_n"], e["exposures_n"] = len(e["assets"]), len(e["exposures"])
                e["assets"] = sorted(e["assets"]) if len(e["assets"]) <= 60 else None
                del e["exposures"]
    return out


# --------------------------------------------------------------------------- 2. candidate rules
class Rule:
    """One candidate: a venue field equal to a value, containing a value, holding exactly one value, or (Aster) that
    exact single value together with underlyingType COIN."""

    def __init__(self, venue, field, kind, value):
        self.venue, self.field, self.kind, self.value = venue, field, kind, value
        op = {"eq": "==", "has": " contains ", "only": " == only ", "coin_only": " == only "}[kind]
        self.id = f"{venue}.{field}{op}{value}" + (" AND underlyingType == COIN" if kind == "coin_only" else "")

    def match_vmeta(self, venue, vm):
        if venue != self.venue or not vm:
            return False
        v = vm.get(self.field)
        if v is None:
            return False
        if self.kind == "eq":
            return str(v) == self.value
        lst = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        if self.kind == "has":
            return self.value in lst
        if self.kind == "only":
            return lst == [self.value]
        return lst == [self.value] and str(vm.get("underlyingType")) == "COIN"

    def semantics(self):
        """(states a crypto asset class, note): the field's documentation and what the value itself states."""
        _, field_note = SEMANTICS.get((self.venue, self.field), (False, "no documented meaning"))
        stated = VALUE_SEMANTICS.get((self.venue, self.field), {}).get(self.value)
        crypto = (self.venue, self.field, self.value) in CRYPTO_CLASS_VALUES
        note = field_note + (f"; the value states: {stated}" if stated else "; the value states no asset class")
        return crypto, note


def rules_from(observations):
    seen = {}
    for obs in observations:
        for c in obs["kept"]:
            for field, v in (c.get("vmeta") or {}).items():
                key = (c["venue"], field)
                if key in TEXT_FIELDS:
                    continue
                if isinstance(v, list):
                    for x in v:
                        for kind in ("has", "only", "coin_only"):
                            seen.setdefault((c["venue"], field, kind, str(x)), None)
                else:
                    seen.setdefault((c["venue"], field, "eq", str(v)), None)
    return [Rule(*k) for k in sorted(seen)]


# --------------------------------------------------------------------------- 3. projection
@contextlib.contextmanager
def candidate_evidence(rule):
    """v8.identity with the rule added as crypto venue evidence (projection only; restored on exit)."""
    orig = ID.venue_field_evidence

    def patched(row, lists):
        ev = orig(row, lists)
        if rule is not None and rule.match_vmeta(row.get("dex"), row.get("_vmeta")):
            ev = ev + [(ID.CRYPTO, "CANDIDATE:" + rule.id, ID.VENUE_METADATA)]
        return ev

    ID.venue_field_evidence = patched
    try:
        yield
    finally:
        ID.venue_field_evidence = orig


def rows_with_vmeta(snap):
    rows = RS.rows_of(snap)
    recs = [c for c in SN.contract_records(snap) if c.get("legacy") in KEPT]
    it = {d: iter([c for c in recs if c["venue"] == d]) for d in sc.DEXES}
    for d, lst in rows.items():
        for r in lst:
            c = next(it[d])
            assert c["raw"] == r["sym"], (d, c["raw"], r["sym"])
            r["_vmeta"] = c.get("vmeta") or {}
    return rows


def resolve(rows, rule=None):
    with candidate_evidence(rule):
        return ID.resolve(rows, sc.DEXES, ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME),
                          sc.in_my_dexes)


def project(obs, rows, base, rule):
    after = resolve(rows, rule)
    changed = []
    for t, a in after.assets.items():
        b = base.assets.get(t) or {}
        if b.get("state") != a["state"]:
            coin = after.coins.get(t) or {}
            bexp = {g["id"]: g["class"] for g in b.get("exposures") or []}
            aexp = {g["id"]: g["class"] for g in a.get("exposures") or []}
            changed.append({"asset": t, "from": b.get("state"), "to": a["state"], "decision": a["decision"],
                            "venues": sorted(coin.get("venues") or {}),
                            "symbols": [f"{d}:{v.get('sym')}" for d, v in (coin.get("venues") or {}).items()],
                            "best_vol": coin.get("best_vol"), "trade_vol": coin.get("trade_vol"),
                            "liquid_1m": (coin.get("trade_vol") or 0) >= 1_000_000,
                            "exposures_changed": sorted(k for k in aexp if bexp.get(k) != aexp[k]),
                            "other_exposures": {k: v for k, v in aexp.items() if bexp.get(k) == v}})
    trans = collections.Counter(f"{c['from']}->{c['to']}" for c in changed)
    return {"changed": sorted(changed, key=lambda c: -(c["best_vol"] or 0)), "transitions": dict(trans),
            "states_after": dict(collections.Counter(a["state"] for a in after.assets.values()))}


# --------------------------------------------------------------------------- 4. the gate
def evaluate(rule, observations, bases):
    per_obs, gate = {}, {k: True for k in "ABCDE"}
    doc, why_doc = rule.semantics()
    gate["A"] = bool(doc)
    for obs in observations:
        sel = [c for c in obs["kept"] if rule.match_vmeta(c["venue"], c.get("vmeta"))]
        by_exp = collections.Counter(c.get("exp_state") or "NONE" for c in sel)
        by_asset = collections.Counter(obs["astate"](c["asset"]) or "NONE" for c in sel)
        bad = lambda st: [{"contract": c["id"], "asset": c["asset"], "exposure": c.get("exposure"),  # noqa: E731
                           "exp_reason": c.get("exp_reason"), "own_evidence": c.get("evidence"),
                           "asset_state": obs["astate"](c["asset"]), "price": c.get("npx")}
                          for c in sel if c.get("exp_state") == st or obs["astate"](c["asset"]) == st]
        tradfi, amb = bad(ID.VERIFIED_TRADFI), bad(ID.AMBIGUOUS)
        own_tradfi = [c["id"] for c in sel if c.get("cls") == ID.TRADFI]
        controls = sorted({c["asset"] for c in sel if c["asset"] in CONTROLS})
        rows, base = bases[obs["label"]]
        proj = project(obs, rows, base, rule)
        leak = [c for c in proj["changed"] if c["from"] in (ID.VERIFIED_TRADFI, ID.AMBIGUOUS)]
        ctl_changed = [c["asset"] for c in proj["changed"] if c["asset"] in CONTROLS]
        # E: on a ticker with more than one exposure, only exposures that hold a selected contract may change
        sel_exps = {c.get("exposure") for c in sel}
        spill = [c for c in proj["changed"] if any(x not in sel_exps for x in c["exposures_changed"])]
        g = {"B": not tradfi, "C": not amb, "D": not own_tradfi and not leak and not ctl_changed, "E": not spill}
        for k, v in g.items():
            gate[k] = gate[k] and v
        per_obs[obs["label"]] = {
            "selected_contracts": len(sel), "selected_assets": len({c["asset"] for c in sel}),
            "by_exposure_state": dict(sorted(by_exp.items())), "by_asset_state": dict(sorted(by_asset.items())),
            "tradfi_examples": tradfi[:20], "ambiguous_examples": amb[:20], "own_tradfi_evidence": own_tradfi[:20],
            "controls_selected": controls, "unverified_assets": sorted({c["asset"] for c in sel
                                                                        if obs["astate"](c["asset"]) == ID.UNVERIFIED}),
            "projection": proj, "projection_leaks": leak, "controls_changed": ctl_changed,
            "exposure_spill": spill, "gate": g}
    reasons = []
    if not gate["A"]:
        reasons.append("A: " + why_doc)
    for k, txt in (("B", "selects contracts on VERIFIED_TRADFI exposures/assets"),
                   ("C", "selects contracts on AMBIGUOUS exposures/assets"),
                   ("D", "negative controls fail (own tradfi evidence, or a tradfi/ambiguous asset would change)"),
                   ("E", "the projected promotion changes an exposure no selected contract belongs to")):
        if not gate[k]:
            reasons.append(f"{k}: {txt}")
    useful = any(p["projection"]["changed"] for p in per_obs.values())
    return {"rule": rule.id, "venue": rule.venue, "field": rule.field, "kind": rule.kind, "value": rule.value,
            "semantics": {"documented_asset_class": bool(doc), "note": why_doc}, "gate": gate,
            "qualified": all(gate.values()), "would_change_outputs": useful, "rejected_because": reasons,
            "observations": per_obs}


# --------------------------------------------------------------------------- 5. inventory and controls
def inventory(obs, base, rules):
    out = []
    for t, a in sorted(base.assets.items()):
        if a["state"] != ID.UNVERIFIED:
            continue
        coin = base.coins.get(t) or {}
        cs = [c for c in obs["kept"] if c["asset"] == t]
        out.append({"asset": t, "venues": sorted(coin.get("venues") or {}),
                    "raw_symbols": sorted(c["id"] for c in cs),
                    "candidate_evidence": {c["id"]: c.get("vmeta") for c in cs if c.get("vmeta")},
                    "best_vol": coin.get("best_vol"), "trade_vol": coin.get("trade_vol"),
                    "liquid_1m": (coin.get("trade_vol") or 0) >= 1_000_000,
                    "matching_rules": sorted({r.id for r in rules for c in cs
                                              if r.match_vmeta(c["venue"], c.get("vmeta"))})})
    return out


def controls(obs, base):
    out = {}
    for t in CONTROLS:
        a = base.assets.get(t)
        if a is None:
            out[t] = None
            continue
        out[t] = {"state": a["state"], "decision": a["decision"], "collision": a["collision"],
                  "exposures": [[g["id"], g["class"], g["anchor_price"], g["members"]] for g in a["exposures"]]}
    return out


def collisions(base):
    return {t: {"state": a["state"], "decision": a["decision"],
                "exposures": [[g["id"], g["class"], g["anchor_price"], g["members"]] for g in a["exposures"]]}
            for t, a in sorted(base.assets.items()) if a["collision"]}


# --------------------------------------------------------------------------- report
def report(paths):
    observations = [observation(p) for p in paths]
    bases, repro = {}, {}
    for obs in observations:
        rows = rows_with_vmeta(obs["snap"])
        base = resolve(rows)
        # v8 Phase 5: a snapshot is reproduced by the identity version that recorded it (v8 Phase 6: explicitly,
        # VERSION_RULES: v8.identity/2 by rules=2, /3 by rules=3, /4 by rules=4); the candidate projections are always
        # measured against this checkout's rules
        recorded = obs["meta"].get("identity_version")
        rules = ID.VERSION_RULES.get(recorded, ID.RULES)
        same = base if rules == ID.RULES else ID._resolve(
            rows, sc.DEXES, ID.Lists(sc.TRADFI, sc.KNOWN_CRYPTO, sc.is_fx, sc.TRADFI_NAME), sc.in_my_dexes, None,
            rules=rules)
        diff = sorted(t for t, a in same.assets.items() if obs["astate"](t) != a["state"])
        repro[obs["label"]] = {"assets": len(base.assets), "state_differences": diff, "recorded_version": recorded,
                               "states": dict(collections.Counter(a["state"] for a in base.assets.values())),
                               "states_now_vs_recorded": sorted(t for t, a in base.assets.items()
                                                                if obs["astate"](t) != a["state"])}
        bases[obs["label"]] = (rows, base)
    rules = rules_from(observations)
    results = [evaluate(r, observations, bases) for r in rules]
    qualified = [r for r in results if r["qualified"]]
    return {
        "schema": "v8.candidate-census/1", "identity_version": ID.VERSION,
        "observations": [o["meta"] for o in observations],
        "reproduction": repro,
        "census": {o["label"]: census(o) for o in observations},
        "rules": results,
        "qualified_rules": [r["rule"] for r in qualified],
        "qualified_with_impact": [r["rule"] for r in qualified if r["would_change_outputs"]],
        "unverified_inventory": {o["label"]: inventory(o, bases[o["label"]][1], rules) for o in observations},
        "controls": {o["label"]: controls(o, bases[o["label"]][1]) for o in observations},
        "collisions": {o["label"]: collisions(bases[o["label"]][1]) for o in observations},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snapshots", nargs="+")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    rep = report(a.snapshots)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True, default=str, ensure_ascii=False)
    print(json.dumps({"observations": rep["observations"], "reproduction": {
        k: {"assets": v["assets"], "state_differences": len(v["state_differences"]), "states": v["states"]}
        for k, v in rep["reproduction"].items()},
        "rules": [{"rule": r["rule"], "qualified": r["qualified"], "gate": r["gate"],
                   "impact": {k: v["projection"]["transitions"] for k, v in r["observations"].items()},
                   "rejected_because": r["rejected_because"]} for r in rep["rules"]],
        "qualified_rules": rep["qualified_rules"], "qualified_with_impact": rep["qualified_with_impact"]},
        indent=1, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
