"""Offline A5 trade-tape diagnostics; never emits an accepted hourly archive."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

FIELDS = ('o', 'h', 'l', 'c', 'qv', 'tbqv')
HEADER = ['id', 'price', 'qty', 'quote_qty', 'time', 'is_buyer_maker']
PROTOCOL = Path(__file__).resolve().parents[2] / 'docs/v9/phase-a5-trade-reconstruction.md'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def positive(value):
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('invalid decimal') from exc
    if not d.is_finite() or d <= 0 or len(d.as_tuple().digits) > 30 or abs(d.adjusted()) > 30:
        raise ValueError('invalid positive finite decimal')
    return d


def integer(value):
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('invalid integer')
    return int(value)


def records(raw, day):
    """Stream validated daily records as (id, microsecond time, price, quote, buy)."""
    start = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    previous = None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if len(names) != 1 or not names[0].endswith('.csv'):
            raise ValueError('expected exactly one CSV')
        with z.open(names[0]) as stream:
            for line, row in enumerate(csv.reader(io.TextIOWrapper(stream, encoding='utf8', newline=''))):
                if line == 0 and row == HEADER:
                    continue
                if len(row) != 6:
                    raise ValueError('expected six trade columns')
                ident, stamp = integer(row[0]), integer(row[4])
                # Detect units by the requested UTC day, not a lossy float conversion.
                if start*1000 <= stamp < (start+86400)*1000:
                    stamp *= 1000
                elif not start*1000000 <= stamp < (start+86400)*1000000:
                    raise ValueError('trade outside requested day')
                price, qty, quote = map(positive, row[1:4])
                if row[5].lower() not in ('true', 'false'):
                    raise ValueError('invalid buyer-maker flag')
                if previous and (ident <= previous[0] or stamp < previous[1]):
                    raise ValueError('duplicate or out-of-order trade')
                previous = ident, stamp
                yield ident, stamp, price, quote, row[5].lower() == 'false'


def aggregate(rows):
    if not rows:
        return None
    return dict(zip(FIELDS, (rows[0][2], max(r[2] for r in rows), min(r[2] for r in rows),
                            rows[-1][2], sum((r[3] for r in rows), Decimal(0)),
                            sum((r[3] for r in rows if r[4]), Decimal(0)))))


def audit(raw, checksum, filename, day, references):
    """References maps four-hour open seconds to the six original source fields."""
    if not re.fullmatch(r'[A-Z0-9_]+USDT-trades-' + re.escape(day) + r'\.zip', filename):
        raise ValueError('source filename does not identify the requested USD-M day')
    tokens = checksum.decode('ascii').split()
    if len(tokens) != 2 or tokens[1].lstrip('*') != filename or tokens[0].lower() != sha(raw):
        raise ValueError('provider checksum or filename mismatch')
    start = int(datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    if not references or any(type(t) is not int or t % 14400 or not start <= t < start+86400 for t in references):
        raise ValueError('invalid requested four-hour blocks')
    selected = {t: [] for t in references}
    before, after = {}, {}
    count = 0
    for row in records(raw, day):
        count += 1
        stamp = row[1]
        for t in selected:
            if stamp < t*1000000:
                before[t] = row[0]
            elif stamp < (t+14400)*1000000:
                selected[t].append(row)
            elif t not in after:
                after[t] = row[0]
    if not count:
        raise ValueError('empty trade file')
    blocks = []
    with localcontext() as ctx:
        ctx.prec = 80
        for t, rows in sorted(selected.items()):
            values = aggregate(rows)
            ids = ([before[t]] if t in before else []) + [r[0] for r in rows] + ([after[t]] if t in after else [])
            gaps = [[a+1, b] for a, b in zip(ids, ids[1:]) if b != a+1]
            hours = []
            for hour in range(t, t+14400, 3600):
                group = [r for r in rows if hour*1000000 <= r[1] < (hour+3600)*1000000]
                h = aggregate(group)
                hours.append(dict(t=hour, trades=len(group), fields={k:str(v) for k,v in h.items()} if h else None))
            conflicts = []
            for field in FIELDS:
                target = Decimal(str(references[t][field]))
                if not target.is_finite() or target < 0 or (field in FIELDS[:4] and target == 0):
                    raise ValueError('invalid pinned reference')
                actual = values[field] if values else None
                if actual is None or abs(actual-target) > Decimal('1e-8')*max(abs(actual), abs(target)):
                    conflicts.append(dict(field=field, reconstructed=str(actual) if actual is not None else None, pinned=str(target)))
            blocks.append(dict(t=t, hours=hours, conflicts=conflicts, id_gaps=gaps,
                               bracketed=t in before and t in after,
                               continuity_checked=bool(rows) and t in before and t in after and not gaps,
                               aggregate_matches=not conflicts))
    return dict(schema='v9.trade-reconstruction-diagnostic/1', day=day, source_filename=filename,
                source_sha256=sha(raw), checksum_sha256=sha(checksum), source_records=count,
                blocks=blocks, accepted_dataset=False, replay_complete=False, promotion_authority=False)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('zip', 'checksum', 'day', 'reference', 'out'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--blocks', nargs='+', type=int, required=True)
    a = p.parse_args(argv)
    if len(set(a.blocks)) != len(a.blocks):
        raise ValueError('duplicate requested block')
    refs = {}
    with gzip.open(a.reference, 'rt', encoding='utf8', newline='') as f:
        for row in csv.DictReader(f):
            t = int(row['t'])
            if t in a.blocks:
                if t in refs:
                    raise ValueError('duplicate reference block')
                refs[t] = row
    if set(refs) != set(a.blocks):
        raise ValueError('missing reference block')
    source = Path(a.zip)
    result = audit(source.read_bytes(), Path(a.checksum).read_bytes(), source.name, a.day, refs)
    result.update(reference_sha256=sha(Path(a.reference).read_bytes()),
                  protocol_sha256=sha(PROTOCOL.read_bytes()), implementation_sha256=sha(Path(__file__).read_bytes()))
    # Exclusive creation preserves earlier diagnostics and never updates source data.
    with Path(a.out).open('x', encoding='utf8', newline='\n') as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
