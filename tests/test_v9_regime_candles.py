"""Synthetic closed-candle acquisition, no external requests."""
import copy
from pathlib import Path
import tempfile
import unittest
from tools.v9 import regime_candles as C, regime_research as R
from v9.paper_history import canonical

D=R.DAY
NOW=500*D+1800


def btc():return [[i*D,90,110,100,101,2] for i in range(300,501)][::-1]
def dvol():return dict(result=dict(data=[[500*D*1000-3600000,59,61,58,60],
                                      [500*D*1000,60,99,59,98]],continuation=None))


class Capture(unittest.TestCase):
    def fetch(self,url):return canonical(btc() if 'coinbase' in url else dvol())

    def test_current_candles_excluded_and_all_history_only_available_at_capture(self):
        for kind,payload,count in [('btc_close',btc(),200),('dvol',dvol(),1)]:
            result=C.parse(canonical(payload),kind,NOW,NOW+10)
            self.assertTrue(result['required_current_window_complete'])
            self.assertEqual(len(result['observations']),count)
            self.assertEqual(result['excluded_outside_completed_window'],1)
            self.assertTrue(all(x['available_at']==NOW+10 and x['period_end']<=NOW for x in result['observations']))
        rows=C.parse(canonical(btc()),'btc_close',NOW,NOW+10)['observations']
        inputs=R.Inputs(rows)
        self.assertEqual(inputs.at('BTC_ABOVE_SMA200',NOW+10)['state'],'UNKNOWN')
        self.assertEqual(inputs.at('BTC_ABOVE_SMA200',NOW+11)['state'],'OFF')

    def test_capture_reverification_exclusive_output_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'capture'
            report=C.capture(root,request=self.fetch,now=lambda:NOW)
            self.assertEqual(report,C.verify(root));self.assertEqual(report['unavailable'],{})
            self.assertEqual(len(report['observations']),201)
            self.assertFalse(report['dataset_accepted']);self.assertFalse(report['historical_availability_inferred'])
            with self.assertRaises(FileExistsError):C.capture(root,request=self.fetch,now=lambda:NOW)
            (root/'btc_close.json').write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError,'binding'):C.verify(root)

    def test_failed_source_preserves_other_source_without_retry(self):
        calls=[]
        def fetch(url):
            calls.append(url)
            if 'deribit' in url:raise OSError('offline')
            return self.fetch(url)
        with tempfile.TemporaryDirectory() as tmp:
            result=C.capture(Path(tmp)/'capture',request=fetch,now=lambda:NOW)
            self.assertEqual(len(calls),2)
            self.assertEqual(result['unavailable'],{'dvol':'FAILED'})
            self.assertEqual(len(result['observations']),200)

    def test_incomplete_window_not_emitted_as_usable_input(self):
        def fetch(url):return canonical(btc()[2:] if 'coinbase' in url else dict(result=dict(data=[],continuation=None)))
        with tempfile.TemporaryDirectory() as tmp:
            result=C.capture(Path(tmp)/'capture',request=fetch,now=lambda:NOW)
            self.assertEqual(result['observations'],[])
            self.assertEqual(set(result['unavailable']),set(C.KINDS))

    def test_duplicate_invalid_geometry_partial_response_and_nonfinite_fail(self):
        bad=btc();bad.append(copy.deepcopy(bad[-1]))
        cases=[('btc_close',bad),('btc_close',[[400*D,100,90,99,98,1]]),
               ('btc_close',[[400*D,90,110,100,101,-1]]),
               ('dvol',dict(result=dict(data=[],continuation=123))),
               ('dvol',dict(result=dict(data=[[500*D*1000+1,60,61,59,60]],continuation=None)))]
        for kind,payload in cases:
            with self.assertRaises(ValueError):C.parse(canonical(payload),kind,NOW,NOW)
        with self.assertRaises(ValueError):C.parse(b'[[1,NaN,2,1,1,1]]','btc_close',NOW,NOW)
        with self.assertRaises(ValueError):C.parse(b'[[34560000,1e-999999999,2,1,1,1]]','btc_close',NOW,NOW)
