"""A5 per-trial position ledger; preserves every supplied signal attempt."""
import math
from tools.v9.hourly_execution import simulate, HOUR

DAY = 86400
PARAMETERS = ('direction', 'stop', 'target', 'trail', 'be', 'hold')


def replay(signals, rows, quality_schedule, start, end, funding=None, funding_complete=None):
    """One trial per call. Unknown price state locks only that segment.

    This layer consumes preregistered signals; it does not generate or qualify
    them. A single unresolved executed outcome invalidates the full net series.
    """
    if (type(start) is not int or type(end) is not int or start % DAY or end % DAY or end <= start):
        raise ValueError('invalid study window')
    schedule = {}
    for item in quality_schedule:
        day = item['schedule']
        t = day['known_at']
        selected = [r['coin'] for r in day['selected']]
        if (type(t) is not int or t % DAY or t in schedule or day['valid_until'] != t + DAY or
                len(set(selected)) != len(selected) or not set(selected) <= set(rows) or
                type(item['new_entries_allowed']) is not bool):
            raise ValueError('invalid quality schedule')
        schedule[t] = (set(selected), item['new_entries_allowed'])
    if set(schedule) != set(range(start, end, DAY)):
        raise ValueError('quality schedule does not cover exact study window')
    prepared, seen = [], set()
    for ordinal, signal in enumerate(signals):
        t, coin = signal['signal_time'], signal['coin']
        if type(t) is not int or t % HOUR or coin not in rows:
            raise ValueError('invalid signal identity')
        if (signal['direction'] not in (-1, 1) or type(signal['direction']) is bool or
                type(signal['hold']) is not int or signal['hold'] <= 0 or
                not all(math.isfinite(signal[k]) for k in ('stop', 'target', 'trail', 'be')) or
                signal['stop'] <= 0 or min(signal[k] for k in ('target', 'trail', 'be')) < 0):
            raise ValueError('invalid signal parameters')
        identity = (coin, t, signal['direction'])
        if identity in seen:
            raise ValueError('duplicate signal')
        seen.add(identity)
        prepared.append((t, coin, ordinal, signal))
    prepared.sort(key=lambda row: row[:3])
    # Remove future bars at the study boundary, rather than use them to resolve
    # a censored position. Warm-up rows before start cannot become entries.
    bounded_rows = {coin: {t: bar for t, bar in bars.items() if start <= t < end}
                    for coin, bars in rows.items()}
    funding = {} if funding is None else funding
    funding_complete = {} if funding_complete is None else funding_complete
    busy_until, unknown_position, attempts = {}, set(), []
    for t, coin, ordinal, signal in prepared:
        entry = t + HOUR
        rejection = None
        if not start <= entry < end:
            rejection = 'OUTSIDE_ENTRY_WINDOW'
        elif coin in unknown_position:
            rejection = 'BLOCKED_UNKNOWN_POSITION'
        elif entry < busy_until.get(coin, start):
            rejection = 'POSITION_OPEN'
        else:
            selected, allowed = schedule[entry // DAY * DAY]
            if not allowed:
                rejection = 'QUALITY_EMBARGO'
            elif coin not in selected:
                rejection = 'NOT_SELECTED_AT_ENTRY'
        identity = dict(signal_ordinal=ordinal, coin=coin, signal_time=t,
                        entry_time=entry, parameters={k: signal[k] for k in PARAMETERS})
        if rejection:
            attempts.append(dict(identity, status='UNEXECUTED', reason=rejection, net_R=None))
            continue
        outcome = simulate(bounded_rows[coin], t, **{k: signal[k] for k in PARAMETERS},
                           funding=funding.get(coin, {}), funding_complete=funding_complete.get(coin, {}))
        attempts.append(dict(identity, **{k: v for k, v in outcome.items() if k not in identity}))
        if outcome['status'] == 'UNRESOLVED':
            unknown_position.add(coin)
        elif outcome['status'] in ('RESOLVED', 'UNRESOLVED_FUNDING'):
            busy_until[coin] = outcome['exit_time']
    unresolved = sum(a['status'].startswith('UNRESOLVED') for a in attempts)
    days = list(range(start, end + 1, DAY))
    daily = dict.fromkeys(days, None if unresolved else 0.)
    if not unresolved:
        for attempt in attempts:
            if attempt['status'] == 'RESOLVED':
                day = attempt['exit_time'] // DAY * DAY
                if day not in daily or not math.isfinite(attempt['net_R']):
                    raise ValueError('invalid resolved outcome')
                daily[day] += attempt['net_R']
    return dict(attempts=attempts, unresolved_executed_outcomes=unresolved,
                net_series_available=not unresolved,
                daily_net_R=[dict(day=t, net_R=daily[t]) for t in days],
                segments_locked_by_unknown_position=sorted(unknown_position))
