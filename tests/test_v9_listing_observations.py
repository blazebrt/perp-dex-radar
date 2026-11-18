"""Synthetic local source evidence only; no market requests or outcome study."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.v9 import listing_observations as L

B='BINANCE_USDM_EXCHANGE_INFO'
U='UPBIT_KR_MARKETS'


def binance(symbol='BTCUSDT', onboard=900000, status='TRADING'):
    return dict(symbol=symbol, baseAsset=symbol.removesuffix('USDT'), quoteAsset='USDT',
                contractType='PERPETUAL', status=status, onboardDate=onboard)


class Evidence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'sources';self.root.mkdir()
        self.manifest={'schema':'v9.listing-observation-input/1','captures':[]}

    def capture(self,source,stamp,payload):
        raw=L.canonical(payload);name=str(len(self.manifest['captures']))+'.json'
        (self.root/name).write_bytes(raw)
        ref=dict(source=source,retrieved_at=stamp,path=name,bytes=len(raw),sha256=L.sha(raw),
                 request_url=L.SOURCES[source][0],http_status=200)
        self.manifest['captures'].append(ref);return ref

    def audit(self):return L.audit(self.manifest,self.root,10000)

    def test_baseline_addition_absence_reappearance_are_not_listing_events(self):
        self.capture(U,1000,[{'market':'KRW-BTC'}])
        self.capture(U,1100,[{'market':'KRW-BTC'},{'market':'KRW-ETH'}])
        self.capture(U,1200,[{'market':'KRW-ETH'}])
        self.capture(U,1300,[{'market':'KRW-BTC'},{'market':'KRW-ETH'}])
        before=copy.deepcopy(self.manifest);r=self.audit();rows=r['captures']
        self.assertEqual(rows[0]['additions'][0]['observation_kind'],'BASELINE_MEMBER')
        self.assertEqual(rows[1]['additions'][0]['observation_kind'],'NEWLY_OBSERVED_MEMBER')
        self.assertEqual(rows[2]['absences'][0]['observation_kind'],'ABSENT_FROM_RESPONSE')
        self.assertIsNone(rows[2]['absences'][0]['delisting_time'])
        reappeared=rows[3]['additions'][0]
        self.assertEqual(reappeared['observation_kind'],'REOBSERVED_MEMBER')
        self.assertEqual(reappeared['first_known_in_this_series_at'],1000)
        self.assertEqual(rows[3]['observation_gap_s'],100)
        for capture in rows:
            for row in capture['additions']:
                self.assertIsNone(row['listing_time']);self.assertFalse(row['identity_verified'])
        self.assertEqual(r['verified_listing_events'],0)
        self.assertFalse(r['listing_study_eligible']);self.assertFalse(r['trade_authorization'])
        self.assertEqual(self.manifest,before)
        self.assertEqual(r,self.audit())

    def test_reported_onboard_date_never_backdates_availability(self):
        self.capture(B,1000,{'symbols':[binance(),binance('ETHUSDT',1100000,'PENDING_TRADING')]})
        self.capture(B,1200,{'symbols':[binance(onboard=800000),binance('ETHUSDT',1100000)]})
        r=self.audit();baseline=r['captures'][0]['additions']
        self.assertEqual(baseline[0]['metadata']['onboard_state'],'REPORTED_METADATA')
        self.assertEqual(baseline[1]['metadata']['onboard_state'],'SCHEDULED_METADATA')
        self.assertEqual(baseline[0]['observed_at'],1000)
        self.assertIsNone(baseline[0]['listing_time'])
        self.assertEqual(len(r['captures'][1]['metadata_changes']),2)
        self.assertEqual(r['captures'][1]['additions'],[])
        for value in (None,0,-1,True,'900000',8640000000000000):
            row=L.normalize(B,{'symbols':[binance(onboard=value)]},1000)['BTCUSDT']
            self.assertEqual(row['onboard_state'],'UNAVAILABLE');self.assertIsNone(row['reported_onboard_ms'])

    def test_venues_and_quote_markets_stay_separate_and_reordering_is_deterministic(self):
        self.capture(U,1100,[{'market':'BTC-ETH'},{'market':'KRW-ETH'}])
        self.capture(B,1000,{'symbols':[binance('ETHUSDT')]})
        a=self.audit();self.manifest['captures'].reverse();b=self.audit()
        self.assertEqual(a['captures'],b['captures'])
        self.assertNotEqual(a['manifest_sha256'],b['manifest_sha256'])
        self.assertEqual([r['markets'] for r in a['captures']],[1,2])
        self.assertTrue(all(row['observation_kind']=='BASELINE_MEMBER' for c in a['captures'] for row in c['additions']))

    def test_bad_source_contract_times_and_bindings_fail(self):
        ref=self.capture(U,1000,[{'market':'KRW-BTC'}]);original=copy.deepcopy(ref)
        for key,value in [('source','UPBIT_GLOBAL'),('request_url','https://example.com'),('http_status',True),
                          ('retrieved_at',True),('retrieved_at',10001),('bytes',True),('sha256','f'*64)]:
            with self.subTest(key=key):
                ref.clear();ref.update(original);ref[key]=value
                with self.assertRaises(ValueError):self.audit()
        ref.clear();ref.update(original);(self.root/ref['path']).write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError,'binding'):self.audit()

    def test_empty_duplicate_malformed_and_nonfinite_payloads_fail(self):
        for source,payload in [(U,[]),(U,[{'market':'KRW-BTC'},{'market':'KRW-BTC'}]),
                               (U,[{'market':'BTC'}]),(B,{'symbols':[]}),(B,[binance()]),
                               (B,{'symbols':[binance(),binance()]}),(B,{'symbols':[{'symbol':'BTCUSDT'}]})]:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):L.normalize(source,payload,1000)
        for raw in (b'{"symbols":[],"symbols":[]}',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1e400}'):
            with self.assertRaises(ValueError):L.decode(raw)
        self.capture(U,1000,[{'market':'KRW-BTC'}])
        self.capture(U,1000,[{'market':'KRW-ETH'}])
        with self.assertRaisesRegex(ValueError,'ambiguous capture'):self.audit()

    def test_paths_and_size_limits_fail_closed(self):
        ref=self.capture(U,1000,[{'market':'KRW-BTC'}])
        for name in ('../escape','/absolute','C:/outside','dir\\file','./0.json'):
            ref['path']=name
            with self.assertRaises(ValueError):self.audit()
        ref['path']='0.json'
        with patch.object(L,'MAX_BYTES',1):
            with self.assertRaises(ValueError):self.audit()
        with patch.object(L,'MAX_CAPTURES',0):
            with self.assertRaises(ValueError):self.audit()
        with patch.object(L,'MAX_MARKETS',0):
            with self.assertRaises(ValueError):self.audit()
        outside=Path(self.tmp.name)/'outside.json';outside.write_bytes((self.root/'0.json').read_bytes())
        try:(self.root/'link.json').symlink_to(outside)
        except OSError:return
        ref['path']='link.json'
        with self.assertRaisesRegex(ValueError,'escape'):self.audit()

    def test_cli_preserves_sources_and_never_overwrites_previous_report(self):
        self.capture(U,1000,[{'market':'KRW-BTC'}]);manifest=Path(self.tmp.name)/'manifest.json'
        manifest.write_bytes(L.canonical(self.manifest));out=Path(self.tmp.name)/'report.json'
        args=['--manifest',str(manifest),'--root',str(self.root),'--as-of','10000','--out',str(out)]
        self.assertEqual(L.main(args),0);first=out.read_bytes()
        self.assertEqual(L.decode(first)['status'],'CONTENT_BINDINGS_VERIFIED')
        with self.assertRaises(FileExistsError):L.main(args)
        self.assertEqual(out.read_bytes(),first)
        args[-1]=str(self.root/'overwrite.json')
        with self.assertRaisesRegex(ValueError,'outside'):L.main(args)
