"""A7 public venue candle acquisition and offline coverage; no outcome study."""
import argparse
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
import urllib.request

from v9.paper_history import canonical, decode, require, sha

URL = 'https://api.hyperliquid.xyz/info'
WIDTHS = {'4h': 14400000, '1d': 86400000}
MAX_BYTES = 8 * 1024 * 1024
MAX_COINS = 2000
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class CaptureBudgetExceeded(ValueError):
    """Stop collection without retrying or deleting the retained prefix."""


def universe(raw):
    doc = decode(raw)
    require(isinstance(doc, dict) and isinstance(doc.get('universe'), list), 'invalid venue metadata')
    rows = doc['universe']
    require(0 < len(rows) <= MAX_COINS, 'invalid universe size')
    result, names = [], set()
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('name'), str)
                and 0 < len(row['name']) <= 200, 'invalid instrument name')
        name = row['name']
        require(name not in names and type(row.get('isDelisted', False)) is bool, 'ambiguous instrument')
        names.add(name)
        result.append(dict(name=name, isDelisted=row.get('isDelisted', False)))
    return result


def coverage(raw, coin, interval, start, end):
    width = WIDTHS[interval]
    require(type(start) is int and type(end) is int and 0 <= start < end
            and start % width == end % width == 0, 'invalid closed-bar window')
    rows = decode(raw)
    require(isinstance(rows, list) and len(rows) <= 5000, 'invalid candle response')
    times = []
    for row in rows:
        require(isinstance(row, dict) and row.get('s') == coin and row.get('i') == interval,
                'candle identity mismatch')
        t, close = row.get('t'), row.get('T')
        require(type(t) is int and type(close) is int and start <= t < end
                and t % width == 0 and close == t + width - 1, 'invalid candle time')
        require(type(row.get('n')) is int and row['n'] >= 0, 'invalid trade count')
        values = []
        for key in ('o', 'h', 'l', 'c', 'v'):
            value = row.get(key)
            require(isinstance(value, str) and 0 < len(value) <= 100, 'invalid decimal representation')
            try:
                number = Decimal(value)
            except InvalidOperation as error:
                raise ValueError('invalid decimal') from error
            require(number.is_finite(), 'nonfinite candle value')
            values.append(number)
        o, h, l, c, volume = values
        require(0 < l <= min(o, c) <= max(o, c) <= h and volume >= 0, 'invalid candle geometry')
        require(not times or t > times[-1], 'duplicate or unordered candle')
        times.append(t)
    expected = (end-start)//width
    return dict(rows=len(rows), expected_window_bars=expected, unavailable_window_bars=expected-len(rows),
                first_open_ms=times[0] if times else None, last_open_ms=times[-1] if times else None,
                internal_missing_bars=sum((b-a)//width-1 for a, b in zip(times, times[1:])),
                response_at_documented_cap=len(rows) == 5000,
                requested_window_complete=len(rows) == expected,
                historical_listing_coverage_verified=False, funding_coverage_verified=False)


def request(body):
    req = urllib.request.Request(URL, data=canonical(body), headers={'Content-Type': 'application/json',
                                 'User-Agent': 'perp-dex-radar/A7-source-collection'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(MAX_BYTES+1)
    require(len(data) <= MAX_BYTES, 'response exceeds limit')
    return data


def save(root, path, body):
    with (root/path).open('xb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    return dict(path=path, bytes=len(body), sha256=sha(body))


def acquire(out, start, end, *, fetch=request, sleep=time.sleep, now=time.time):
    require(type(start) is int and type(end) is int and 0 <= start < end
            and start % WIDTHS['1d'] == end % WIDTHS['1d'] == 0, 'use UTC day boundaries in milliseconds')
    require(end <= int(now()*1000), 'window includes future bars')
    root = Path(out); root.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema='v9.venue-candle-capture/1', endpoint=URL, start_ms=start, end_ms=end,
                    started_ms=int(now()*1000), state='STARTED', metadata=None, requests=[],
                    outcome_execution_authorized=False)

    def checkpoint():
        temporary = root/'manifest.tmp'
        with temporary.open('wb') as stream:
            stream.write(canonical(manifest)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, root/'manifest.json')

    checkpoint()
    total = 0
    try:
        raw = fetch({'type': 'meta'})
        require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'invalid response bytes')
        if len(raw) > MAX_TOTAL_BYTES:
            raise CaptureBudgetExceeded('capture byte budget exceeded')
        manifest['metadata'] = save(root, 'metadata.json', raw)
        total += len(raw)
        checkpoint()
        coins = universe(raw)
        for ordinal, coin in enumerate(coins):
            for interval in WIDTHS:
                body = dict(type='candleSnapshot', req=dict(coin=coin['name'], interval=interval,
                            startTime=start, endTime=end-1))
                row = dict(ordinal=ordinal, coin=coin['name'], interval=interval, request=body,
                           state='STARTED', raw=None)
                manifest['requests'].append(row); checkpoint()
                sleep(6)  # At most ten candle requests/minute; no hidden retry/pagination.
                try:
                    raw = fetch(body)
                    require(isinstance(raw, bytes) and len(raw) <= MAX_BYTES, 'invalid response bytes')
                    if total + len(raw) > MAX_TOTAL_BYTES:
                        raise CaptureBudgetExceeded('capture byte budget exceeded')
                    row['raw'] = save(root, f'{ordinal:04d}-{interval}.json', raw)
                    total += len(raw)
                    row['coverage'] = coverage(raw, coin['name'], interval, start, end)
                    row['state'] = 'RETAINED'
                except Exception as error:
                    row['state'] = 'FAILED'
                    row['error_type'] = type(error).__name__
                    if isinstance(error, CaptureBudgetExceeded):
                        raise
                row['finished_ms'] = int(now()*1000); checkpoint()
        manifest['state'] = 'FINISHED'
    except BaseException:
        manifest['state'] = 'INTERRUPTED'; checkpoint()
        raise
    checkpoint()
    return verify(root)


def verify(root):
    root = Path(root)
    require(not root.is_symlink(), 'symlink capture root')
    def read(path):
        p = root/path
        require(not p.is_symlink() and p.is_file() and p.stat().st_size <= MAX_BYTES, 'invalid retained file')
        return p.read_bytes()
    manifest = decode(read('manifest.json'))
    require(isinstance(manifest, dict) and manifest.get('schema') == 'v9.venue-candle-capture/1'
            and manifest.get('endpoint') == URL and manifest.get('outcome_execution_authorized') is False,
            'invalid capture manifest')
    require(manifest.get('state') in ('STARTED', 'INTERRUPTED', 'FINISHED'), 'invalid capture state')
    def retained(ref, path):
        require(isinstance(ref, dict) and ref.get('path') == path, 'unexpected response path')
        raw = read(path)
        require(type(ref.get('bytes')) is int and len(raw) == ref['bytes'] and sha(raw) == ref.get('sha256'),
                'response binding mismatch')
        return raw
    coins = universe(retained(manifest.get('metadata'), 'metadata.json'))
    start, end = manifest.get('start_ms'), manifest.get('end_ms')
    require(type(start) is int and type(end) is int and 0 <= start < end
            and start % WIDTHS['1d'] == end % WIDTHS['1d'] == 0, 'invalid capture window')
    requests = manifest.get('requests')
    require(isinstance(requests, list) and len(requests) <= len(coins)*2, 'invalid request inventory')
    expected = [(i, coin, interval) for i, coin in enumerate(coins) for interval in WIDTHS]
    verified, failed = [], 0
    for row, (ordinal, coin, interval) in zip(requests, expected):
        require(isinstance(row, dict) and type(row.get('ordinal')) is int and row['ordinal'] == ordinal
                and row.get('coin') == coin['name'] and row.get('interval') == interval,
                'request inventory mismatch')
        require(row.get('request') == dict(type='candleSnapshot', req=dict(coin=coin['name'], interval=interval,
                startTime=start, endTime=end-1)), 'request parameters mismatch')
        require(row.get('state') in ('RETAINED', 'FAILED', 'STARTED'), 'invalid request state')
        raw = retained(row['raw'], f'{ordinal:04d}-{interval}.json') if row.get('raw') is not None else None
        if row['state'] == 'RETAINED':
            require(raw is not None, 'missing successful response')
            result = coverage(raw, coin['name'], interval, start, end)
            require(result == row.get('coverage'), 'coverage mismatch')
            verified.append(dict(coin=coin['name'], interval=interval, isDelisted=coin['isDelisted'], **result))
        else:
            failed += 1
    complete = manifest.get('state') == 'FINISHED' and len(requests) == len(expected) and failed == 0
    return dict(schema='v9.venue-candle-coverage/1', capture_manifest_sha256=sha(read('manifest.json')),
                status='SOURCE_RESPONSES_VERIFIED' if complete else 'INCOMPLETE_CAPTURE',
                instruments=len(coins), delisted_instruments=sum(c['isDelisted'] for c in coins),
                expected_requests=len(expected), attempted_requests=len(requests), failed_or_interrupted=failed,
                unattempted_requests=len(expected)-len(requests), coverage=verified,
                historical_universe_complete=False, historical_listing_times_verified=False,
                dataset_accepted=False, outcome_execution_authorized=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    collect = sub.add_parser('acquire'); collect.add_argument('--out', required=True)
    collect.add_argument('--start-ms', type=int, required=True); collect.add_argument('--end-ms', type=int, required=True)
    check = sub.add_parser('verify'); check.add_argument('--capture', required=True)
    args = parser.parse_args(argv)
    result = acquire(args.out, args.start_ms, args.end_ms) if args.command == 'acquire' else verify(args.capture)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
