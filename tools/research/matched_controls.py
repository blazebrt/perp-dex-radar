"""Point-in-time nearest-neighbour controls. Missing dimensions never become full authority."""
from __future__ import annotations

import math
import numpy as np

VERSION = "v8.matched-controls/1"
FEATURES = ("btc_beta", "realized_volatility", "pit_liquidity", "market_cap", "listing_age", "funding",
            "trend_state", "market_regime")
CATEGORICAL = {"trend_state", "market_regime"}


def feature(value, known_at, source):
    return {"value": value, "known_at": known_at, "source": source}


def known(row, name, decision_time):
    item = row.get("features", {}).get(name)
    if not isinstance(item, dict) or not isinstance(item.get("known_at"), (int, float)):
        return None
    if item["known_at"] > decision_time or item.get("source") != "PIT_OBSERVED":
        return None
    value = item.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def match(signal, candidates, limit=100, min_controls=50):
    """Cross-sectional normalization uses only same-time eligible assets' pre-entry features.

    Categorical trend/regime match exactly. Numeric distances use same-time population
    standard deviations (constant dimensions scale 1), Euclidean distance, asset-ID tie break.
    Input adapters must supply governed PIT observations; current-only fields are rejected.
    """
    t, side, asset = signal["decision_time"], signal["direction"], signal["asset"]
    if limit < min_controls or min_controls < 1:
        raise ValueError("invalid control counts")
    eligible = [r for r in candidates if r.get("decision_time") == t and r.get("direction") == side and
                r.get("eligible") is True and r.get("asset") != asset]
    ids = [r.get("asset") for r in eligible]
    if any(not isinstance(a, str) or not a for a in ids) or len(set(ids)) != len(ids):
        raise ValueError("controls need unique nonempty asset IDs")
    available = [k for k in FEATURES if known(signal, k, t) is not None]
    missing = sorted(set(FEATURES) - set(available))
    usable = [r for r in eligible if all(known(r, k, t) is not None for k in available)]
    numeric = [k for k in available if k not in CATEGORICAL]
    if not numeric:
        usable = []
    scale = {k: float(np.std([known(signal, k, t)] + [known(r, k, t) for r in usable])) or 1.0 for k in numeric}
    ranked = []
    for row in usable:
        if any(known(row, k, t) != known(signal, k, t) for k in available if k in CATEGORICAL):
            continue
        distance = math.sqrt(sum(((known(row, k, t) - known(signal, k, t)) / scale[k]) ** 2 for k in numeric))
        ranked.append({"asset": row["asset"], "distance": distance})
    ranked.sort(key=lambda r: (r["distance"], r["asset"]))
    selected = ranked[:limit]
    reasons = []
    if "market_cap" in missing:
        reasons.append("MATCHED_CONTROL_MARKET_CAP_MISSING")
    if missing:
        reasons.append("FULL_MATCHED_CONTROL_UNAVAILABLE")
    if len(selected) < min_controls:
        reasons.append("MATCHED_CONTROLS_INSUFFICIENT")
    return {"schema": VERSION, "status": "FULL" if not reasons else "PARTIAL_DIAGNOSTIC",
            "missing_dimensions": missing, "reasons": reasons, "controls": selected,
            "control_count": len(selected), "required_controls": min_controls, "scales": scale,
            "decision_time": t, "direction": side}


def outcome(matching, candidate_r, controls):
    """Only same-geometry, fully qualified simulation outcomes enter the control distribution.
    Confidence across candidate signals is clustered by decision day in the adjudicator.
    """
    ids = {r["asset"] for r in matching["controls"]}
    rows = [r for r in controls if r.get("asset") in ids and r.get("fully_qualified") is True and
            r.get("same_geometry") is True and r.get("decision_time") == matching["decision_time"] and
            r.get("direction") == matching["direction"] and isinstance(r.get("net_R"), (int, float)) and
            math.isfinite(r["net_R"])]
    if len({r["asset"] for r in rows}) != len(rows):
        raise ValueError("duplicate control outcomes")
    values = [r["net_R"] for r in rows]
    full = matching["status"] == "FULL" and len(values) >= matching["required_controls"]
    edge = float(candidate_r - np.mean(values)) if values else None
    return {**matching, "candidate_R": candidate_r, "control_distribution": values,
            "qualified_control_count": len(values), "matched_edge": edge, "full": full,
            "matched_edge_SE": None, "confidence_interval": None,
            "uncertainty_note": "Controls share market exposure; signal-day clustered inference required across signals."}
