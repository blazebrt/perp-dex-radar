import copy
import gzip
import csv
import json
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.v9 import hourly_quote_precision as Q
from tools.v9 import hourly_trades as T
from tests.test_v9_hourly_trades import tape, trades, reference, NAME, DAY, BLOCK


def fixture(rows=None):
    rows = trades() if rows is None else rows
    raw, checksum = tape(rows)
    d = T.audit(raw,checksum,NAME,DAY,reference())
    d['coin'] = 'TEST'
    return raw,d


class QuotePrecision(unittest.TestCase):
    def test_equal_quotes_reproduce_original(self):
        raw,d = fixture()
        r = Q.compare(raw,d,reference())
        b = r['blocks'][0]
        self.assertTrue(b['product_aggregate_matches'])
        self.assertTrue(b['continuity_checked'])
        self.assertEqual(sum(h['different_quote_records'] for h in b['hours']),0)
        self.assertEqual(b['volume_comparisons'][0]['product'],'55')
        self.assertEqual(b['volume_comparisons'][1]['product'],'34')

    def test_rounded_quotes_preserved_product_separate(self):
        rows = trades()
        rows[1][2] = '1.00001'
        raw,d = fixture(rows)
        refs = reference();refs[BLOCK]['qv']='55.0001';refs[BLOCK]['tbqv']='34.0001'
        b = Q.compare(raw,d,refs)['blocks'][0]
        for c in b['volume_comparisons']:
            self.assertTrue(c['product_matches']);self.assertFalse(c['published_matches'])
            self.assertEqual(Decimal(c['product_minus_published']),Decimal('.0001'))
        self.assertEqual(b['hours'][0]['different_quote_records'],1)
        self.assertEqual(b['hours'][0]['published_qv'],'22')
        self.assertEqual(Decimal(b['hours'][0]['product_qv']),Decimal('22.0001'))

    def test_matching_volume_never_removes_price_or_id_conflicts(self):
        raw,d = fixture()
        d['blocks'][0]['conflicts']=[dict(field='c',pinned='14',reconstructed='13')]
        d['blocks'][0]['id_gaps']=[[5,6]]
        d['blocks'][0]['continuity_checked']=False
        b = Q.compare(raw,d,reference())['blocks'][0]
        self.assertFalse(b['product_aggregate_matches'])
        self.assertFalse(b['continuity_checked'])
        self.assertEqual(b['id_gaps'],[[5,6]])
        self.assertEqual(b['price_conflicts'],d['blocks'][0]['conflicts'])

    def test_changed_object_counts_or_original_sums_fail(self):
        raw,d = fixture()
        with self.assertRaises(ValueError):Q.compare(raw+b'x',d,reference())
        for change in ('daily','hourly','quote','grid'):
            bad=copy.deepcopy(d)
            if change=='daily':bad['source_records']+=1
            elif change=='hourly':bad['blocks'][0]['hours'][0]['trades']+=1
            elif change=='quote':bad['blocks'][0]['hours'][0]['fields']['qv']='23'
            else:bad['blocks'][0]['hours'][0]['t']+=3600
            with self.subTest(change=change),self.assertRaises(ValueError):Q.compare(raw,bad,reference())

    def test_bad_rows_outside_selected_block_still_rejected(self):
        raw,d = fixture()
        for col,value in [(1,'NaN'),(2,'0'),(5,'yes'),(4,'0')]:
            rows=trades();rows[0][col]=value;bad,_=tape(rows)
            prior=copy.deepcopy(d);prior['source_sha256']=T.sha(bad)
            with self.subTest(col=col),self.assertRaises(ValueError):Q.compare(bad,prior,reference())

    def test_empty_hour_and_microseconds(self):
        rows=trades();rows.pop(4)
        for row in rows:row[4]=str(int(row[4])*1000)
        raw,d=fixture(rows)
        b=Q.compare(raw,d,reference())['blocks'][0]
        self.assertFalse(b['hours'][2]['observed'])
        self.assertEqual(b['hours'][2]['trades'],0)
        self.assertFalse(b['product_aggregate_matches'])

    def test_corrupt_prior_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'prior.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'committed record'):
                Q.run(p,p/'prior.json',p/'output')
            self.assertFalse((p/'output').exists())

    def test_batch_completes_all_objects_binds_sources_and_preserves_failure(self):
        raw,d=fixture()
        checksum=(T.sha(raw)+'  '+NAME+'\n').encode()
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);diagnostics=[]
            for i in range(94):
                item=copy.deepcopy(d);item['coin']=f'TEST{i}'
                folder=p/(item['coin']+'-'+DAY);folder.mkdir()
                (folder/NAME).write_bytes(raw);(folder/(NAME+'.CHECKSUM')).write_bytes(checksum)
                with gzip.open(folder/'reference.csv.gz','wt',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=['t',*T.FIELDS]);w.writeheader()
                    w.writerow(dict(t=BLOCK,**reference()[BLOCK]))
                item['reference_sha256']=T.sha((folder/'reference.csv.gz').read_bytes())
                diagnostics.append(item)
            prior=dict(schema='v9.a5-trade-diagnostics-record/1',accepted_dataset=False,diagnostics=diagnostics)
            prior_raw=json.dumps(prior).encode();(p/'prior.json').write_bytes(prior_raw)
            with patch.object(Q,'PRIOR_SHA256',T.sha(prior_raw)),patch('builtins.print'):
                result=Q.run(p,p/'prior.json',p/'complete')
                self.assertEqual(len(result['results']),94)
                self.assertFalse(result['accepted_dataset'])
                self.assertEqual(result['prior_record_sha256'],T.sha(prior_raw))
                with self.assertRaises(FileExistsError):Q.run(p,p/'prior.json',p/'complete')
                (p/('TEST1-'+DAY)/NAME).write_bytes(b'corrupt')
                with self.assertRaises(ValueError):Q.run(p,p/'prior.json',p/'failed')
            failure=json.loads((p/'failed/failure.json').read_text())
            self.assertEqual(failure['completed_objects'],1)
            self.assertFalse((p/'failed/diagnostic.json').exists())
            self.assertTrue((p/'failed'/('TEST0-'+DAY+'.json')).exists())


if __name__ == '__main__':
    unittest.main()
