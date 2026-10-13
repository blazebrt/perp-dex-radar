"""Predeclared Phase 9 gate. Pure evidence adjudication; no deployment writer."""
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
    "minimum_side_trades": 20, "side_mean_floor_R": -0.05,
    "oos_fraction": 1 / 3, "bootstrap_replications": 5000, "block_days": 7,
    "cscv_segments": 16, "cscv_min_segment_days": 14,
}


def adjudicate(e):
    """Unavailable/incomplete evidence yields INSUFFICIENT, never an optimistic pass.

    REJECTED requires a fully available gate; a missing method cannot be bypassed
    by another successful statistic. No strategy identifier participates in a verdict.
    """
    missing, failed = [], []
    for key in ("trial_census_complete", "trial_return_universe_complete", "pit_integrity_ok",
                "prospective_registration_valid", "full_feature_authority", "robustness_slices_complete"):
        if e.get(key) is not True:
            missing.append(key.upper())
    checks = {
        "pit_calendar_days": (GATE["pit_calendar_days"], ">="),
        "qualified_closed_trades": (GATE["qualified_closed_trades"], ">="),
        "mean_R": (0, ">"), "mean_R_lower_95": (0, ">"),
        "matched_edge": (0, ">"), "matched_lower_95": (0, ">"),
        "full_matched_fraction": (.90, ">="), "controls_per_signal": (50, ">="), "dsr_probability": (.95, ">="),
        "pbo": (.20, "<="), "spa_p": (.05, "<="), "white_rc_p": (.10, "<="),
        "by_q": (.05, "<="), "oos_mean_R": (0, ">"), "stress_1_5_mean_R": (0, ">"),
        "top1_positive_fraction": (.20, "<="), "top5_positive_fraction": (.50, "<="),
        "top10_positive_fraction": (.75, "<="), "month_positive_fraction": (.50, "<="),
        "leave_one_asset_out_min_mean_R": (0, ">"),
    }
    for key, (threshold, op) in checks.items():
        value = e.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            missing.append(key.upper() + "_UNAVAILABLE")
            continue
        ok = value >= threshold if op == ">=" else value <= threshold if op == "<=" else value > threshold
        if not ok:
            if key in ("pit_calendar_days", "qualified_closed_trades", "full_matched_fraction", "controls_per_signal"):
                missing.append(key.upper() + "_INSUFFICIENT")
            else:
                failed.append(key.upper() + "_FAILED")
    if e.get("both_sides") is True:
        for side in ("long", "short"):
            row = e.get("sides", {}).get(side, {})
            if row.get("n", 0) < GATE["minimum_side_trades"]:
                missing.append(side.upper() + "_SAMPLE_INSUFFICIENT")
            elif row.get("mean_R") is None or row.get("upper_95") is None:
                missing.append(side.upper() + "_INFERENCE_UNAVAILABLE")
            elif row["mean_R"] < GATE["side_mean_floor_R"] and row["upper_95"] < 0:
                failed.append(side.upper() + "_MATERIAL_NEGATIVE_EDGE")
    state = "INSUFFICIENT_EVIDENCE" if missing else "REJECTED" if failed else "REQUALIFIED"
    return {"research_state": state, "status": state, "reasons": sorted(set(missing + failed)),
            "blocking_reasons": sorted(set(missing + failed)), "gate": GATE}
