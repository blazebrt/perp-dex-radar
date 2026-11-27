import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from tools.v9.premium_inventory import audit

ROOT=Path(__file__).resolve().parents[1]

class PremiumInventory(unittest.TestCase):
    def setUp(self):
        self.records=json.loads((ROOT/'research/v9/premium_population_assessment/responses.json').read_text(encoding='utf-8'))

    def test_retained_population_and_explicit_unsupported_inputs(self):
        report=audit(self.records)
        expected=json.loads((ROOT/'research/v9/premium_population_assessment/report.json').read_text(encoding='utf-8'))
        self.assertEqual(report,expected)
        self.assertEqual(report['prefix_count'],1011)
        self.assertEqual(len(report['importer_unsupported_symbols']),5)
        self.assertTrue(set(report['importer_unsupported_symbols']) <= set(report['symbols']))
        for key in ('atomic_snapshot','historical_population_accepted','coverage_verified','study_eligible','trade_authorization'):
            self.assertIs(report[key],False)

    def test_incomplete_reordered_duplicate_corrupted_and_wrong_source(self):
        cases=[self.records[:1],list(reversed(self.records)),self.records+[self.records[-1]]]
        for key,value in [('sha256','0'*64),('bytes',True),('status',404),('requested_at',True),
                          ('completed_at',self.records[1]['requested_at']-1),
                          ('url',self.records[1]['url'].replace('marker=','other=')),
                          ('url',self.records[1]['url']+'&marker=duplicate'),
                          ('url',self.records[1]['url'].replace('https:','http:'))]:
            rows=copy.deepcopy(self.records);rows[1][key]=value;cases.append(rows)
        for rows in cases:
            with self.subTest(rows=len(rows)),self.assertRaises(ValueError):audit(rows)

    def test_bound_but_invalid_xml_contracts(self):
        original=base64.b64decode(self.records[1]['body_base64']).decode()
        changes=[original.replace('<IsTruncated>false</IsTruncated>','<IsTruncated>true</IsTruncated>'),
                 original.replace('<IsTruncated>false</IsTruncated>','<IsTruncated>false</IsTruncated><IsTruncated>false</IsTruncated>'),
                 original.replace('<Name>data.binance.vision</Name>','<Name>other</Name>'),
                 original.replace('<Delimiter>/</Delimiter>','<Delimiter>x</Delimiter>'),
                 '<!DOCTYPE x>'+original]
        for text in changes:
            self.assertNotEqual(text,original)
            raw=text.encode();rows=copy.deepcopy(self.records)
            rows[1].update(body_base64=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
            with self.subTest(text=text[:20]),self.assertRaises(ValueError):audit(rows)
