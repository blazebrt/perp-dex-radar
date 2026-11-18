import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.v9 import hourly_quality_build as B
from tools.v9 import hourly_quality_publish as P
from tests import test_v9_hourly_quality_build as fixtures


class PublicationTests(unittest.TestCase):
    def setup_candidate(self, root):
        source, plan, manifest, decisions = fixtures.QualityBuildTests().prepare(root)
        original = root / 'original'
        candidate = B.build_archive(source, original, plan, manifest, decisions)
        B.write_json(original / 'quality_candidate_manifest.json', candidate)
        digest = B.sha(original / 'quality_candidate_manifest.json')
        record = dict(status='LOCAL_CANDIDATE_INDEPENDENTLY_VERIFIED', candidate_manifest=candidate,
            candidate_manifest_sha256=digest, independent_verification=dict(candidate_manifest_sha256=digest,
                all_artifacts_verified=True, all_modified_rows_and_masks_verified=True,
                all_embargo_days_verified=True, original_schedule_and_funding_preserved=True))
        path = root / 'record.json'
        B.write_json(path, record)
        return source, path, record, candidate

    def run_synthetic(self, source, out, record):
        with patch.object(P, 'RECORD_SHA256', B.sha(record)), \
                patch.object(B, 'MANIFEST', B.sha(source / 'rejected_manifest.json')), \
                patch.object(P.Q, 'bound_json', side_effect=fixtures.fixture()[:3]):
            return P.reproduce(source, out, record)

    def test_exact_replica(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, path, record, candidate = self.setup_candidate(root)
            out = root / 'replica'
            self.assertEqual(self.run_synthetic(source, out, path), candidate)
            self.assertEqual(B.sha(out / 'quality_candidate_manifest.json'), record['candidate_manifest_sha256'])

    def test_changed_record_and_missing_verification_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, path, record, _ = self.setup_candidate(root)
            with self.assertRaisesRegex(ValueError, 'record changed'):
                P.reproduce(source, root / 'bad', path)
            record['independent_verification']['all_artifacts_verified'] = False
            B.write_json(path, record)
            with self.assertRaisesRegex(ValueError, 'lacks independent'):
                self.run_synthetic(source, root / 'bad', path)
            self.assertFalse((root / 'bad').exists())

    def test_any_different_output_prevents_publication_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, path, record, _ = self.setup_candidate(root)
            record['candidate_manifest']['artifacts_sha256']['h1/X.csv.gz'] = 'wrong'
            B.write_json(path, record)
            out = root / 'different'
            with self.assertRaisesRegex(ValueError, 'differs'):
                self.run_synthetic(source, out, path)
            self.assertTrue((out / 'failure.json').exists())
            self.assertFalse((out / 'quality_candidate_manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
