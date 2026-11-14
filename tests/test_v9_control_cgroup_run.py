import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch,Mock
from tools.v9 import control_cgroup_run as C


class IsolatedAccounting(unittest.TestCase):
    def test_bootstrap_verifies_placement_before_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(Path,'read_text',return_value='0::/expected\n'),patch.object(C.os,'execvpe') as execute:
                C.enter(root,'/expected',root/'receipt.json',['python','test.py'])
                execute.assert_called_once()
            self.assertEqual(json.loads((root/'receipt.json').read_text())['group'],'/expected')
            with patch.object(Path,'read_text',return_value='0::/wrong\n'),patch.object(C.os,'execvpe') as execute:
                with self.assertRaises(ValueError):C.enter(root,'/expected',root/'other.json',['python'])
                execute.assert_not_called()
            self.assertFalse((root/'other.json').exists())

    def test_parent_and_command_fail_before_any_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'out'
            for parent,cmd,timeout in [('/tmp',['python'],1),('/sys/fs/cgroup',['python'],1),('/tmp',[],1),('/tmp',['python'],True)]:
                with self.assertRaises(ValueError):C.run(parent,cmd,out,timeout)
                self.assertFalse(out.exists())

    def simulate(self,root,mode):
        parent=root/'delegated';parent.mkdir();out=root/'output'
        mkdir=Path.mkdir;rmdir=Path.rmdir
        def create(path,*args,**kwargs):
            mkdir(path,*args,**kwargs)
            if path.parent==parent:
                values={'cgroup.procs':'','cgroup.events':'populated 0\n',
                        'memory.peak':'1' if mode=='dirty' else '0',
                        'memory.events':'high 0\nmax 0\noom 0\noom_kill 0\n','cgroup.kill':''}
                for name,value in values.items():(path/name).write_text(value)
                if mode=='missing':(path/'memory.peak').unlink()
        def remove(path):
            self.assertEqual(path.parent,parent)
            for p in path.iterdir():p.unlink()
            rmdir(path)
        def spawn(argv,**kwargs):
            group=Path(argv[3]);receipt=Path(argv[5]);proc=Mock(pid=123,returncode=0)
            receipt.write_text(json.dumps(dict(pid=123,group='/synthetic')))
            (group/'memory.peak').write_text('8388608')
            if mode=='oom':(group/'memory.events').write_text('high 0\nmax 1\noom 1\noom_kill 1\n')
            proc.poll.return_value=0
            proc.wait.side_effect=[subprocess.TimeoutExpired('synthetic',1),0] if mode=='timeout' else [0,0]
            return proc
        with patch.object(C,'validate_parent',return_value=parent),patch.object(C,'membership_path',return_value='/synthetic'),\
             patch.object(Path,'mkdir',create),patch.object(Path,'rmdir',remove),patch.object(C.subprocess,'Popen',side_effect=spawn) as launch:
            result=C.run(parent,['synthetic-command'],out,1)
        self.assertEqual(json.loads((out/'accounting.json').read_text()),result)
        self.assertEqual(list(parent.iterdir()),[])
        self.assertFalse(result['resource_qualified'])
        return result,launch.call_count

    def test_fresh_group_retains_peak_and_removes_only_own_group(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.simulate(Path(directory),'normal')
            self.assertEqual(calls,1)
            self.assertEqual(result['status'],'MEASURED_DIAGNOSTIC')
            self.assertEqual(result['memory_peak_bytes'],8388608)
            self.assertTrue(result['placement_verified'])
            self.assertTrue(result['group_removed'])

    def test_dirty_group_refuses_workload(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.simulate(Path(directory),'dirty')
            self.assertEqual(calls,0)
            self.assertEqual(result['status'],'FAILED')

    def test_missing_peak_refuses_workload_and_still_removes_empty_group(self):
        with tempfile.TemporaryDirectory() as directory:
            result,calls=self.simulate(Path(directory),'missing')
            self.assertEqual(calls,0)
            self.assertTrue(result['group_removed'])
            self.assertEqual(result['status'],'CLEANUP_OR_MEASUREMENT_FAILED')

    def test_timeout_and_oom_are_retained_as_failures(self):
        for mode in ('timeout','oom'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                result,calls=self.simulate(Path(directory),mode)
                self.assertEqual(calls,1)
                self.assertEqual(result['memory_peak_bytes'],8388608)
                self.assertNotEqual(result['status'],'MEASURED_DIAGNOSTIC')
                if mode=='timeout':self.assertTrue(result['timed_out'])
                else:self.assertEqual(result['status'],'OOM_OR_MEMORY_FAILURE')
