"""A6 source-bound price adapter; construction alone never generates outcomes.

Production callers must supply control_extract.prepare's verified context and
independently verified A6.2 records. This adapter does not verify the package or
recompute original generator geometry; those remain separate acceptance gates.
"""
import csv
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
from collections import OrderedDict
from pathlib import Path
from tools.v9 import control_execution as E, control_pairs as P, control_sources as S


class Adapter:
    def __init__(self, directory, context, price_cache_size=8):
        S.require(type(price_cache_size) is int and price_cache_size > 0, 'invalid cache size')
        self.directory, self.context = Path(directory), context
        self.limit, self.prices = price_cache_size, OrderedDict()
        self.loaded = set()
        self.temporary = tempfile.TemporaryDirectory(prefix='a6-price-index-')
        self.db = sqlite3.connect(Path(self.temporary.name)/'prices.sqlite')
        # Disposable private index: rebuilt from hash-verified sources, never resumed.
        # Retained evidence databases/files keep their existing durability settings.
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.execute('PRAGMA cache_size=-8192')
        self.db.execute('CREATE TABLE prices(asset TEXT,t INTEGER,o REAL,h REAL,l REAL,c REAL,qv REAL, PRIMARY KEY(asset,t)) WITHOUT ROWID')
        self.candidate_key, self.candidate_rows = None, None
        self.trials = {t['trial_id'] for t in context['trials'] if t['archive_requirement']=='4h'}

    def close(self):
        if getattr(self,'db',None) is not None:
            self.db.close();self.db=None
        if getattr(self,'temporary',None) is not None:
            self.temporary.cleanup();self.temporary=None
        if hasattr(self,'prices'):self.prices.clear()

    def __del__(self):self.close()

    def price_rows(self, asset, start=None, end=None):
        S.require(asset in self.context['segments'] and S.safe_asset(asset), 'unknown price segment')
        S.require(self.db is not None,'price index is closed')
        if asset not in self.loaded:
            view = self.context['segments'][asset]
            raw = S.bound((self.directory/'h4'/(asset+'.csv.gz')).read_bytes(), view.source_sha256)
            reader = csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf8')))
            S.require(reader.fieldnames is not None and {'t','o','h','l','c','qv'} <= set(reader.fieldnames),
                      'missing price columns')
            rows = {}
            for row in reader:
                t = int(row['t'])
                S.require(t not in rows, 'duplicate price timestamp')
                values = {}
                for key in ('o','h','l','c','qv'):
                    try: values[key] = float(row[key])
                    except (ValueError, TypeError): values[key] = None
                rows[t] = values
            S.require(list(rows)==view.times, 'price/feature calendar mismatch')
            S.require(all(rows[t]['qv']==v for t,v in zip(view.times,view.volumes)), 'price/feature volume mismatch')
            with self.db:
                self.db.executemany('INSERT INTO prices VALUES(?,?,?,?,?,?,?)',
                    ((asset,t,*(row[k] for k in ('o','h','l','c','qv'))) for t,row in rows.items()))
            self.loaded.add(asset)
        view=self.context['segments'][asset]
        start=view.times[0] if start is None else start
        end=view.times[-1]+E.BAR if end is None else end
        key=(asset,start,end)
        if key not in self.prices:
            self.prices[key]={t:dict(zip(('o','h','l','c','qv'),values)) for t,*values in
                self.db.execute('SELECT t,o,h,l,c,qv FROM prices WHERE asset=? AND t>=? AND t<? ORDER BY t',(asset,start,end))}
            if len(self.prices)>self.limit:self.prices.popitem(last=False)
        self.prices.move_to_end(key)
        return self.prices[key]

    def execute(self, asset, decision, direction, geometry, eligible):
        view = self.context['segments'][asset]
        # A terminal segment is censored, never extended using a different listing.
        end = min(self.context['end'], view.times[-1]+E.BAR)
        S.require(type(geometry.get('hold')) is int and geometry['hold']>0,'invalid hold')
        rows=self.price_rows(asset,decision,min(end,decision+geometry['hold']*E.BAR))
        return E.simulate(rows,decision,direction,geometry,eligible,view.disputed,end)

    def match(self, signal):
        c = self.context
        i,j = signal['panel_i'],signal['panel_j']
        S.require(type(i) is int and type(j) is int and 0<=i<len(c['times']) and 0<=j<len(c['assets']),
                  'invalid retained panel indices')
        asset,decision,direction = signal['asset'],signal['decision_time'],signal['direction']
        S.require(signal['trial_id'] in self.trials and asset==c['assets'][j] and
                  decision==int(c['times'][i])+E.BAR and c['start']<=decision<=c['end'], 'signal source identity mismatch')
        eligible = bool(c['eligibility'][i][j])
        view = c['segments'][asset]
        identity = [signal['trial_id'],signal['source_ordinal'],asset,decision,direction]
        digest = hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()
        S.require(signal['signal_id']==digest and signal['source_sha256']==view.source_sha256 and
                  signal['original_eligible'] is eligible and signal['features']==view.snapshot(decision,direction,eligible)
                  and signal['history']==view.history(decision), 'retained signal/source mismatch')
        S.require(signal['full_matched_authority'] is False and signal['promotion_authority'] is False,
                  'unsupported signal authority')
        key = (i,direction)
        if key != self.candidate_key:
            self.candidate_rows = [c['segments'][a].snapshot(decision,direction,bool(c['eligibility'][i][k]))
                                   for k,a in enumerate(c['assets'])]
            self.candidate_key = key
        return P.match(signal,self.candidate_rows,self.execute)
