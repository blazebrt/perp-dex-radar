import sys
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
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
        self.assertGreater(result['sampled_session_rss_peak_bytes'],0)
        self.assertGreaterEqual(result['sampled_session_process_peak'],1)
        self.assertGreaterEqual(result['sampled_visible_peak_bytes'],result['pipeline']['outcome_bytes'])
        self.assertGreater(result['disk_samples'],1)
        self.assertEqual(result['worker_exit'],0)
        self.assertEqual(result['pipeline']['audit_status'],'FAILED')
        self.assertTrue(result['pipeline']['failure_retained'])

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux RSS unit contract')
    def test_invalid_inputs_rejected_before_worker(self):
        for kind,n,bars in [('unknown',3,400),('full',True,400),('full',101,400),('full',3,4001)]:
            with self.assertRaises(ValueError):M.measure(kind,n,bars)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux allocated-block semantics')
    def test_allocated_blocks_deduplicate_links_and_include_deleted_open_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'data'
            with path.open('wb') as stream:
                stream.write(b'x'*8192);stream.flush()
                os.link(path,root/'link')
                self.assertEqual(M.allocated_bytes(root),root.stat().st_blocks*512+path.stat().st_blocks*512)
                blocks=path.stat().st_blocks*512
                path.unlink();(root/'link').unlink()
                self.assertGreaterEqual(M.allocated_bytes(root,os.getpid()),M.allocated_bytes(root)+blocks)

    def test_disappearing_directory_scan_is_tolerated(self):
        from unittest.mock import patch
        def walk(root,onerror):
            onerror(FileNotFoundError('removed'));return iter(())
        with patch.object(M.os,'walk',side_effect=walk):self.assertEqual(M.visible_bytes('.'),0)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux descriptor coverage')
    def test_unavailable_descriptor_access_is_reported(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            coverage={'fd_access_denied_samples':0}
            with patch.object(Path,'iterdir',side_effect=PermissionError('worker exited')):
                self.assertGreaterEqual(M.allocated_bytes(directory,123,coverage),0)
            self.assertEqual(coverage['fd_access_denied_samples'],1)

    def test_session_rss_counts_children_and_excludes_other_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for pid,sid,rss in [(10,10,7),(11,10,13),(12,12,999)]:
                (root/str(pid)).mkdir()
                fields=['S','1',str(pid),str(sid)]+['0']*17+[str(rss)]
                (root/str(pid)/'stat').write_text(str(pid)+' (worker (with) spaces) '+' '.join(fields))
            result=M.session_rss(10,root,4096)
            self.assertEqual(result['rss_bytes'],20*4096)
            self.assertEqual(result['processes'],2)
            self.assertTrue(result['scan_complete'])

    def test_session_rss_preserves_malformed_vanished_and_permission_gaps(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for pid in ('10','11','12'):(root/pid).mkdir()
            (root/'10/stat').write_text('broken')
            (root/'12/stat').write_text('12 (bad) S 1 12 12 '+'0 '*17+'-1')
            result=M.session_rss(10,root,4096)
            self.assertEqual(result['read_errors'],2)
            self.assertEqual(result['vanished_processes'],1)
            self.assertFalse(result['scan_complete'])
            with patch.object(Path,'iterdir',side_effect=PermissionError('denied')):
                result=M.session_rss(10,root,4096)
            self.assertFalse(result['scan_complete'])
            self.assertEqual(result['read_errors'],1)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux process sessions')
    def test_live_session_includes_memory_of_child_process(self):
        import subprocess,time
        with tempfile.TemporaryDirectory() as directory:
            ready=Path(directory)/'ready'
            child="import pathlib,time; data=bytearray(16*1024*1024); pathlib.Path(%r).write_text('ready'); time.sleep(20)"%str(ready)
            parent="import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',%r]); p.wait()"%child
            process=subprocess.Popen([sys.executable,'-c',parent],start_new_session=True)
            try:
                deadline=time.monotonic()+10
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(ready.exists())
                result=M.session_rss(process.pid)
                self.assertEqual(result['processes'],2)
                self.assertGreater(result['rss_bytes'],16*1024*1024)
            finally:
                import signal
                os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
