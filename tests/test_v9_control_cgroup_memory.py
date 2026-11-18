import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from tools.v9.control_cgroup_memory import snapshot


class CgroupMemory(unittest.TestCase):
    def fixture(self,root):
        proc=root/'proc';mount=root/'cgroup';group=mount/'job'
        (proc/'self').mkdir(parents=True);group.mkdir(parents=True)
        (proc/'self/cgroup').write_text('0::/job\n')
        (proc/'self/mountinfo').write_text(f'1 2 0:3 / {mount} rw - cgroup2 cgroup rw\n')
        for name,value in {'memory.current':'1024','memory.peak':'8192','memory.max':'max',
                           'memory.swap.current':'0','memory.swap.max':'4096',
                           'memory.events':'low 0\nhigh 2\nmax 3\noom 1\noom_kill 1\n'}.items():
            (group/name).write_text(value)
        return proc,mount,group

    def test_valid_counters_are_shared_and_never_run_qualification(self):
        with tempfile.TemporaryDirectory() as d:
            proc,mount,group=self.fixture(Path(d));result=snapshot(proc,mount)
            self.assertEqual(result['status'],'SHARED_GROUP_COUNTERS_ONLY')
            self.assertEqual(result['counters']['memory.peak'],8192)
            self.assertIsNone(result['counters']['memory.max'])
            self.assertEqual(result['events']['oom_kill'],1)
            self.assertFalse(result['isolated_run_verified'])
            self.assertFalse(result['resource_qualified'])

    def test_missing_peak_and_denied_reads_are_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            proc,mount,group=self.fixture(Path(d));(group/'memory.peak').unlink()
            result=snapshot(proc,mount);self.assertEqual(result['status'],'UNAVAILABLE')
            self.assertNotIn('counters',result)
            with patch.object(Path,'read_text',side_effect=PermissionError('denied')):
                result=snapshot(proc,mount)
            self.assertEqual(result['error_type'],'PermissionError')

    def test_unsafe_ambiguous_and_non_root_mounts_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            proc,mount,group=self.fixture(Path(d))
            for raw in ('0::/../outside\n','0::relative\n','0::/job\n0::/other\n','1:memory:/job\n'):
                (proc/'self/cgroup').write_text(raw)
                self.assertEqual(snapshot(proc,mount)['status'],'UNAVAILABLE')
            (proc/'self/cgroup').write_text('0::/job\n')
            (proc/'self/mountinfo').write_text(f'1 2 0:3 /subtree {mount} rw - cgroup2 cgroup rw\n')
            self.assertEqual(snapshot(proc,mount)['status'],'UNAVAILABLE')

    def test_malformed_counter_and_duplicate_or_missing_events_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            proc,mount,group=self.fixture(Path(d))
            for value in ('-1','NaN','1.5','max',''):
                (group/'memory.peak').write_text(value)
                self.assertEqual(snapshot(proc,mount)['status'],'UNAVAILABLE')
            (group/'memory.peak').write_text('8192')
            for value in ('oom 0\noom 1\n','high 0\n','oom -1\n'):
                (group/'memory.events').write_text(value)
                self.assertEqual(snapshot(proc,mount)['status'],'UNAVAILABLE')
