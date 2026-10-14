"""Unified decision engine (v8 Phase 11): one deterministic decision authority over every discovered perp asset.

    What should the trader pay attention to right now, why, and what prevents an opportunity from being stronger?

This module consumes the existing authorities and never recomputes them:

    discovery            v8.discovery/1 records (universal: every active perp of every healthy venue)
    identity / exposure  the record's v8.identity/4 state, exposure flags and admitted contracts
    venue health         the record's data quality, the discovery provenance and each contract's health
    strategy authority   the Phase 9 reviewed policy rows (v8.quant-strategy-policy/1), never a profit or a score
    signals              quant.py's own strategy functions at the latest closed bar (the quant audit records them)
    execution liquidity  the record's v8.liquidity execution gate
    funding              venue-reported current rates of the asset's admitted trade-DEX contracts (never a default)
    portfolio risk       Phase 10 what_if() of the proposed position against the whole open book (v8.portfolio-risk/1)

and turns them into one record per opportunity and one per asset, with a TRADE / WATCH / AVOID state, the gate that
decided it, the governed ranking inputs, the section it was placed in and an INPUT -> RULE -> RESULT -> EFFECT trace.

    build(snapshot)                  the whole decision document (data/v8/decision.json)
    evaluate_asset(snapshot, asset)  the same evaluation for one asset (the Analyzer's engine): identical state, gates,
                                     blockers, authority and trace to the market-wide document

State rule (policy states.precedence): a FAIL gate (a known disqualifier) is AVOID; otherwise any CAP (a governed
ceiling, e.g. a LEGACY_HOLDOVER strategy) or MISSING (an authority that is not there) gate is WATCH; only when every
mandatory gate PASSes is it TRADE. Ranking happens after the state, inside a section's eligible states only, so no
rank can override a gate. Every threshold, effect and ranking rule is read from decision_policy.json
(v8.decision-policy/1); this file holds none. Nothing here executes, sizes for real money, or writes back to an engine."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from . import portfolio_risk as PR

VERSION = "v8.decision/1"
POLICY_VERSION = "v8.decision-policy/1"
PATH = Path(__file__).with_name("decision_policy.json")
FILE = "data/v8/decision.json"
REVIEW_STATUS = "POLICY_REVIEWED_INITIAL_V1"      # the one accepted review status of v8.decision-policy/1
TRADE, WATCH, AVOID = "TRADE", "WATCH", "AVOID"
STATES = (TRADE, WATCH, AVOID)
STATE_ORDER = {TRADE: 0, WATCH: 1, AVOID: 2}
PASS, CAP, MISSING, FAIL, INFO, NA = "PASS", "CAP", "MISSING", "FAIL", "INFO", "NOT_APPLICABLE"
EFFECT_RESULT = {"PASS": PASS, "CAP_WATCH": CAP, "WATCH_MISSING": MISSING, "AVOID": FAIL}
DIRECTIONAL, EMERGING, FUNDING = "DIRECTIONAL_STRATEGY", "EMERGING_OBSERVATION", "FUNDING_SPREAD"
TYPES = (DIRECTIONAL, EMERGING, FUNDING)
SECTIONS = ("best_trades_now", "emerging_opportunities", "funding_opportunities")
TRACE_STEPS = ("DISCOVERY", "IDENTITY", "ECONOMIC_EXPOSURE", "VENUE_HEALTH", "SIGNAL", "STRATEGY_AUTHORITY",
               "EXECUTION_LIQUIDITY", "FUNDING", "PORTFOLIO_BEFORE", "PROPOSED_TRADE", "PORTFOLIO_AFTER",
               "RISK_LIMITS", "DECISION_STATE")
PLACEMENT_STEPS = ("RANKING", "SECTION_PLACEMENT")
RANK_FIELDS = {
    "best_trades_now": {"signal_kind_order": "num", "signal_age_s": "num", "slippage_rate": "num",
                        "after_executable_risk": "num", "asset": "str", "strategy": "str", "direction": "num"},
    "emerging_opportunities": {"primary_evidence_count": "num", "evidence_count": "num",
                               "outstanding_blockers": "num", "asset": "str"},
    "funding_opportunities": {"net_carry": "num", "basis_abs": "num", "asset": "str"},
}
DEPLOYMENT = ("LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "PAPER_ONLY", "DISABLED")
RESEARCH = ("REQUALIFIED", "PROBATION", "REJECTED", "INSUFFICIENT_EVIDENCE", "INVALIDATED")
HEALTHY = "HEALTHY"
REQUIRED_INPUT_TIMES = ("discovery", "quant", "portfolio")
EFFECT_TEXT = {PASS: "passes", CAP: "caps the decision at WATCH", MISSING: "authority missing: at most WATCH",
               FAIL: "known disqualifier: AVOID", INFO: "recorded", NA: "not applicable to this opportunity type"}


class PolicyError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers
def _num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def _int(x):
    return not isinstance(x, bool) and isinstance(x, int)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _clean(x):
    """JSON-ready, deterministic: floats as computed, no negative zero, tuples as lists, dict keys as strings."""
    if isinstance(x, float):
        return x + 0.0
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def implementation_hash():
    """SHA-256 of the exact bytes of this decision implementation."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- policy
SECTION_KEYS = {
    "states": ("precedence", "max_state_by_type"),
    "identity": ("trade_identity",),
    "exposure": ("conflict_flags", "degraded_flags"),
    "venue_health": ("healthy_data_quality",),
    "signal": ("max_age_s", "max_stop_fraction"),
    "strategy_authority": ("trade_deployment_states", "trade_research_states", "watch_deployment_states",
                           "avoid_deployment_states", "avoid_research_states"),
    "execution": ("effects",),
    "funding": ("venue_rule", "max_rate_age_s"),
    "freshness": ("max_input_age_s",),
    "portfolio": ("after_state_effects",),
    "emerging": ("evidence_from_flags", "primary_evidence", "warning_flags"),
    "funding_spread": ("holding_hours", "max_basis", "min_net_carry", "leg_volume_threshold"),
    "sections": SECTIONS,
    "ranking": SECTIONS,
}


def _v(policy, section, key):
    return policy[section][key]["value"]


def validate_policy(policy):
    """The policy, unchanged, or PolicyError: exact keys, POLICY basis, and the safety invariants no reviewed value may
    break (only ACTIVE_REQUALIFIED/REQUALIFIED can support TRADE, a breach is always AVOID, sections hold at most 5...)."""
    def need(ok, why):
        if not ok:
            raise PolicyError("DECISION_POLICY_INVALID: " + why)
    need(isinstance(policy, dict) and policy.get("schema") == POLICY_VERSION, "schema")
    need(set(policy) == {"schema", "review_status", "statement", *SECTION_KEYS}, "top-level keys")
    # exactly the reviewed status: the old pending status, a free-form or "validated" label, or an empty one is refused
    need(isinstance(policy["review_status"], str) and policy["review_status"] == REVIEW_STATUS,
         "review_status must be " + REVIEW_STATUS)
    need(isinstance(policy["statement"], str) and bool(policy["statement"].strip()), "statement")
    for sec, keys in SECTION_KEYS.items():
        need(isinstance(policy[sec], dict) and set(policy[sec]) == set(keys), sec + " keys")
        for k in keys:
            e = policy[sec][k]
            need(isinstance(e, dict) and set(e) == {"value", "basis", "rationale"}, f"{sec}.{k} value/basis/rationale")
            need(e["basis"] == "POLICY", f"{sec}.{k} basis must be POLICY (nothing here is empirically validated)")
            need(isinstance(e["rationale"], str) and bool(e["rationale"].strip()), f"{sec}.{k} rationale")
    v = lambda s, k: policy[s][k]["value"]   # noqa: E731
    need(v("states", "precedence") == ["AVOID", "WATCH", "TRADE"], "states.precedence is fixed")
    mx = v("states", "max_state_by_type")
    need(isinstance(mx, dict) and set(mx) == set(TYPES) and mx[DIRECTIONAL] in STATES, "states.max_state_by_type")
    need(mx[EMERGING] in (WATCH, AVOID) and mx[FUNDING] in (WATCH, AVOID),
         "an emerging observation or a funding spread has no governed authority for TRADE")
    need(v("identity", "trade_identity") == "VERIFIED_CRYPTO", "identity.trade_identity must be VERIFIED_CRYPTO")
    for k in ("conflict_flags", "degraded_flags"):
        need(isinstance(v("exposure", k), list) and all(isinstance(x, str) for x in v("exposure", k)), "exposure." + k)
    need("ECONOMIC_EXPOSURE_CONFLICT" in v("exposure", "conflict_flags"), "an exposure conflict must be AVOID")
    need(v("venue_health", "healthy_data_quality") == HEALTHY, "venue_health.healthy_data_quality")
    ma = v("signal", "max_age_s")
    need(isinstance(ma, dict) and set(ma) == {"4h", "1d"} and all(_int(x) and x > 0 for x in ma.values()),
         "signal.max_age_s")
    need(_num(v("signal", "max_stop_fraction")) and 0 < v("signal", "max_stop_fraction") < 1, "signal.max_stop_fraction")
    sa = {k: v("strategy_authority", k) for k in SECTION_KEYS["strategy_authority"]}
    for k, allowed in (("trade_deployment_states", DEPLOYMENT), ("watch_deployment_states", DEPLOYMENT),
                       ("avoid_deployment_states", DEPLOYMENT), ("trade_research_states", RESEARCH),
                       ("avoid_research_states", RESEARCH)):
        need(isinstance(sa[k], list) and set(sa[k]) <= set(allowed), "strategy_authority." + k)
    need(set(sa["trade_deployment_states"]) <= {"ACTIVE_REQUALIFIED"}, "only ACTIVE_REQUALIFIED can support TRADE")
    need(set(sa["trade_research_states"]) <= {"REQUALIFIED"}, "only REQUALIFIED research can support TRADE")
    need("DISABLED" in sa["avoid_deployment_states"], "a DISABLED strategy must be AVOID")
    need(not (set(sa["trade_deployment_states"]) & set(sa["watch_deployment_states"]))
         and not (set(sa["watch_deployment_states"]) & set(sa["avoid_deployment_states"]))
         and not (set(sa["trade_deployment_states"]) & set(sa["avoid_deployment_states"])),
         "deployment-state lists must be disjoint")
    need(set(sa["trade_deployment_states"]) | set(sa["watch_deployment_states"]) | set(sa["avoid_deployment_states"])
         == set(DEPLOYMENT), "every deployment state must be mapped")
    ef = v("execution", "effects")
    need(isinstance(ef, dict) and set(ef) == {"KNOWN_PASS", "KNOWN_BELOW_GATE", "MISSING", "NO_COIN_RECORD",
                                             "NOT_ON_TRADE_DEX"} and set(ef.values()) <= set(EFFECT_RESULT),
         "execution.effects")
    need(all(ef[k] != "PASS" for k in ef if k != "KNOWN_PASS"), "only known liquidity at the gate can pass")
    need(v("funding", "venue_rule") == "MOST_ADVERSE_OBSERVED_TRADE_DEX", "funding.venue_rule")
    need(_int(v("funding", "max_rate_age_s")) and v("funding", "max_rate_age_s") > 0, "funding.max_rate_age_s")
    need(_int(v("freshness", "max_input_age_s")) and v("freshness", "max_input_age_s") > 0, "freshness")
    pe = v("portfolio", "after_state_effects")
    need(isinstance(pe, dict) and set(pe) == set(PR.STATES) and set(pe.values()) <= set(EFFECT_RESULT),
         "portfolio.after_state_effects")
    need(pe[PR.BREACHED] == "AVOID", "a Phase 10 limit breach after the addition is always AVOID")
    need(pe[PR.UNEVALUABLE] != "PASS", "an unevaluable portfolio can never pass")
    em = {k: v("emerging", k) for k in SECTION_KEYS["emerging"]}
    need(isinstance(em["evidence_from_flags"], dict)
         and all(isinstance(a, str) and isinstance(b, str) for a, b in em["evidence_from_flags"].items()),
         "emerging.evidence_from_flags")
    need(isinstance(em["primary_evidence"], list) and bool(em["primary_evidence"]), "emerging.primary_evidence")
    need(isinstance(em["warning_flags"], list), "emerging.warning_flags")
    need(not (set(em["warning_flags"]) & set(em["evidence_from_flags"])), "a warning flag is never positive evidence")
    fs = {k: v("funding_spread", k) for k in SECTION_KEYS["funding_spread"]}
    need(_num(fs["holding_hours"]) and fs["holding_hours"] > 0, "funding_spread.holding_hours")
    need(_num(fs["max_basis"]) and 0 < fs["max_basis"] < 1, "funding_spread.max_basis")
    need(_num(fs["min_net_carry"]) and fs["min_net_carry"] >= 0, "funding_spread.min_net_carry")
    need(fs["leg_volume_threshold"] == "EXECUTION_LIQUIDITY_THRESHOLD", "funding_spread.leg_volume_threshold")
    for s in SECTIONS:
        sv = v("sections", s)
        need(isinstance(sv, dict) and _int(sv.get("max")) and 0 <= sv["max"] <= 5, f"sections.{s}.max (at most 5)")
        need(isinstance(sv.get("states"), list) and isinstance(sv.get("types"), list)
             and set(sv["types"]) <= set(TYPES), f"sections.{s} states/types")
        need(set(sv) <= {"max", "states", "types", "exclude_assets_in"}, f"sections.{s} keys")
        rk = v("ranking", s)
        need(isinstance(rk, list) and bool(rk) and all(isinstance(r, list) and len(r) == 2 and r[0] in RANK_FIELDS[s]
                                                        and r[1] in ("asc", "desc") for r in rk), f"ranking.{s}")
        need(all(r[1] == "asc" for r in rk if RANK_FIELDS[s][r[0]] == "str"), f"ranking.{s}: text fields sort asc")
        need(any(r[0] == "asset" for r in rk), f"ranking.{s} needs the deterministic asset tie-break")
    need(v("sections", "best_trades_now")["states"] == [TRADE], "best_trades_now holds TRADE only")
    need(set(v("sections", "emerging_opportunities")["states"]) <= {WATCH}
         and set(v("sections", "funding_opportunities")["states"]) <= {WATCH}, "emerging/funding hold WATCH only")
    return policy


def load_policy(path=PATH):
    return validate_policy(json.loads(Path(path).read_text(encoding="utf-8")))


def policy_hash(policy):
    return digest(policy)


# --------------------------------------------------------------------------- gates
def _gate(step, inp, rule, result, code=None, effect=None):
    return {"step": step, "input": inp, "rule": rule, "result": result, "code": code,
            "effect": effect or EFFECT_TEXT[result]}


def _effect_gate(step, inp, rule, effect_name, code):
    res = EFFECT_RESULT[effect_name]
    return _gate(step, inp, rule, res, None if res == PASS else code)


def _asset_gates(rec, snap, policy):
    """DISCOVERY, IDENTITY, ECONOMIC_EXPOSURE, VENUE_HEALTH: the same for every opportunity of the asset."""
    prov = (snap.get("discovery") or {}).get("provenance") or {}
    out = []
    if rec is None:
        out.append(_gate("DISCOVERY", None, "the asset must be a discovery record (an active supported perp on a venue "
                         "whose market list loaded)", FAIL, "NOT_IN_DISCOVERY"))
        for step in ("IDENTITY", "ECONOMIC_EXPOSURE", "VENUE_HEALTH"):
            out.append(_gate(step, None, "no discovery record", FAIL, "NOT_IN_DISCOVERY"))
        return out
    dinp = {"stage": rec.get("discovery_stage"), "venues": rec.get("venues"),
            "fallback_universe": prov.get("fallback_universe"),
            "available_venue_discovery_qualified": prov.get("available_venue_discovery_qualified")}
    if not rec.get("discovery_visible") or not rec.get("contracts"):
        out.append(_gate("DISCOVERY", dinp, "an active supported perp in discovery", FAIL, "UNSUPPORTED_OR_INACTIVE_MARKET"))
    elif prov.get("fallback_universe") is not False or prov.get("available_venue_discovery_qualified") is not True:
        out.append(_gate("DISCOVERY", dinp, "discovery must be qualified (not the fallback universe)", MISSING,
                         "DISCOVERY_DEGRADED"))
    else:
        out.append(_gate("DISCOVERY", dinp, "an active supported perp in qualified universal discovery", PASS))
    stale = _freshness(snap, policy)
    if stale:
        out.append(_gate("DISCOVERY", {"stale_inputs": stale}, "every input must be from this scan "
                         "(freshness.max_input_age_s)", MISSING, "INPUT_STALE"))
    ident = rec.get("identity")
    want = _v(policy, "identity", "trade_identity")
    iinp = {"state": ident, "reason": rec.get("identity_reason")}
    if ident == want:
        out.append(_gate("IDENTITY", iinp, "v8.identity/4 state must be " + want, PASS))
    else:
        out.append(_gate("IDENTITY", iinp, "v8.identity/4 state must be " + want, FAIL,
                         "IDENTITY_NON_CRYPTO" if ident == "VERIFIED_TRADFI" else "IDENTITY_NOT_VERIFIED"))
    flags = rec.get("anomaly_flags") or []
    conflict = [f for f in flags if f in _v(policy, "exposure", "conflict_flags")]
    degraded = [f for f in flags if f in _v(policy, "exposure", "degraded_flags")]
    xinp = {"flags": conflict + degraded, "exposure_check_state": rec.get("exposure_check_state")}
    if conflict:
        out.append(_gate("ECONOMIC_EXPOSURE", xinp, "no conflicting economic evidence or ticker collision", FAIL,
                         "ECONOMIC_EXPOSURE_CONFLICT"))
    elif degraded:
        out.append(_gate("ECONOMIC_EXPOSURE", xinp, "exposure checks must have run cleanly", MISSING,
                         "EXPOSURE_METADATA_DEGRADED"))
    else:
        out.append(_gate("ECONOMIC_EXPOSURE", xinp, "admitted economic exposure without conflict", PASS))
    dq = rec.get("data_quality")
    vinp = {"data_quality": dq, "venues_failed": prov.get("venues_failed_names")}
    if dq == _v(policy, "venue_health", "healthy_data_quality"):
        out.append(_gate("VENUE_HEALTH", vinp, "every contract of the asset healthy", PASS))
    else:
        out.append(_gate("VENUE_HEALTH", vinp, "every contract of the asset healthy", MISSING, "VENUE_DATA_DEGRADED"))
    return out


def _execution_gate(rec, policy, label="EXECUTION_LIQUIDITY"):
    el = (rec or {}).get("execution_liquidity") or {}
    st = el.get("state")
    if st == "KNOWN":
        key = "KNOWN_PASS" if el.get("passes") is True else "KNOWN_BELOW_GATE"
    elif st in ("MISSING", "NOT_ON_TRADE_DEX", "NO_COIN_RECORD"):
        key = st
    else:
        key = "MISSING"
    code = {"KNOWN_BELOW_GATE": "EXECUTION_LIQUIDITY_BELOW_GATE", "MISSING": "EXECUTION_LIQUIDITY_UNKNOWN",
            "NO_COIN_RECORD": "EXECUTION_LIQUIDITY_UNKNOWN", "NOT_ON_TRADE_DEX": "NOT_ON_TRADE_DEX"}.get(key)
    return _effect_gate(label, {"state": st, "observed_value": el.get("observed_value"),
                                "threshold": el.get("threshold"), "passes": el.get("passes")},
                        "v8.liquidity execution gate: KNOWN 24h trade-DEX volume >= threshold",
                        _v(policy, "execution", "effects")[key], code)


def _trade_contracts(asset, snap):
    tdx = set(snap.get("trade_dexes") or ())
    out = []
    for c in snap.get("contracts") or []:
        if (c.get("asset") == asset and c.get("type") == "perp" and c.get("active") and c.get("admitted") is True
                and (not tdx or c.get("venue") in tdx)):
            out.append(c)
    return sorted(out, key=lambda c: (c.get("venue") or "", c.get("id") or ""))


def _funding_obs(asset, snap, policy):
    """Fresh venue-reported funding of the asset's admitted trade-DEX contracts (observed zero kept, missing dropped)."""
    as_of, age = snap.get("as_of"), _v(policy, "funding", "max_rate_age_s")
    obs = []
    for c in _trade_contracts(asset, snap):
        r, t = c.get("fund8h"), c.get("rcv_ts")
        if _num(r) and _int(t) and 0 <= as_of - t <= age:
            obs.append({"venue": c.get("venue"), "contract": c.get("id"), "rate_8h": float(r),
                        "interval_h": c.get("fund_iv_h"), "source_ts": c.get("src_ts"), "received_ts": t,
                        "health": c.get("health"), "volume": c.get("vol"),
                        "price": c.get("npx") if _num(c.get("npx")) else None,
                        "basis": "VENUE_REPORTED_CURRENT_RATE_8H"})
    return obs


def _directional_funding(asset, d, snap, policy):
    obs = [o for o in _funding_obs(asset, snap, policy) if o["health"] == HEALTHY]
    if not obs:
        return {"state": "MISSING", "rate_8h": None, "venue": None, "observations": [],
                "reason": "NO_FRESH_OBSERVED_FUNDING_ON_A_TRADE_DEX_CONTRACT"}
    worst = max(obs, key=lambda o: (d * o["rate_8h"], o["venue"] or ""))
    return {"state": "OBSERVED_ZERO" if worst["rate_8h"] == 0 else "OBSERVED", "rate_8h": worst["rate_8h"],
            "venue": worst["venue"], "contract": worst["contract"], "interval_h": worst["interval_h"],
            "received_ts": worst["received_ts"], "source_ts": worst["source_ts"],
            "rule": _v(policy, "funding", "venue_rule"), "observations": obs}


def _freshness(snap, policy):
    as_of, lim = snap.get("as_of"), _v(policy, "freshness", "max_input_age_s")
    times = snap.get("inputs_as_of")
    if not isinstance(times, dict):
        return list(REQUIRED_INPUT_TIMES)
    stale = []
    for k in sorted(set(REQUIRED_INPUT_TIMES) | set(times), key=str):
        t = times.get(k)
        if not (_int(as_of) and as_of >= 0 and _int(t) and t >= 0 and 0 <= as_of - t <= lim):
            stale.append(k)
    return stale


def _horizon(snap, policy):
    """Until when the document's inputs stay within freshness.max_input_age_s: the engine's own INPUT_STALE rule
    evaluated at a later time (every declared input time, and the decision time itself, plus max_input_age_s)."""
    ts = [t for t in (snap.get("inputs_as_of") or {}).values() if _int(t)]
    return min([snap["as_of"]] + ts) + _v(policy, "freshness", "max_input_age_s")


def _valid_until(cand, snap, policy):
    """Until when a decision's time-bound inputs, as its trace records them, stay within their policy ages: the
    document horizon, the signal's max_age_s for its timeframe and every used funding observation's max_rate_age_s.
    A consumer (the Analyzer) must treat the decision as stale after it and fail closed; nothing is re-decided."""
    rate_age = _v(policy, "funding", "max_rate_age_s")
    until = [_horizon(snap, policy)]
    if cand["type"] == DIRECTIONAL:
        s = next((g["input"] for g in cand["trace"] if g["step"] == "SIGNAL" and isinstance(g["input"], dict)
                  and "bar_close_t" in g["input"]), {})
        tf = s.get("timeframe")
        ma = _v(policy, "signal", "max_age_s").get(tf) if isinstance(tf, str) else None
        if _int(s.get("bar_close_t")) and ma is not None:
            until.append(s["bar_close_t"] + ma)
        until += [o["received_ts"] + rate_age for o in (cand.get("funding") or {}).get("observations") or []
                  if _int(o.get("received_ts"))]
    elif cand["type"] == FUNDING:
        until += [leg["received_ts"] + rate_age for leg in (cand.get("legs") or {}).values()
                  if _int(leg.get("received_ts"))]
    return min(until)


def _resolve(gates, max_state):
    fails = [g for g in gates if g["result"] == FAIL]
    if fails:
        return AVOID, fails[0]["step"]
    if any(g["result"] in (CAP, MISSING) for g in gates) or max_state != TRADE:
        return WATCH if max_state != AVOID else AVOID, None
    return TRADE, None


def _summarise(cand):
    g = cand["trace"]
    cand["blockers"] = [x["code"] for x in g if x["result"] == FAIL and x["code"]]
    cand["caps"] = [x["code"] for x in g if x["result"] == CAP and x["code"]]
    cand["missing_authorities"] = [x["code"] for x in g if x["result"] == MISSING and x["code"]]
    cand["warnings"] = sorted(set(cand.get("warnings") or []))
    if cand["state"] == TRADE:
        cand["explanation"] = {"why_trade": [{"step": x["step"], "rule": x["rule"]} for x in g if x["result"] == PASS]}
    elif cand["state"] == WATCH:
        cand["explanation"] = {"why_interesting": cand.get("positive_evidence") or [],
                               "why_not_trade": cand["caps"] + cand["missing_authorities"],
                               "missing_authority": cand["missing_authorities"],
                               "to_become_trade": [{"step": x["step"], "code": x["code"], "rule": x["rule"]}
                                                   for x in g if x["result"] in (CAP, MISSING)]}
    else:
        cand["explanation"] = {"rejection_step": cand["blocking_step"], "blockers": cand["blockers"]}
    return cand


def _decision_gate(cand):
    return _gate("DECISION_STATE", {"fail": cand_codes(cand, FAIL), "cap": cand_codes(cand, CAP),
                                    "missing": cand_codes(cand, MISSING)},
                 "AVOID if any gate FAILs; else WATCH if any gate is CAP or MISSING (or the type is capped); else TRADE",
                 INFO, None, cand["state"] + (f" (rejected at {cand['blocking_step']})" if cand["blocking_step"] else ""))


def cand_codes(cand, result):
    return [g["code"] for g in cand["trace"] if g["result"] == result and g["code"]]


# --------------------------------------------------------------------------- opportunity types
def _directional(asset, rec, sig, snap, policy, base):
    as_of = snap.get("as_of")
    sid, d = sig.get("strategy"), sig.get("direction")
    strat = (snap.get("strategies") or {}).get(sid)
    cid = f"{DIRECTIONAL}:{asset}:{sid}:{'LONG' if d == 1 else 'SHORT' if d == -1 else d}"
    gates = copy.deepcopy(base)
    tf = (strat or {}).get("tf")
    max_age = _v(policy, "signal", "max_age_s").get(tf) if isinstance(tf, str) else None
    bar, stop = sig.get("bar_close_t"), sig.get("stop_pct")
    age = as_of - bar if _int(bar) else None
    sinp = {"strategy": sid, "direction": d, "kind": sig.get("kind"), "bar_close_t": bar, "age_s": age,
            "stop_pct": stop, "timeframe": tf, "source": "quant.py strategy functions at the latest closed bar"}
    if d not in (1, -1) or isinstance(d, bool) or not (_num(stop) and 0 < stop < _v(policy, "signal", "max_stop_fraction")):
        gates.append(_gate("SIGNAL", sinp, "a direction and a stop distance in (0, max_stop_fraction)", FAIL,
                           "SIGNAL_INVALID"))
    elif max_age is None:
        gates.append(_gate("SIGNAL", sinp, "the strategy's timeframe must be known", FAIL, "SIGNAL_TIMEFRAME_UNKNOWN"))
    elif age is None or age < 0 or age > max_age:
        gates.append(_gate("SIGNAL", sinp, f"signal bar closed within max_age_s[{tf}] = {max_age}s", FAIL,
                           "SIGNAL_STALE"))
    else:
        gates.append(_gate("SIGNAL", sinp, f"current signal (bar closed within {max_age}s)", PASS))
    # The paper desk opens a paper trade for every new signal: a NEW signal's own just-opened paper position is taken
    # out of the book so the what-if is the marginal effect of this position; any other open position of the same
    # strategy, asset and direction means this is not a new opportunity.
    pf = snap.get("portfolio") if isinstance(snap.get("portfolio"), dict) else None
    own = sig.get("trade_id") if sig.get("kind") == "NEW" else None
    held = [p for p in (pf or {}).get("positions") or []
            if isinstance(p, dict) and p.get("asset") == asset and p.get("strategy") == sid and p.get("direction") == d
            and p.get("id") != own]
    if held:
        gates.append(_gate("SIGNAL", {"open_positions": sorted(str(p.get("id")) for p in held)},
                           "a new opportunity, not a position the book already holds", FAIL, "POSITION_ALREADY_OPEN"))
    if pf is not None and own is not None:
        pf = dict(pf, positions=[p for p in pf.get("positions") or [] if not (isinstance(p, dict)
                                                                                and p.get("id") == own)])
    sa = {k: _v(policy, "strategy_authority", k) for k in SECTION_KEYS["strategy_authority"]}
    ainp = {"strategy": sid, "deployment_state": (strat or {}).get("deployment_state"),
            "research_state": (strat or {}).get("research_state"), "source": "v8.quant-strategy-policy/1 (Phase 9)"}
    ds, rs = ainp["deployment_state"], ainp["research_state"]
    if strat is None or ds not in DEPLOYMENT or rs not in RESEARCH:
        gates.append(_gate("STRATEGY_AUTHORITY", ainp, "the strategy must be governed by the Phase 9 policy", FAIL,
                           "STRATEGY_UNGOVERNED"))
    elif ds in sa["avoid_deployment_states"]:
        gates.append(_gate("STRATEGY_AUTHORITY", ainp, "a disabled strategy cannot create a directional opportunity",
                           FAIL, "STRATEGY_DISABLED"))
    elif rs in sa["avoid_research_states"]:
        gates.append(_gate("STRATEGY_AUTHORITY", ainp, "research state must not be rejected or invalidated", FAIL,
                           "STRATEGY_RESEARCH_" + rs))
    elif ds in sa["trade_deployment_states"] and rs in sa["trade_research_states"]:
        gates.append(_gate("STRATEGY_AUTHORITY", ainp, "ACTIVE_REQUALIFIED / REQUALIFIED: sufficient for TRADE", PASS))
    else:
        gates.append(_gate("STRATEGY_AUTHORITY", ainp, "runtime continuity is not research authority", CAP,
                           "STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT"))
    gates.append(_execution_gate(rec, policy))
    fund = _directional_funding(asset, d if d in (1, -1) else 1, snap, policy)
    finp = {k: fund.get(k) for k in ("state", "rate_8h", "venue", "contract", "interval_h", "received_ts", "rule")}
    if fund["state"] in ("OBSERVED", "OBSERVED_ZERO"):
        gates.append(_gate("FUNDING", finp, "current venue-reported funding of a trade-DEX contract (most adverse)", PASS))
    else:
        gates.append(_gate("FUNDING", finp, "funding must be observed now; missing is never zero", MISSING,
                           "FUNDING_UNKNOWN"))
    # Phase 10 what-if against the whole open book
    price = (rec or {}).get("price")
    sizing = snap.get("sizing") or {}
    proposal = {"id": "PROPOSED:" + cid.split(":", 1)[1], "asset": asset, "strategy": sid, "direction": d,
                "mark": price if _num(price) and price > 0 else None,
                "stop": (price * (1 - d * stop) if _num(price) and price > 0 and _num(stop) and d in (1, -1) else None),
                "risk_fraction": sizing.get("risk_per_trade"), "entered": False, "actionability": PR.PROPOSED,
                "liquidity": {"state": ((rec or {}).get("execution_liquidity") or {}).get("state"),
                              "volume": ((rec or {}).get("execution_liquidity") or {}).get("observed_value")},
                "funding": {"state": fund["state"], "rate_8h": fund.get("rate_8h")},
                "hold_hours_remaining": (strat or {}).get("hold_h")}
    w = PR.what_if(pf, {"action": "ADD", "position": proposal}) if pf is not None else None
    before = (w or {}).get("before") or {}
    gates.append(_gate("PORTFOLIO_BEFORE", {"state": before.get("state"), "breached": before.get("breached"),
                                            "missing": len(before.get("missing_authorities") or []),
                                            "own_paper_position_excluded": own},
                       "Phase 10 evaluation of the whole open book (actionable and identity-blocked)", INFO))
    row = next((p for p in ((w or {}).get("after_result") or {}).get("positions") or []
                if p.get("id") == proposal["id"]), None)
    evaluated_equity = ((w or {}).get("after_result") or {}).get("equity")
    pinp = {"id": proposal["id"], "mark": proposal["mark"], "stop": proposal["stop"],
            "risk_fraction": proposal["risk_fraction"], "sizing_basis": sizing.get("basis"),
            "status": (row or {}).get("status"), "leverage": (row or {}).get("leverage"),
            "stop_risk": (row or {}).get("account_risk"), "expected_fees": (row or {}).get("expected_fees"),
            "expected_slippage": (row or {}).get("expected_slippage"),
            # Exact Phase 10 sizing, exposed for consumers without another risk calculation. The USD stop risk is
            # only a unit conversion of Phase 10's account-risk fraction at its evaluated equity.
            "equity": evaluated_equity, "quantity": (row or {}).get("quantity"),
            "notional": (row or {}).get("notional_usd"),
            "stop_risk_usd": ((row or {}).get("account_risk") * evaluated_equity
                              if _num((row or {}).get("account_risk")) and _num(evaluated_equity) else None)}
    if w is None:
        gates.append(_gate("PROPOSED_TRADE", pinp, "a Phase 10 portfolio input is required", MISSING,
                           "PORTFOLIO_INPUT_MISSING"))
    elif row is None or row.get("status") != "VALID":
        gates.append(_gate("PROPOSED_TRADE", pinp, "the proposal must be quantifiable (price, stop, size)", MISSING,
                           "PROPOSAL_UNQUANTIFIABLE"))
    elif row.get("expected_slippage") is None:
        gates.append(_gate("PROPOSED_TRADE", pinp, "required costs must be known (fees and slippage)", MISSING,
                           "COST_UNKNOWN"))
    else:
        gates.append(_gate("PROPOSED_TRADE", pinp, "quantified proposal with known fees and slippage", PASS))
    after = (w or {}).get("after") or {}
    ast = after.get("state")
    eff = _v(policy, "portfolio", "after_state_effects").get(ast, "WATCH_MISSING")
    code = {"APPROACHING_LIMITS": "PORTFOLIO_APPROACHING_LIMITS", "LIMIT_BREACHED": "PORTFOLIO_LIMIT_BREACHED",
            "UNEVALUABLE": "PORTFOLIO_UNEVALUABLE"}.get(ast, "PORTFOLIO_UNEVALUABLE")
    gates.append(_effect_gate("PORTFOLIO_AFTER", {"state": ast, "effect": (w or {}).get("effect"),
                                                  "missing": (after.get("missing_authorities") or [])[:10]},
                              "Phase 10 after-state effect: " + json.dumps(_v(policy, "portfolio", "after_state_effects"),
                                                                          sort_keys=True), eff, code))
    gates.append(_gate("RISK_LIMITS", {"breached": after.get("breached"), "approaching": after.get("approaching"),
                                       "limit_changes": (w or {}).get("limit_changes")},
                       "Phase 10 limits (v8.portfolio-risk-policy/1, unchanged)", INFO))
    metrics = after.get("metrics") or {}
    cand = {"id": cid, "type": DIRECTIONAL, "asset": asset, "strategy": sid, "direction": d,
            "positive_evidence": [{"type": "CURRENT_STRATEGY_SIGNAL", "strategy": sid, "direction": d,
                                   "kind": sig.get("kind")}],
            "funding": fund, "proposal": pinp,
            "portfolio": {"before": before, "after": after, "effect": (w or {}).get("effect"),
                          "delta": (w or {}).get("delta"), "explanation": (w or {}).get("explanation")},
            "ranking_inputs": {"signal_kind_order": 0 if sig.get("kind") == "NEW" else 1, "signal_age_s": age,
                               "slippage_rate": ((row or {}).get("liquidity") or {}).get("slippage_rate"),
                               "after_executable_risk": metrics.get("max_executable_risk"),
                               "asset": asset, "strategy": sid, "direction": d},
            "trace": gates}
    return cand


def _emerging(asset, rec, base, directional, policy):
    evidence = []
    for f in rec.get("anomaly_flags") or []:
        t = _v(policy, "emerging", "evidence_from_flags").get(f)
        if t:
            ev = {"type": t, "source": "v8.discovery/1 flag " + f}
            if f == "NEW_LISTING":
                ev.update(first_seen=rec.get("first_seen"), listing_age=rec.get("listing_age"),
                          note="first seen by this desk after tracking started; not a listing date")
            evidence.append(ev)
    for c in directional:
        if c["state"] == WATCH:
            evidence.append({"type": "CURRENT_STRATEGY_SIGNAL", "strategy": c["strategy"], "direction": c["direction"],
                             "candidate": c["id"], "source": "a WATCH directional decision of an enabled strategy"})
    primary = [e for e in evidence if e["type"] in _v(policy, "emerging", "primary_evidence")]
    if not primary:
        return None
    gates = copy.deepcopy(base)
    gates.append(_gate("SIGNAL", {"evidence": sorted({e["type"] for e in evidence})},
                       "at least one primary governed observation", PASS))
    gates.append(_gate("STRATEGY_AUTHORITY", {"strategy": None},
                       "an observation is not a governed strategy signal: at most WATCH", CAP,
                       "NO_GOVERNED_STRATEGY_AUTHORITY"))
    gates.append(_execution_gate(rec, policy))
    for step in ("FUNDING", "PORTFOLIO_BEFORE", "PROPOSED_TRADE", "PORTFOLIO_AFTER", "RISK_LIMITS"):
        gates.append(_gate(step, None, "an observation proposes no position", NA))
    warnings = [f for f in rec.get("anomaly_flags") or [] if f in _v(policy, "emerging", "warning_flags")]
    outstanding = sum(1 for g in gates if g["result"] in (CAP, MISSING))
    return {"id": f"{EMERGING}:{asset}", "type": EMERGING, "asset": asset, "positive_evidence": evidence,
            "warnings": warnings,
            "ranking_inputs": {"primary_evidence_count": len({e["type"] for e in primary}),
                               "evidence_count": len({e["type"] for e in evidence}),
                               "outstanding_blockers": outstanding, "asset": asset},
            "trace": gates}


def _funding_spread(asset, rec, base, snap, policy):
    fresh = _funding_obs(asset, snap, policy)
    # Pair eligibility: a leg is an active, admitted trade-DEX perp with fresh venue-reported funding AND a HEALTHY
    # contract. An unhealthy contract is never a candidate leg (it cannot be chosen and then merely flagged), so a
    # degraded venue with an extreme rate cannot hijack the pair. Fewer than two healthy venues: no spread at all
    # (never a zero or "no spread" finding, never stale funding, a default rate or journal funding in its place).
    obs = [o for o in fresh if o["health"] == HEALTHY]
    if len({o["venue"] for o in obs}) < 2:
        return None
    long_ = min(obs, key=lambda o: (o["rate_8h"], o["venue"] or ""))
    short = max([o for o in obs if o["venue"] != long_["venue"]], key=lambda o: (o["rate_8h"], o["venue"] or ""))
    spread = short["rate_8h"] - long_["rate_8h"]
    gates = copy.deepcopy(base)
    legs = {"long": {k: long_[k] for k in ("venue", "contract", "rate_8h", "interval_h", "received_ts", "volume", "price",
                                           "health")},
            "short": {k: short[k] for k in ("venue", "contract", "rate_8h", "interval_h", "received_ts", "volume", "price",
                                            "health")}}
    gates.append(_gate("SIGNAL", {"spread_8h": spread, "legs": [long_["venue"], short["venue"]],
                                  "eligible_venues": sorted({o["venue"] for o in obs}),
                                  "unhealthy_excluded": sorted({o["venue"] for o in fresh if o["health"] != HEALTHY})},
                       "a positive funding differential between two healthy trade-DEX venues",
                       PASS if spread > 0 else FAIL, None if spread > 0 else "NO_FUNDING_SPREAD"))
    gates.append(_gate("STRATEGY_AUTHORITY", None, "no research authority for funding-spread persistence: at most WATCH",
                       CAP, "FUNDING_SPREAD_RESEARCH_AUTHORITY_MISSING"))
    thr = ((rec or {}).get("execution_liquidity") or {}).get("threshold")
    prpol = PR.load_policy()
    fee = prpol["costs"]["fee_taker"]["value"]
    leg_ok, slips = [], {}
    for side, o in (("long", long_), ("short", short)):
        vol = o["volume"]
        if not _num(vol) or not _num(thr):
            leg_ok.append((side, MISSING, "LEG_LIQUIDITY_UNKNOWN"))
        elif vol < thr:
            leg_ok.append((side, FAIL, "LEG_LIQUIDITY_BELOW_GATE"))
        else:
            leg_ok.append((side, PASS, None))
        slips[side] = PR.slippage_tier(vol, prpol) if _num(vol) else None
    worst = FAIL if any(r == FAIL for _, r, _ in leg_ok) else MISSING if any(r == MISSING for _, r, _ in leg_ok) else PASS
    gates.append(_gate("EXECUTION_LIQUIDITY", {"legs": leg_ok, "threshold": thr},
                       "both legs' own venue volume >= the execution threshold (both legs are healthy contracts)", worst,
                       next((c for _, r, c in leg_ok if r == worst and c), None)))
    costs = (2 * (fee + slips["long"]) + 2 * (fee + slips["short"])
             if slips["long"] is not None and slips["short"] is not None else None)
    hours = _v(policy, "funding_spread", "holding_hours")
    carry = spread * hours / 8.0
    net = carry - costs if costs is not None else None
    gates.append(_gate("FUNDING", {"long": legs["long"], "short": legs["short"], "carry": carry, "costs": costs,
                                   "net_carry": net, "holding_hours": hours},
                       "both legs observed now; carry over holding_hours minus four taker fills and slippage > min",
                       (MISSING if net is None else PASS if net > _v(policy, "funding_spread", "min_net_carry") else FAIL),
                       (None if net is not None and net > _v(policy, "funding_spread", "min_net_carry")
                        else "COST_UNKNOWN" if net is None else "CARRY_NOT_POSITIVE_AFTER_COSTS")))
    pl, ps = long_["price"], short["price"]
    basis = abs(ps - pl) / ((ps + pl) / 2) if _num(pl) and _num(ps) and pl > 0 and ps > 0 else None
    gates.append(_gate("PROPOSED_TRADE", {"basis_abs": basis, "max_basis": _v(policy, "funding_spread", "max_basis")},
                       "the legs' prices per coin within max_basis", (MISSING if basis is None else
                                                                      PASS if basis <= _v(policy, "funding_spread",
                                                                                          "max_basis") else FAIL),
                       (None if basis is not None and basis <= _v(policy, "funding_spread", "max_basis")
                        else "BASIS_UNKNOWN" if basis is None else "BASIS_TOO_WIDE")))
    gates.append(_gate("PORTFOLIO_BEFORE", None, "recorded at portfolio level", INFO))
    gates.append(_gate("PORTFOLIO_AFTER", None, "Phase 10 has no hedge model (its positions need stops)", MISSING,
                       "PORTFOLIO_HEDGE_MODEL_UNAVAILABLE"))
    gates.append(_gate("RISK_LIMITS", None, "not evaluable for a hedged pair", NA))
    order = ["DISCOVERY", "IDENTITY", "ECONOMIC_EXPOSURE", "VENUE_HEALTH", "SIGNAL", "STRATEGY_AUTHORITY",
             "EXECUTION_LIQUIDITY", "FUNDING", "PORTFOLIO_BEFORE", "PROPOSED_TRADE", "PORTFOLIO_AFTER", "RISK_LIMITS"]
    gates.sort(key=lambda g: order.index(g["step"]))
    return {"id": f"{FUNDING}:{asset}", "type": FUNDING, "label": "FUNDING_SPREAD_OPPORTUNITY", "asset": asset,
            "legs": legs, "spread_8h": spread, "carry": carry, "costs": costs, "net_carry": net, "basis_abs": basis,
            "positive_evidence": [{"type": "FUNDING_SPREAD", "spread_8h": spread, "net_carry": net}],
            "warnings": ["NOT_RISK_FREE: funding rates change; the carry is a projection at current rates"],
            "ranking_inputs": {"net_carry": net, "basis_abs": basis, "asset": asset}, "trace": gates}


def _finish(cand, policy):
    mx = _v(policy, "states", "max_state_by_type")[cand["type"]]
    cand["state"], cand["blocking_step"] = _resolve(cand["trace"], mx)
    cand["trace"].append(_decision_gate(cand))
    return _summarise(cand)


def _evaluate_asset(asset, rec, snap, policy):
    """Every opportunity of one asset and its asset-level decision. The single evaluation path of build() and
    evaluate_asset()."""
    base = _asset_gates(rec, snap, policy)
    directional = [_finish(_directional(asset, rec, s, snap, policy, base), policy)
                   for s in sorted((snap.get("signals") or {}).get(asset) or [],
                                   key=lambda s: (str(s.get("strategy")), str(s.get("direction"))))]
    opps = list(directional)
    if rec is not None:
        e = _emerging(asset, rec, base, directional, policy)
        if e:
            opps.append(_finish(e, policy))
        f = _funding_spread(asset, rec, base, snap, policy)
        if f:
            opps.append(_finish(f, policy))
    for c in opps:
        c["valid_until"] = _valid_until(c, snap, policy)
    opps.sort(key=lambda c: c["id"])
    best = min((c["state"] for c in opps), key=lambda s: STATE_ORDER[s]) if opps else AVOID
    asset_blockers = [g["code"] for g in base if g["result"] in (FAIL, MISSING) and g["code"]]
    el = ((rec or {}).get("execution_liquidity") or {})
    record = {"asset": asset, "state": best, "opportunities": [c["id"] for c in opps],
              "identity": (rec or {}).get("identity"), "execution_liquidity": el.get("state"),
              "execution_passes": el.get("passes"), "data_quality": (rec or {}).get("data_quality"),
              "lane": (rec or {}).get("priority_lane"),
              "identity_blocked": (rec or {}).get("identity") != _v(policy, "identity", "trade_identity"),
              "execution_blocked": el.get("passes") is not True,
              "blockers": asset_blockers + ([] if opps else ["NO_CURRENT_OPPORTUNITY"]),
              "trace": base}
    return record, opps


# --------------------------------------------------------------------------- ranking and sections
def _key(cand, rules, section):
    out = []
    for field, order in rules:
        v = cand["ranking_inputs"].get(field)
        if v is None:
            out.append((1, 0))
        elif RANK_FIELDS[section][field] == "str":
            out.append((0, str(v)))
        else:
            out.append((0, -v if order == "desc" else v))
    return tuple(out) + ((0, cand["id"]),)


def explain_order(a, b, rules, section):
    """Why candidate a ranks above b: the first ranking rule whose values differ."""
    for field, order in rules:
        va, vb = a["ranking_inputs"].get(field), b["ranking_inputs"].get(field)
        if va != vb:
            return {"rule": [field, order], "above": {"id": a["id"], field: va}, "below": {"id": b["id"], field: vb}}
    return {"rule": ["id", "asc"], "above": a["id"], "below": b["id"], "note": "every ranking input is equal"}


def _sections(cands, policy):
    out, placed = {}, {}
    for s in SECTIONS:
        sv, rules = _v(policy, "sections", s), _v(policy, "ranking", s)
        excl = {placed_c["asset"] for name in sv.get("exclude_assets_in") or [] for placed_c in out.get(name, {}).get(
            "_selected", [])}
        typed = [c for c in cands if c["type"] in sv["types"]]
        eligible = sorted([c for c in typed if c["state"] in sv["states"] and c["asset"] not in excl],
                          key=lambda c: _key(c, rules, s))
        selected = eligible[:sv["max"]]
        beyond = eligible[sv["max"]:]
        gated = sorted([c for c in typed if c["state"] not in sv["states"]], key=lambda c: _key(c, rules, s))
        for i, c in enumerate(selected):
            placed[c["id"]] = (s, i + 1, "SELECTED")
        for i, c in enumerate(beyond):
            placed.setdefault(c["id"], (s, sv["max"] + i + 1, "EXCLUDED_BY_SECTION_MAXIMUM"))
        for c in typed:
            if c["asset"] in excl and c["state"] in sv["states"]:
                placed.setdefault(c["id"], (s, None, "EXCLUDED_ASSET_ALREADY_IN_" + "_".join(sv["exclude_assets_in"])))
        trace = {"max": sv["max"], "eligible_states": sv["states"], "types": sv["types"], "ranking_rules": rules,
                 "eligible": len(eligible), "selected": [c["id"] for c in selected],
                 "fewer_than_max": len(selected) < sv["max"],
                 "why_fewer": (None if len(selected) >= sv["max"] else
                               f"only {len(eligible)} candidate(s) of type {sv['types']} are in state {sv['states']}; "
                               "nothing else is promoted to fill the section"),
                 "order": [explain_order(selected[i], selected[i + 1], rules, s) for i in range(len(selected) - 1)],
                 "cutoff": (explain_order(selected[-1], beyond[0], rules, s) if selected and beyond else None),
                 "excluded_after_cutoff": [c["id"] for c in beyond[:5]],
                 "removed_by_gate": [{"id": c["id"], "state": c["state"], "step": c["blocking_step"],
                                      "codes": c["blockers"] + c["caps"] + c["missing_authorities"]}
                                     for c in gated[:5]]}
        out[s] = {"items": [{"rank": i + 1, "id": c["id"], "asset": c["asset"], "state": c["state"],
                             "ranking_inputs": c["ranking_inputs"]} for i, c in enumerate(selected)],
                  "count": len(selected), "selection_trace": trace, "_selected": selected}
    for s in SECTIONS:
        out[s].pop("_selected")
    return out, placed


def _placement(cand, placed, policy):
    p = placed.get(cand["id"])
    sec_for_type = [s for s in SECTIONS if cand["type"] in _v(policy, "sections", s)["types"]]
    section = sec_for_type[0] if sec_for_type else None
    if p and p[2] == "SELECTED":
        res = {"section": p[0], "rank": p[1], "reason": "SELECTED"}
    elif p:
        res = {"section": None, "rank": p[1], "reason": p[2], "candidate_for": p[0]}
    else:
        res = {"section": None, "rank": None, "candidate_for": section,
               "reason": (f"NOT_ELIGIBLE: state {cand['state']}"
                          + (f" (rejected at {cand['blocking_step']})" if cand["blocking_step"] else ""))}
    rules = _v(policy, "ranking", section) if section else []
    res["trace"] = [
        _gate("RANKING", cand["ranking_inputs"], "ranking happens after the state, inside eligible states only: "
              + json.dumps(rules), INFO, None, f"position {res['rank']}" if res["rank"] else "not ranked"),
        _gate("SECTION_PLACEMENT", {"candidate_for": section}, "up to the section maximum, never a minimum", INFO, None,
              res["reason"] + (f" in {res['section']} at #{res['rank']}" if res["section"] else ""))]
    return res


# --------------------------------------------------------------------------- change explanation
def _index(cands):
    return {c["id"]: {"state": c["state"], "rank": c["placement"]["rank"] if c["placement"]["section"] else None,
                      "section": c["placement"]["section"], "blockers": c["blockers"] + c["caps"] + c["missing_authorities"],
                      "ranking_inputs": c["ranking_inputs"]} for c in cands}


def _changes(index, previous, info):
    if not isinstance(previous, dict) or previous.get("schema") != VERSION or not isinstance(previous.get("index"), dict):
        return {"previous_available": False, "reason": "NO_PREVIOUS_PHASE11_AUTHORITY",
                "note": "no earlier governed Phase 11 decision snapshot: no past state or rank is inferred"}
    prev = previous["index"]
    out = []
    for cid in sorted(set(index) | set(prev)):
        a, b = prev.get(cid), index.get(cid)
        if a is None:
            out.append({"id": cid, "change": "NEW_CANDIDATE", "current_state": b["state"], "current_rank": b["rank"]})
            continue
        if b is None:
            out.append({"id": cid, "change": "NO_LONGER_A_CANDIDATE", "previous_state": a["state"],
                        "previous_rank": a["rank"]})
            continue
        if a["state"] == b["state"] and a["rank"] == b["rank"] and a["section"] == b["section"]:
            continue
        rk = sorted(k for k in set(a["ranking_inputs"]) | set(b["ranking_inputs"])
                    if a["ranking_inputs"].get(k) != b["ranking_inputs"].get(k))
        out.append({"id": cid, "previous_state": a["state"], "current_state": b["state"], "previous_rank": a["rank"],
                    "current_rank": b["rank"], "previous_section": a["section"], "current_section": b["section"],
                    "state_change_reason": ({"added": sorted(set(b["blockers"]) - set(a["blockers"])),
                                             "removed": sorted(set(a["blockers"]) - set(b["blockers"]))}
                                            if a["state"] != b["state"] else None),
                    "rank_change_reason": ({"ranking_inputs_changed": rk} if a["rank"] != b["rank"] else None)})
    return {"previous_available": True, "previous_as_of": previous.get("as_of"),
            "previous_policy_hash": previous.get("policy_hash"),
            "policy_changed": previous.get("policy_hash") != info["policy_hash"], "changes": out}


# --------------------------------------------------------------------------- public API
def _validate_inputs(snap, policy):
    """Refuse an incomplete public snapshot before any authoritative decision can be emitted.

    These are the production adapter's existing knowledge authorities, not optional gate defaults. A correctly
    shaped but explicitly degraded discovery still follows the existing WATCH gate; an absent authority has no
    document authority at all. Both public APIs use this same boundary and the adapter publishes failure as a gap.
    """
    def need(ok, field):
        if not ok:
            raise ValueError("DECISION_INPUT_INVALID: " + field)

    need(_int(snap.get("as_of")) and snap["as_of"] >= 0, "as_of")
    times = snap.get("inputs_as_of")
    need(isinstance(times, dict), "inputs_as_of")
    for name in REQUIRED_INPUT_TIMES:
        need(name in times and _int(times[name]) and times[name] >= 0, "inputs_as_of." + name)
    stale = _freshness(snap, policy)
    need(not stale, "inputs_as_of freshness: " + ", ".join(str(k) for k in stale))
    discovery = snap.get("discovery")
    need(isinstance(discovery, dict), "discovery")
    prov = discovery.get("provenance")
    need(isinstance(prov, dict), "discovery.provenance")
    need(prov.get("schema") == "v8.discovery/1", "discovery.provenance.schema")
    for flag in ("fallback_universe", "available_venue_discovery_qualified"):
        need(isinstance(prov.get(flag), bool), "discovery.provenance." + flag)
    generated = prov.get("generated_at")
    need(_int(generated) and generated >= 0 and 0 <= snap["as_of"] - generated <= _v(policy, "freshness", "max_input_age_s"),
         "discovery.provenance.generated_at")
    need(prov.get("identity_version") == "v8.identity/4", "discovery.provenance.identity_version")
    need(prov.get("coverage_state") in ("FULL", "DEGRADED", "FALLBACK"), "discovery.provenance.coverage_state")
    failed = prov.get("venues_failed_names")
    need(isinstance(failed, list) and all(isinstance(v, str) and bool(v) for v in failed),
         "discovery.provenance.venues_failed_names")


def _context(snapshot, policy):
    if policy is None:
        policy = load_policy()
    else:
        validate_policy(policy)
    snap = snapshot if isinstance(snapshot, dict) else {}
    _validate_inputs(snap, policy)
    recs = {r["asset"]: r for r in (snap.get("discovery") or {}).get("assets") or [] if isinstance(r, dict)
            and isinstance(r.get("asset"), str)}
    return policy, snap, recs


def evaluate_asset(snapshot, asset, policy=None):
    """One asset with the same rules, inputs and code path as build(): its asset record and its opportunities (state,
    gates, blockers, evidence, ranking inputs, trace). Rank and section are market-relative and come only from build()."""
    policy, snap, recs = _context(snapshot, policy)
    record, opps = _evaluate_asset(asset, recs.get(asset), snap, policy)
    return _clean({"schema": VERSION, "policy_hash": policy_hash(policy), "implementation_hash": implementation_hash(),
                   "as_of": snap["as_of"], "valid_until": _horizon(snap, policy), "asset": record,
                   "opportunities": opps})


def authority(snap, policy):
    a = dict(snap.get("authorities") or {})
    prp = PR.load_policy()
    a.update(decision_schema=VERSION, decision_policy_schema=POLICY_VERSION, decision_policy_hash=policy_hash(policy),
             decision_policy_review_status=policy["review_status"], decision_implementation_hash=implementation_hash(),
             portfolio_schema=PR.VERSION, portfolio_policy_hash=PR.policy_hash(prp),
             portfolio_implementation_hash=hashlib.sha256(Path(PR.__file__).read_bytes()).hexdigest())
    a["authority_hash"] = digest(a)
    return a


def build(snapshot, policy=None):
    """The whole decision document: one record per discovered asset, one per opportunity, the three sections, the
    portfolio, the market summary, the selection traces, the change explanation and the authority binding."""
    policy, snap, recs = _context(snapshot, policy)
    names = sorted(set(recs) | set((snap.get("signals") or {})))
    assets, cands = [], []
    for t in names:
        record, opps = _evaluate_asset(t, recs.get(t), snap, policy)
        assets.append(record)
        cands.extend(opps)
    cands.sort(key=lambda c: c["id"])
    sections, placed = _sections(cands, policy)
    for c in cands:
        c["placement"] = _placement(c, placed, policy)
    pf = snap.get("portfolio") if isinstance(snap.get("portfolio"), dict) else None
    book = PR.evaluate(pf) if pf is not None else None
    portfolio = {"phase10": PR.audit_summary(book) if book else PR.audit_summary(None),
                 "binding": {"phase10_audit_state": snap.get("phase10_state"),
                             "engine_book_state": (book or {}).get("state"),
                             "consistent": (book or {}).get("state") == snap.get("phase10_state"),
                             "portfolio_input_hash": digest(pf) if pf is not None else None,
                             "book": (pf or {}).get("book")}}
    info = {"policy_hash": policy_hash(policy)}
    index = _index(cands)
    prov = (snap.get("discovery") or {}).get("provenance") or {}
    missing = {}
    for c in cands:
        for m in c["missing_authorities"]:
            missing[m] = missing.get(m, 0) + 1
    states = {s: sum(1 for c in cands if c["state"] == s) for s in STATES}
    summary = {"discovered_assets": len(recs), "evaluated_assets": len(assets), "opportunities": len(cands),
               "opportunity_states": states,
               "opportunity_states_by_type": {t: {s: sum(1 for c in cands if c["type"] == t and c["state"] == s)
                                                  for s in STATES} for t in TYPES},
               "asset_states": {s: sum(1 for a in assets if a["state"] == s) for s in STATES},
               "best_trades_now": sections["best_trades_now"]["count"],
               "emerging_opportunities": sections["emerging_opportunities"]["count"],
               "funding_opportunities": sections["funding_opportunities"]["count"],
               "identity_blocked_assets": sum(1 for a in assets if a["identity_blocked"]),
               "execution_blocked_assets": sum(1 for a in assets if a["execution_blocked"]),
               "current_strategy_signals": sum(len(v or []) for v in (snap.get("signals") or {}).values()),
               "portfolio_state": portfolio["phase10"].get("state"),
               "major_missing_authorities": dict(sorted(missing.items(), key=lambda kv: (-kv[1], kv[0]))[:10]),
               "venue_degradation": {"venues_failed": prov.get("venues_failed_names") or [],
                                     "fallback_universe": prov.get("fallback_universe"),
                                     "coverage_state": prov.get("coverage_state")},
               "zero_trade": states[TRADE] == 0}
    doc = {"schema": VERSION, "policy_schema": POLICY_VERSION, "policy_hash": info["policy_hash"],
           "implementation_hash": implementation_hash(), "as_of": snap["as_of"],
           "valid_until": _horizon(snap, policy),
           "authority": authority(snap, policy), "inputs": snap.get("input_provenance"),
           "best_trades_now": sections["best_trades_now"], "emerging_opportunities": sections["emerging_opportunities"],
           "funding_opportunities": sections["funding_opportunities"], "portfolio": portfolio,
           "market_summary": summary, "assets": assets, "candidates": cands, "index": index,
           "changes": _changes(index, snap.get("previous"), info),
           "vocabulary": {"states": {TRADE: "the governed evidence is sufficient to present it as trade-ready for "
                                            "discretionary human consideration",
                                     WATCH: "a credible current reason to monitor, without the authority or readiness "
                                            "to call it trade-ready",
                                     AVOID: "do not take this opportunity now under the governed rules (a current "
                                            "decision, not a permanent verdict on the asset)"},
                          "gate_results": EFFECT_TEXT, "trace_steps": list(TRACE_STEPS) + list(PLACEMENT_STEPS),
                          "valid_until": "after this time the decision's inputs exceed their policy ages (freshness, "
                                         "signal age, funding age): a consumer must treat it as stale and fail closed",
                          "execution": "NONE: nothing here places, sizes for real money or ranks a trade for execution"}}
    return _clean(doc)


def summary(doc):
    """The audit snapshot's view of a decision document."""
    if not isinstance(doc, dict) or doc.get("schema") != VERSION:
        return {"schema": VERSION, "status": "UNAVAILABLE"}
    top = {s: [i["id"] for i in doc[s]["items"]] for s in SECTIONS}
    blockers = {}
    for c in doc["candidates"]:
        for b in c["blockers"] + c["caps"]:
            blockers[b] = blockers.get(b, 0) + 1
    return {"schema": VERSION, "status": "OK", "policy_schema": doc["policy_schema"], "policy_hash": doc["policy_hash"],
            "implementation_hash": doc["implementation_hash"], "authority_hash": doc["authority"]["authority_hash"],
            "as_of": doc["as_of"], "valid_until": doc.get("valid_until"), "market_summary": doc["market_summary"],
            "section_counts": {s: doc[s]["count"] for s in SECTIONS}, "top_selections": top,
            "blockers": dict(sorted(blockers.items(), key=lambda kv: (-kv[1], kv[0]))[:20]),
            "degraded_authorities": doc["market_summary"]["major_missing_authorities"],
            "trace_available": all(len(c["trace"]) >= len(TRACE_STEPS) for c in doc["candidates"]),
            "portfolio_binding": doc["portfolio"]["binding"], "changes_previous_available":
                doc["changes"]["previous_available"]}
