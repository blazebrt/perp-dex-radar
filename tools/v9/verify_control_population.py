"""Independently reconcile A6 rows with original generator arrays and source bars.

No extraction, projection or feature-construction helpers are imported.
Callers must separately bind the archive, original generator and panel inputs.
"""
import bisect
import hashlib
import json
import math
from numbers import Real

BAR, DAY = 14400, 86400
KEYS = {'i', 'j', 'd', 'stop', 'target', 'trail', 'be', 'hold'}


def check(ok, message):
    if not ok:
        raise ValueError(message)


def number(value, integral=False):
    check(isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value), 'invalid raw signal number')
    check(not integral or int(value)==value, 'fractional raw signal number')
    return int(value) if integral else float(value)


def digest(value):
    return hashlib.sha256(json.dumps(value,separators=(',', ':'),allow_nan=False).encode()).hexdigest()


class Source:
    """Index independently supplied source rows once; reconstruct exact windows."""
    def __init__(self, metadata, times, volumes, disputes, source_sha256):
        self.meta = dict(metadata)
        self.times = list(times)
        values = list(volumes)
        check(self.times and len(self.times)==len(values), 'source shape mismatch')
        check(all(type(t) is int and t>=0 and t % BAR==0 for t in self.times)
              and all(a<b for a,b in zip(self.times,self.times[1:])), 'source calendar mismatch')
        check(self.times[0]==self.meta['first_bar'], 'source first bar mismatch')
        check(all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0 for v in values),
              'source volume mismatch')
        self.rows = dict(zip(self.times,values))
        self.disputes = sorted(disputes)
        check(len(set(self.disputes))==len(self.disputes) and
              all(type(t) is int and t>=0 and t % BAR==0 for t in self.disputes), 'invalid source disputes')
        self.dispute_set = set(self.disputes)
        self.sha = source_sha256

    def reconstruct(self, decision, direction, eligible):
        end = decision-decision % DAY
        start = end-7*DAY
        expected = range(start,end,BAR)
        missing = [t for t in expected if t not in self.rows]
        disputed = [t for t in expected if t in self.dispute_set]
        rows = [(t,self.rows[t]) for t in expected if t in self.rows]
        reasons = []
        if missing: reasons.append('UNAVAILABLE_MISSING_VOLUME_BAR')
        if disputed: reasons.append('UNAVAILABLE_DISPUTED_VOLUME_BAR')
        first = self.times[0]
        if first+BAR > decision: reasons.append('UNAVAILABLE_SEGMENT_NOT_YET_OBSERVED')
        features = dict(asset=self.meta['asset'], source_symbol=self.meta['source_symbol'],
            decision_time=decision, direction=direction, eligible=eligible, provenance='ARCHIVE_RECONSTRUCTION',
            segment_first_bar=first, first_bar_known_at=first+BAR, volume_window_start=start, volume_window_end=end,
            volume_known_at=end, volume_observations=len(rows),
            mean_daily_quote_volume=None if reasons else math.fsum(v for _,v in rows)/7,
            feature_status='UNAVAILABLE' if reasons else 'DIAGNOSTIC_WINDOW_AVAILABLE', reasons=reasons,
            missing_opens=missing, disputed_opens=disputed, window_sha256=digest(dict(rows=rows,disputed_opens=disputed)),
            quality_scope='KNOWN_DISPUTES_ONLY_NOT_EXHAUSTIVE', quality_selection='RETROSPECTIVE',
            signal_quality_qualified=False, full_matched_authority=False, promotion_authority=False)
        observed = bisect.bisect_left(self.times,decision)
        expected_count = max(0,(decision-first)//BAR)
        history = dict(own_segment_missing_bars=max(0,expected_count-observed),
            own_segment_disputed_bars=bisect.bisect_left(self.disputes,decision),
            scope='OWN_SEGMENT_PREFIX_NOT_COMPLETE_INDICATOR_PROOF', signal_quality_qualified=False)
        return features, history


def verify_trial(trial_id, raw, times, assets, eligibility, sources, start, end, retained, population):
    """Verify a successfully extracted trial, consuming retained rows once.

    A failed or hourly-unavailable trial cannot be certified by this function.
    Raw arrays must come from the original generator, not reconstructed output.
    """
    check(set(raw)==KEYS and all(len(raw[k])==len(raw['i']) for k in KEYS), 'raw array schema mismatch')
    times = [number(t,True) for t in times]
    check(times and all(t>=0 and t % BAR==0 for t in times) and
          all(b-a==BAR for a,b in zip(times,times[1:])), 'panel calendar mismatch')
    check(len(set(assets))==len(assets) and all(a in sources for a in assets), 'panel source roster mismatch')
    check(len(eligibility)==len(times) and all(len(row)==len(assets) for row in eligibility), 'eligibility shape mismatch')
    check(type(start) is int and type(end) is int and times[0]<=start<=end<=times[-1]+BAR, 'window mismatch')
    counts = dict(generated=len(raw['i']), before_window=0, after_window=0, retained=0,
                  full_matched_authority=False, promotion_authority=False)
    stream = iter(retained)
    sentinel = object()
    for ordinal in range(len(raw['i'])):
        i,j,d,hold = [number(raw[k][ordinal],True) for k in ('i','j','d','hold')]
        geometry = {k:number(raw[k][ordinal]) for k in ('stop','target','trail','be')}
        check(0<=i<len(times) and 0<=j<len(assets) and d in (-1,1) and hold>0 and
              geometry['stop']>0 and all(geometry[k]>=0 for k in ('target','trail','be')), 'invalid raw geometry/index')
        decision = times[i]+BAR
        if decision < start:
            counts['before_window'] += 1
            continue
        if decision > end:
            counts['after_window'] += 1
            continue
        asset = assets[j]
        source = sources[asset]
        check(source.meta['asset']==asset and eligibility[i][j] in (True,False), 'source/eligibility mismatch')
        eligible = bool(eligibility[i][j])
        feature,history = source.reconstruct(decision,d,eligible)
        expected = dict(signal_id=digest([trial_id,ordinal,asset,decision,d]), trial_id=trial_id,
            source_ordinal=ordinal, asset=asset, decision_time=decision, direction=d, panel_i=i,panel_j=j,
            geometry=dict(geometry,hold=hold), original_eligible=eligible,
            next_entry_bar_observed=i+1<len(times) and decision in source.rows,
            features=feature, source_sha256=source.sha, history=history,
            full_matched_authority=False,promotion_authority=False)
        row = next(stream,sentinel)
        check(row is not sentinel, 'missing generated ordinal '+str(ordinal))
        # Canonical JSON comparison also rejects bool/int substitutions and extra keys.
        check(json.dumps(row,sort_keys=True,allow_nan=False)==json.dumps(expected,sort_keys=True,allow_nan=False),
              'source/generator mismatch at ordinal '+str(ordinal))
        counts['retained'] += 1
    check(next(stream,sentinel) is sentinel, 'extra retained signal')
    check(json.dumps(population,sort_keys=True,allow_nan=False)==json.dumps(counts,sort_keys=True,allow_nan=False),
          'generator population counts mismatch')
    return dict(trial_id=trial_id, **counts, generator_array_projection_verified=True,
                source_feature_values_verified=True, original_generator_mathematics_verified=False,
                externally_bound_inputs_verified=False)
