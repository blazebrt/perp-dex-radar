"""Predeclared Phase 9 gate. Pure evidence adjudication; no deployment writer.

GATE is the single numerical authority of the gate: every threshold adjudicate() applies is read from a named GATE
field at call time (CHECKS names the evidence key, its GATE field and its comparison); no threshold is a literal.

Which sides of a strategy must carry evidence is derived from the strategy definition being adjudicated - its
canonical expanded parameters (`params["sides"]`: "both", "long" or "short") - never from a self-reported evidence
flag, the strategy ID or runtime metadata. A redundant `both_sides` evidence flag, when present, must agree with the
definition; a disagreement fails closed."""
from __future__ import annotations

import math

VERSION = "v8.strategy-research/1"
GATE = {
    "pit_calendar_days": 180, "qualified_closed_trades": 100,
    "mean_R": 0, "mean_R_lower_95": 0, "matched_edge": 0, "matched_lower_95": 0,
    "full_matched_fraction": 0.90, "controls_per_signal": 50,
    "dsr_probability": 0.95, "pbo": 0.20, "spa_p": 0.05, "white_rc_p": 0.10,
    "by_q": 0.05, "oos_mean_R": 0, "stress_1_5_mean_R": 0,
    "max_top1_positive_fraction": 0.20, "max_top5_positive_fraction": 0.50,
    "max_top10_positive_fraction": 0.75, "max_month_positive_fraction": 0.50,
    "leave_one_asset_out_min_mean_R": 0,
    "minimum_side_trades": 20, "side_mean_floor_R": -0.05, "side_upper_95_max_R": 0,
    "oos_fraction": 1 / 3, "bootstrap_replications": 5000, "block_days": 7,
    "cscv_segments": 16, "cscv_min_segment_days": 14,
}
# evidence key, GATE field, comparison, failing kind: INSUFFICIENT (more data could pass) or FAILED (a verdict)
INSUFFICIENT, FAILED = "INSUFFICIENT", "FAILED"
CHECKS = (
    ("pit_calendar_days", "pit_calendar_days", ">=", INSUFFICIENT),
    ("qualified_closed_trades", "qualified_closed_trades", ">=", INSUFFICIENT),
    ("mean_R", "mean_R", ">", FAILED),
    ("mean_R_lower_95", "mean_R_lower_95", ">", FAILED),
    ("matched_edge", "matched_edge", ">", FAILED),
    ("matched_lower_95", "matched_lower_95", ">", FAILED),
    ("full_matched_fraction", "full_matched_fraction", ">=", INSUFFICIENT),
    ("controls_per_signal", "controls_per_signal", ">=", INSUFFICIENT),
    ("dsr_probability", "dsr_probability", ">=", FAILED),
    ("pbo", "pbo", "<=", FAILED),
    ("spa_p", "spa_p", "<=", FAILED),
    ("white_rc_p", "white_rc_p", "<=", FAILED),
    ("by_q", "by_q", "<=", FAILED),
    ("oos_mean_R", "oos_mean_R", ">", FAILED),
    ("stress_1_5_mean_R", "stress_1_5_mean_R", ">", FAILED),
    ("top1_positive_fraction", "max_top1_positive_fraction", "<=", FAILED),
    ("top5_positive_fraction", "max_top5_positive_fraction", "<=", FAILED),
    ("top10_positive_fraction", "max_top10_positive_fraction", "<=", FAILED),
    ("month_positive_fraction", "max_month_positive_fraction", "<=", FAILED),
    ("leave_one_asset_out_min_mean_R", "leave_one_asset_out_min_mean_R", ">", FAILED),
)
REQUIRED_TRUE = ("trial_census_complete", "trial_return_universe_complete", "pit_integrity_ok",
                 "prospective_registration_valid", "full_feature_authority", "robustness_slices_complete")
SIDE_VALUES = {"both": ("long", "short"), "long": ("long",), "short": ("short",)}


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _passes(value, threshold, op):
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    raise ValueError("unknown gate comparison " + repr(op))


def required_sides(definition):
    """The sides whose evidence the gate requires, from the adjudicated definition's canonical parameters; None
    when the definition does not state them (fail closed)."""
    params = definition.get("params") if isinstance(definition, dict) else None
    sides = params.get("sides") if isinstance(params, dict) else None
    return SIDE_VALUES.get(sides) if isinstance(sides, str) else None


def adjudicate(e, definition):
    """Unavailable/incomplete evidence yields INSUFFICIENT, never an optimistic pass.

    `definition` is the exact strategy definition whose research identity is bound (a catalog row: implementation and
    canonical expanded params); the side requirements come from it. REJECTED requires a fully available gate; a
    missing method cannot be bypassed by another successful statistic. No strategy identifier participates in a
    verdict."""
    e = e if isinstance(e, dict) else {}
    missing, failed = [], []
    for key in REQUIRED_TRUE:
        if e.get(key) is not True:
            missing.append(key.upper())
    for key, gate_key, op, kind in CHECKS:
        value = e.get(key)
        if not _number(value):
            missing.append(key.upper() + "_UNAVAILABLE")
        elif not _passes(value, GATE[gate_key], op):
            (missing if kind == INSUFFICIENT else failed).append(key.upper() + ("_INSUFFICIENT" if kind == INSUFFICIENT
                                                                                else "_FAILED"))
    sides = required_sides(definition)
    if sides is None:
        missing.append("STRATEGY_SIDE_DEFINITION_UNAVAILABLE")
    else:
        if "both_sides" in e and e["both_sides"] is not (sides == SIDE_VALUES["both"]):
            missing.append("BOTH_SIDES_FLAG_DISAGREES_WITH_DEFINITION")
        rows = e.get("sides") if isinstance(e.get("sides"), dict) else {}
        for side in sides:
            row = rows.get(side) if isinstance(rows.get(side), dict) else {}
            n = row.get("n")
            if not _number(n) or n < GATE["minimum_side_trades"]:
                missing.append(side.upper() + "_SAMPLE_INSUFFICIENT")
            elif not _number(row.get("mean_R")) or not _number(row.get("upper_95")):
                missing.append(side.upper() + "_INFERENCE_UNAVAILABLE")
            elif row["mean_R"] < GATE["side_mean_floor_R"] and row["upper_95"] < GATE["side_upper_95_max_R"]:
                failed.append(side.upper() + "_MATERIAL_NEGATIVE_EDGE")
    state = "INSUFFICIENT_EVIDENCE" if missing else "REJECTED" if failed else "REQUALIFIED"
    return {"research_state": state, "status": state, "reasons": sorted(set(missing + failed)),
            "blocking_reasons": sorted(set(missing + failed)), "gate": dict(GATE)}
