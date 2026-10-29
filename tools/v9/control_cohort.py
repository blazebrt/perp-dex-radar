"""A6.1 archive-derived diagnostic cohorts; no outcome or authority calculation."""
import bisect
import hashlib
import json
import math

VERSION = 'v9.a6-cohort/1'
DAY = 86400
COUNT = 50
AGE_EDGES = (30, 90, 180, 365, 730)
LIQUIDITY_EDGES = (5_000_000, 10_000_000, 25_000_000, 50_000_000, 100_000_000)


def number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def features(row, decision):
    """Return fixed bins, or explicit unavailability; first bar is only an age proxy."""
    if row.get('provenance') != 'ARCHIVE_RECONSTRUCTION':
        return None
    first, known = row.get('segment_first_bar'), row.get('first_bar_known_at')
    end, observed = row.get('volume_window_end'), row.get('volume_known_at')
    volume = row.get('mean_daily_quote_volume')
    if not all(type(v) is int and 0 <= v <= decision for v in (first, known, end, observed)):
        return None
    if known < first or observed < end or end != decision // DAY * DAY:
        return None
    if row.get('volume_window_start') != end - 7 * DAY or row.get('volume_observations') != 42:
        return None
    if not number(volume) or volume < LIQUIDITY_EDGES[0] or first > end - 7 * DAY:
        return None
    age = (decision - first) / DAY
    if age < AGE_EDGES[0]:
        return None
    return dict(archive_age_bucket=bisect.bisect_right(AGE_EDGES, age)-1,
                liquidity_bucket=bisect.bisect_right(LIQUIDITY_EDGES, volume)-1)


def identity(row):
    return all(isinstance(row.get(k), str) and row[k].strip() == row[k] and row[k]
               for k in ('asset', 'source_symbol'))


def select(trial_id, signal, candidates):
    if not isinstance(trial_id, str) or not trial_id:
        raise ValueError('trial identity required')
    decision, direction = signal.get('decision_time'), signal.get('direction')
    if not identity(signal) or type(decision) is not int or decision < 0 or type(direction) is not int or direction not in (-1, 1):
        raise ValueError('invalid signal identity/time/direction')
    result = dict(schema=VERSION, trial_id=trial_id, signal_asset=signal['asset'],
                  decision_time=decision, direction=direction, controls=[], required_controls=COUNT,
                  full_matched_authority=False, promotion_authority=False,
                  age_interpretation='ARCHIVE_SEGMENT_AGE_NOT_VERIFIED_LISTING_AGE',
                  eligible_candidates=0, feature_unavailable=0, bucket_mismatched=0,
                  same_symbol_excluded=0, matching_candidates=0)
    bins = features(signal, decision)
    if signal.get('eligible') is not True or bins is None:
        return dict(result, status='UNAVAILABLE_SIGNAL_FEATURES', control_count=0)
    result['signal_buckets'] = bins
    eligible = [r for r in candidates if r.get('decision_time') == decision
                and type(r.get('decision_time')) is int and r.get('direction') == direction
                and type(r.get('direction')) is int and r.get('eligible') is True]
    if any(not identity(r) for r in eligible):
        raise ValueError('invalid eligible candidate identity')
    if any(len({r[k] for r in eligible}) != len(eligible) for k in ('asset', 'source_symbol')):
        raise ValueError('ambiguous duplicate asset or source symbol')
    result['eligible_candidates'] = len(eligible)
    selected = []
    for row in eligible:
        if row['asset'] == signal['asset'] or row['source_symbol'] == signal['source_symbol']:
            result['same_symbol_excluded'] += 1
            continue
        other = features(row, decision)
        if other is None:
            result['feature_unavailable'] += 1
            continue
        if other != bins:
            result['bucket_mismatched'] += 1
            continue
        key = [VERSION, trial_id, decision, direction, signal['asset'], row['asset']]
        rank = hashlib.sha256(json.dumps(key, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        # Retain only selection-time inputs, never arbitrary outcome fields.
        provenance = {k: row[k] for k in ('asset', 'source_symbol', 'decision_time', 'direction',
                      'eligible', 'provenance', 'segment_first_bar', 'first_bar_known_at',
                      'volume_window_start', 'volume_window_end', 'volume_known_at',
                      'volume_observations', 'mean_daily_quote_volume')}
        selected.append(dict(asset=row['asset'], rank_sha256=rank, features=provenance, buckets=other))
    selected.sort(key=lambda r: (r['rank_sha256'], r['asset']))
    result['matching_candidates'] = len(selected)
    result['controls'] = selected[:COUNT]
    result['control_count'] = len(result['controls'])
    result['status'] = 'DIAGNOSTIC_COHORT_50' if len(selected) >= COUNT else 'INSUFFICIENT_CONTROLS'
    return result
