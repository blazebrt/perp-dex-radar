"""A5's causal liquid-universe schedule, built from the pinned four-hour archive.

No hourly prices, future volume, present listing flags or strategy returns are used.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_COMMIT = '4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7'
BAR, DAY = 14400, 86400
PROTOCOL = ROOT / 'docs/v9/phase-a5-hourly-protocol.md'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def daily_candidates(times, volumes, first, cutoffs):
    """Trailing seven *complete* days, known at cutoff; no forward-filled volume."""
    if len(times) != len(volumes) or not times:
        raise ValueError('nonempty matching time and volume arrays required')
    if any(type(t) is not int or t % BAR for t in times):
        raise ValueError('unaligned timestamp')
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError('timestamps must be strictly increasing')
    if first != times[0]:
        raise ValueError('segment first bar mismatch')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or v < 0 for v in volumes):
        raise ValueError('invalid quote volume')
    for cutoff in cutoffs:
        if type(cutoff) is not int or cutoff % DAY:
            raise ValueError('cutoff must be UTC midnight')
        if cutoff - first < 30 * DAY:
            continue
        lo = bisect.bisect_left(times, cutoff - 7 * DAY)
        hi = bisect.bisect_left(times, cutoff)
        # Aligned, unique bars + 42 rows imply every 4h bar is present.
        if hi - lo != 42:
            continue
        volume = math.fsum(volumes[lo:hi]) / 7
        if volume >= 5e6:
            yield cutoff, volume


def build(md):
    md = Path(md)
    universe = json.loads((md / 'universe.json').read_text(encoding='utf8'))
    rows = universe['coins']
    coins = {r['t']: r for r in rows if not r['excluded']}
    if len({r['t'] for r in rows}) != len(rows) or not coins:
        raise ValueError('duplicate or empty universe')
    for name, r in coins.items():
        if not name or '/' in name or '\\' in name or name in ('.', '..'):
            raise ValueError('unsafe coin identity')
        if (type(r['first_bar']) is not int or type(r['last_bar']) is not int or
                r['first_bar'] % BAR or r['last_bar'] % BAR or r['first_bar'] > r['last_bar']):
            raise ValueError('invalid segment bounds')
    expected = {name + '.csv.gz' for name in coins}
    if {p.name for p in (md / 'h4').glob('*.csv.gz')} != expected:
        raise ValueError('archive files do not match the complete research universe')
    start = min(r['first_bar'] for r in coins.values()) + 120 * DAY
    start = ((start + DAY - 1) // DAY) * DAY
    end = universe['archive_end_bar'] + BAR
    if type(end) is not int or end % DAY or end <= start:
        raise ValueError('archive must end at UTC midnight after warm-up')
    cutoffs = list(range(start, end, DAY))
    ranked = {t: [] for t in cutoffs}
    inputs = {'universe.json': sha(md / 'universe.json')}
    for name, r in sorted(coins.items()):
        path = md / 'h4' / (name + '.csv.gz')
        inputs['h4/' + path.name] = sha(path)
        with gzip.open(path, 'rt', encoding='utf8', newline='') as fh:
            reader = csv.DictReader(fh)
            if not {'t', 'qv'} <= set(reader.fieldnames or []):
                raise ValueError('missing timestamp or quote volume column')
            bars = [(int(x['t']), float(x['qv'])) for x in reader]
        if not bars or bars[-1][0] != r['last_bar'] or r['last_bar'] >= end:
            raise ValueError('segment last bar mismatch')
        for t, volume in daily_candidates([b[0] for b in bars], [b[1] for b in bars], r['first_bar'], cutoffs):
            ranked[t].append((name, volume))
    days = []
    selected = set()
    for t in cutoffs:
        candidates = sorted(ranked[t], key=lambda x: (-x[1], x[0]))
        chosen = candidates[:150]
        selected.update(c for c, _ in chosen)
        days.append(dict(known_at=t, valid_until=t + DAY, eligible_count=len(candidates),
                         selected=[dict(coin=c, mean_daily_quote_volume=v) for c, v in chosen]))
    # BTC is an indicator input for BTC_LEAD, never an unconditional trade candidate.
    context = ['BTC'] if 'BTC' in coins else []
    if not context:
        raise ValueError('BTC reference segment absent')
    fetch = sorted(selected | set(context))
    return dict(schema='v9.hourly-plan/1', archive_commit=ARCHIVE_COMMIT,
                protocol_sha256=sha(PROTOCOL), source_files_sha256=inputs,
                window=[start, end], top=150, ranking='previous_7_complete_days_quote_volume',
                context_only=sorted(set(context)-selected), days=days,
                fetch_coins=[coins[c] for c in fetch], promotion_authority=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--md', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise ValueError('refuse to replace an existing plan')
    plan = build(args.md)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n', encoding='utf8')
    print(f"A5 plan: {len(plan['days'])} days, {len(plan['fetch_coins'])} distinct segments to fetch")


if __name__ == '__main__':
    main()
