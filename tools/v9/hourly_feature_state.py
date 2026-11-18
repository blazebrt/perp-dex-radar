"""Causal continuity/warm-up boundaries for A5; no indicator or signal replay."""
import math

HOUR = 3600
ALIASES = {'FAIL_BRK', 'FUND_CARRY', 'PULLBACK', 'LIQ_FLUSH', 'BTC_LEAD', 'VOL_SPIKE', 'FUND_FADE'}


def runs(rows):
    """Return fresh indicator sessions; zero-trade rows break continuity."""
    result, current = [], []
    previous = None
    for t, row in sorted(rows.items()):
        if type(t) is not int or t < 0 or t % HOUR:
            raise ValueError('invalid hourly grid')
        o, h, l, c, v = (float(row[k]) for k in ('o', 'h', 'l', 'c', 'qv'))
        if (not all(math.isfinite(x) for x in (o, h, l, c, v)) or
                min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c) or v < 0):
            raise ValueError('invalid feature candle')
        if previous is not None and t != previous + HOUR or v == 0:
            if current:
                result.append(current)
                current = []
        if v > 0:
            current.append(t)
        previous = t
    if current:
        result.append(current)
    return result


def readiness(rows, alias, btc_rows=None):
    """Signal-open timestamps eligible after closed-bar minimum warm-up.

    This is only a ceiling; daily membership, original signal predicates and
    every required finite indicator still apply. BTC context never grants entry.
    """
    if alias not in ALIASES:
        raise ValueError('unknown registered definition')
    sessions = runs(rows)
    if alias == 'BTC_LEAD':
        if btc_rows is None:
            raise ValueError('BTC context required')
        btc_valid = {t for session in runs(btc_rows) for t in session}
        own_valid = {t for session in sessions for t in session}
        sessions = runs({t: rows[t] for t in own_valid & btc_valid})
    ready = set()
    for session in sessions:
        first_four = ((session[0] + 4 * HOUR - 1) // (4 * HOUR)) * 4 * HOUR
        for count, t in enumerate(session, 1):
            if count < 720:
                continue
            complete_four = max(0, (t + HOUR - first_four) // (4 * HOUR))
            if alias != 'PULLBACK' or complete_four >= 200:
                ready.add(t)
    return ready
