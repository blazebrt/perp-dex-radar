"""Replay the retained source assessment without network or outcome research."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from tools.v9.premium_inputs import parse_day, BAR, DAY

ROOT = Path(__file__).resolve().parents[1]

class PremiumSourceAssessment(unittest.TestCase):
    def test_retained_fixed_samples(self):
        folder = ROOT / 'research/v9/premium_source_assessment'
        plan = json.loads((folder/'plan.json').read_text(encoding='utf-8'))
        expected = [['BTCUSDT','2020-01-01'],['BTCUSDT','2026-09-01'],['BLZUSDT','2022-01-01']]
        self.assertEqual(plan['samples'], expected)
        records = json.loads((folder/'responses.json').read_text(encoding='utf-8'))
        self.assertEqual(len(records), 7)
        bodies = []
        for record in records:
            self.assertEqual(record['status'], 200)
            self.assertLessEqual(record['requested_at'], record['completed_at'])
            raw = base64.b64decode(record['body_base64'], validate=True)
            self.assertEqual(len(raw), record['bytes'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
            bodies.append(raw)
        self.assertEqual(records[0]['url'], 'https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data%2Ffutures%2Fum%2Fdaily%2FpremiumIndexKlines%2F&delimiter=%2F')
        directory = ET.fromstring(bodies[0])
        ns = {'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
        self.assertEqual(directory.findtext('s:IsTruncated', namespaces=ns), 'true')
        self.assertEqual(len(directory.findall('s:CommonPrefixes', ns)), 1000)
        for i, (symbol, day) in enumerate(expected):
            index = 1 + i*2
            filename = f'{symbol}-4h-{day}.zip'
            url = f'https://data.binance.vision/data/futures/um/daily/premiumIndexKlines/{symbol}/4h/{filename}'
            self.assertEqual(records[index]['url'], url)
            self.assertEqual(records[index+1]['url'], url+'.CHECKSUM')
            self.assertEqual(bodies[index+1].decode('ascii').split(), [records[index]['sha256'], filename])
            start = int(datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
            rows = parse_day(bodies[index], start, filename[:-4]+'.csv')
            self.assertEqual(sorted(rows), list(range(start,start+DAY,BAR)))
            self.assertTrue(all(row['closed_at'] <= records[index]['completed_at'] for row in rows.values()))
