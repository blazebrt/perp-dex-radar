"""Point-in-time inputs for historical portfolio-risk states (v8 Phase 10). RESEARCH ONLY.

A historical portfolio state may use only what was knowable at that time. v8.portfolio_risk (a live-safe module that
never imports the history) evaluates whatever inputs it is given; this adapter supplies the liquidity input of a
historical position from the v8 point-in-time history at that time, never from today's universe:

    historical_liquidity(history, t, asset)   v8.pit.History.liquidity_at(t, asset), kept KNOWN only when the record
                                              is fresh, KNOWN and precise enough to decide every slippage-tier
                                              threshold of the portfolio-risk policy; otherwise it is not KNOWN and
                                              the position's executable risk is UNAVAILABLE (never a tier, never 0)

Returns are read by v8.portfolio_risk itself only for bars closed at the evaluation time. Funding has no
point-in-time portfolio input here: a historical position without an observed funding settlement stays MISSING."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from v8 import pit as PIT  # noqa: E402
from v8 import portfolio_risk as PR  # noqa: E402

UNDECIDABLE = "TIER_THRESHOLD_UNDECIDABLE"


def historical_liquidity(history, t, asset, policy=None):
    policy = PR.load_policy() if policy is None else PR.validate_policy(policy)
    rec = history.liquidity_at(t, asset)
    out = {"state": rec.get("state"), "volume": None, "observed_at": rec.get("observed_at"),
           "source": "v8.pit.liquidity_at", "reason": rec.get("reason")}
    if rec.get("state") != PR.LIQUIDITY_KNOWN:
        return out
    for lo, _slip in policy["costs"]["slippage_tiers"]["value"]:
        decided = PIT.decides(rec.get("value"), rec.get("precision"), lo)
        if decided is None:
            out.update(state=PIT.LIQUIDITY_PRECISION_UNQUALIFIED, reason=UNDECIDABLE)
            return out
        if decided:
            break
    out["volume"] = float(rec["value"])
    return out
