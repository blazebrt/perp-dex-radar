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
        for kind,n,bars in [('unknown',3,400),('full',True,400),('full',25001,400),('full',3,4001)]:
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


class ProbeScale(unittest.TestCase):
    def test_custom_scale_reaches_every_scenario_and_is_recorded(self):
        with patch.object(M,'measure',return_value={}) as measure, patch('tools.v9.control_cgroup_memory.snapshot',return_value={}):
            result=M.probe(100,4000)
        self.assertEqual(measure.call_args_list,[unittest.mock.call(k,100,4000,assets=61,definitions=3,unavailable=1,shard_rows=4) for k in ('full','mixed','sparse','interrupted')])
        self.assertEqual(result['requested_scales'],[dict(signals_per_available_trial=100,bars_per_asset=4000,assets=61,definitions=3,unavailable_definitions=1)])
        self.assertEqual(result['status'],'NOT_RESOURCE_QUALIFIED')
        self.assertFalse(result['promotion_authority'])

    def test_default_scales_preserve_eight_case_protocol(self):
        with patch.object(M,'measure',return_value={}) as measure, patch('tools.v9.control_cgroup_memory.snapshot',return_value={}):
            result=M.probe()
        self.assertEqual(measure.call_args_list,[unittest.mock.call(k,n,b,assets=61,definitions=3,unavailable=1,shard_rows=4) for n,b in ((8,1000),(32,4000)) for k in ('full','mixed','sparse','interrupted')])
        self.assertEqual(len(result['requested_scales']),2)

    def test_partial_or_invalid_scale_rejected_before_measurement(self):
        with patch.object(M,'measure') as measure, patch('tools.v9.control_cgroup_memory.snapshot') as snapshot:
            for n,b in [(3,None),(None,400),(True,400),(25001,400),(3,4001),(3,False)]:
                with self.subTest(signals=n,bars=b),self.assertRaises(ValueError):M.probe(n,b)
        measure.assert_not_called();snapshot.assert_not_called()


    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux measurement CLI')
    def test_cli_honors_explicit_scale_in_actual_report(self):
        import json,subprocess
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'report.json'
            subprocess.run([sys.executable,str(Path(M.__file__).resolve()),'--signals','3','--bars','400','--assets','62','--definitions','4','--unavailable','2','--shard-rows','25000','--out',str(out)],check=True,capture_output=True)
            report=json.loads(out.read_text())
        self.assertEqual(report['requested_scales'],[dict(signals_per_available_trial=3,bars_per_asset=400,assets=62,definitions=4,unavailable_definitions=2)])
        self.assertEqual(report['outcome_shard_max_rows'],25000)
        self.assertTrue(all(c['pipeline']['outcome_shard_max_rows']==25000 for c in report['cases']))
        self.assertEqual(len(report['cases']),4)
        self.assertEqual([c['pipeline']['assets'] for c in report['cases']],[62,62,8,62])
        self.assertTrue(all(c['pipeline']['definitions']==4 and c['pipeline']['unavailable_definitions']==2 for c in report['cases']))
        self.assertEqual([case['pipeline']['audit_status'] for case in report['cases']],['VERIFIED_REGISTERED_PRICE_DIAGNOSTICS']*3+['FAILED'])


@unittest.skipUnless(sys.platform.startswith('linux'),'Linux private process group cleanup')
class WorkerCleanup(unittest.TestCase):
    def test_cleanup_kills_term_resistant_child_when_leader_exits(self):
        self.check_cleanup(False)

    def test_cleanup_escalates_when_leader_and_child_ignore_term(self):
        self.check_cleanup(True)

    def check_cleanup(self,ignore_parent):
        import subprocess,time,signal
        with tempfile.TemporaryDirectory() as directory:
            ready=Path(directory)/'ready'
            child="import signal,os,pathlib,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path(%r).write_text(str(os.getpid())); time.sleep(30)"%str(ready)
            parent="import subprocess,sys,signal; "+("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore_parent else "")+"p=subprocess.Popen([sys.executable,'-c',%r]); p.wait()"%child
            process=subprocess.Popen([sys.executable,'-c',parent],start_new_session=True)
            try:
                deadline=time.monotonic()+10
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue(ready.exists())
                child_pid=int(ready.read_text())
                started=time.monotonic();M.stop_worker_group(process,.1)
                self.assertLess(time.monotonic()-started,6)
                self.assertIsNotNone(process.returncode)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    try:
                        raw=Path('/proc',str(child_pid),'stat').read_text()
                        if raw[raw.rfind(')')+2:].split()[0]=='Z':break
                    except FileNotFoundError:break
                    time.sleep(.02)
                else:self.fail('child still running after cleanup')
            finally:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)

    def test_observer_failure_calls_group_cleanup_and_preserves_error(self):
        import subprocess
        with patch.object(M.subprocess,'Popen') as launch, patch.object(M,'visible_bytes',side_effect=RuntimeError('observer failed')), patch.object(M,'stop_worker_group') as cleanup:
            process=launch.return_value
            with self.assertRaisesRegex(RuntimeError,'observer failed'):M.measure('full',3,400)
        cleanup.assert_called_once_with(process)

    def test_missing_group_is_already_clean_and_waits_are_bounded(self):
        from unittest.mock import Mock
        process=Mock(pid=123)
        with patch.object(M.os,'killpg',side_effect=ProcessLookupError):M.stop_worker_group(process)
        self.assertEqual(process.wait.call_args_list,[unittest.mock.call(timeout=2),unittest.mock.call(timeout=5)])
