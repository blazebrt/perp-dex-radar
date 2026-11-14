"""Stream original generator outputs before execution filtering; diagnostic only."""
import bisect
import hashlib
import json
import math
from numbers import Real

from tools.v9 import control_features as F

KEYS = ('i', 'j', 'd', 'stop', 'target', 'trail', 'be', 'hold')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def numeric(value, integral=False):
    require(not isinstance(value, bool) and isinstance(value, Real) and math.isfinite(value), 'invalid signal number')
    require(not integral or value == int(value), 'fractional signal index/direction/hold')
    return int(value) if integral else float(value)


class SegmentView:
    """Index already source-validated rows without replacing missing observations."""
    def __init__(self, loaded):
        self.segment = dict(loaded['segment'])
        self.times = list(loaded['times'])
        self.volumes = list(loaded['volumes'])
        self.disputed = sorted(loaded['disputed_opens'])
        self.source_sha256 = loaded['source_sha256']
        # Validate complete inputs once using the same strict helper.
        require(self.times, 'empty segment')
        F.snapshot(self.segment, self.times, self.volumes, self.times[-1]+F.BAR, 1, False, self.disputed)

    def snapshot(self, decision, direction, eligible):
        end = decision // F.DAY * F.DAY
        lo = bisect.bisect_left(self.times, end-7*F.DAY)
        hi = bisect.bisect_left(self.times, end)
        times, volumes = self.times[lo:hi], self.volumes[lo:hi]
        if not times or times[0] != self.times[0]:
            times = [self.times[0]] + times
            volumes = [self.volumes[0]] + volumes
        return F.snapshot(self.segment, times, volumes, decision, direction, eligible, self.disputed)

    def history(self, decision):
        observed = bisect.bisect_left(self.times, decision)
        expected = max(0, (decision-self.times[0]) // F.BAR)
        return dict(own_segment_missing_bars=max(0, expected-observed),
                    own_segment_disputed_bars=bisect.bisect_left(self.disputed, decision),
                    scope='OWN_SEGMENT_PREFIX_NOT_COMPLETE_INDICATOR_PROOF',
                    signal_quality_qualified=False)


def project(trial_id, raw, panel_times, panel_assets, eligibility, segments, start, end, emit):
    """Emit every in-window ordinal; caller retains partial output if validation fails."""
    require(isinstance(trial_id, str) and trial_id, 'trial ID required')
    require(set(raw) == set(KEYS), 'generator schema mismatch')
    n = len(raw['i'])
    require(all(len(raw[k]) == n for k in KEYS), 'generator array lengths differ')
    times = [numeric(t, True) for t in panel_times]
    require(times and all(t >= 0 and t % F.BAR == 0 for t in times)
            and all(b-a == F.BAR for a,b in zip(times,times[1:])), 'panel calendar mismatch')
    require(len(set(panel_assets)) == len(panel_assets) and all(a in segments for a in panel_assets), 'panel segment identities mismatch')
    require(len(eligibility) == len(times) and all(len(r) == len(panel_assets) for r in eligibility), 'eligibility shape mismatch')
    require(type(start) is int and type(end) is int and start <= end
            and start >= times[0] and end <= times[-1]+F.BAR, 'invalid population window')
    summary = dict(generated=n, before_window=0, after_window=0, retained=0,
                   full_matched_authority=False, promotion_authority=False)
    for ordinal in range(n):
        i,j,d,hold = (numeric(raw[k][ordinal], True) for k in ('i','j','d','hold'))
        geometry = {k:numeric(raw[k][ordinal]) for k in ('stop','target','trail','be')}
        require(0 <= i < len(times) and 0 <= j < len(panel_assets) and d in (-1,1), 'invalid generator index/direction')
        require(hold > 0 and geometry['stop'] > 0 and all(geometry[k] >= 0 for k in ('target','trail','be')), 'invalid signal geometry')
        decision = times[i]+F.BAR
        if decision < start:
            summary['before_window'] += 1
            continue
        if decision > end:
            summary['after_window'] += 1
            continue
        asset = panel_assets[j]
        view = segments[asset]
        require(view.segment['asset'] == asset, 'source segment does not match panel')
        original_eligible = eligibility[i][j]
        require(original_eligible in (True,False), 'invalid original eligibility')
        eligible = bool(original_eligible)
        feature = view.snapshot(decision,d,eligible)
        identity = [trial_id,ordinal,asset,decision,d]
        signal_id = hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()
        emit(dict(signal_id=signal_id, trial_id=trial_id, source_ordinal=ordinal,
                  asset=asset, decision_time=decision, direction=d, panel_i=i, panel_j=j,
                  geometry=dict(geometry,hold=hold), original_eligible=eligible,
                  next_entry_bar_observed=bool(i+1 < len(times) and
                      bisect.bisect_left(view.times,decision) < len(view.times) and
                      view.times[bisect.bisect_left(view.times,decision)] == decision),
                  features=feature, source_sha256=view.source_sha256, history=view.history(decision),
                  full_matched_authority=False,promotion_authority=False))
        summary['retained'] += 1
    require(summary['retained']+summary['before_window']+summary['after_window']==n, 'population accounting mismatch')
    return summary
