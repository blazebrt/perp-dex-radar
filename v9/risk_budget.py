"""Constrained incremental risk budgeting; never rebalance or mutate a book."""
import math
import copy
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


# Numerical/resource bounds, not fitted trading thresholds. Failure is explicit.
REBALANCE_NUMERICS = dict(max_positions=64, max_sweeps=2048, tolerance=1e-8, max_scale_steps=32)


def _budget_weights(cov, budgets):
    """Positive coordinate descent on .5*x'C*x - sum(b*log(x))."""
    n = len(budgets)
    vol = [math.sqrt(cov[i][i]) for i in range(n)]
    corr = [[cov[i][j]/(vol[i]*vol[j]) for j in range(n)] for i in range(n)]
    b = [v/math.fsum(budgets) for v in budgets]
    x = [math.sqrt(v) for v in b]
    for sweep in range(REBALANCE_NUMERICS['max_sweeps']):
        for i in range(n):
            other = math.fsum(corr[i][j]*x[j] for j in range(n) if j != i)
            root = math.sqrt(other*other + 4*corr[i][i]*b[i])
            x[i] = (2*b[i]/(root+other) if other >= 0 else (root-other)/(2*corr[i][i]))
        rc = [x[i]*math.fsum(corr[i][j]*x[j] for j in range(n)) for i in range(n)]
        total = math.fsum(rc)
        if not finite(total) or total <= 0 or not all(finite(v) and v > 0 for v in x):
            return None
        error = max(abs(rc[i]/total-b[i]) for i in range(n))
        if error <= REBALANCE_NUMERICS['tolerance'] and all(v > 0 for v in rc):
            return [x[i]/vol[i] for i in range(n)], b, sweep+1
    return None


def rebalance(portfolio, multipliers):
    """Read-only, reduction-only whole-book target, including modeled turnover costs."""
    unavailable = dict(status='UNAVAILABLE', reason=None, trade_authorization=False,
                       existing_positions_changed=False, whole_book_parity=False,
                       numerical_policy=dict(REBALANCE_NUMERICS))
    try:
        return _rebalance(portfolio, multipliers, unavailable)
    except (ArithmeticError, ValueError):
        return dict(unavailable, reason='NUMERICAL_INPUT_UNAVAILABLE')


def _rebalance(portfolio, multipliers, unavailable):
    def fail(reason):
        return dict(unavailable, reason=reason)
    if not isinstance(portfolio, dict) or not isinstance(multipliers, dict):
        return fail('BOOK_UNAVAILABLE')
    policy = PR.load_policy()
    before = PR.evaluate(portfolio, policy)
    rows = before.get('positions') or []
    if before.get('state') == PR.UNEVALUABLE or any(r.get('status') != 'VALID' for r in rows):
        return fail('BOOK_UNEVALUABLE')
    if not rows:
        return dict(unavailable, status='EMPTY', reason='NO_GOVERNED_POSITIONS')
    if len(rows) > REBALANCE_NUMERICS['max_positions']:
        return fail('POSITION_RESOURCE_LIMIT')
    if any(not r.get('entered') or r.get('actionability') != PR.ACTIONABLE for r in rows):
        return fail('POSITION_ACTIONABILITY_UNAVAILABLE')
    rows = sorted(rows, key=lambda r: r['id'])
    if len({r['id'] for r in rows}) != len(rows):
        return fail('DUPLICATE_POSITION_ID')
    equity = before.get('equity')
    sizing = portfolio.get('sizing')
    risk = sizing.get('risk_per_trade') if isinstance(sizing, dict) else None
    if not finite(equity) or equity <= 0 or not finite(risk) or risk <= 0:
        return fail('SIZING_INPUT_UNAVAILABLE')
    tiers = [multipliers.get(r['id']) for r in rows]
    if any(not finite(t) or not 0 < t <= 1 for t in tiers):
        return fail('EXISTING_TIER_UNKNOWN')
    rates = [r['liquidity'].get('slippage_rate') for r in rows]
    if any(not finite(v) or v < 0 for v in rates):
        return fail('TURNOVER_COST_UNAVAILABLE')
    fee = policy['costs']['fee_taker']['value']
    names = sorted({r['asset'] for r in rows})
    source, now = portfolio.get('returns'), portfolio.get('as_of')
    if not isinstance(source, dict) or type(now) is not int or now <= 0:
        return fail('RETURNS_UNAVAILABLE')
    series = {a: PR._returns(source.get(a), now, policy) for a in names}
    if any(not v for v in series.values()):
        return fail('RETURNS_UNAVAILABLE')
    keys = sorted(set.intersection(*(set(v) for v in series.values())))
    dep = policy['dependence']
    if len(keys) < dep['min_overlap_bars']['value']:
        return fail('COMMON_HISTORY_INSUFFICIENT')
    if now-keys[-1] >= dep['bar_seconds']['value']:
        return fail('COMMON_HISTORY_STALE')
    means = {a: math.fsum(series[a][k] for k in keys)/len(keys) for a in names}
    vectors = [[r['direction']*(series[r['asset']][k]-means[r['asset']]) for k in keys] for r in rows]
    cov = [[math.fsum(a*b for a,b in zip(x,y))/(len(keys)-1) for y in vectors] for x in vectors]
    if any(not finite(v) for row in cov for v in row) or any(cov[i][i] <= 0 for i in range(len(rows))):
        return fail('COVARIANCE_UNAVAILABLE')
    solved = _budget_weights(cov, [t*t for t in tiers])
    if solved is None:
        return fail('PARITY_DID_NOT_CONVERGE')
    shape, target_shares, sweeps = solved
    caps = [min(r['notional_usd'], equity*risk*t/r['stop_distance']) for r,t in zip(rows,tiers)]
    if any(not finite(v) or v <= 0 for v in caps):
        return fail('POSITION_CAP_UNAVAILABLE')
    scale = min(cap/x for cap,x in zip(caps,shape))
    originals = {p['id']: p for p in portfolio['positions']}
    for step in range(REBALANCE_NUMERICS['max_scale_steps']):
        targets = [min(cap, scale*x) for cap,x in zip(caps,shape)]
        trims = [max(0., r['notional_usd']-t) for r,t in zip(rows,targets)]
        fees = math.fsum(v*fee for v in trims)
        slippage = math.fsum(v*s for v,s in zip(trims,rates))
        remaining_equity = equity-fees-slippage
        if not finite(remaining_equity) or remaining_equity <= 0:
            return fail('TURNOVER_COST_EXCEEDS_EQUITY')
        model = copy.deepcopy(portfolio)
        model['equity'] = remaining_equity
        model['positions'] = []
        for r,t in zip(rows,targets):
            p = copy.deepcopy(originals[r['id']])
            for k in ('quantity','notional','risk_fraction'):
                p.pop(k,None)
            p['notional'] = t
            model['positions'].append(p)
        after = PR.evaluate(model, policy)
        caps_hold = all(t*r['stop_distance']/remaining_equity <= risk*m for r,t,m in zip(rows,targets,tiers))
        if after.get('state') == PR.WITHIN and caps_hold:
            rc = [targets[i]*math.fsum(cov[i][j]*targets[j] for j in range(len(rows))) for i in range(len(rows))]
            total = math.fsum(rc)
            if not finite(total) or total <= 0 or any(not finite(v) or v <= 0 for v in rc):
                return fail('PARITY_VERIFICATION_FAILED')
            shares = [v/total for v in rc]
            error = max(abs(a-b) for a,b in zip(shares,target_shares))
            if error > REBALANCE_NUMERICS['tolerance']:
                return fail('PARITY_VERIFICATION_FAILED')
            return dict(unavailable, status='MODEL_WITHIN_LIMITS', reason=None, whole_book_parity=True,
                        source_as_of=now, common_returns=len(keys), last_return_end=keys[-1], sweeps=sweeps,
                        uniform_scale_steps=step, max_share_error=error, equity_before=equity,
                        modeled_equity_after_costs=remaining_equity, turnover_usd=math.fsum(trims),
                        estimated_fees_usd=fees, estimated_slippage_usd=slippage,
                        phase10_after=PR.audit_summary(after), reductions_only=True,
                        positions=[dict(id=r['id'], asset=r['asset'], strategy=r['strategy'], direction=r['direction'],
                                        current_notional_usd=r['notional_usd'], target_notional_usd=t,
                                        reduction_usd=trim, tier_multiplier=tier,
                                        target_risk_share=b, modeled_risk_share=a)
                                   for r,t,trim,tier,b,a in zip(rows,targets,trims,tiers,target_shares,shares)],
                        limitations=['Hypothetical targets at current marks; no orders or journal changes.',
                                     'Costs use the existing fee/slippage model, not guaranteed fills.',
                                     'Venue lot sizes, minimum orders and execution sequencing are not modeled.',
                                     'Costs are deducted from the supplied paper account equity; no live NAV is inferred.'])
        scale *= .5
    return fail('NO_WITHIN_LIMITS_TARGET')
