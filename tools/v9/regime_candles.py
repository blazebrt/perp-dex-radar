"""Bounded prospective BTC/DVOL raw capture, with no historical availability inference."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request

from v9.paper_history import canonical, invalid_constant, pairs, require, sha
from tools.v9.regime_research import DAY, Inputs

MAX_BYTES = 2*1024*1024
KINDS = ('btc_close', 'dvol')


def urls(as_of):
    require(type(as_of) is int and as_of > 201*DAY, 'invalid request time')
    end = as_of//DAY*DAY
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return {'btc_close': 'https://api.exchange.coinbase.com/products/BTC-USD/candles?'+
            urllib.parse.urlencode(dict(granularity=DAY,start=iso(end-200*DAY),end=iso(end))),
            'dvol': 'https://www.deribit.com/api/v2/public/get_volatility_index_data?'+
            urllib.parse.urlencode(dict(currency='BTC',resolution=3600,
                                       start_timestamp=(as_of-8*DAY)*1000,end_timestamp=as_of*1000))}


def numeric(value):
    require(type(value) in (int, Decimal), 'invalid source number')
    value = Decimal(value)
    require(value.is_finite() and len(value.as_tuple().digits)<=40
            and -40<=value.as_tuple().exponent<=18 and abs(value)<=Decimal('1e18'),
            'invalid source magnitude or precision')
    return value


def parse(raw, kind, as_of, captured_at):
    require(kind in KINDS and isinstance(raw,bytes) and len(raw)<=MAX_BYTES, 'invalid raw source')
    require(type(captured_at) is int and captured_at >= as_of, 'invalid capture time')
    urls(as_of)
    doc=json.loads(raw.decode('utf-8'),parse_float=Decimal,parse_constant=invalid_constant,object_pairs_hook=pairs)
    if kind=='dvol':
        require(isinstance(doc,dict) and 'error' not in doc and isinstance(doc.get('result'),dict), 'invalid DVOL envelope')
        require(doc['result'].get('continuation') is None, 'incomplete DVOL response')
        rows=doc['result'].get('data'); width=3600
    else: rows=doc; width=DAY
    require(isinstance(rows,list) and len(rows)<= (300 if kind=='btc_close' else 250), 'invalid candle count')
    observations,seen=[],set(); excluded=0
    lower=as_of//DAY*DAY-200*DAY if kind=='btc_close' else as_of-8*DAY
    for row in rows:
        require(isinstance(row,list) and len(row)==(6 if kind=='btc_close' else 5), 'invalid candle shape')
        stamp=row[0]
        require(type(stamp) is int and stamp>=0, 'invalid candle timestamp')
        if kind=='dvol':
            require(stamp%1000==0,'subsecond DVOL timestamp'); opened=stamp//1000
            o,h,l,c=[numeric(v) for v in row[1:]]
        else:
            opened=stamp; l,h,o,c,volume=[numeric(v) for v in row[1:]]
            require(volume>=0,'negative volume')
        require(opened%width==0 and opened not in seen,'duplicate/off-grid candle');seen.add(opened)
        require(0<=l<=min(o,c)<=max(o,c)<=h and (kind=='dvol' or l>0),'invalid OHLC')
        end=opened+width
        if opened<lower or end>as_of:
            excluded+=1;continue
        observations.append(dict(feature=kind,period_end=end,available_at=captured_at,
                                 value=format(c,'f'),source_sha256=sha(raw)))
    observations.sort(key=lambda x:x['period_end'])
    Inputs(observations)
    if kind=='btc_close':
        required={as_of//DAY*DAY-i*DAY for i in range(200)}
        complete={x['period_end'] for x in observations}==required
    else:
        complete=bool(observations) and observations[-1]['period_end']==as_of//3600*3600
    return dict(observations=observations,returned_rows=len(rows),excluded_outside_completed_window=excluded,
                required_current_window_complete=complete)


def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'perp-dex-radar/regime-source-capture'})
    with urllib.request.urlopen(req,timeout=30) as response: raw=response.read(MAX_BYTES+1)
    require(len(raw)<=MAX_BYTES,'response size limit')
    return raw


def capture(out, *, request=fetch, now=time.time):
    root=Path(out);root.mkdir(parents=True,exist_ok=False)
    as_of=int(now()); requests=urls(as_of)
    manifest=dict(schema='v9.regime-candle-capture/1',as_of=as_of,captured_at=None,sources={},
                  collector_sha256=sha(Path(__file__).read_bytes()))
    def checkpoint():
        p=root/'manifest.tmp'
        with p.open('wb') as stream:
            stream.write(canonical(manifest));stream.flush();os.fsync(stream.fileno())
        os.replace(p,root/'manifest.json')
    checkpoint()
    for kind,url in requests.items():
        ref=dict(url=url,path=kind+'.json',status='STARTED');manifest['sources'][kind]=ref;checkpoint()
        try:
            raw=request(url)
            require(isinstance(raw,bytes) and len(raw)<=MAX_BYTES,'response size/type')
            with (root/ref['path']).open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            ref.update(status='RETAINED',bytes=len(raw),sha256=sha(raw),received_at=int(now()))
        except Exception as error:ref.update(status='FAILED',error_type=type(error).__name__)
        checkpoint()
    manifest['captured_at']=int(now());checkpoint()
    return verify(root)


def verify(root):
    root=Path(root)
    def read(path):
        p=root/path
        require(not root.is_symlink() and not p.is_symlink() and p.is_file()
                and p.stat().st_size<=MAX_BYTES,'invalid retained file')
        return p.read_bytes()
    raw_manifest=read('manifest.json')
    manifest=json.loads(raw_manifest,object_pairs_hook=pairs,parse_constant=invalid_constant)
    require(manifest.get('schema')=='v9.regime-candle-capture/1','invalid manifest')
    require(manifest.get('collector_sha256')==sha(Path(__file__).read_bytes()),'collector implementation mismatch')
    as_of=manifest.get('as_of'); expected=urls(as_of)
    sources=manifest.get('sources');require(isinstance(sources,dict) and set(sources)<=set(KINDS),'invalid sources')
    captured=manifest.get('captured_at');valid_time=type(captured) is int and captured>=as_of
    observations=[]; unavailable={};details={}
    for kind,url in expected.items():
        ref=sources.get(kind)
        if ref is None:unavailable[kind]='NOT_ATTEMPTED';continue
        require(ref.get('url')==url and ref.get('path')==kind+'.json','request binding mismatch')
        require(ref.get('status') in ('STARTED','FAILED','RETAINED'),'invalid request state')
        if ref['status']!='RETAINED':unavailable[kind]=ref['status'];continue
        raw=read(ref['path'])
        require(type(ref.get('bytes')) is int and ref['bytes']==len(raw) and ref.get('sha256')==sha(raw),'raw binding mismatch')
        if not valid_time or type(ref.get('received_at')) is not int or not as_of<=ref['received_at']<=captured:
            unavailable[kind]='UNVERIFIED_CAPTURE_TIME';continue
        try:result=parse(raw,kind,as_of,captured)
        except (ValueError,ArithmeticError,TypeError):unavailable[kind]='INVALID_SOURCE_RESPONSE';continue
        details[kind]={k:v for k,v in result.items() if k!='observations'}
        if not result['required_current_window_complete']:unavailable[kind]='INCOMPLETE_CURRENT_WINDOW'
        else:observations.extend(result['observations'])
    return dict(schema='v9.regime-candle-inputs/1',manifest_sha256=sha(raw_manifest),
                collector_sha256=manifest['collector_sha256'],
                observations=observations,unavailable=unavailable,coverage=details,
                historical_availability_inferred=False,dataset_accepted=False,live_regime_gating_authorized=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['capture','verify']);parser.add_argument('--directory',required=True)
    args=parser.parse_args(argv)
    print(json.dumps(capture(args.directory) if args.mode=='capture' else verify(args.directory),sort_keys=True))


if __name__=='__main__':main()
