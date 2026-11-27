"""Offline D4 premium-index inputs, never prices, funding or study authority."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile
from .listing_observations import canonical, decode, read, require, sha, timestamp

BAR = 14400
DAY = 86400
MAX_ZIP = 4 * 1024 * 1024
MAX_FILES = 10000
MAX_GRID = 500000
HEADER = ['open_time','open','high','low','close','volume','close_time','quote_volume',
          'count','taker_buy_volume','taker_buy_quote_volume','ignore']


def number(text):
    require(isinstance(text,str) and 0 < len(text) <= 128 and
            re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',text), 'invalid premium value')
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError('invalid premium number') from error
    require(value.is_finite(), 'nonfinite premium value')
    return value


def parse_day(raw, day, member):
    require(len(raw) <= MAX_ZIP, 'compressed input limit')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries)==1, 'ambiguous archive members')
        entry = entries[0]
        require(entry.filename==member and not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16)
                and not entry.flag_bits & 1, 'invalid archive member')
        require(0 < entry.file_size <= MAX_ZIP, 'expanded input limit')
        with archive.open(entry) as stream:
            body = stream.read(MAX_ZIP+1)
        require(len(body)<=MAX_ZIP, 'expanded input limit')
    rows = list(csv.reader(io.StringIO(body.decode('utf-8'))))
    if rows and rows[0]==HEADER:
        rows = rows[1:]
    require(0 < len(rows) <= 6, 'invalid daily row count')
    out = {}
    for row in rows:
        require(len(row)==12 and re.fullmatch('[0-9]+',row[0]) and re.fullmatch('[0-9]+',row[6]), 'invalid premium row')
        opened, closed = int(row[0]), int(row[6])
        require(opened % (BAR*1000)==0 and day*1000 <= opened < (day+DAY)*1000
                and closed==opened+BAR*1000-1, 'premium timestamp or grid mismatch')
        t = opened//1000
        require(t not in out, 'duplicate premium bar')
        o,h,l,c = [number(x) for x in row[1:5]]
        require(l <= min(o,c) <= max(o,c) <= h, 'invalid premium OHLC')
        out[t] = dict(bar_open=t, closed_at=t+BAR, premium_open=str(o), premium_high=str(h),
                      premium_low=str(l), premium_close=str(c))
    return out


def audit(manifest, root, as_of):
    require(timestamp(as_of), 'invalid audit cutoff')
    require(isinstance(manifest,dict) and manifest.get('schema')=='v9.premium-input/1', 'invalid manifest')
    segments, files = manifest.get('segments'), manifest.get('files')
    require(isinstance(segments,list) and 0 < len(segments) <= 20000, 'invalid segment inventory')
    require(isinstance(files,list) and len(files) <= MAX_FILES, 'invalid file inventory')
    root = Path(root).resolve()
    by_id, by_symbol, count = {}, {}, 0
    for seg in segments:
        require(isinstance(seg,dict), 'invalid segment')
        sid,symbol,lo,hi = [seg.get(k) for k in ('segment_id','symbol','start','end')]
        require(isinstance(sid,str) and 0<len(sid)<=100 and sid not in by_id, 'duplicate or invalid segment identity')
        require(isinstance(symbol,str) and re.fullmatch('[A-Z0-9_]{1,80}',symbol), 'unsupported symbol')
        require(timestamp(lo) and timestamp(hi) and lo% BAR==0 and hi%BAR==0 and lo<hi<=as_of, 'invalid segment bounds')
        count += (hi-lo)//BAR
        require(count<=MAX_GRID, 'requested grid limit')
        by_id[sid] = dict(segment_id=sid,symbol=symbol,start=lo,end=hi,rows={})
        by_symbol.setdefault(symbol,[]).append((lo,hi,sid))
    for spans in by_symbol.values():
        spans.sort()
        require(all(a[1]<=b[0] for a,b in zip(spans,spans[1:])), 'overlapping symbol segments')
    inventory, paths, source_keys, total_bytes = [], set(), set(), 0
    for ref in files:
        require(isinstance(ref,dict), 'invalid file reference')
        symbol, date, name, received = [ref.get(k) for k in ('symbol','day','path','retrieved_at')]
        require(isinstance(symbol,str) and symbol in by_symbol, 'unrequested source symbol')
        require(isinstance(date,str) and re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}',date), 'invalid source day')
        day = int(datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
        member = symbol+'-4h-'+date+'.csv'
        key = 'data/futures/um/daily/premiumIndexKlines/'+symbol+'/4h/'+symbol+'-4h-'+date+'.zip'
        require(ref.get('source_key')==key and key not in source_keys, 'wrong or duplicate premium source key')
        source_keys.add(key)
        require(timestamp(received) and received<=as_of, 'invalid source capture time')
        require(isinstance(name,str) and name and '\\' not in name and ':' not in name, 'unsafe input path')
        relative=PurePosixPath(name)
        require(not relative.is_absolute() and '..' not in relative.parts and str(relative)==name, 'unsafe input path')
        path=(root/name).resolve()
        require(path.is_relative_to(root) and name not in paths, 'duplicate or escaping path');paths.add(name)
        require(type(ref.get('bytes')) is int and 0<ref['bytes']<=MAX_ZIP, 'invalid byte binding')
        total_bytes += ref['bytes'];require(total_bytes<=128*1024*1024, 'aggregate input limit')
        require(isinstance(ref.get('sha256'),str) and re.fullmatch('[a-f0-9]{64}',ref['sha256']), 'invalid hash binding')
        raw=read(path);require(len(raw)==ref['bytes'] and sha(raw)==ref['sha256'], 'source binding mismatch')
        rows=parse_day(raw,day,member)
        outside=0
        for t,row in rows.items():
            require(row['closed_at']<=received, 'capture predates closed bar')
            match=next((sid for lo,hi,sid in by_symbol[symbol] if lo<=t<hi),None)
            if match is None:
                outside+=1;continue
            output=by_id[match]['rows'];require(t not in output, 'overlapping source bars')
            output[t]=dict(row,captured_at=received,historical_publication_time=None,source_path=name)
        inventory.append(dict(ref,parsed_rows=len(rows),outside_requested_segments=outside))
    result=[]
    for sid in sorted(by_id):
        seg=by_id[sid];missing=[]
        for t in range(seg['start'],seg['end'],BAR):
            if t not in seg['rows']:
                if missing and missing[-1]['end']==t:missing[-1]['end']+=BAR
                else:missing.append(dict(start=t,end=t+BAR))
        n=(seg['end']-seg['start'])//BAR
        result.append(dict(segment_id=sid,symbol=seg['symbol'],start=seg['start'],end=seg['end'],
                           expected_bars=n,observed_bars=len(seg['rows']),missing_bars=n-len(seg['rows']),
                           missing_intervals=missing,rows=[seg['rows'][t] for t in sorted(seg['rows'])]))
    return dict(schema='v9.premium-input-audit/1',as_of=as_of,manifest_sha256=sha(canonical(manifest)),
                status='CONTENT_BINDINGS_VERIFIED' if files else 'NO_SOURCE_FILES',segments=result,sources=sorted(inventory,key=lambda x:x['source_key']),
                missing_bars=sum(s['missing_bars'] for s in result),trade_authorization=False,study_eligible=False,
                interpretation='PREMIUM_INDEX_ONLY_NOT_PRICE_OR_FUNDING',
                limitations=['Caller-supplied source keys, captures and hashes do not authenticate upstream provenance.',
                             'Capture time is known only from supplied metadata; historical publication latency is unverified.',
                             'Missing rows are not zero; no interpolation or funding/price substitution.',
                             'No strategy, outcome study, historical population acceptance or live activation.'])


def known_at(report, segment_id, decision_time):
    """Conservative availability: require closure AND capture, never infer old publication time."""
    require(timestamp(decision_time), 'invalid decision time')
    require(report.get('schema')=='v9.premium-input-audit/1' and report.get('status')=='CONTENT_BINDINGS_VERIFIED', 'invalid report')
    rows=[s for s in report['segments'] if s['segment_id']==segment_id]
    require(len(rows)==1, 'missing or ambiguous segment')
    return [dict(r) for r in rows[0]['rows'] if r['closed_at']<=decision_time and r['captured_at']<=decision_time]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path);parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--as-of',required=True,type=int);parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args(argv)
    require(not args.out.resolve().is_relative_to(args.root.resolve()) and args.out.resolve()!=args.manifest.resolve(),
            'report must be outside sources and distinct from manifest')
    report=audit(decode(read(args.manifest)),args.root,args.as_of)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as stream:stream.write(canonical(report)+b'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
