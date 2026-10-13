"""Portfolio and risk realism (v8 Phase 10): one governed, deterministic portfolio-risk authority. Standard library only.

Phase 9 decides whether a strategy has research authority. This module answers a different question: if several
positions are open at once, what is the portfolio-level risk after shared exposures, dependence, concentration,
liquidity, leverage, funding, execution costs and adverse conditions? It observes and reports; it never sizes, ranks,
opens or closes a trade, and no engine reads it back.

    evaluate(portfolio)            current portfolio -> risk result (state, metrics, limits, stress, trace)
    what_if(portfolio, proposal)   current portfolio + proposed ADD / REDUCE -> before, after and the explained change
    live_portfolio(...)            the quant desk's actionable open positions as a portfolio input (audit adapter)

Every threshold and stress size is read from the governed policy file (portfolio_risk_policy.json,
v8.portfolio-risk-policy/1) at call time; this file holds no numerical threshold. Each policy value states its basis:
POLICY (a reviewed choice) or GOVERNED_CONSTANT (a cost constant shared with the cost model). No value is an
empirically validated quantity, and the schema refuses one: the repository holds no qualified portfolio history.

Risk states, in order of precedence:

    UNEVALUABLE         the policy or equity is invalid, or a required authority is missing and no limit is already
                        proven breached by the known part of the portfolio (unknown never becomes safe)
    LIMIT_BREACHED      a metric is above its limit (a known lower bound above a limit is a proven breach)
    APPROACHING_LIMITS  every authority is present, no limit is breached, a metric is at or above approach_fraction of
                        its limit (exactly at a limit is APPROACHING, never BREACHED)
    WITHIN_LIMITS       every authority is present and every metric is below approach_fraction of its limit

All quantities are fractions of equity unless named *_usd. Positions are dicts:

    id, asset, strategy, direction (1 long / -1 short), mark (current price; the entry price of a proposal),
    stop (current stop price), exactly one of quantity / notional / risk_fraction, entered (True: only the exit order
    is still to pay; False: entry and exit), liquidity {"state": v8.liquidity state, "volume": KNOWN 24h volume},
    funding {"state": "OBSERVED" | "OBSERVED_ZERO" | "MISSING", "rate_8h": signed rate}, hold_hours_remaining,
    optional funding_accrued {"state": "OBSERVED" | "MISSING", "amount_usd": funding already paid (+) or received (-)}.

The portfolio is {"equity", "as_of", "positions", "returns": {asset: [[bar_start, close], ...]},
"closed_trade_r": [...]}. Returns are read only for bars closed at as_of (bar_start + bar_seconds <= as_of) and inside
the trailing window, so appending later bars never changes an evaluation (point-in-time). A historical portfolio state
must also take its liquidity from the point-in-time history at that time, never today's: the research-side adapter
tools/research/portfolio_risk_pit.py does that (this module, like every live v8 module, never imports v8.pit)."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

VERSION = "v8.portfolio-risk/1"
POLICY_VERSION = "v8.portfolio-risk-policy/1"
PATH = Path(__file__).with_name("portfolio_risk_policy.json")
BASES = ("POLICY", "GOVERNED_CONSTANT")
WITHIN, APPROACHING, BREACHED, UNEVALUABLE = "WITHIN_LIMITS", "APPROACHING_LIMITS", "LIMIT_BREACHED", "UNEVALUABLE"
STATES = (WITHIN, APPROACHING, BREACHED, UNEVALUABLE)
OK, NEAR, OVER, UNAVAILABLE = "OK", "APPROACHING", "BREACHED", "UNAVAILABLE"
SECTIONS = {
    "limits": ("max_position_leverage", "max_gross_leverage", "max_net_leverage", "max_executable_risk",
               "max_asset_stop_risk", "max_strategy_stop_risk", "max_side_stop_risk", "max_cluster_stop_risk",
               "max_stressed_loss"),
    "costs": ("fee_taker", "slippage_tiers"),
    "dependence": ("bar_seconds", "lookback_bars", "min_overlap_bars", "cluster_correlation", "market_asset",
                   "min_regime_bars"),
    "stress": ("market_move", "stop_gap_fraction", "cost_multiplier", "liquidity_tier_steps",
               "unknown_liquidity_multiplier", "adverse_funding_8h"),
    "empirical": ("tail_min_closed_trades",),
}
SCENARIOS = ("CORRELATED_MARKET_MOVE", "DIVERSIFICATION_FAILURE", "STOP_SLIPPAGE", "EXECUTION_COST",
             "LIQUIDITY_DEGRADATION", "FUNDING_DETERIORATION")
FUNDING_KNOWN = ("OBSERVED", "OBSERVED_ZERO")
LIQUIDITY_KNOWN = "KNOWN"
EFFECTS = ("REDUCES_RISK", "INCREASES_RISK", "MIXED", "NO_CHANGE", "BREACHES_LIMIT", "INSUFFICIENT_AUTHORITY",
           "PROPOSAL_INVALID")


class PolicyError(ValueError):
    pass


# --------------------------------------------------------------------------- helpers
def _num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def _int(x):
    return not isinstance(x, bool) and isinstance(x, int)


def _r(x):
    """Published values: floats exactly as computed (so a metric equal to its limit stays equal), no negative zero,
    tuples as lists. Python float arithmetic is deterministic, so identical inputs give byte-identical output."""
    if isinstance(x, float):
        return x + 0.0
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v) for v in x]
    return x


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


# --------------------------------------------------------------------------- policy
def _check_value(section, key, v):
    def need(ok, why):
        if not ok:
            raise PolicyError(f"PORTFOLIO_RISK_POLICY_INVALID: {section}.{key} {why}")
    if section == "limits":
        need(_num(v) and v > 0, "must be a positive finite number")
    elif key == "fee_taker":
        need(_num(v) and 0 <= v < 0.1, "must be a finite fee in [0, 0.1)")
    elif key == "slippage_tiers":
        need(isinstance(v, list) and len(v) >= 1, "must be a non-empty tier list")
        prev_lo, prev_s = math.inf, -math.inf
        for row in v:
            need(isinstance(row, list) and len(row) == 2 and _num(row[0]) and _num(row[1]), "rows are [volume, slip]")
            need(row[0] >= 0 and row[0] < prev_lo, "volumes strictly descending and non-negative")
            need(0 < row[1] < 0.1 and row[1] >= prev_s, "slippage positive and non-decreasing as volume falls")
            prev_lo, prev_s = row[0], row[1]
        need(v[-1][0] == 0, "the last tier must start at volume 0")
    elif key in ("bar_seconds", "lookback_bars", "min_overlap_bars", "min_regime_bars", "tail_min_closed_trades"):
        need(_int(v) and v >= (1 if key in ("bar_seconds", "tail_min_closed_trades") else 2), "must be a positive int")
    elif key == "cluster_correlation":
        need(_num(v) and 0 < v <= 1, "must be in (0, 1]")
    elif key == "market_asset":
        need(isinstance(v, str) and bool(v), "must be an asset name")
    elif key == "market_move":
        need(_num(v) and 0 < v < 1, "must be in (0, 1)")
    elif key in ("stop_gap_fraction", "adverse_funding_8h"):
        need(_num(v) and v >= 0, "must be a non-negative finite number")
    elif key in ("cost_multiplier", "unknown_liquidity_multiplier"):
        need(_num(v) and v >= 1, "must be a finite number >= 1")
    elif key == "liquidity_tier_steps":
        need(_int(v) and v >= 0, "must be a non-negative int")
    elif key == "approach_fraction":
        need(_num(v) and 0 < v <= 1, "must be in (0, 1]")


def _check_entry(section, key, entry):
    if not isinstance(entry, dict) or set(entry) != {"value", "unit", "basis", "rationale"}:
        raise PolicyError(f"PORTFOLIO_RISK_POLICY_INVALID: {section}.{key} must be value/unit/basis/rationale")
    if entry["basis"] not in BASES:
        raise PolicyError(f"PORTFOLIO_RISK_POLICY_INVALID: {section}.{key} basis {entry['basis']!r} is not one of "
                          f"{BASES} (no empirically validated policy value exists)")
    if not (isinstance(entry["rationale"], str) and entry["rationale"].strip() and isinstance(entry["unit"], str)):
        raise PolicyError(f"PORTFOLIO_RISK_POLICY_INVALID: {section}.{key} needs a unit and a rationale")
    _check_value(section, key, entry["value"])


def validate_policy(policy):
    """The policy, unchanged, or PolicyError. Exact keys: nothing missing, nothing extra, no fallback."""
    if not isinstance(policy, dict) or policy.get("schema") != POLICY_VERSION:
        raise PolicyError("PORTFOLIO_RISK_POLICY_INVALID: schema")
    expected = {"schema", "review_status", "statement", "approach_fraction", *SECTIONS}
    if set(policy) != expected:
        raise PolicyError("PORTFOLIO_RISK_POLICY_INVALID: top-level keys " + repr(sorted(set(policy) ^ expected)))
    if not (isinstance(policy["review_status"], str) and isinstance(policy["statement"], str)):
        raise PolicyError("PORTFOLIO_RISK_POLICY_INVALID: review_status / statement")
    _check_entry("approach_fraction", "approach_fraction", policy["approach_fraction"])
    for section, keys in SECTIONS.items():
        block = policy[section]
        if not isinstance(block, dict) or set(block) != set(keys):
            raise PolicyError(f"PORTFOLIO_RISK_POLICY_INVALID: {section} keys")
        for key in keys:
            _check_entry(section, key, block[key])
    if policy["dependence"]["min_overlap_bars"]["value"] > policy["dependence"]["lookback_bars"]["value"]:
        raise PolicyError("PORTFOLIO_RISK_POLICY_INVALID: dependence.min_overlap_bars exceeds lookback_bars")
    if policy["dependence"]["min_regime_bars"]["value"] > policy["dependence"]["lookback_bars"]["value"]:
        raise PolicyError("PORTFOLIO_RISK_POLICY_INVALID: dependence.min_regime_bars exceeds lookback_bars")
    return policy


def load_policy(path=PATH):
    return validate_policy(json.loads(Path(path).read_text(encoding="utf-8")))


def policy_hash(policy):
    return digest(policy)


def _v(policy, section, key=None):
    return policy[section]["value"] if key is None else policy[section][key]["value"]


def slippage_tier(volume, policy, steps=0):
    """Slippage per market order for a KNOWN volume; `steps` tiers worse (clamped to the worst tier)."""
    tiers = _v(policy, "costs", "slippage_tiers")
    for k, (lo, _s) in enumerate(tiers):
        if volume >= lo:
            return tiers[min(k + steps, len(tiers) - 1)][1]
    return tiers[-1][1]


# --------------------------------------------------------------------------- positions
def _position(raw, equity, policy):
    """(row, missing): one position's trade-level risk. A malformed position is reported with its reasons and
    excluded from every sum (its exposure is unknown, so the portfolio cannot be WITHIN_LIMITS)."""
    pid = raw.get("id") if isinstance(raw, dict) else None
    pid = pid if isinstance(pid, str) and pid else "?"
    bad, missing = [], []
    if not isinstance(raw, dict):
        return {"id": pid, "status": "MALFORMED", "reasons": ["POSITION_NOT_A_RECORD"]}, ["POSITION_MALFORMED:" + pid]
    asset, strategy, d = raw.get("asset"), raw.get("strategy"), raw.get("direction")
    mark, stop = raw.get("mark"), raw.get("stop")
    if not (isinstance(asset, str) and asset):
        bad.append("ASSET_MISSING")
    if not (isinstance(strategy, str) and strategy):
        bad.append("STRATEGY_MISSING")
    if d not in (1, -1) or isinstance(d, bool):
        bad.append("DIRECTION_INVALID")
    if not (_num(mark) and mark > 0):
        bad.append("MARK_MISSING_OR_INVALID")
    if stop is None:
        bad.append("STOP_MISSING")
    elif not (_num(stop) and stop > 0):
        bad.append("STOP_INVALID")
    sizes = [k for k in ("quantity", "notional", "risk_fraction") if raw.get(k) is not None]
    if len(sizes) != 1:
        bad.append("SIZE_AMBIGUOUS_OR_MISSING")
    elif not (_num(raw[sizes[0]]) and raw[sizes[0]] > 0):
        bad.append("SIZE_INVALID")
    entered = raw.get("entered", True)
    if not isinstance(entered, bool):
        bad.append("ENTERED_INVALID")
    hours = raw.get("hold_hours_remaining")
    if hours is not None and not (_num(hours) and hours >= 0):
        bad.append("HOLD_HORIZON_INVALID")
    if not bad:
        dist = d * (mark - stop) / mark
        if not dist > 0:
            bad.append("STOP_WRONG_SIDE")
    if bad:
        return ({"id": pid, "status": "MALFORMED", "reasons": sorted(bad)},
                [f"POSITION_MALFORMED:{pid}"] + [f"{b}:{pid}" for b in sorted(bad) if b.startswith("STOP")])
    size = sizes[0]
    if size == "quantity":
        qty = float(raw["quantity"])
    elif size == "notional":
        qty = raw["notional"] / mark
    else:
        qty = raw["risk_fraction"] * equity / (dist * mark)
    notional = qty * mark
    lev = notional / equity
    stop_risk = lev * dist
    orders = 1 if entered else 2
    fee = _v(policy, "costs", "fee_taker")
    fees = orders * fee * lev
    liq = raw.get("liquidity") if isinstance(raw.get("liquidity"), dict) else {}
    liq_state = liq.get("state") if isinstance(liq.get("state"), str) else "MISSING"
    vol = liq.get("volume")
    if liq_state == LIQUIDITY_KNOWN and _num(vol) and vol >= 0:
        slip_rate = slippage_tier(vol, policy)
        slippage = orders * slip_rate * lev
    else:
        liq_state = liq_state if liq_state != LIQUIDITY_KNOWN else "KNOWN_VOLUME_INVALID"
        slip_rate, slippage = None, None
        missing.append("LIQUIDITY_UNKNOWN:" + pid)
    worst = _v(policy, "costs", "slippage_tiers")[-1][1]
    degraded_slip = slippage if slippage is not None else orders * worst * _v(policy, "stress", "unknown_liquidity_multiplier") * lev
    fund = raw.get("funding") if isinstance(raw.get("funding"), dict) else {}
    f_state = fund.get("state") if isinstance(fund.get("state"), str) else "MISSING"
    rate = fund.get("rate_8h")
    if hours is None:
        missing.append("HOLD_HORIZON_UNKNOWN:" + pid)
    if f_state in FUNDING_KNOWN and _num(rate) and (f_state != "OBSERVED_ZERO" or rate == 0):
        funding = d * rate * (hours / 8.0) * lev if hours is not None else None
    else:
        f_state = f_state if f_state not in FUNDING_KNOWN else "FUNDING_RATE_INVALID"
        rate, funding = None, None
        missing.append("FUNDING_UNKNOWN:" + pid)
    adverse_funding = max(0.0, funding) if funding is not None else None
    acc = raw.get("funding_accrued") if isinstance(raw.get("funding_accrued"), dict) else {}
    accrued = (acc["amount_usd"] / equity
               if acc.get("state") in FUNDING_KNOWN and _num(acc.get("amount_usd")) else None)
    executable = (stop_risk + fees + slippage + adverse_funding
                  if slippage is not None and adverse_funding is not None else None)
    gap = _v(policy, "stress", "stop_gap_fraction")
    row = {"id": pid, "status": "VALID", "asset": asset, "strategy": strategy, "direction": d,
           "entry": raw.get("entry") if _num(raw.get("entry")) else None, "mark": float(mark), "stop": float(stop),
           "stop_distance": dist, "quantity": qty, "notional_usd": notional, "sizing_input": size,
           "entered": entered, "leverage": lev, "account_risk": stop_risk,
           "expected_fees": fees, "orders_to_pay": orders,
           "liquidity": {"state": liq_state, "volume": float(vol) if liq_state == LIQUIDITY_KNOWN else None,
                         "slippage_rate": slip_rate},
           "expected_slippage": slippage,
           "funding": {"state": f_state, "rate_8h": rate, "expected": funding,
                       "accrued": accrued, "accrued_state": "OBSERVED" if accrued is not None else "UNKNOWN",
                       "cumulative": (accrued + funding) if accrued is not None and funding is not None else None},
           "hold_hours_remaining": hours,
           "risk": {"theoretical_stop": stop_risk, "expected_executable": executable,
                    "degraded_liquidity_bound": stop_risk + fees + degraded_slip,
                    "normal_stop": stop_risk, "gap_slippage": stop_risk * gap,
                    "adverse_cost": (fees + slippage + adverse_funding) if executable is not None else None,
                    "nominal_R": 1.0, "stressed_stop_R": 1.0 + gap,
                    "expected_executable_R": executable / stop_risk if executable is not None else None}}
    return row, missing


# --------------------------------------------------------------------------- dependence (point-in-time)
def _returns(series, as_of, policy):
    """{bar_end: log return} for consecutive closed bars inside the trailing window ending at as_of, or None."""
    bar = _v(policy, "dependence", "bar_seconds")
    look = _v(policy, "dependence", "lookback_bars")
    if not isinstance(series, list):
        return None
    pts = {}
    for row in series:
        if not (isinstance(row, (list, tuple)) and len(row) == 2 and _int(row[0]) and _num(row[1]) and row[1] > 0):
            return None
        t, c = row
        if t + bar > as_of:          # not closed at the evaluation time: invisible
            continue
        if t in pts:
            return None
        pts[t] = float(c)
    out = {}
    lo = as_of - look * bar
    for t in sorted(pts):
        prev = t - bar
        end = t + bar
        if prev in pts and end > lo:
            out[end] = math.log(pts[t] / pts[prev])
    return out


def _pearson(a, b, keys):
    n = len(keys)
    xa = [a[k] for k in keys]
    xb = [b[k] for k in keys]
    ma, mb = sum(xa) / n, sum(xb) / n
    va = sum((x - ma) ** 2 for x in xa)
    vb = sum((x - mb) ** 2 for x in xb)
    if va <= 0 or vb <= 0:
        return None
    return max(-1.0, min(1.0, sum((x - ma) * (y - mb) for x, y in zip(xa, xb)) / math.sqrt(va * vb)))


def _beta(a, m, keys):
    n = len(keys)
    xa = [a[k] for k in keys]
    xm = [m[k] for k in keys]
    ma, mm = sum(xa) / n, sum(xm) / n
    vm = sum((x - mm) ** 2 for x in xm)
    if vm <= 0:
        return None
    return sum((x - ma) * (y - mm) for x, y in zip(xa, xm)) / vm


def dependence(assets, returns, as_of, policy):
    """Pairwise correlations, market betas and down-market correlations from closed bars only."""
    min_n = _v(policy, "dependence", "min_overlap_bars")
    min_reg = _v(policy, "dependence", "min_regime_bars")
    market = _v(policy, "dependence", "market_asset")
    returns = returns if isinstance(returns, dict) else {}
    series = {a: _returns(returns.get(a), as_of, policy) for a in sorted(set(assets) | {market})}
    corr, down, missing = {}, {}, []
    m = series.get(market)
    names = sorted(set(assets))
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            key = a + "|" + b
            sa, sb = series.get(a), series.get(b)
            keys = sorted(set(sa) & set(sb)) if sa is not None and sb is not None else []
            rho = _pearson(sa, sb, keys) if len(keys) >= min_n else None
            corr[key] = {"value": rho, "n": len(keys)}
            if rho is None:
                missing.append("DEPENDENCE_UNAVAILABLE:" + key)
            dk = [k for k in keys if m is not None and k in m and m[k] < 0]
            down[key] = {"value": _pearson(sa, sb, dk) if len(dk) >= min_reg else None, "n": len(dk)}
    betas = {}
    for a in names:
        sa = series.get(a)
        if a == market and sa is not None and len(sa) >= min_n:
            betas[a] = {"value": 1.0, "n": len(sa)}
            continue
        keys = sorted(set(sa) & set(m)) if sa is not None and m is not None else []
        b = _beta(sa, m, keys) if len(keys) >= min_n else None
        betas[a] = {"value": b, "n": len(keys)}
        if b is None:
            missing.append("BETA_UNAVAILABLE:" + a)
    return {"correlation": corr, "down_market_correlation": down, "beta": betas,
            "series_bars": {a: (len(s) if s is not None else None) for a, s in series.items()}}, missing


# --------------------------------------------------------------------------- evaluation
def _groups(rows, key):
    out = {}
    for p in rows:
        g = out.setdefault(p[key] if key != "side" else ("long" if p["direction"] > 0 else "short"),
                           {"notional": 0.0, "net": 0.0, "stop_risk": 0.0, "positions": 0})
        g["notional"] += p["leverage"]
        g["net"] += p["direction"] * p["leverage"]
        g["stop_risk"] += p["account_risk"]
        g["positions"] += 1
    return out


def _overlap(rows):
    """{"S1|S2": [shared assets]} for every pair of strategies holding the same asset."""
    held = {}
    for r in rows:
        held.setdefault(r["strategy"], set()).add(r["asset"])
    names = sorted(held)
    out = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = sorted(held[a] & held[b])
            if common:
                out[a + "|" + b] = common
    return out


def _shares(values):
    vals = sorted(values, reverse=True)
    total = math.fsum(vals)
    if total <= 0:
        return {"largest": None, "top3": None, "top5": None}
    return {"largest": vals[0] / total, "top3": math.fsum(vals[:3]) / total, "top5": math.fsum(vals[:5]) / total}


def _clusters(rows, eff, threshold):
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for (i, j), e in eff.items():
        if e is not None and e >= threshold:
            parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(rows):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        out.append({"positions": sorted(rows[i]["id"] for i in members),
                    "stop_risk": math.fsum(rows[i]["account_risk"] for i in members)})
    return sorted(out, key=lambda c: (-c["stop_risk"], c["positions"]))


def _limit(policy, key, value, complete):
    lim = _v(policy, "limits", key)
    if value is not None and value > lim:
        status = OVER
    elif not complete or value is None:
        status = UNAVAILABLE
    elif value >= _v(policy, "approach_fraction") * lim:
        status = NEAR
    else:
        status = OK
    return {"metric": value, "limit": lim, "basis": policy["limits"][key]["basis"], "complete": bool(complete),
            "status": status}


def _trace(category, inp, rule, result, effect):
    return {"category": category, "input": inp, "rule": rule, "result": result, "effect": effect}


def _unevaluable(reason, policy_info):
    return _r({"schema": VERSION, **policy_info, "state": UNEVALUABLE, "missing_authorities": [reason],
               "breached": [], "approaching": [], "limits": {}, "positions": [],
               "trace": [_trace("STATE", reason, "a required authority is missing", UNEVALUABLE,
                                "the portfolio cannot be evaluated; unknown is never safe")]})


def evaluate(portfolio, policy=None):
    """The deterministic portfolio-risk result. Never raises for bad input: it reports it."""
    try:
        policy = load_policy() if policy is None else validate_policy(policy)
    except (OSError, ValueError, PolicyError) as e:
        return _unevaluable("PORTFOLIO_RISK_POLICY_INVALID", {"policy_schema": POLICY_VERSION, "policy_hash": None,
                                                              "policy_error": str(e)[:300]})
    info = {"policy_schema": POLICY_VERSION, "policy_hash": policy_hash(policy),
            "policy_review_status": policy["review_status"]}
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    equity, as_of = portfolio.get("equity"), portfolio.get("as_of")
    if not (_num(equity) and equity > 0):
        return _unevaluable("EQUITY_INVALID", info)
    if not _int(as_of):
        return _unevaluable("AS_OF_INVALID", info)
    raw = portfolio.get("positions")
    if not isinstance(raw, list):
        return _unevaluable("POSITIONS_INVALID", info)
    trace = [_trace("POLICY", {"schema": POLICY_VERSION, "hash": info["policy_hash"]},
                    "every threshold is read from the governed policy", policy["review_status"],
                    "limits are reviewed policy choices, not empirical estimates"),
             _trace("EQUITY", equity, "all risk is measured as a fraction of equity", "VALID", "sizing reference")]
    rows, missing, seen = [], [], set()
    for p in raw:
        row, miss = _position(p, equity, policy)
        if row["id"] in seen or row["id"] == "?":
            row = {"id": row["id"], "status": "MALFORMED", "reasons": ["ID_DUPLICATE_OR_MISSING"]}
            miss = ["POSITION_MALFORMED:" + row["id"]]
        seen.add(row["id"])
        rows.append(row)
        missing.extend(miss)
        trace.append(_trace("POSITION", {k: row.get(k) for k in ("id", "asset", "strategy", "direction")},
                            "stop distance x notional / equity = stop risk; costs from the liquidity authority",
                            row["status"] if row["status"] != "VALID" else
                            {"leverage": row["leverage"], "stop_risk": row["account_risk"],
                             "executable_risk": row["risk"]["expected_executable"]},
                            "excluded from every sum; portfolio cannot be WITHIN_LIMITS" if row["status"] != "VALID"
                            else "included"))
    valid = [r for r in rows if r["status"] == "VALID"]
    malformed = len(valid) != len(rows)

    # gross / net exposure and leverage
    long_ = math.fsum(r["leverage"] for r in valid if r["direction"] > 0)
    short = math.fsum(r["leverage"] for r in valid if r["direction"] < 0)
    exposure = {"gross_leverage": long_ + short, "long_leverage": long_, "short_leverage": short,
                "net_leverage": long_ - short, "gross_notional_usd": (long_ + short) * equity,
                "gross_long_usd": long_ * equity, "gross_short_usd": short * equity,
                "net_usd": (long_ - short) * equity,
                "max_position_leverage": max((r["leverage"] for r in valid), default=0.0)}
    trace.append(_trace("GROSS_EXPOSURE", {"positions": len(valid)}, "gross = long + short; net = long - short",
                        {k: exposure[k] for k in ("gross_leverage", "net_leverage")},
                        "a hedged net never offsets gross leverage"))

    # concentration (nominal and stop-risk)
    by_asset, by_strategy, by_side = _groups(valid, "asset"), _groups(valid, "strategy"), _groups(valid, "side")
    total_stop = math.fsum(r["account_risk"] for r in valid)
    concentration = {"asset": by_asset, "strategy": by_strategy, "side": by_side,
                     "nominal_share": _shares([r["leverage"] for r in valid]),
                     "stop_risk_share": _shares([r["account_risk"] for r in valid]),
                     "asset_nominal_share": _shares([g["notional"] for g in by_asset.values()]),
                     "asset_stop_risk_share": _shares([g["stop_risk"] for g in by_asset.values()]),
                     "shared_assets": sorted(a for a, g in by_asset.items() if g["positions"] > 1),
                     "offsetting_assets": sorted(a for a in by_asset if {r["direction"] for r in valid
                                                                          if r["asset"] == a} == {1, -1}),
                     "multi_strategy_assets": sorted(a for a in by_asset
                                                     if len({r["strategy"] for r in valid if r["asset"] == a}) > 1),
                     "strategy_overlap": _overlap(valid)}
    trace.append(_trace("CONCENTRATION", {"assets": len(by_asset), "strategies": len(by_strategy)},
                        "group stop risk by asset, strategy and side; same asset = one exposure",
                        {"max_asset_stop_risk": max((g["stop_risk"] for g in by_asset.values()), default=0.0),
                         "shared_assets": concentration["shared_assets"]},
                        "several strategies on one asset add up"))

    # dependence
    dep, dep_missing = dependence([r["asset"] for r in valid], portfolio.get("returns"), as_of, policy)
    pair_missing = [m for m in dep_missing if m.startswith("DEPENDENCE_UNAVAILABLE")]
    beta_missing = [m for m in dep_missing if m.startswith("BETA_UNAVAILABLE")]
    eff = {}
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            a, b = valid[i], valid[j]
            if a["asset"] == b["asset"]:
                rho = 1.0
            else:
                rho = dep["correlation"]["|".join(sorted((a["asset"], b["asset"])))]["value"]
            eff[(i, j)] = a["direction"] * b["direction"] * rho if rho is not None else None
    dep_complete = not pair_missing
    r = [p["account_risk"] for p in valid]
    diversified = None
    if dep_complete:
        s = math.fsum(x * x for x in r) + 2 * math.fsum(r[i] * r[j] * e for (i, j), e in eff.items())
        diversified = math.sqrt(max(0.0, s))
    clusters = _clusters(valid, eff, _v(policy, "dependence", "cluster_correlation"))
    betas = {a: dep["beta"][a]["value"] for a in {p["asset"] for p in valid}}
    beta_net = (math.fsum(p["direction"] * p["leverage"] * betas[p["asset"]] for p in valid)
                if not beta_missing else None)
    effs = [e for e in eff.values() if e is not None]
    down_effs = []
    for (i, j), e in eff.items():
        a, b = valid[i], valid[j]
        if a["asset"] == b["asset"]:
            continue
        dv = dep["down_market_correlation"]["|".join(sorted((a["asset"], b["asset"])))]["value"]
        if dv is not None:
            down_effs.append(a["direction"] * b["direction"] * dv)
    dependence_out = {**dep, "complete": dep_complete,
                      "diversified_stop_risk": diversified,
                      "independence_stop_risk": math.sqrt(math.fsum(x * x for x in r)),
                      "no_diversification_stop_risk": total_stop,
                      "diversification_claimed": (1 - diversified / total_stop) if diversified is not None and total_stop
                      else None,
                      "beta_weighted_net_leverage": beta_net,
                      "clusters": clusters,
                      "mean_effective_correlation": math.fsum(effs) / len(effs) if effs else None,
                      "regime": {"basis": "pairs on market-down bars (market return < 0)",
                                 "mean_effective_down_correlation": math.fsum(down_effs) / len(down_effs) if down_effs else None,
                                 "pairs_available": len(down_effs), "status": "DIAGNOSTIC"},
                      "same_direction": {"long": sum(1 for p in valid if p["direction"] > 0),
                                         "short": sum(1 for p in valid if p["direction"] < 0)},
                      "note": "diversified_stop_risk assumes losses scale with direction-adjusted return correlation; "
                              "a DIAGNOSTIC, never a limit. Limits use clusters and the no-diversification sum."}
    trace.append(_trace("DEPENDENCE", {"pairs": len(dep["correlation"]), "as_of": as_of},
                        "direction-adjusted correlation from closed bars only; clusters at >= cluster_correlation",
                        {"complete": dep_complete, "clusters": len(clusters),
                         "max_cluster_stop_risk": clusters[0]["stop_risk"] if clusters else 0.0},
                        "positions that co-move are one exposure; missing dependence is never independence"))

    # liquidity and funding
    liq_unknown = [p["id"] for p in valid if p["expected_slippage"] is None]
    fund_unknown = [p["id"] for p in valid if p["funding"]["expected"] is None]
    liquidity = {"theoretical_stop_risk": total_stop,
                 "expected_executable_risk": (math.fsum(p["risk"]["expected_executable"] for p in valid)
                                              if all(p["risk"]["expected_executable"] is not None for p in valid)
                                              else None),
                 "executable_risk_known_lower_bound": math.fsum(p["risk"]["expected_executable"] or p["account_risk"]
                                                          for p in valid),
                 "degraded_liquidity_bound": math.fsum(p["risk"]["degraded_liquidity_bound"] for p in valid),
                 "unknown_liquidity_positions": liq_unknown}
    funding = {"known_expected": math.fsum(p["funding"]["expected"] for p in valid if p["funding"]["expected"] is not None),
               "known_adverse": math.fsum(max(0.0, p["funding"]["expected"]) for p in valid
                                    if p["funding"]["expected"] is not None),
               "unknown_positions": fund_unknown,
               "accrued_known": math.fsum(p["funding"]["accrued"] for p in valid if p["funding"]["accrued"] is not None),
               "accrued_unknown_positions": [p["id"] for p in valid if p["funding"]["accrued"] is None],
               "rule": "credits never reduce risk; missing funding stays missing (never 0)"}
    trace.append(_trace("LIQUIDITY", {"unknown": liq_unknown}, "slippage only from a KNOWN v8.liquidity volume tier",
                        {"theoretical": total_stop, "executable": liquidity["expected_executable_risk"],
                         "degraded_bound": liquidity["degraded_liquidity_bound"]},
                        "unknown liquidity is never zero slippage"))
    trace.append(_trace("FUNDING", {"unknown": fund_unknown}, "expected funding = direction x rate x hours/8",
                        {"known_adverse": funding["known_adverse"]}, "unknown funding is never assumed zero"))

    # stress
    stress = _stress(valid, betas, beta_missing, policy)
    trace.append(_trace("STRESS", {k: _v(policy, "stress", k) for k in SECTIONS["stress"]},
                        "deterministic governed scenarios; losses as a fraction of equity",
                        {k: (v["loss"], v["status"]) for k, v in stress["scenarios"].items()},
                        "an unavailable scenario is never a pass"))

    # tail evidence (empirical diagnostic, never a limit)
    tail = tail_evidence(portfolio.get("closed_trade_r"), policy)

    # limits
    exec_complete = not malformed and liquidity["expected_executable_risk"] is not None
    limits = {
        "max_position_leverage": _limit(policy, "max_position_leverage", exposure["max_position_leverage"], not malformed),
        "max_gross_leverage": _limit(policy, "max_gross_leverage", exposure["gross_leverage"], not malformed),
        "max_net_leverage": _limit(policy, "max_net_leverage", abs(exposure["net_leverage"]), not malformed),
        "max_executable_risk": _limit(policy, "max_executable_risk",
                                      liquidity["expected_executable_risk"] if exec_complete
                                      else liquidity["executable_risk_known_lower_bound"], exec_complete),
        "max_asset_stop_risk": _limit(policy, "max_asset_stop_risk",
                                      max((g["stop_risk"] for g in by_asset.values()), default=0.0), not malformed),
        "max_strategy_stop_risk": _limit(policy, "max_strategy_stop_risk",
                                         max((g["stop_risk"] for g in by_strategy.values()), default=0.0), not malformed),
        "max_side_stop_risk": _limit(policy, "max_side_stop_risk",
                                     max((g["stop_risk"] for g in by_side.values()), default=0.0), not malformed),
        "max_cluster_stop_risk": _limit(policy, "max_cluster_stop_risk",
                                        clusters[0]["stop_risk"] if clusters else 0.0,
                                        not malformed and dep_complete),
        "max_stressed_loss": _limit(policy, "max_stressed_loss", stress["worst_available_loss"],
                                    not malformed and stress["complete"]),
    }
    for key, lim in limits.items():
        trace.append(_trace("LIMIT", {"metric": lim["metric"], "complete": lim["complete"]},
                            f"{key} <= {lim['limit']} ({lim['basis']})", lim["status"],
                            {OVER: "the portfolio exceeds a reviewed limit", NEAR: "at or above approach_fraction",
                             UNAVAILABLE: "required authority missing", OK: "within"}[lim["status"]]))
    breached = sorted(k for k, v in limits.items() if v["status"] == OVER)
    approaching = sorted(k for k, v in limits.items() if v["status"] == NEAR)
    missing_all = sorted(set(missing + dep_missing))
    if breached:
        state = BREACHED
    elif missing_all or any(v["status"] == UNAVAILABLE for v in limits.values()):
        state = UNEVALUABLE
    elif approaching:
        state = APPROACHING
    else:
        state = WITHIN
    trace.append(_trace("STATE", {"breached": breached, "approaching": approaching, "missing": len(missing_all)},
                        "BREACHED if any limit is exceeded; else UNEVALUABLE if any authority is missing; else "
                        "APPROACHING if any metric >= approach_fraction x limit; else WITHIN",
                        state, "portfolio effect for the human decision-maker (no trade is executed or ranked)"))
    return _r({"schema": VERSION, **info, "as_of": as_of, "equity": float(equity), "state": state,
               "breached": breached, "approaching": approaching, "missing_authorities": missing_all,
               "positions": rows, "exposure": exposure, "concentration": concentration,
               "dependence": dependence_out, "liquidity": liquidity, "funding": funding, "stress": stress,
               "stop_realism": {"normal_stop": total_stop,
                                "gap_slippage": total_stop * _v(policy, "stress", "stop_gap_fraction"),
                                "adverse_cost": (liquidity["expected_executable_risk"] - total_stop
                                                 if liquidity["expected_executable_risk"] is not None else None),
                                "statement": "A stop is not a guaranteed maximum loss: gaps, slippage and costs add to "
                                             "it. The gap allowance is a POLICY stress size, not a fitted tail model.",
                                "empirical_tail": tail},
               "limits": limits, "trace": trace})


def _stress(valid, betas, beta_missing, policy):
    gap = _v(policy, "stress", "stop_gap_fraction")
    mult = _v(policy, "stress", "cost_multiplier")
    steps = _v(policy, "stress", "liquidity_tier_steps")
    unk = _v(policy, "stress", "unknown_liquidity_multiplier")
    adverse = _v(policy, "stress", "adverse_funding_8h")
    move = _v(policy, "stress", "market_move")
    fee = _v(policy, "costs", "fee_taker")
    worst = _v(policy, "costs", "slippage_tiers")[-1][1]
    out = {}

    def scenario(name, losses, missing, rule):
        status = "AVAILABLE" if not missing else "UNAVAILABLE"
        out[name] = {"status": status, "loss": math.fsum(losses) if not missing else None,
                     "known_lower_bound": math.fsum(x for x in losses if x is not None), "missing": sorted(missing),
                     "rule": rule}

    if beta_missing:
        scenario("CORRELATED_MARKET_MOVE", [], beta_missing, "market factor +/- market_move x beta, losses capped "
                 "at the stop")
    else:
        worst_dir = None
        for s in (-1, 1):
            loss = 0.0
            for p in valid:
                pnl = p["direction"] * betas[p["asset"]] * s * move * p["leverage"]
                loss += min(-pnl, p["account_risk"])
            worst_dir = loss if worst_dir is None else max(worst_dir, loss)
        scenario("CORRELATED_MARKET_MOVE", [max(0.0, worst_dir)] if valid else [0.0], [],
                 "market factor +/- market_move x beta, losses capped at the stop, the worse direction")
    known_costs = [p["expected_fees"] + p["expected_slippage"] if p["expected_slippage"] is not None else None
                   for p in valid]
    cost_missing = ["LIQUIDITY_UNKNOWN:" + p["id"] for p, c in zip(valid, known_costs) if c is None]
    scenario("DIVERSIFICATION_FAILURE",
             [p["account_risk"] + c if c is not None else p["account_risk"] for p, c in zip(valid, known_costs)],
             cost_missing, "correlations go to 1 against every position: every stop is hit, plus expected costs")
    scenario("STOP_SLIPPAGE",
             [p["account_risk"] * (1 + gap) + (c or 0.0) for p, c in zip(valid, known_costs)],
             cost_missing, "every stop fills stop_gap_fraction of its distance beyond the stop, plus expected costs")
    scenario("EXECUTION_COST",
             [p["account_risk"] + mult * (c or 0.0) for p, c in zip(valid, known_costs)],
             cost_missing, "every stop is hit; fees and slippage at cost_multiplier")
    deg = []
    for p in valid:
        if p["liquidity"]["state"] == LIQUIDITY_KNOWN:
            rate = slippage_tier(p["liquidity"]["volume"], policy, steps)
        else:
            rate = worst * unk
        deg.append(p["account_risk"] + p["orders_to_pay"] * (fee + rate) * p["leverage"])
    scenario("LIQUIDITY_DEGRADATION", deg, [], "every stop is hit; KNOWN volumes pay liquidity_tier_steps worse "
             "slippage; unknown liquidity pays the worst tier x unknown_liquidity_multiplier")
    fl, fmiss = [], list(cost_missing)
    for p, c in zip(valid, known_costs):
        hours = p["hold_hours_remaining"]
        if hours is None:
            fmiss.append("HOLD_HORIZON_UNKNOWN:" + p["id"])
            fl.append(None)
            continue
        observed = (max(0.0, p["direction"] * p["funding"]["rate_8h"])
                    if p["funding"]["rate_8h"] is not None else 0.0)
        fl.append(p["account_risk"] + (c or 0.0) + max(adverse, observed) * (hours / 8.0) * p["leverage"])
    scenario("FUNDING_DETERIORATION", fl, fmiss, "every stop is hit at the end of the remaining horizon after "
             "paying max(adverse_funding_8h, observed adverse rate) against its direction")
    avail = [v["loss"] for v in out.values() if v["status"] == "AVAILABLE"]
    lower = [v["known_lower_bound"] for v in out.values()]
    complete = all(v["status"] == "AVAILABLE" for v in out.values())
    return {"scenarios": out, "complete": complete,
            "worst_available_loss": max(avail + lower) if (avail or lower) else 0.0,
            "worst_scenario": max(out, key=lambda k: (out[k]["loss"] if out[k]["loss"] is not None
                                                      else out[k]["known_lower_bound"], k)) if out else None,
            "basis": "POLICY stress sizes; deterministic; no probability is attached"}


def tail_evidence(closed_r, policy):
    """Observed loss beyond the stop in identity-qualified closed trades: an EMPIRICAL DIAGNOSTIC, never a limit."""
    need = _v(policy, "empirical", "tail_min_closed_trades")
    rs = [float(x) for x in closed_r if _num(x)] if isinstance(closed_r, list) else None
    if rs is None:
        return {"status": "UNAVAILABLE", "n": 0, "min_n": need, "basis": "EMPIRICAL_DIAGNOSTIC"}
    out = {"status": "AVAILABLE" if len(rs) >= need else "INSUFFICIENT", "n": len(rs), "min_n": need,
           "basis": "EMPIRICAL_DIAGNOSTIC",
           "statement": "Too few qualified closed trades to describe tail loss; the gap allowance stays a POLICY value."
           if len(rs) < need else "Observed only; it does not set or validate any limit."}
    if len(rs) >= need:
        out.update(worst_r=min(rs), beyond_stop_fraction=sum(1 for x in rs if x < -1) / len(rs))
    return out


# --------------------------------------------------------------------------- what-if
def _summary(result):
    if result is None:
        return None
    lim = result.get("limits") or {}
    return {"state": result["state"], "breached": result.get("breached", []),
            "approaching": result.get("approaching", []), "missing_authorities": result.get("missing_authorities", []),
            "metrics": {k: v["metric"] for k, v in lim.items()},
            "limit_status": {k: v["status"] for k, v in lim.items()}}


def what_if(portfolio, proposal, policy=None):
    """Before and after one proposed change, and what it does to portfolio risk. Never executes, sizes or ranks.

    proposal: {"action": "ADD", "position": {...}} or {"action": "REDUCE", "id": position id, "fraction": (0, 1]}"""
    before = evaluate(portfolio, policy)
    base = {"schema": VERSION, "proposal": copy.deepcopy(proposal), "authority": "DIAGNOSTIC_NO_EXECUTION_NO_RANKING",
            "before": _summary(before)}
    after_pf = copy.deepcopy(portfolio) if isinstance(portfolio, dict) else {}
    positions = after_pf.get("positions") if isinstance(after_pf.get("positions"), list) else None
    action = proposal.get("action") if isinstance(proposal, dict) else None
    why = None
    if positions is None:
        why = "PORTFOLIO_POSITIONS_INVALID"
    elif action == "ADD":
        pos = proposal.get("position")
        if not isinstance(pos, dict):
            why = "PROPOSED_POSITION_NOT_A_RECORD"
        elif any(isinstance(p, dict) and p.get("id") == pos.get("id") for p in positions):
            why = "PROPOSED_ID_ALREADY_OPEN"
        else:
            positions.append(dict(pos, entered=pos.get("entered", False)))
    elif action == "REDUCE":
        frac = proposal.get("fraction")
        idx = [k for k, p in enumerate(positions) if isinstance(p, dict) and p.get("id") == proposal.get("id")]
        if len(idx) != 1:
            why = "REDUCE_ID_NOT_OPEN"
        elif not (_num(frac) and 0 < frac <= 1):
            why = "REDUCE_FRACTION_INVALID"
        else:
            p = positions[idx[0]]
            size = [k for k in ("quantity", "notional", "risk_fraction") if p.get(k) is not None]
            if frac == 1:
                positions.pop(idx[0])
            elif len(size) == 1 and _num(p[size[0]]):
                p[size[0]] = p[size[0]] * (1 - frac)
            else:
                why = "REDUCE_POSITION_SIZE_INVALID"
    else:
        why = "PROPOSAL_ACTION_INVALID"
    if why:
        return _r({**base, "after": None, "effect": "PROPOSAL_INVALID", "explanation": [why], "delta": {},
                   "limit_changes": {},
                   "trace": [_trace("PROPOSAL", proposal if isinstance(proposal, (dict, list, str)) else None,
                                    "ADD a position or REDUCE an open one", why, "nothing evaluated")]})
    after = evaluate(after_pf, policy)
    sb, sa = _summary(before), _summary(after)
    delta = {}
    for k, v in sa["metrics"].items():
        b = sb["metrics"].get(k)
        delta[k] = v - b if _num(v) and _num(b) else None
    changes = {k: [sb["limit_status"].get(k), s] for k, s in sa["limit_status"].items()
               if sb["limit_status"].get(k) != s}
    new_missing = sorted(set(sa["missing_authorities"]) - set(sb["missing_authorities"]))
    newly_breached = sorted(set(sa["breached"]) - set(sb["breached"]))
    explanation = []
    if sa["state"] == UNEVALUABLE and (new_missing or sb["state"] != UNEVALUABLE):
        effect = "INSUFFICIENT_AUTHORITY"
        explanation.append("the change adds missing authority: " + ", ".join(new_missing or sa["missing_authorities"]))
    elif newly_breached:
        effect = "BREACHES_LIMIT"
        explanation.append("newly breached: " + ", ".join(newly_breached))
    else:
        ds = [d for d in delta.values() if d is not None]
        up, down = any(d > 1e-15 for d in ds), any(d < -1e-15 for d in ds)
        effect = "MIXED" if up and down else "INCREASES_RISK" if up else "REDUCES_RISK" if down else "NO_CHANGE"
    for k, d in sorted(delta.items()):
        if d is not None and abs(d) > 1e-15:
            explanation.append(f"{k}: {sb['metrics'][k]:.6g} -> {sa['metrics'][k]:.6g}")
    trace = [_trace("PROPOSAL", {"action": action, "id": proposal.get("id") or (proposal.get("position") or {}).get("id")},
                    "evaluate the portfolio before and after, same policy, nothing executed or ranked",
                    {"before": sb["state"], "after": sa["state"]}, effect)]
    if action == "ADD":
        pid = proposal["position"].get("id")
        row = next((r for r in after["positions"] if r.get("id") == pid), None)
        trace.append(_trace("PROPOSED_TRADE_RISK", {"id": pid}, "trade-level risk of the proposal",
                            row if row is None or row.get("status") != "VALID" else
                            {"stop_risk": row["account_risk"], "leverage": row["leverage"],
                             "executable_risk": row["risk"]["expected_executable"],
                             "liquidity": row["liquidity"]["state"], "funding": row["funding"]["state"]},
                            "added to the portfolio for evaluation only"))
    for k, d in sorted(delta.items()):
        if d is not None and abs(d) > 1e-15:
            trace.append(_trace("LIMIT_DELTA", {"before": sb["metrics"][k], "after": sa["metrics"][k]},
                                f"{k} <= {after['limits'][k]['limit']}", sa["limit_status"][k],
                                "raises" if d > 0 else "lowers"))
    trace.append(_trace("FINAL_PORTFOLIO_EFFECT", {"before": sb["state"], "after": sa["state"]},
                        "INSUFFICIENT_AUTHORITY > BREACHES_LIMIT > metric deltas", effect,
                        "information for the human decision-maker"))
    return _r({**base, "after": sa, "effect": effect, "explanation": explanation, "delta": delta,
               "limit_changes": changes, "before_result": before, "after_result": after, "trace": trace})


# --------------------------------------------------------------------------- live adapter (audit)
def live_portfolio(open_trades, universe, daily, now, account, risk, trade_dexes=(), closed_trade_r=None,
                   market_asset=None):
    """The quant desk's actionable open paper positions as a portfolio input, at the page's default sizing
    (account x risk per trade at the entry stop distance). Observational: nothing is read back by quant.py.

    Liquidity comes from v8.liquidity on this scan's universe record. Funding is MISSING: the journal's funding sums
    treat a missing settlement as zero, so they are not an authority. Returns are the scan's closed daily bars."""
    from . import liquidity as LQ
    positions = []
    for tr in open_trades or []:
        res = tr.get("res") or {}
        px, stop_pct = tr.get("px"), tr.get("stop_pct")
        qty = (account * risk / (stop_pct * px)) if _num(px) and px > 0 and _num(stop_pct) and stop_pct > 0 else None
        ev = LQ.evaluate((universe or {}).get(tr.get("c")), tuple(trade_dexes or ()))
        end = (tr.get("t_in") or 0) + (tr.get("hold_h") or 0) * 3600
        positions.append({
            "id": tr.get("id"), "asset": tr.get("c"), "strategy": tr.get("s"), "direction": tr.get("d"),
            "entry": px, "mark": res.get("last_px", px), "stop": res.get("stop_now", tr.get("stop")),
            "quantity": qty, "entered": True,
            "liquidity": {"state": ev["state"], "volume": ev["value"]},
            "funding": {"state": "MISSING", "reason": "NO_AUTHORITATIVE_LIVE_FUNDING"},
            "hold_hours_remaining": max(0.0, (end - now) / 3600.0) if _int(tr.get("t_in")) and tr.get("hold_h") else None})
    assets = sorted({p["asset"] for p in positions if isinstance(p["asset"], str)} | ({market_asset} if market_asset
                                                                                      else set()))
    returns = {a: [[int(x["t"]), x["c"]] for x in (daily or {}).get(a) or []] for a in assets if (daily or {}).get(a)}
    return {"equity": float(account), "as_of": int(now), "positions": positions, "returns": returns,
            "closed_trade_r": list(closed_trade_r) if closed_trade_r is not None else None,
            "sizing": {"basis": "PAGE_DEFAULT_SIZING", "account": account, "risk_per_trade": risk}}


def audit_summary(result):
    """The compact audit view of an evaluation (the full result, trace included, is in the quant audit part)."""
    if not isinstance(result, dict):
        return {"schema": VERSION, "state": UNEVALUABLE, "missing_authorities": ["PORTFOLIO_RISK_NOT_EVALUATED"]}
    miss = result.get("missing_authorities") or []
    return {"schema": result.get("schema"), "policy_schema": result.get("policy_schema"),
            "policy_hash": result.get("policy_hash"), "policy_review_status": result.get("policy_review_status"),
            "as_of": result.get("as_of"), "state": result.get("state"), "breached": result.get("breached"),
            "approaching": result.get("approaching"), "missing_authorities": miss[:50],
            "missing_authority_count": len(miss), "positions": len(result.get("positions") or []),
            "limits": {k: {"metric": v.get("metric"), "limit": v.get("limit"), "status": v.get("status")}
                       for k, v in (result.get("limits") or {}).items()},
            "exposure": result.get("exposure"),
            "stress": {k: v.get("loss") for k, v in ((result.get("stress") or {}).get("scenarios") or {}).items()}}
