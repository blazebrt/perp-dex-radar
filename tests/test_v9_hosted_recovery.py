from pathlib import Path
import shutil
import tempfile
import unittest
from tools.v9 import control_hosted_recovery as H


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.identity=H.environment('a'*40,'123','1')
        self.digest=H.produce(self.root/'producer',self.identity)
        self.transfer=self.root/'downloaded';shutil.copytree(self.root/'producer/transfer',self.transfer)
        shutil.rmtree(self.root/'producer')

    def test_exact_handoff_without_original_worker_and_without_recomputation(self):
        result=H.recover(self.transfer,self.root/'recovered',self.digest,self.identity,require_distinct_boot=False)
        self.assertEqual(result['status'],'SYNTHETIC_TRANSFER_RECOVERY_VERIFIED')
        self.assertEqual(sorted(result['states'].values()),['CLAIMED','FAILED','PENDING','PENDING','RECORDED'])
        self.assertEqual(result['refused_recomputations'],3)
        self.assertFalse(result['independent_boot_verified'])
        for k in ('resource_qualified','long_term_retention_qualified','execution_authorized'):self.assertFalse(result[k])

    def test_wrong_digest_identity_and_same_boot_are_rejected(self):
        for digest,identity,distinct in [('0'*64,self.identity,False),(self.digest,dict(self.identity,run_id='999'),False),
                                         (self.digest,self.identity,True)]:
            with self.assertRaises(ValueError):H.recover(self.transfer,self.root/'bad',digest,identity,require_distinct_boot=distinct)
        self.assertFalse((self.root/'bad').exists())

    def test_missing_corrupt_and_extra_transfer_files_are_rejected(self):
        path=next((self.transfer/'objects').iterdir());raw=path.read_bytes();path.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'inventory'):H.recover(self.transfer,self.root/'bad',self.digest,self.identity,require_distinct_boot=False)
        path.write_bytes(raw);path.unlink()
        with self.assertRaisesRegex(ValueError,'inventory'):H.recover(self.transfer,self.root/'bad',self.digest,self.identity,require_distinct_boot=False)
        path.write_bytes(raw);(self.transfer/'unexpected').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'inventory'):H.recover(self.transfer,self.root/'bad',self.digest,self.identity,require_distinct_boot=False)


class Workflow(unittest.TestCase):
    def test_read_only_pinned_two_job_probe_without_secrets_or_market_activation(self):
        text=(H.ROOT/'.github/workflows/a6_hosted_recovery.yml').read_text(encoding='utf-8')
        self.assertIn('contents: read',text);self.assertNotIn('contents: write',text)
        self.assertNotIn('secrets.',text);self.assertNotIn('workflow_dispatch:',text)
        self.assertIn('needs: produce',text);self.assertIn('artifact-ids: ${{ needs.produce.outputs.artifact_id }}',text)
        self.assertEqual(text.count('retention-days: 1'),2);self.assertEqual(text.count('overwrite: false'),2)
        self.assertEqual(text.count('persist-credentials: false'),2)
        import re
        uses=re.findall(r'uses: (\S+)',text)
        self.assertTrue(uses and all(re.fullmatch(r'actions/[a-z-]+@[0-9a-f]{40}',u) for u in uses))
