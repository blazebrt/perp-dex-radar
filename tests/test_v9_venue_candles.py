"""Synthetic public-response fixtures; no network or outcomes."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.v9 import venue_candles as V

DAY = V.WIDTHS['1d']


def bar(coin, interval, t=0):
    return dict(s=coin, i=interval, t=t, T=t+V.WIDTHS[interval]-1,
                o='10', h='12', l='9', c='11', v='0', n=0)


class Venue(unittest.TestCase):
    def fetch(self, body):
        if body['type'] == 'meta':
            return V.canonical(dict(universe=[dict(name='BTC'), dict(name='OLD', isDelisted=True)]))
        req = body['req']
        return V.canonical([bar(req['coin'], req['interval'])])

    def acquire(self, root, fetch=None):
        return V.acquire(root, 0, DAY, fetch=fetch or self.fetch, sleep=lambda _: None, now=lambda: DAY/1000)

    def test_all_metadata_instruments_including_delisted_retained_and_reverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'
            report = self.acquire(root)
            self.assertEqual(report, V.verify(root))
            self.assertEqual(report['expected_requests'], 4)
            self.assertEqual(report['delisted_instruments'], 1)
            self.assertEqual(report['status'], 'SOURCE_RESPONSES_VERIFIED')
            self.assertEqual(report['coverage'][0]['unavailable_window_bars'], 5)
            self.assertTrue(report['coverage'][1]['requested_window_complete'])
            self.assertFalse(report['historical_universe_complete'])
            self.assertFalse(report['dataset_accepted'])
            self.assertFalse(report['outcome_execution_authorized'])
            with self.assertRaises(FileExistsError): self.acquire(root)

    def test_partial_failure_retains_raw_and_other_instruments_without_retry(self):
        calls = []
        def fetch(body):
            calls.append(copy.deepcopy(body))
            if body.get('req', {}).get('coin') == 'OLD': return b'not JSON'
            return self.fetch(body)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'; result = self.acquire(root, fetch)
            self.assertEqual(len(calls), 5)
            self.assertEqual(result['status'], 'INCOMPLETE_CAPTURE')
            self.assertEqual(result['failed_or_interrupted'], 2)
            self.assertEqual((root/'0001-4h.json').read_bytes(), b'not JSON')
            self.assertEqual(result, V.verify(root))

    def test_interruption_retains_started_request_and_does_not_resume(self):
        def fetch(body):
            if body['type'] != 'meta': raise KeyboardInterrupt()
            return self.fetch(body)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'
            with self.assertRaises(KeyboardInterrupt): self.acquire(root, fetch)
            result = V.verify(root)
            self.assertEqual(result['status'], 'INCOMPLETE_CAPTURE')
            self.assertEqual(result['failed_or_interrupted'], 1)
            self.assertEqual(result['unattempted_requests'], 3)

    def test_binding_inventory_and_summary_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'; self.acquire(root)
            original = (root/'manifest.json').read_bytes()
            for mutate in (lambda m: m['requests'].reverse(),
                           lambda m: m['requests'][0]['coverage'].update(rows=999),
                           lambda m: m['requests'][0]['raw'].update(path='../outside'),
                           lambda m: m['requests'][0]['request']['req'].update(endTime=999)):
                doc = V.decode(original); mutate(doc)
                (root/'manifest.json').write_bytes(V.canonical(doc))
                with self.assertRaises(ValueError): V.verify(root)
            (root/'manifest.json').write_bytes(original)
            (root/'0000-4h.json').write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError, 'binding'): V.verify(root)

    def test_geometry_times_decimal_identity_order_and_limit(self):
        good = bar('BTC', '4h')
        for update in ({'s':'OTHER'}, {'i':'1d'}, {'t':True}, {'T':1}, {'n':True},
                       {'o':'NaN'}, {'v':'-1'}, {'l':'13'}, {'c':11}, {'v':'1e999999999999999999999'}):
            row = dict(good, **update)
            with self.assertRaises(ValueError): V.coverage(V.canonical([row]), 'BTC', '4h', 0, DAY)
        with self.assertRaises(ValueError): V.coverage(V.canonical([good, good]), 'BTC', '4h', 0, DAY)
        with self.assertRaises(ValueError): V.coverage(V.canonical([good]*5001), 'BTC', '4h', 0, DAY)
        result = V.coverage(V.canonical([good, bar('BTC', '4h', 2*V.WIDTHS['4h'])]), 'BTC', '4h', 0, DAY)
        self.assertEqual(result['internal_missing_bars'], 1)
        self.assertEqual(result['unavailable_window_bars'], 4)
        self.assertEqual(V.coverage(b'[]', 'BTC', '4h', 0, DAY)['unavailable_window_bars'], 6)

    def test_duplicate_metadata_and_future_window_refused(self):
        for doc in ({'universe':[]}, {'universe':[{'name':'X'}, {'name':'X'}]},
                    {'universe':[{'name':'X','isDelisted':'false'}]}):
            with self.assertRaises(ValueError): V.universe(V.canonical(doc))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'
            with self.assertRaisesRegex(ValueError, 'future'):
                V.acquire(root, 0, DAY, now=lambda: 0)
            self.assertFalse(root.exists())

    def test_total_budget_stops_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'capture'
            with patch.object(V, 'MAX_TOTAL_BYTES', len(self.fetch({'type':'meta'}))):
                with self.assertRaises(V.CaptureBudgetExceeded): self.acquire(root)
            result = V.verify(root)
            self.assertEqual(result['status'], 'INCOMPLETE_CAPTURE')
            self.assertEqual(result['attempted_requests'], 1)
            self.assertEqual(result['unattempted_requests'], 3)
