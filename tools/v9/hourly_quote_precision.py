"""Streaming comparison of published trade quotes and decimal price times quantity."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import gzip
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import hourly_trades as T

PROTOCOL = ROOT/'docs/v9/phase-a5-quote-precision.md'
PRIOR_SHA256 = '4eaa3297b048621b4cd0931c95d408e51cd49aa497687953793903af0c1ba22e'


def compare(raw, previous, references):
    if T.sha(raw) != previous['source_sha256']:
        raise ValueError('trade object changed')
    start = int(datetime.strptime(previous['day'], '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    old = {h['t']: h for b in previous['blocks'] for h in b['hours']}
    if any(b['t'] % 14400 or [h['t'] for h in b['hours']] != list(range(b['t'],b['t']+14400,3600)) for b in previous['blocks']):
        raise ValueError('invalid four-hour grid')
    if len(old) != len(previous['blocks'])*4 or set(references) != {b['t'] for b in previous['blocks']}:
        raise ValueError('duplicate or missing requested blocks')
    if any(type(t) is not int or t % 3600 or not start <= t < start+86400 for t in old):
        raise ValueError('invalid requested hour')
    accum = {t: [Decimal(0) for _ in range(4)] for t in old}
    counts = dict.fromkeys(old, 0)
    changed = dict.fromkeys(old, 0)
    last = None
    total = 0
    with localcontext() as ctx:
        ctx.prec = 80
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.namelist()) != 1 or not z.namelist()[0].endswith('.csv'):
                raise ValueError('expected one CSV')
            with z.open(z.namelist()[0]) as f:
                for line, row in enumerate(csv.reader(io.TextIOWrapper(f, encoding='utf8', newline=''))):
                    if line == 0 and row == T.HEADER:
                        continue
                    if len(row) != 6:
                        raise ValueError('expected six columns')
                    ident, stamp = T.integer(row[0]), T.integer(row[4])
                    if start*1000 <= stamp < (start+86400)*1000:
                        stamp *= 1000
                    elif not start*1000000 <= stamp < (start+86400)*1000000:
                        raise ValueError('trade outside requested day')
                    if last and (ident <= last[0] or stamp < last[1]):
                        raise ValueError('duplicate or out-of-order trade')
                    last = ident, stamp
                    price, qty, quote = map(T.positive, row[1:4])
                    if row[5].lower() not in ('true','false'):
                        raise ValueError('invalid buyer-maker flag')
                    total += 1
                    hour = stamp//3600000000*3600
                    if hour not in old:
                        continue
                    product = price*qty
                    counts[hour] += 1
                    changed[hour] += product != quote
                    a = accum[hour]
                    a[0] += quote; a[2] += product
                    if row[5].lower() == 'false':
                        a[1] += quote; a[3] += product
        if total != previous['source_records']:
            raise ValueError('daily trade count changed')
        for t, h in old.items():
            if counts[t] != h['trades']:
                raise ValueError('hourly trade count changed')
            if counts[t]:
                if any(accum[t][i] != Decimal(h['fields'][field]) for i,field in enumerate(('qv','tbqv'))):
                    raise ValueError('original quote sums do not reproduce')
            elif h['fields'] is not None:
                raise ValueError('empty hour previously had fields')
        blocks = []
        for b in previous['blocks']:
            hours = []
            for h in b['hours']:
                t = h['t'];a = accum[t]
                hours.append(dict(t=t,trades=counts[t],different_quote_records=changed[t],
                                  published_qv=str(a[0]),published_tbqv=str(a[1]),
                                  product_qv=str(a[2]),product_tbqv=str(a[3]),
                                  product_minus_published_qv=str(a[2]-a[0]),
                                  observed=bool(counts[t])))
            comparisons = []
            for field,offset in [('qv',0),('tbqv',1)]:
                target = Decimal(str(references[b['t']][field]))
                if not target.is_finite() or target < 0:
                    raise ValueError('invalid pinned volume')
                published = sum((accum[h['t']][offset] for h in b['hours']),Decimal(0))
                product = sum((accum[h['t']][offset+2] for h in b['hours']),Decimal(0))
                def matches(value):
                    return abs(value-target) <= Decimal('1e-8')*max(abs(value),abs(target))
                comparisons.append(dict(field=field,pinned=str(target),published=str(published),product=str(product),
                                        published_matches=matches(published),product_matches=matches(product),
                                        product_minus_published=str(product-published)))
            price_conflicts = [c for c in b['conflicts'] if c['field'] in T.FIELDS[:4]]
            blocks.append(dict(t=b['t'],hours=hours,volume_comparisons=comparisons,
                               price_conflicts=price_conflicts,id_gaps=b['id_gaps'],bracketed=b['bracketed'],
                               continuity_checked=b['continuity_checked'],
                               product_aggregate_matches=not price_conflicts and all(c['product_matches'] for c in comparisons)))
    return dict(coin=previous['coin'],day=previous['day'],source_filename=previous['source_filename'],
                source_sha256=T.sha(raw),source_records=total,blocks=blocks)


def run(inputs, prior_path, out):
    inputs, out = Path(inputs), Path(out)
    prior_raw = Path(prior_path).read_bytes()
    if T.sha(prior_raw) != PRIOR_SHA256:
        raise ValueError('prior diagnostic does not match committed record')
    prior = json.loads(prior_raw)
    if prior['schema'] != 'v9.a5-trade-diagnostics-record/1' or prior['accepted_dataset']:
        raise ValueError('invalid prior diagnostic')
    if len(prior['diagnostics']) != 94 or sum(len(d['blocks']) for d in prior['diagnostics']) != 94:
        raise ValueError('must cover all 94 original objects and blocks')
    identities = [(d['coin'], d['day']) for d in prior['diagnostics']]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate diagnostic object')
    out.mkdir(exist_ok=False)
    results = []
    try:
        for d in prior['diagnostics']:
            folder = inputs/(d['coin']+'-'+d['day'])
            raw = (folder/d['source_filename']).read_bytes()
            checksum = (folder/(d['source_filename']+'.CHECKSUM')).read_bytes()
            tokens = checksum.decode('ascii').split()
            if (T.sha(checksum) != d['checksum_sha256'] or len(tokens) != 2
                    or tokens[0].lower() != T.sha(raw) or tokens[1].lstrip('*') != d['source_filename']):
                raise ValueError('checksum changed')
            ref = (folder/'reference.csv.gz').read_bytes()
            if T.sha(ref) != d['reference_sha256']:
                raise ValueError('reference changed')
            refs = {}
            wanted = {b['t'] for b in d['blocks']}
            with gzip.open(io.BytesIO(ref),'rt',encoding='utf8',newline='') as f:
                for row in csv.DictReader(f):
                    t = int(row['t'])
                    if t in wanted:
                        if t in refs: raise ValueError('duplicate reference')
                        refs[t] = row
            result = compare(raw,d,refs)
            (out/(d['coin']+'-'+d['day']+'.json')).write_text(json.dumps(result,sort_keys=True)+'\n',encoding='utf8')
            results.append(result)
            print('precision diagnostic:',d['coin'],d['day'],flush=True)
    except Exception as exc:
        (out/'failure.json').write_text(json.dumps(dict(error=str(exc),completed_objects=len(results),
            prior_record_sha256=T.sha(prior_raw),protocol_sha256=T.sha(PROTOCOL.read_bytes()),
            accepted_dataset=False))+'\n',encoding='utf8')
        raise
    doc = dict(schema='v9.a5-quote-precision/1',prior_record_sha256=T.sha(prior_raw),
               protocol_sha256=T.sha(PROTOCOL.read_bytes()),implementation_sha256=T.sha(Path(__file__).read_bytes()),
               parser_helpers_sha256=T.sha(Path(T.__file__).read_bytes()),results=results,
               accepted_dataset=False,replay_complete=False,promotion_authority=False)
    (out/'diagnostic.json').write_text(json.dumps(doc,sort_keys=True)+'\n',encoding='utf8')
    return doc


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('inputs','prior','out'):p.add_argument('--'+name,required=True)
    a = p.parse_args()
    run(a.inputs,a.prior,a.out)
