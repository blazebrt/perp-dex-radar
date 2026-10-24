"""Synthetic-only A6 adapter resource probe; never reads market data."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_adapter as A, control_signals as S, control_extract as X


def probe(signals=20):
    if type(signals) is not int or not 1<=signals<=100:raise ValueError('synthetic signal count must be 1..100')
    assets=['SYNTH%03d'%i for i in range(61)];times=list(range(0,400*14400,14400));tid='a'*64
    raw='t,o,h,l,c,qv\n'+''.join(f'{t},100,100.5,99.5,100.1,2000000\n' for t in times)
    blob=gzip.compress(raw.encode(),mtime=0);digest=hashlib.sha256(blob).hexdigest()
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'h4').mkdir();(root/'pairs').mkdir()
        segments={}
        for asset in assets:
            (root/'h4'/(asset+'.csv.gz')).write_bytes(blob)
            segments[asset]=S.SegmentView(dict(segment=dict(asset=asset,source_symbol=asset+'USDT',first_bar=0),
                times=times,volumes=[2e6]*len(times),disputed_opens=[],source_sha256=digest))
        eligibility=[[True]*len(assets) for _ in times]
        context=dict(trials=[dict(trial_id=tid,archive_requirement='4h')],times=times,assets=assets,
                     eligibility=eligibility,segments=segments,start=30*86400,end=times[-1]+14400)
        generated=dict(i=list(range(180,180+signals)),j=[0]*signals,d=[1]*signals,stop=[.02]*signals,
                       target=[2.]*signals,trail=[0.]*signals,be=[0.]*signals,hold=[6]*signals)
        retained=[]
        S.project(tid,generated,times,assets,eligibility,segments,context['start'],context['end'],retained.append)
        adapter=A.Adapter(root,context);sink=X.Shards(root/'pairs',tid)
        reads=0;bytes_read=0;observed=0;plain_bytes=0
        original=Path.read_bytes
        def measured(path):
            nonlocal reads,bytes_read
            data=original(path)
            if path.parent==root/'h4':reads+=1;bytes_read+=len(data)
            return data
        started=time.perf_counter()
        with patch.object(Path,'read_bytes',measured):
            try:
                for signal in retained:
                    pair=adapter.match(signal)
                    observed+=pair['pair_status']=='PRICE_PAIR_OBSERVED'
                    plain_bytes+=len((json.dumps(pair,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode())
                    sink.emit(pair)
            finally:
                sink.close();adapter.close()
        elapsed=time.perf_counter()-started
        compressed=sum(p.stat().st_size for p in (root/'pairs').iterdir())
    return dict(schema='v9.a6-synthetic-resource-probe/1',status='NOT_RESOURCE_QUALIFIED',synthetic_only=True,
        market_data_loaded=False,assets=len(assets),bars_per_asset=len(times),signals=signals,
        observed_price_pairs=observed,price_file_reads=reads,compressed_price_bytes_read=bytes_read,
        distinct_available_price_files=len(assets),adapter_cache_windows=8,price_storage='HASH_BOUND_SQLITE_WINDOW_INDEX',
        rereads_beyond_available_files=max(0,reads-len(assets)),elapsed_seconds=elapsed,
        pair_json_bytes=plain_bytes,pair_gzip_bytes=compressed,
        naive_full_inventory_json_bytes=plain_bytes/signals*4263580,
        naive_full_inventory_gzip_bytes=compressed/signals*4263580,
        extrapolation_warning='SYNTHETIC_REPETITIVE_PRICES_NOT_A_MARKET_SIZE_OR_RUNTIME_GUARANTEE',
        measured_scope='ADAPTER_AND_PAIR_SHARD_ONLY_EXCLUDES_PREPARATION_SUMMARY_AUDIT_AND_GIT',
        source_sha256={p.name:X.sha(p) for p in (Path(__file__),Path(A.__file__),Path(A.P.__file__),
            Path(A.E.__file__),Path(S.__file__),Path(X.__file__))},promotion_authority=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--signals',type=int,default=20);ap.add_argument('--out',required=True)
    args=ap.parse_args();path=Path(args.out)
    if path.exists():raise FileExistsError('preserve previous resource probe')
    result=probe(args.signals)
    with path.open('x',encoding='utf8',newline='\n') as stream:stream.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
