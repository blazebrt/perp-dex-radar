import sys
import tempfile
from pathlib import Path
import unittest
from tools.v9 import control_resource_measure as M


class Measurements(unittest.TestCase):
    def test_visible_file_bytes_includes_nested_scratch_and_tracks_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scratch').mkdir()
            (root/'retained').write_bytes(b'abc');(root/'scratch/index').write_bytes(b'12345')
            self.assertEqual(M.visible_bytes(root),8)
            (root/'scratch/index').unlink();self.assertEqual(M.visible_bytes(root),3)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux RSS unit contract')
    def test_isolated_pipeline_reports_memory_disk_and_partial_audit(self):
        result=M.measure('interrupted',3,400)
        self.assertGreater(result['peak_rss_bytes'],0)
        self.assertGreaterEqual(result['sampled_visible_peak_bytes'],result['pipeline']['outcome_bytes'])
        self.assertGreater(result['disk_samples'],1)
        self.assertEqual(result['worker_exit'],0)
        self.assertEqual(result['pipeline']['audit_status'],'FAILED')
        self.assertTrue(result['pipeline']['failure_retained'])

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux RSS unit contract')
    def test_invalid_inputs_rejected_before_worker(self):
        for kind,n,bars in [('unknown',3,400),('full',True,400),('full',101,400),('full',3,4001)]:
            with self.assertRaises(ValueError):M.measure(kind,n,bars)
