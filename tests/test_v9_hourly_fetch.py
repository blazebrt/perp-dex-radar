import csv
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.v9 import hourly_fetch as F
from tests.test_v9_hourly_plan import archive


def zipped(rows):
    text = io.StringIO()
    csv.writer(text, lineterminator='\n').writerows(rows)
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('data.csv', text.getvalue())
    return b.getvalue()


def row(t):
    return [str(t*1000), '10', '12', '9', '11', '100', str((t+3600)*1000-1), '1000', '10', '50', '500', '0']


class Parsing(unittest.TestCase):
    def test_units_header_zero_and_month_boundary(self):
        t = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        r = row(t)
        r[0] = str(t*1000000)
        self.assertEqual(F.parse(zipped([['open_time'], r]), '2020-01')[0][0], t)
        r[5] = r[7] = r[8] = r[10] = '0'
        self.assertEqual(F.parse(zipped([r]), '2020-01')[0][5], 0)
        self.assertEqual(F.months(t, t+31*86400), ['2020-01'])
        self.assertEqual(F.months(t, t+31*86400+3600), ['2020-01', '2020-02'])

    def test_bad_price_volume_timestamp_and_duplicates_fail(self):
        t = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        for col, value in [(0, str(t*1000+1)), (1, 'nan'), (2, '8'), (3, '13'),
                           (4, '0'), (7, '-1'), (10, '1001')]:
            r = row(t)
            r[col] = value
            with self.subTest(col=col), self.assertRaises(ValueError):
                F.parse(zipped([r]), '2020-01')
        with self.assertRaises(ValueError):
            F.parse(zipped([row(t), row(t)]), '2020-01')
        with self.assertRaises(ValueError):
            F.parse(zipped([row(t)]), '2020-02')
        with self.assertRaises(ValueError):
            F.parse(zipped([['not a header']]), '2020-01')

    def test_segment_excludes_other_lifetimes_and_reports_gaps(self):
        rows = [(t, 1, 1, 1, 1, 1, 0) for t in [0, 3600, 10800, 14400]]
        kept, c = F.segment(rows, 3600, 14400)
        self.assertEqual([r[0] for r in kept], [3600, 10800])
        self.assertEqual(c['missing_intervals'], [[7200, 10800]])
        self.assertEqual(c['expected_hours'], 3)
        with self.assertRaises(ValueError):
            F.segment(rows+[rows[1]], 3600, 14400)

    def test_zero_trade_carry_prices_do_not_define_four_hour_ohlc(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'reference.csv.gz'
            with gzip.open(path, 'wt') as f:
                f.write('t,o,h,l,c,qv,tbqv\n0,10,12,9,11,2000,1000\n')
            rows = [(0, 1, 1, 1, 1, 0, 0), (3600, 10, 12, 9, 11, 1000, 500),
                    (7200, 11, 12, 9, 11, 1000, 500), (10800, 99, 99, 99, 99, 0, 0)]
            self.assertEqual(F.reconcile(rows, path)['reconciled_four_hour_bars'], 1)
            changed = list(rows)
            changed[0] = (0, 1, 1, 1, 1, 1, 0)
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                F.reconcile(changed, path)
        r = row(0)
        r[7] = r[10] = '0'
        with self.assertRaisesRegex(ValueError, 'trading activity'):
            F.parse(zipped([r]), '1970-01')


class Collection(unittest.TestCase):
    def fixture(self, root):
        md = root/'md'
        md.mkdir()
        coins = archive(md)
        (md/'fund_bn').mkdir()
        for c in coins:
            with gzip.open(md/'fund_bn'/f"{c['t']}.csv.gz", 'wt') as f:
                f.write('t,rate,interval_h\n0,0.0001,8\n')
        plan = root/'plan.json'
        plan.write_text(json.dumps(F.P.build(md)))
        objects = {}
        for c in coins:
            by_month = {}
            for t in range(0, 122*86400, 3600):
                month = datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m')
                r = row(t)
                r[7], r[10] = '250000', '125000'
                by_month.setdefault(month, []).append(r)
            sym = c['symbol']
            for month, rows in by_month.items():
                objects[f'data/futures/um/monthly/klines/{sym}/1h/{sym}-1h-{month}.zip'] = zipped(rows)
        return md, plan, objects

    def run_fake(self, md, plan, out, objects):
        def listing(prefix):
            return ([dict(key=k, size=len(v), etag='test') for k, v in objects.items() if k.startswith(prefix)], [])
        with patch.object(F.A, 's3_list', side_effect=listing), patch.object(
                F.A, 'cached', side_effect=lambda cache, item: (objects[item['key']], False)):
            return F.run(md, plan, out, out.parent/'cache', workers=2)

    def test_full_collection_hashes_funding_and_deterministic_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md, plan, objects = self.fixture(root)
            a = self.run_fake(md, plan, root/'out', objects)
            self.assertTrue(a['all_hours_observed'])
            self.assertFalse(a['replay_complete'])
            self.assertFalse(a['promotion_authority'])
            for path, digest in a['artifacts_sha256'].items():
                self.assertEqual(F.P.sha(root/'out'/path), digest)
            self.assertEqual((root/'out/fund_bn/BTC.csv.gz').read_bytes(), (md/'fund_bn/BTC.csv.gz').read_bytes())
            b = self.run_fake(md, plan, root/'out2', objects)
            self.assertEqual(a, b)
            with self.assertRaisesRegex(ValueError, 'empty'):
                self.run_fake(md, plan, root/'out', objects)

    def test_missing_month_has_no_completion_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md, plan, objects = self.fixture(root)
            del objects[sorted(objects)[0]]
            with self.assertRaisesRegex(ValueError, 'month missing'):
                self.run_fake(md, plan, root/'out', objects)
            self.assertFalse((root/'out/hourly_manifest.json').exists())

    def test_changed_source_refuses_to_collect(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md, plan, objects = self.fixture(root)
            data = json.loads(plan.read_text())
            data['days'][0]['selected'] = []
            plan.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'reproduce'):
                self.run_fake(md, plan, root/'out', objects)
            self.assertFalse((root/'out/hourly_manifest.json').exists())

    def test_conflicts_preserved_across_symbols_without_accepted_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md, plan, objects = self.fixture(root)
            key = sorted(objects)[0]
            with zipfile.ZipFile(io.BytesIO(objects[key])) as z:
                rows = list(csv.reader(io.StringIO(z.read(z.namelist()[0]).decode())))
            rows[0][7] = '250001'
            objects[key] = zipped(rows)
            with self.assertRaisesRegex(ValueError, 'source reconciliation failed'):
                self.run_fake(md, plan, root/'out', objects)
            self.assertFalse((root/'out/hourly_manifest.json').exists())
            rejected = json.loads((root/'out/rejected_manifest.json').read_text())
            self.assertEqual(rejected['schema'], 'v9.hourly-archive-rejected/1')
            self.assertFalse(rejected['source_reconciliation_passed'])
            self.assertEqual(rejected['source_conflict_count'], 1)
            self.assertEqual(set(rejected['coverage']), {'BTC','C000'})
            for path, digest in rejected['artifacts_sha256'].items():
                self.assertEqual(F.P.sha(root/'out'/path), digest)

    def test_price_disagreement_and_gaps_are_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            md, _, _ = self.fixture(root)
            rows = [(t, 10, 12, 9, 11, 250000, 125000) for t in range(0, 122*86400, 3600)]
            cov = F.reconcile(rows[1:], md/'h4/BTC.csv.gz')
            self.assertEqual(cov['incomplete_four_hour_groups'], 1)
            with gzip.open(md/'h4/tiny.csv.gz', 'wt') as f:
                f.write('t,o,h,l,c,qv,tbqv\n0,1e-10,2e-10,1e-10,1e-10,4,2\n')
            tiny = [(t, 1e-9, 2e-9, 1e-9, 1e-9, 1, 0.5) for t in range(0, 14400, 3600)]
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                F.reconcile(tiny, md/'h4/tiny.csv.gz')
            rows[0] = (0, 10, 12, 9, 11, 500000, 125000)
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                F.reconcile(rows, md/'h4/BTC.csv.gz')


if __name__ == '__main__':
    unittest.main()
