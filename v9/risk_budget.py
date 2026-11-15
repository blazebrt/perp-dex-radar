"""Constrained incremental risk budgeting; never rebalance or mutate a book."""
import math
from v8 import portfolio_risk as PR


def finite(x):
    try:
        return type(x) in (int, float) and math.isfinite(x)
    except OverflowError:
        return False


def allocate(portfolio, asset, direction, stop, cap, tier_multiplier, multipliers):
    try:
        return _allocate(portfolio, asset, direction, stop, cap, tier_multiplier, multipliers)
    except (ArithmeticError, ValueError):
        return dict(status='UNAVAILABLE', risk_fraction=None, reason='NUMERICAL_INPUT_UNAVAILABLE',
                    existing_positions_changed=False, whole_book_parity=False)


def _allocate(portfolio, asset, direction, stop, cap, tier_multiplier, multipliers):
    """Target the new position's tier-weighted share of variance contribution.

    Existing notionals stay fixed. Covariance uses common closed daily returns
    under the unchanged Phase 10 window/coverage policy. Tier budget is the square
    of its size multiplier. A stop-risk cap can prevent reaching the target.
    """
    out = dict(status='UNAVAILABLE', risk_fraction=None, reason=None,
               method='FIXED_BOOK_MARGINAL_VARIANCE_BUDGET', existing_positions_changed=False,
               whole_book_parity=False)

    def fail(reason):
        return dict(out, reason=reason)

    if not (isinstance(portfolio, dict) and isinstance(multipliers, dict) and isinstance(asset, str) and asset
            and type(direction) is int and direction in (-1, 1)
            and finite(stop) and 0 < stop < 1 and finite(cap) and cap > 0
            and finite(tier_multiplier) and 0 < tier_multiplier <= 1):
        return fail('INVALID_SIZING_INPUT')
    policy = PR.load_policy()
    evaluated = PR.evaluate(portfolio, policy)
    rows = evaluated.get('positions') or []
    if evaluated.get('state') == PR.UNEVALUABLE or any(r.get('status') != 'VALID' for r in rows):
        return fail('BOOK_UNEVALUABLE')
    weights, budgets, assets = [], [], []
    for row in rows:
        multiplier = multipliers.get(row.get('id'))
        if not finite(multiplier) or not 0 < multiplier <= 1:
            return fail('EXISTING_TIER_UNKNOWN')
        weight = row.get('leverage')
        if not finite(weight) or weight <= 0:
            return fail('EXISTING_SIZE_UNKNOWN')
        weights.append(weight * row['direction'])
        budgets.append(multiplier ** 2)
        assets.append(row['asset'])
    names = sorted(set(assets + [asset]))
    source = portfolio.get('returns')
    now = portfolio.get('as_of')
    if not isinstance(source, dict) or type(now) is not int or now <= 0:
        return fail('RETURNS_UNAVAILABLE')
    try:
        series = {name: PR._returns(source.get(name), now, policy) for name in names}
    except (ValueError, OverflowError, ZeroDivisionError):
        return fail('RETURNS_INVALID')
    if any(not value for value in series.values()):
        return fail('RETURNS_UNAVAILABLE')
    keys = sorted(set.intersection(*(set(value) for value in series.values())))
    dep = policy['dependence']
    if len(keys) < dep['min_overlap_bars']['value']:
        return fail('COMMON_HISTORY_INSUFFICIENT')
    if now - keys[-1] >= dep['bar_seconds']['value']:
        return fail('COMMON_HISTORY_STALE')
    means = {name: math.fsum(series[name][k] for k in keys) / len(keys) for name in names}
    centered = {name: [series[name][k] - means[name] for k in keys] for name in names}

    def covariance(a, b):
        return math.fsum(x * y for x, y in zip(centered[a], centered[b])) / (len(keys) - 1)

    variance = covariance(asset, asset)
    if not finite(variance) or variance <= 0:
        return fail('VOLATILITY_UNAVAILABLE')
    cap_weight = cap / stop
    if not finite(cap_weight):
        return fail('SIZE_OVERFLOW')
    out.update(common_returns=len(keys), last_return_end=keys[-1], daily_volatility=math.sqrt(variance),
               tier_budget=tier_multiplier ** 2, stop_risk_cap=cap)
    if not rows:
        return dict(out, status='SINGLE_POSITION', risk_fraction=cap, target_share=1.0,
                    actual_share=1.0, whole_book_parity=True, reason=None)
    book_returns = [math.fsum(w * centered[a][i] for a, w in zip(assets, weights)) for i in range(len(keys))]
    old_variance = math.fsum(x*x for x in book_returns) / (len(keys)-1)
    cross = direction * math.fsum(x*y for x, y in zip(book_returns, centered[asset])) / (len(keys)-1)
    if not finite(old_variance) or old_variance <= 0 or not finite(cross):
        return fail('BOOK_VARIANCE_UNAVAILABLE')
    share = tier_multiplier ** 2 / (math.fsum(budgets) + tier_multiplier ** 2)
    # Solve (1-b)*v*x^2 + (1-2*b)*c*x - b*V = 0.
    aa, bb, cc = (1-share)*variance, (1-2*share)*cross, share*old_variance
    disc = bb*bb + 4*aa*cc
    if not finite(disc) or disc <= 0:
        return fail('BUDGET_SOLUTION_UNAVAILABLE')
    root = math.sqrt(disc)
    target = 2*cc/(root+bb) if bb >= 0 else (root-bb)/(2*aa)
    weight = min(cap_weight, target)
    total = old_variance + 2*cross*weight + variance*weight*weight
    contribution = weight*(cross+variance*weight)
    if not all(finite(v) and v > 0 for v in (target, weight, total, contribution)):
        return fail('NONPOSITIVE_RISK_CONTRIBUTION')
    details = []
    for row, a, w, budget in zip(rows, assets, weights, budgets):
        cov_book = math.fsum(x*y for x, y in zip(centered[a], book_returns))/(len(keys)-1)
        rc = w*(cov_book + direction*weight*covariance(a, asset))
        if not finite(rc) or rc < 0:
            return fail('NEGATIVE_EXISTING_RISK_CONTRIBUTION')
        details.append(dict(id=row['id'], actual_share=rc/total,
                            target_share=budget/(math.fsum(budgets)+tier_multiplier**2)))
    return dict(out, status='CAPPED' if cap_weight < target else 'TARGETED', reason=None,
                risk_fraction=min(cap, weight*stop), target_share=share, actual_share=contribution/total,
                target_notional_fraction=target, actual_notional_fraction=weight,
                portfolio_daily_volatility=math.sqrt(total), existing_contributions=details,
                whole_book_parity=False)
