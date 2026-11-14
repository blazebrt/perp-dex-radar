import sys
import tempfile
from pathlib import Path
import unittest
from tools.v9 import control_publication_probe as P


@unittest.skipUnless(sys.platform.startswith('linux'),'Linux isolated Git simulation')
class Publication(unittest.TestCase):
    def test_success_and_failure_artifacts_survive_git_and_existing_checkout_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for folder in ('outcomes','audit'):(root/folder).mkdir()
            (root/'outcomes/manifest.json').write_text('{"status":"FAILED_OR_PARTIAL"}')
            (root/'outcomes/partial.gz').write_bytes(b'partial')
            (root/'audit/failure.json').write_text('{"status":"FAILED"}')
            result=P.retain(root)
            self.assertEqual(result['files'],3)
            self.assertGreater(result['git_metadata_bytes'],0)
            self.assertFalse(result['network_used']);self.assertFalse(result['remote_publication_verified'])
            with self.assertRaises(FileExistsError):P.retain(root)
