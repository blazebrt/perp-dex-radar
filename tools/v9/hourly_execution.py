"""A5 observable execution kernel; no signal generation or market replay."""
import math

HOUR = 3600
TAKER = 0.00045
MAKER = 0.00015
SLIP = 0.001


def simulate(rows, signal_time, direction, stop, target=0., trail=0., be=0., hold=24,
             funding=None, funding_complete=None, entry_allowed=True):
    """Rows keyed by UTC hour; funding applies at hourly openings after entry.

    Completeness is evidence supplied by the adapter, never inferred here.
    Unknown price state must block later entries in the caller's batch ledger.
    """
    if (type(signal_time) is not int or signal_time % HOUR or direction not in (-1, 1) or
            type(direction) is bool or type(hold) is not int or hold <= 0 or
            not all(math.isfinite(x) for x in (stop, target, trail, be)) or
            stop <= 0 or min(target, trail, be) < 0 or type(entry_allowed) is not bool):
        raise ValueError('invalid execution parameters')
    funding = {} if funding is None else funding
    funding_complete = {} if funding_complete is None else funding_complete
    entry_time = signal_time + HOUR
    result = dict(signal_time=signal_time, entry_time=entry_time, direction=direction,
                  status='UNEXECUTED', reason=None, entry_price=None, exit_time=None,
                  exit_price=None, gross_R=None, net_R=None, funding_R=None,
                  uncertainty_time=None, price_path_known=False, funding_path_known=True)
    if not entry_allowed:
        return dict(result, reason='ENTRY_GATE')

    def observed(t):
        row = rows.get(t)
        if row is None:
            return None
        o, h, l, c, v = (float(row[k]) for k in ('o', 'h', 'l', 'c', 'qv'))
        if (not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or
                h < max(o, c) or l > min(o, c) or v < 0):
            raise ValueError('invalid observed candle')
        return (o, h, l, c) if v > 0 else None

    first = observed(entry_time)
    if first is None:
        return dict(result, reason='UNOBSERVABLE_ENTRY', uncertainty_time=entry_time)
    entry = first[0]; risk = entry * stop
    stop_price = entry - direction * risk
    initial_stop = stop_price
    target_price = entry + direction * target * risk
    best = entry
    funding_sum = 0.
    funding_known = True
    first_funding_unknown = None
    result.update(entry_price=entry, status='UNRESOLVED')
    for offset in range(hold):
        t = entry_time + offset * HOUR
        bar = observed(t)
        if bar is None:
            return dict(result, reason='UNOBSERVABLE_PRICE_PATH', price_uncertainty_time=t,
                        uncertainty_time=t if first_funding_unknown is None else first_funding_unknown,
                        funding_path_known=False)
        amount = funding.get(t)
        if amount is not None and not math.isfinite(amount):
            raise ValueError('nonfinite funding')
        if funding_complete.get(t) is not True or amount is None:
            funding_known = False
            if first_funding_unknown is None:
                first_funding_unknown = t
        elif offset:
            funding_sum += amount
        o, h, l, c = bar
        exit_price = None; reason = None
        if offset and direction * (o - stop_price) <= 0:
            exit_price, reason = o, 'GAP_STOP'
        elif (l <= stop_price if direction > 0 else h >= stop_price):
            exit_price = stop_price
            reason = 'TRAIL_STOP' if direction * (stop_price - initial_stop) > 0 else 'STOP'
        elif target > 0 and (h >= target_price if direction > 0 else l <= target_price):
            exit_price, reason = target_price, 'TARGET'
        elif offset == hold - 1:
            exit_price, reason = c, 'TIME'
        if exit_price is not None:
            gross = direction * (exit_price - entry) / entry
            cost = TAKER + SLIP + (MAKER if reason == 'TARGET' else TAKER + SLIP)
            funding_cost = direction * funding_sum
            return dict(result, status='RESOLVED' if funding_known else 'UNRESOLVED_FUNDING',
                        reason=reason, exit_time=t + HOUR, exit_price=exit_price,
                        price_path_known=True, funding_path_known=funding_known,
                        uncertainty_time=first_funding_unknown, gross_R=gross / stop,
                        net_R=(gross - cost - funding_cost) / stop if funding_known else None,
                        funding_R=funding_cost / stop if funding_known else None)
        if trail > 0:
            best = max(best, c) if direction > 0 else min(best, c)
            proposed = best - direction * entry * trail
            stop_price = max(stop_price, proposed) if direction > 0 else min(stop_price, proposed)
        favorable = (h - entry) / risk if direction > 0 else (entry - l) / risk
        if be > 0 and favorable >= be:
            stop_price = max(stop_price, entry) if direction > 0 else min(stop_price, entry)
    raise AssertionError('unreachable hold termination')
