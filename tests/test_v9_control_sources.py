import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from tools.v9 import control_sources as S


class Sources(unittest.TestCase):
    def fixture(self):
        coins=[dict(t=str(i),symbol=str(i)+'USDT',first_bar=0,last_bar=10*S.BAR) for i in range(87)]
        plan=dict(archive_commit=S.ARCHIVE,fetch_coins=coins,
                  source_files_sha256={'universe.json':'u',**{'h4/'+c['t']+'.csv.gz':c['t'] for c in coins}})
        audit=dict(archive_commit=S.ARCHIVE,source_conflict_count=189,
                   coverage={c['t']:dict(four_hour_conflicts=[]) for c in coins})
        ledger=[]
        for i in range(94):
            asset=str(i%87);t=(i//87)*S.BAR
            for field in (['qv','tbqv','c'] if i==0 else ['qv','tbqv']):
                audit['coverage'][asset]['four_hour_conflicts'].append(dict(timestamp=t,field=field))
            ledger.append(dict(coin=asset,t=t,evidence=dict(coin=asset,reference_sha256=asset)))
        return audit,plan,ledger

    def test_complete_original_inventory_not_only_quarantined_subset(self):
        args=self.fixture();result=S.build(*args)
        self.assertEqual(len(result['disputed_blocks']),94)
        self.assertEqual(result['disputed_segment_count'],87)
        self.assertEqual(result['disputed_field_count'],189)
        self.assertFalse(result['promotion_authority'])
        self.assertEqual(result,S.build(args[0],args[1],list(reversed(args[2]))))

    def test_missing_duplicate_or_mismatched_evidence_rejected(self):
        for kind in ('missing','duplicate','source','field','archive','time'):
            with self.subTest(kind=kind):
                a,p,l=self.fixture()
                if kind=='missing':l.pop()
                if kind=='duplicate':l.append(l[0])
                if kind=='source':l[0]['evidence']['reference_sha256']='wrong'
                if kind=='field':a['coverage']['0']['four_hour_conflicts'].append(a['coverage']['0']['four_hour_conflicts'][0])
                if kind=='archive':p['archive_commit']='wrong'
                if kind=='time':a['coverage']['0']['four_hour_conflicts'][0]['timestamp']=True
                with self.assertRaises(ValueError):S.build(a,p,l)

    def archive(self,root):
        (root/'h4').mkdir()
        data=gzip.compress(b't,qv\n0,0\n14400,12\n')
        (root/'h4/A.csv.gz').write_bytes(data)
        meta=dict(t='A',symbol='AUSDT',first_bar=0,last_bar=14400,bars=2,excluded=None)
        uni=json.dumps(dict(coins=[meta])).encode();(root/'universe.json').write_bytes(uni)
        inv=dict(archive_commit=S.ARCHIVE,disputed_blocks=[dict(asset='A',open=0)],
                 source_files_sha256={'universe.json':S.sha(uni),'h4/A.csv.gz':S.sha(data)})
        return meta,inv

    def test_load_exact_source_keeps_zero_and_segment_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);meta,inv=self.archive(root)
            self.assertEqual(S.load_universe(root,inv),{'A':meta})
            result=S.load_segment(root,inv,meta)
            self.assertEqual(result['times'],[0,14400])
            self.assertEqual(result['volumes'],[0.,12.])
            self.assertEqual(result['disputed_opens'],[0])
            self.assertEqual(result['segment']['source_symbol'],'AUSDT')

    def test_corrupt_or_subset_sources_and_metadata_rejected(self):
        for kind in ('hash','subset','extra','bounds','unsafe'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);meta,inv=self.archive(root)
                if kind=='hash':(root/'h4/A.csv.gz').write_bytes(b'changed')
                if kind=='subset':inv['source_files_sha256']['h4/B.csv.gz']='missing'
                if kind=='extra':(root/'h4/B.csv.gz').write_bytes(b'extra')
                if kind=='bounds':meta['last_bar']=28800
                if kind=='unsafe':meta['t']='../A'
                with self.assertRaises((ValueError,KeyError)):
                    if kind in ('subset','extra'):S.load_universe(root,inv)
                    else:S.load_segment(root,inv,meta)

    def test_malformed_bound_csv_rejected(self):
        for csv in (b't,qv\n0,1\n0,2\n',b't,qv\n0,nan\n14400,2\n',b't,qv\n0,-1\n14400,2\n',b't,x\n0,1\n'):
            with self.subTest(csv=csv),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);meta,inv=self.archive(root)
                data=gzip.compress(csv);(root/'h4/A.csv.gz').write_bytes(data)
                inv['source_files_sha256']['h4/A.csv.gz']=S.sha(data)
                with self.assertRaises(ValueError):S.load_segment(root,inv,meta)
