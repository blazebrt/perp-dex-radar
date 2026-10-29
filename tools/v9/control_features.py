"""Pure A6 diagnostic feature windows; no archive acceptance or signal authority."""
import hashlib
import json
import math

BAR, DAY = 14400, 86400


def snapshot(segment, times, volumes, decision, direction, eligible, disputed_opens):
    if (type(decision) is not int or decision < 0 or type(direction) is not int
            or direction not in (-1, 1) or type(eligible) is not bool):
        raise ValueError('invalid decision, direction or eligibility')
    if any(not isinstance(segment.get(k), str) or not segment[k]
           or segment[k].strip() != segment[k] for k in ('asset', 'source_symbol')):
        raise ValueError('invalid segment identity')
    first = segment.get('first_bar')
    if type(first) is not int or first < 0 or first % BAR:
        raise ValueError('invalid first bar')
    if len(times) != len(volumes) or not times or first != times[0]:
        raise ValueError('source rows do not match segment first bar')
    if any(type(t) is not int or t < 0 or t % BAR for t in times):
        raise ValueError('invalid bar timestamp')
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('duplicate or unordered source rows')
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v < 0 for v in volumes):
        raise ValueError('invalid quote volume')
    if disputed_opens is None:
        raise ValueError('explicit dispute inventory required')
    disputed = list(disputed_opens)
    if any(type(t) is not int or t < 0 or t % BAR for t in disputed) or len(set(disputed)) != len(disputed):
        raise ValueError('invalid dispute inventory')
    end = decision // DAY * DAY
    start = end - 7 * DAY
    expected = set(range(start, end, BAR))
    rows = [(t, v) for t, v in zip(times, volumes) if start <= t < end]
    missing = sorted(expected - {t for t, _ in rows})
    conflicts = sorted(expected & set(disputed))
    reasons = []
    if missing:
        reasons.append('UNAVAILABLE_MISSING_VOLUME_BAR')
    if conflicts:
        reasons.append('UNAVAILABLE_DISPUTED_VOLUME_BAR')
    if first + BAR > decision:
        reasons.append('UNAVAILABLE_SEGMENT_NOT_YET_OBSERVED')
    window = dict(rows=rows, disputed_opens=conflicts)
    digest = hashlib.sha256(json.dumps(window, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    volume = None if reasons else math.fsum(v for _, v in rows) / 7
    if volume is not None and not math.isfinite(volume):
        raise ValueError('nonfinite aggregate volume')
    return dict(asset=segment['asset'], source_symbol=segment['source_symbol'],
                decision_time=decision, direction=direction, eligible=eligible,
                provenance='ARCHIVE_RECONSTRUCTION', segment_first_bar=first,
                first_bar_known_at=first + BAR, volume_window_start=start, volume_window_end=end,
                volume_known_at=end, volume_observations=len(rows), mean_daily_quote_volume=volume,
                feature_status='UNAVAILABLE' if reasons else 'DIAGNOSTIC_WINDOW_AVAILABLE',
                reasons=reasons, missing_opens=missing, disputed_opens=conflicts,
                window_sha256=digest, quality_scope='KNOWN_DISPUTES_ONLY_NOT_EXHAUSTIVE',
                quality_selection='RETROSPECTIVE', signal_quality_qualified=False,
                full_matched_authority=False, promotion_authority=False)
