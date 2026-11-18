import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.v9 import hourly_quality as Q
from tools.v9 import hourly_quality_build as B
from tests.test_v9_hourly_quality import evidence, rows


def fixture():
    old, new = evidence()
    d = dict(coin='X', day='1970-01-01', source_filename='XUSDT-trades-1970-01-01.zip',
             source_sha256='source', source_records=8, checksum_sha256='checksum', reference_sha256='reference', blocks=[old])
    p = {k: v for k, v in d.items() if k not in ('checksum_sha256', 'reference_sha256')}
    p['blocks'] = [new]
    plan = dict(fetch_coins=[dict(t='X', symbol='XUSDT', first_bar=0, last_bar=2 * Q.BLOCK)],
                source_files_sha256={'h4/X.csv.gz': 'reference'},
                days=[dict(known_at=Q.DAY, selected=['X']), dict(known_at=9 * Q.DAY, selected=[])])
    manifest = dict(coverage={'X': dict(four_hour_conflicts=[dict(timestamp=0)])})
    return dict(diagnostics=[d]), dict(diagnostic=dict(results=[p])), dict(diagnostic=dict(results=[])), plan, manifest


class QualityBuildTests(unittest.TestCase):
    def test_join_exact_sources_and_conflict_inventory(self):
        args = fixture()
        result = B.join_evidence(*args)
        self.assertEqual(result['X'][0]['action'], 'reconstruct')
        for mutate in ('source', 'reference', 'symbol', 'extra', 'missing', 'duplicate', 'boundary'):
            a = copy.deepcopy(args)
            if mutate == 'source': a[1]['diagnostic']['results'][0]['source_sha256'] = 'changed'
            if mutate == 'reference': a[3]['source_files_sha256']['h4/X.csv.gz'] = 'changed'
            if mutate == 'symbol': a[3]['fetch_coins'][0]['symbol'] = 'YUSDT'
            if mutate == 'extra': a[4]['coverage']['X']['four_hour_conflicts'].append(dict(timestamp=Q.BLOCK))
            if mutate == 'missing': a[1]['diagnostic']['results'] = []
            if mutate == 'duplicate': a[0]['diagnostics'] *= 2
            if mutate == 'boundary': a[2]['diagnostic']['results'] = [dict(coin='Y', t=0)]
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                B.join_evidence(*a)

    def prepare(self, root):
        source = root / 'source'
        source.mkdir()
        (source / 'h1').mkdir(); (source / 'fund_bn').mkdir()
        args = fixture()
        plan, manifest = args[3:]
        B.write_rows(source / 'h1/X.csv.gz', rows())
        (source / 'fund_bn/X.csv.gz').write_bytes(b'original funding bytes')
        B.write_json(source / 'hourly_plan.json', plan)
        B.write_json(source / 'universe.json', dict(coins=plan['fetch_coins']))
        manifest['coverage']['X'].update(missing_hours=0, missing_intervals=[], observed_hours=12,
            zero_volume_hours=0, funding_source_sha256=B.sha(source / 'fund_bn/X.csv.gz'))
        manifest['artifacts_sha256'] = {p.relative_to(source).as_posix(): B.sha(p)
                                      for p in source.rglob('*') if p.is_file()}
        B.write_json(source / 'rejected_manifest.json', manifest)
        return source, plan, manifest, B.join_evidence(*args)

    def test_writer_preserves_funding_schedule_originals_and_hash_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, plan, manifest, decisions = self.prepare(root)
            before = {p: p.read_bytes() for p in source.rglob('*') if p.is_file()}
            out = root / 'derived'
            candidate = B.build_archive(source, out, plan, manifest, decisions)
            self.assertFalse(candidate['accepted_dataset'])
            self.assertTrue(candidate['independent_verification_pending'])
            self.assertFalse((out / 'hourly_manifest.json').exists())
            for name in ('hourly_plan.json', 'universe.json', 'fund_bn/X.csv.gz'):
                self.assertEqual((out / name).read_bytes(), (source / name).read_bytes())
            self.assertEqual(B.read_rows(out / 'h1/X.csv.gz')[4:], rows()[4:])
            self.assertEqual(json.loads((out / 'quality_ledger.json').read_bytes())[0]['before'], rows()[:4])
            Q.verify_artifacts(out, candidate['artifacts_sha256'])
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            with self.assertRaises(FileExistsError):
                B.build_archive(source, out, plan, manifest, decisions)

    def test_quarantine_embargo_and_failure_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, plan, manifest, decisions = self.prepare(root)
            d = decisions['X'][0]
            d.update(action='quarantine', continuity_checked=False, replacement_rows=[])
            out = root / 'quarantine'
            B.build_archive(source, out, plan, manifest, decisions)
            self.assertEqual(B.read_rows(out / 'h1/X.csv.gz'), rows()[4:])
            schedule = json.loads((out / 'quality_schedule.json').read_bytes())
            self.assertEqual([s['new_entries_allowed'] for s in schedule], [False, True])
            failed = root / 'failed'
            with patch.object(B, 'write_rows', side_effect=OSError('injected disk failure')):
                with self.assertRaises(OSError):
                    B.build_archive(source, failed, plan, manifest, decisions)
            self.assertIn('injected disk failure', (failed / 'failure.json').read_text())
            self.assertFalse((failed / 'quality_candidate_manifest.json').exists())
            self.assertFalse((failed / 'hourly_manifest.json').exists())

    def test_corrupt_source_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, plan, manifest, decisions = self.prepare(root)
            (source / 'fund_bn/X.csv.gz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                B.build_archive(source, root / 'derived', plan, manifest, decisions)
            self.assertFalse((root / 'derived').exists())


if __name__ == '__main__':
    unittest.main()
