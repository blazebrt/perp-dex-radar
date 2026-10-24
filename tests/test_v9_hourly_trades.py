import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.v9 import hourly_trades as T

DAY = '2022-01-01'
START = 1640995200
BLOCK = START + 14400
NAME = 'TESTUSDT-trades-2022-01-01.zip'


def tape(rows):
    s = io.StringIO()
    csv.writer(s).writerows([T.HEADER] + rows)
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('trades.csv', s.getvalue())
    raw = b.getvalue()
    return raw, (hashlib.sha256(raw).hexdigest()+'  '+NAME+'\n').encode()


def trades():
    return [[str(i+1), price, '1', price, str(t*1000), maker]
            for i, (t, price, maker) in enumerate([
                (BLOCK-1, '8', 'true'), (BLOCK, '10', 'false'),
                (BLOCK+3599, '12', 'true'), (BLOCK+3600, '11', 'false'),
                (BLOCK+7200, '9', 'true'), (BLOCK+10800, '13', 'false'),
                (BLOCK+14400, '20', 'false')])]


def reference():
    return {BLOCK: dict(zip(T.FIELDS, ['10','13','9','13','55','34']))}


class TradeReconstruction(unittest.TestCase):
    def run_audit(self, rows=None, refs=None):
        raw, checksum = tape(trades() if rows is None else rows)
        return T.audit(raw, checksum, NAME, DAY, reference() if refs is None else refs)

    def test_all_fields_boundaries_and_buyer_direction(self):
        result = self.run_audit()
        block = result['blocks'][0]
        self.assertTrue(block['continuity_checked'])
        self.assertTrue(block['aggregate_matches'])
        self.assertEqual(block['hours'][0]['fields'], dict(o='10', h='12', l='10', c='12', qv='22', tbqv='10'))
        self.assertEqual([h['trades'] for h in block['hours']], [2,1,1,1])
        self.assertFalse(result['accepted_dataset'])
        self.assertFalse(result['promotion_authority'])

    def test_id_gap_and_unbracketed_block_never_claim_continuity(self):
        rows = trades()
        for row in rows[3:]:
            row[0] = str(int(row[0])+1)
        b = self.run_audit(rows)['blocks'][0]
        self.assertEqual(b['id_gaps'], [[4,5]])
        self.assertTrue(b['aggregate_matches'])
        self.assertFalse(b['continuity_checked'])
        for subset in (trades()[1:], trades()[:-1]):
            b = self.run_audit(subset)['blocks'][0]
            self.assertFalse(b['bracketed'])
            self.assertFalse(b['continuity_checked'])

    def test_empty_hour_is_absent_not_filled(self):
        rows = trades()
        rows.pop(4)
        b = self.run_audit(rows)['blocks'][0]
        self.assertIsNone(b['hours'][2]['fields'])
        self.assertEqual(b['hours'][2]['trades'], 0)
        self.assertFalse(b['aggregate_matches'])

    def test_malformed_and_disordered_source_fails(self):
        for col, value in [(0,'-1'), (1,'NaN'), (1,'0'), (2,'-2'), (3,'Infinity'), (4,str(START-1)), (5,'0')]:
            with self.subTest(col=col, value=value):
                rows = trades(); rows[2][col] = value
                with self.assertRaises(ValueError): self.run_audit(rows)
        for col, value in [(0,'2'), (4,str((BLOCK-2)*1000))]:
            rows = trades(); rows[2][col] = value
            with self.assertRaises(ValueError): self.run_audit(rows)

    def test_microsecond_ties_keep_id_order(self):
        rows = trades()
        for row in rows: row[4] = str(int(row[4])*1000)
        rows[2][4] = rows[1][4]
        b = self.run_audit(rows)['blocks'][0]
        self.assertEqual(b['hours'][0]['fields']['o'], '10')
        self.assertEqual(b['hours'][0]['fields']['c'], '12')
        self.assertTrue(b['aggregate_matches'])

    def test_checksum_reference_and_empty_source_fail(self):
        raw, checksum = tape(trades())
        with self.assertRaises(ValueError): T.audit(raw+b'x',checksum,NAME,DAY,reference())
        with self.assertRaises(ValueError): T.audit(raw,checksum,'wrong.zip',DAY,reference())
        with self.assertRaises(ValueError): self.run_audit([])
        with self.assertRaises(ValueError): self.run_audit(refs={BLOCK+1:reference()[BLOCK]})
        refs = reference(); refs[BLOCK]['qv'] = 'NaN'
        with self.assertRaises(ValueError): self.run_audit(refs=refs)

    def test_tiny_price_mismatch_not_hidden_by_absolute_tolerance(self):
        rows = trades()
        for r in rows: r[1] = r[3] = '0.000000001'
        refs = {BLOCK: dict(o='0.000000002', h='0.000000001', l='0.000000001', c='0.000000001', qv='0.000000005', tbqv='0.000000003')}
        b = self.run_audit(rows, refs)['blocks'][0]
        self.assertEqual([c['field'] for c in b['conflicts']], ['o'])

    def test_cli_preserves_inputs_binds_sources_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); raw, checksum = tape(trades())
            (p/NAME).write_bytes(raw); (p/'sum').write_bytes(checksum)
            with gzip.open(p/'ref.gz','wt',newline='') as f:
                w = csv.DictWriter(f,fieldnames=['t',*T.FIELDS]); w.writeheader()
                w.writerow(dict(t=BLOCK,**reference()[BLOCK]))
            original = (p/'ref.gz').read_bytes()
            args = ['--zip',str(p/NAME),'--checksum',str(p/'sum'),'--day',DAY,'--reference',str(p/'ref.gz'),'--out',str(p/'out.json'),'--blocks',str(BLOCK)]
            T.main(args)
            out = json.loads((p/'out.json').read_text())
            self.assertEqual(out['reference_sha256'],T.sha(original))
            self.assertEqual(out['source_sha256'],T.sha(raw))
            self.assertEqual(out['protocol_sha256'],T.sha(T.PROTOCOL.read_bytes()))
            with self.assertRaises(FileExistsError): T.main(args)
            self.assertEqual((p/'ref.gz').read_bytes(),original)
            self.assertFalse((p/'hourly_manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
