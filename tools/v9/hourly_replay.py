"""Pinned A5 archive driver; diagnostics only, never promotion authority."""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import hourly_batch as B
from tools.v9 import hourly_feature_state as S
from tools.v9 import hourly_funding as F

MANIFEST_SHA = 'd9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2'
DATA_COMMIT = '0859e683910a7eea7ef446b27cf9773f33d9e9f8'
PROTOCOL = 'docs/v9/phase-a5-replay-driver.md'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf8')
    temporary.replace(path)


def verify_archive(root):
    root = Path(root)
    manifest_path = root / 'quality_candidate_manifest.json'
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError('unaccepted archive manifest')
    manifest = json.loads(manifest_path.read_bytes())
    inventory = manifest['artifacts_sha256']
    for name, digest in inventory.items():
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
            raise ValueError('invalid artifact path')
        path = root / name
        if any(parent.is_symlink() for parent in [path, *path.parents]) or sha(path) != digest:
            raise ValueError('archive artifact changed: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(inventory) | {'quality_candidate_manifest.json'}:
        raise ValueError('archive inventory mismatch')
    plan = json.loads((root/'hourly_plan.json').read_bytes())
    schedule = json.loads((root/'quality_schedule.json').read_bytes())
    coins = plan['fetch_coins']
    names = [c['t'] for c in coins]
    if len(set(names)) != len(names) or 'BTC' not in names:
        raise ValueError('invalid segment roster/BTC context')
    start, end = plan['window']
    if (type(start) is not int or type(end) is not int or start % B.DAY or end % B.DAY or end <= start or
            [d['schedule'] for d in schedule] != plan['days'] or
            [d['schedule']['known_at'] for d in schedule] != list(range(start, end, B.DAY))):
        raise ValueError('schedule/window mismatch')
    for day in schedule:
        selected = [r['coin'] for r in day['schedule']['selected']]
        if (type(day['new_entries_allowed']) is not bool or
                day['schedule']['valid_until'] != day['schedule']['known_at'] + B.DAY or
                len(selected) != len(set(selected)) or not set(selected) <= set(names)):
            raise ValueError('invalid entry schedule')
    for coin in names:
        if '/' in coin or '\\' in coin or ':' in coin or coin in ('.', '..'):
            raise ValueError('invalid segment name')
        if not all(f'{folder}/{coin}.csv.gz' in inventory for folder in ('h1', 'fund_bn')):
            raise ValueError('segment files missing')
    return plan, schedule, inventory


def read_candles(path):
    rows = {}
    with gzip.open(path, 'rt', encoding='utf8', newline='') as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ['t', 'o', 'h', 'l', 'c', 'qv', 'tbqv']:
            raise ValueError('invalid candle schema')
        for row in reader:
            if None in row or any(row[k] is None for k in reader.fieldnames):
                raise ValueError('malformed candle row')
            t = int(row['t'])
            if t in rows: raise ValueError('duplicate candle timestamp')
            rows[t] = {k: float(row[k]) for k in ('o', 'h', 'l', 'c', 'qv')}
    S.runs(rows)  # validates all observations, including zero-volume rows
    return rows


def segment_replay(alias, coin, rows, first_bar, btc, funding, schedule, start, end):
    from tools.v9 import hourly_signals as G
    if alias == 'FUND_CARRY':
        return dict(status='UNAVAILABLE_CAUSAL_QUORUM_MAPPING', attempts=[], net_series_available=False)
    if alias == 'FUND_FADE' and any(start-S.HOUR <= t < end for t in funding['off_grid_events']):
        return dict(status='UNAVAILABLE_OFF_GRID_FUNDING', attempts=[], net_series_available=False)
    # Compute warm-up from retained earlier bars, but never use data beyond study end.
    rows = {t: r for t, r in rows.items() if t < end}
    btc = {t: r for t, r in btc.items() if t < end}
    generated = G.generate(alias, coin, rows, first_bar, btc_rows=btc, funding=funding['hourly_events'])
    signals = [s for s in generated['signals'] if s['signal_time'] >= start-S.HOUR]
    # Positions have no cross-segment budget. Project membership without reranking
    # or changing the shared embargo; this is equivalent to the full batch ledger.
    projected = [dict(new_entries_allowed=d['new_entries_allowed'], schedule=dict(d['schedule'],
                    selected=[r for r in d['schedule']['selected'] if r['coin'] == coin])) for d in schedule]
    ledger = B.replay(signals, {coin: rows}, projected, start, end,
                      funding={coin: funding['hourly_events']}, funding_complete={coin: {}})
    return dict(ledger, status='REPLAYED', signal_status=generated['status'],
                generated_signal_count=len(signals), funding_coverage='UNAVAILABLE_SOURCE_COVERAGE')


def run(archive, out):
    from tools.v9 import hourly_signals as G
    archive, out = Path(archive), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    try:
        plan, schedule, inventory = verify_archive(archive)
        trials = G.registered()
        if set(trials) != S.ALIASES: raise ValueError('hourly catalogue mismatch')
        start, end = plan['window']
        btc = read_candles(archive/'h1/BTC.csv.gz')
        if not btc: raise ValueError('empty BTC context')
        summaries = {alias: dict(trial_id=t['trial_id'], params=t['params'],
                     status='REPLAYED', segments=0, failed_segments=0, unavailable_segments=0,
                     attempt_counts={}, net_series_available=True,
                     daily_net_R=[dict(day=d, net_R=0.) for d in range(start, end+1, B.DAY)])
                     for alias, t in trials.items()}
        carry = summaries['FUND_CARRY']
        carry.update(status='UNAVAILABLE_CAUSAL_QUORUM_MAPPING', net_series_available=False)
        for day in carry['daily_net_R']: day['net_R'] = None
        with ExitStack() as stack:
            writers = {a: stack.enter_context(gzip.open(out/f'{a}.jsonl.gz', 'wt', encoding='utf8', newline=''))
                       for a in sorted(trials)}
            for coin in sorted(plan['fetch_coins'], key=lambda c: c['t']):
                name = coin['t']
                try:
                    # Recheck the segment immediately before use.
                    for folder in ('h1', 'fund_bn'):
                        rel = f'{folder}/{name}.csv.gz'
                        if sha(archive/rel) != inventory[rel]: raise ValueError('segment changed after preflight')
                    rows = read_candles(archive/f'h1/{name}.csv.gz')
                    funding = F.read(archive/f'fund_bn/{name}.csv.gz')
                    error = None
                except Exception as exc:
                    error = f'{type(exc).__name__}: {exc}'
                for alias in sorted(trials):
                    if alias == 'FUND_CARRY': continue
                    summary = summaries[alias]
                    try:
                        if error: raise ValueError(error)
                        result = segment_replay(alias, name, rows, coin['first_bar'], btc, funding,
                                                schedule, start, end)
                    except Exception as exc:
                        result = dict(status='FAILED_SEGMENT', error=f'{type(exc).__name__}: {exc}',
                                      attempts=[], net_series_available=False)
                    attempts = result.pop('attempts')
                    daily = result.pop('daily_net_R', None)
                    writers[alias].write(json.dumps(dict(kind='segment', coin=name, **result), allow_nan=False)+'\n')
                    for attempt in attempts:
                        writers[alias].write(json.dumps(dict(kind='attempt', **attempt), allow_nan=False)+'\n')
                    summary['segments'] += 1
                    counts = Counter(summary['attempt_counts']); counts.update(a['status'] for a in attempts)
                    summary['attempt_counts'] = dict(counts)
                    summary['failed_segments'] += result['status'] == 'FAILED_SEGMENT'
                    summary['unavailable_segments'] += result['status'].startswith('UNAVAILABLE')
                    summary['net_series_available'] &= result['net_series_available']
                    if result['net_series_available'] and daily is not None:
                        for total, part in zip(summary['daily_net_R'], daily):
                            if total['day'] != part['day']: raise ValueError('daily axis mismatch')
                            total['net_R'] += part['net_R']
            writers['FUND_CARRY'].write(json.dumps(dict(kind='trial', **carry))+'\n')
        for summary in summaries.values():
            if summary['failed_segments']: summary['status'] = 'FAILED_PARTIAL_REPLAY'
            elif summary['unavailable_segments']: summary['status'] = 'UNAVAILABLE_PARTIAL_REPLAY'
            if not summary['net_series_available']:
                for day in summary['daily_net_R']: day['net_R'] = None
        # Manifest written last, after all attempt streams have been closed.
        source_files = [PROTOCOL, 'research/v9/census_replay_plan.json',
                        'docs/v9/phase-a5-execution-contract.md', 'docs/v9/phase-a5-feature-state.md',
                        'docs/v9/phase-a5-signal-integration.md', 'docs/v9/phase-a5-funding-disposition.md']
        source_files += [f'tools/v9/hourly_{n}.py' for n in ('replay','batch','execution','signals','funding','feature_state')]
        evidence = dict(schema='v9.a5-hourly-replay/1', data_commit=DATA_COMMIT,
                        dataset_sha256=MANIFEST_SHA, window=[start,end], trials=summaries,
                        source_sha256={p:sha(ROOT/p) for p in source_files},
                        artifacts_sha256={p.name:sha(p) for p in sorted(out.glob('*.jsonl.gz'))},
                        replay_attempts_recorded=True, known_trial_return_matrix_complete=False,
                        historical_trial_census_complete=False, confirmed=[], promotion_authority=False,
                        funding_coverage='UNAVAILABLE_SOURCE_COVERAGE',
                        restrictions=['retrospective quality selection', 'continuous positive-volume warm-up',
                                      'retrospective entry observability', 'observed-event conditional FUND_FADE'])
        write_json(out/'evidence_a5.json', evidence)
        return evidence
    except Exception as exc:
        write_json(out/'failure.json', dict(error=f'{type(exc).__name__}: {exc}',
                   promotion_authority=False, replay_complete=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--out', required=True)
    run(**vars(parser.parse_args()))
