"""Collect A5 hourly data for the committed causal plan; no strategy simulation."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import archive_fetch as A
from tools.v9 import hourly_plan as P


def months(first, end):
    """UTC months intersecting [first, end)."""
    d = datetime.fromtimestamp(first, timezone.utc)
    y, m = d.year, d.month
    out = []
    while int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp()) < end:
        out.append(f'{y:04}-{m:02}')
        y, m = (y+1, 1) if m == 12 else (y, m+1)
    return out


def parse(raw, month):
    """Validate each raw exchange row; preserve observed zero-volume hours."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('expected one CSV per monthly archive')
        text = z.read(names[0]).decode('utf8')
    rows = []
    for k, r in enumerate(csv.reader(io.StringIO(text))):
        if k == 0 and r and r[0] == 'open_time':
            continue
        if len(r) != 12:
            raise ValueError('invalid hourly row width')
        stamp = int(r[0])
        scale = 1000 if stamp < 10**14 else 1000000
        if stamp % (3600 * scale):
            raise ValueError('unaligned hourly timestamp')
        t = stamp // scale
        if datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m') != month:
            raise ValueError('hour outside requested month')
        o, h, l, c, qv, tbqv = [float(r[i]) for i in (1, 2, 3, 4, 7, 10)]
        base_volume, trades = float(r[5]), int(r[8])
        if (not all(math.isfinite(v) for v in (o, h, l, c, qv, tbqv)) or
                min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or
                min(qv, tbqv) < 0 or tbqv > qv + max(1e-8, qv*1e-10)):
            raise ValueError('invalid hourly OHLC/volume')
        if (not math.isfinite(base_volume) or base_volume < 0 or trades < 0 or
                (qv == 0 and (base_volume != 0 or trades != 0)) or
                (qv > 0 and (base_volume == 0 or trades == 0))):
            raise ValueError('inconsistent observed trading activity')
        if rows and t <= rows[-1][0]:
            raise ValueError('duplicate or unordered hourly timestamp')
        rows.append((t, o, h, l, c, qv, tbqv))
    if not rows:
        raise ValueError('empty monthly archive')
    return rows


def segment(rows, first, end):
    selected = [r for r in rows if first <= r[0] < end]
    if not selected or not any(r[5] > 0 for r in selected):
        raise ValueError('segment has no observed trading hours')
    expected = (end-first)//3600
    observed = {r[0] for r in selected}
    if len(observed) != len(selected):
        raise ValueError('duplicate hour across monthly archives')
    gaps = []
    for t in range(first, end, 3600):
        if t not in observed:
            if gaps and gaps[-1][1] == t:
                gaps[-1][1] += 3600
            else:
                gaps.append([t, t+3600])
    return selected, dict(expected_hours=expected, observed_hours=len(selected),
                          zero_volume_hours=sum(r[5] == 0 for r in selected),
                          missing_hours=expected-len(selected), missing_intervals=gaps)


def reconcile(rows, path):
    """Compare complete hourly groups with the independently pinned 4h file."""
    by_time = {r[0]: r for r in rows}
    checked, missing = 0, 0
    with gzip.open(path, 'rt', encoding='utf8', newline='') as fh:
        reader = csv.DictReader(fh)
        fields = ('o', 'h', 'l', 'c', 'qv', 'tbqv')
        if not {'t', *fields} <= set(reader.fieldnames or []):
            raise ValueError('four-hour reference lacks OHLC/volume columns')
        for reference in reader:
            t = int(reference['t'])
            group = [by_time.get(t+i*3600) for i in range(4)]
            if any(r is None for r in group):
                missing += 1
                continue
            # Zero-trade hourly candles carry a stale price. Exchange 4h OHLC
            # comes from actual trades, not those synthetic carry-forward prices.
            traded = [r for r in group if r[5] > 0]
            if not traded:
                raise ValueError(f'no trading hours for pinned four-hour bar: {path.name} {t}')
            actual = (traded[0][1], max(r[2] for r in traded), min(r[3] for r in traded),
                      traded[-1][4], math.fsum(r[5] for r in group), math.fsum(r[6] for r in group))
            # The pinned archive rounds to ten significant digits on export.
            for field, value in zip(fields, actual):
                target = float(reference[field])
                if not math.isfinite(target) or not math.isclose(value, target, rel_tol=1e-8, abs_tol=0.0):
                    raise ValueError(f'hourly/four-hour mismatch: {path.name} {t} {field}: '
                                     f'hourly={value!r}, pinned={target!r}')
            checked += 1
    if not checked:
        raise ValueError('no complete four-hour groups could be reconciled')
    return dict(reconciled_four_hour_bars=checked, incomplete_four_hour_groups=missing)


def run(md, plan_path, out, cache, workers=8):
    md, out = Path(md), Path(out)
    plan = json.loads(Path(plan_path).read_text(encoding='utf8'))
    if plan != P.build(md):
        raise ValueError('hourly plan does not reproduce from its bound source')
    if workers < 1 or workers > 32:
        raise ValueError('workers must be between 1 and 32')
    if out.exists() and any(out.iterdir()):
        raise ValueError('output directory must be empty; preserve prior attempts')
    for folder in ('h1', 'fund_bn'):
        (out/folder).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan_path, out/'hourly_plan.json')
    grouped = {}
    for coin in plan['fetch_coins']:
        sym = coin['symbol']
        if not sym.endswith('USDT') or '/' in sym or '\\' in sym or '..' in sym:
            raise ValueError('unsafe source symbol')
        grouped.setdefault(sym, []).append(coin)

    def fetch_symbol(item):
        sym, coins = item
        required = sorted({m for c in coins for m in months(c['first_bar'], c['last_bar']+P.BAR)})
        prefix = f'data/futures/um/monthly/klines/{sym}/1h/'
        listed, _ = A.s3_list(prefix)
        files = {r['key']: r for r in listed}
        raw_rows, sources = [], []
        for month in required:
            key = prefix + f'{sym}-1h-{month}.zip'
            if key not in files:
                raise ValueError('required hourly month missing: ' + key)
            raw, _ = A.cached(str(cache), files[key])
            if files[key].get('size') != len(raw):
                raise ValueError('download size mismatch: ' + key)
            raw_rows.extend(parse(raw, month))
            sources.append(dict(key=key, size=len(raw), etag=files[key].get('etag'),
                                sha256=hashlib.sha256(raw).hexdigest()))
        coverage = {}
        for c in coins:
            name = c['t']
            rows, cov = segment(raw_rows, c['first_bar'], c['last_bar']+P.BAR)
            cov.update(reconcile(rows, md/'h4'/f'{name}.csv.gz'))
            path = out/'h1'/f'{name}.csv.gz'
            # Fixed gzip metadata makes identical data reproducible byte-for-byte.
            with path.open('wb') as base:
                with gzip.GzipFile(filename='', fileobj=base, mode='wb', mtime=0) as zipped:
                    with io.TextIOWrapper(zipped, encoding='utf8', newline='') as fh:
                        w = csv.writer(fh, lineterminator='\n')
                        w.writerow(['t', 'o', 'h', 'l', 'c', 'qv', 'tbqv'])
                        w.writerows(rows)
            funding = md/'fund_bn'/f'{name}.csv.gz'
            if not funding.is_file():
                raise ValueError('pinned funding file missing: ' + name)
            shutil.copyfile(funding, out/'fund_bn'/funding.name)
            cov['funding_source_sha256'] = P.sha(funding)
            coverage[name] = cov
        print(f'A5 fetched {sym}: {len(required)} months, {len(coins)} segments', flush=True)
        return sources, coverage

    sources, coverage = [], {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for items, cov in pool.map(fetch_symbol, sorted(grouped.items())):
            sources.extend(items)
            coverage.update(cov)
    universe = json.loads((md/'universe.json').read_text(encoding='utf8'))
    universe.update(interval='1h', coins=plan['fetch_coins'],
                    counts={'fetched_segments': len(plan['fetch_coins'])},
                    selection='hourly_plan.json; fetch union is not entry eligibility')
    (out/'universe.json').write_text(json.dumps(universe, sort_keys=True, indent=2)+'\n', encoding='utf8')
    artifacts = {p.relative_to(out).as_posix(): P.sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    doc = dict(schema='v9.hourly-archive/1', archive_commit=P.ARCHIVE_COMMIT,
               protocol_sha256=P.sha(P.PROTOCOL), collector_sha256=P.sha(__file__),
               aggregation_clarification_sha256=P.sha(ROOT/'docs/v9/phase-a5-hourly-aggregation.md'),
               plan_builder_sha256=P.sha(Path(P.__file__)), network_helpers_sha256=P.sha(Path(A.__file__)),
               source_objects=sorted(sources, key=lambda r: r['key']), coverage=coverage,
               artifacts_sha256=artifacts, all_required_months_downloaded=True,
               all_hours_observed=all(c['missing_hours'] == 0 for c in coverage.values()),
               promotion_authority=False, replay_complete=False)
    # Only this final marker denotes a completed collection, not a successful replay.
    (out/'hourly_manifest.json').write_text(json.dumps(doc, sort_keys=True, indent=2)+'\n', encoding='utf8')
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('md', 'plan', 'out', 'cache'):
        ap.add_argument('--'+name, required=True)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args(argv)
    run(a.md, a.plan, a.out, a.cache, a.workers)


if __name__ == '__main__':
    main()
