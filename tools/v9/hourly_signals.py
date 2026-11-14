"""Session-reset adapter for the registered hourly signal definitions.

No market-data driver: FUND_CARRY is explicitly unavailable pending a compatible
causal quorum decision. Other definitions call the unchanged registered code.
"""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/research'))
import qstrat
from tools.v9 import census_plan
from tools.v9 import hourly_feature_state as S


def registered():
    plan = json.loads((ROOT / 'research/v9/census_replay_plan.json').read_bytes())
    if plan != census_plan.build():
        raise ValueError('registered trial/code bindings changed')
    return {alias: trial for trial in plan['trials'] if trial['archive_requirement'] == 'hourly'
            for alias in trial['aliases']}


def features(times, columns, funding=None):
    """Fresh qstrat features for one complete, contiguous positive-volume session."""
    times = list(times)
    if len(times) < 720 or times != list(range(times[0], times[-1] + S.HOUR, S.HOUR)):
        raise ValueError('feature session is short or noncontiguous')
    for data in columns:
        if S.runs({t: data[t] for t in times}) != [times]:
            raise ValueError('feature session contains unavailable observations')
    p = SimpleNamespace(t=np.asarray(times, dtype=np.int64), T=len(times), N=len(columns),
                        bar=S.HOUR, bar_h=1)
    for source, name in (('o', 'o'), ('h', 'h'), ('l', 'l'), ('c', 'c'), ('qv', 'v')):
        setattr(p, name, np.asarray([[float(data[t][source]) for data in columns] for t in times]))
    # Zero here is only a no-signal sentinel for the legacy event predicate,
    # never a claim that funding is complete or an execution-cost input.
    p.fund = np.zeros((p.T, p.N))
    if funding is not None:
        for i, t in enumerate(times):
            if t in funding:
                p.fund[i, -1] = funding[t]
    return qstrat.Feat(p)


def generate(alias, coin, rows, first_bar, btc_rows=None, funding=None):
    trial = registered().get(alias)
    if trial is None:
        raise ValueError('unknown hourly trial')
    if alias == 'FUND_CARRY':
        return dict(trial_id=trial['trial_id'], status='UNAVAILABLE_CAUSAL_QUORUM_MAPPING', signals=None)
    if type(first_bar) is not int or first_bar < 0 or first_bar % S.HOUR or not isinstance(coin, str) or not coin:
        raise ValueError('invalid segment identity/start')
    if any(t < first_bar for t in rows):
        raise ValueError('row predates segment')
    funding = {} if funding is None else funding
    for t, rate in funding.items():
        if type(t) is not int or t % S.HOUR or not math.isfinite(rate):
            raise ValueError('funding must be finite and exactly hour-aligned')
    sessions = S.runs(rows)
    ready = S.readiness(rows, alias, btc_rows)
    if alias == 'BTC_LEAD':
        if coin == 'BTC':
            return dict(trial_id=trial['trial_id'], status='CONTEXT_ONLY', signals=[])
        valid = {t for session in S.runs(btc_rows) for t in session}
        own = {t for session in sessions for t in session}
        sessions = S.runs({t: rows[t] for t in own & valid})
    output = []
    for times in sessions:
        if not any(t in ready for t in times):
            continue
        columns = [btc_rows, rows] if alias == 'BTC_LEAD' else [rows]
        f = features(times, columns, funding)
        allowed = np.asarray([t in ready and t + S.HOUR - first_bar >= 30 * 86400 for t in times])
        f.elig[:, -1] &= allowed
        if alias == 'BTC_LEAD':
            f.elig[:, 0] = False
        if alias == 'FUND_FADE':
            # Only a recorded event can trigger a funding-dependent signal.
            f.elig[:, -1] &= np.asarray([t in funding and funding[t] != 0 for t in times])
        signals = getattr(qstrat, trial['implementation'])(f, **trial['params'])
        for k, i in enumerate(signals['i']):
            if int(signals['j'][k]) != len(columns) - 1:
                raise ValueError('context column emitted trade signal')
            row = dict(coin=coin, signal_time=int(f.p.t[int(i)]),
                       direction=int(signals['d'][k]), hold=int(signals['hold'][k]))
            row.update({key: float(signals[key][k]) for key in ('stop', 'target', 'trail', 'be')})
            if row['signal_time'] not in ready or not all(math.isfinite(row[key]) for key in ('stop', 'target', 'trail', 'be')):
                raise ValueError('unready/nonfinite signal emitted')
            output.append(row)
    return dict(trial_id=trial['trial_id'], status='GENERATED', signals=output,
                continuity_sessions=len(sessions), ready_hours=len(ready),
                funding_cost_completeness_established=False)
