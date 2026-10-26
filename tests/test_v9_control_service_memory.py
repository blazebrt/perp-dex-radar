import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from tools.v9 import control_service_memory as S


class ServiceMemory(unittest.TestCase):
    def data(self,unit):
        return dict(LoadState='loaded',ActiveState='active',SubState='exited',Result='success',
                    ExecMainCode='1',ExecMainStatus='0',MemoryAccounting='yes',MemoryPeak='1048576',
                    ControlGroup='/system.slice/'+unit)

    def test_properties_reject_missing_duplicate_and_unavailable_peak(self):
        data=self.data('test.service')
        self.assertEqual(S.validate_result(data,'test.service'),1048576)
        for value in ('','infinity',str(2**64-1),'0','-1','1.5'):
            with self.assertRaises(ValueError):S.validate_result(dict(data,MemoryPeak=value),'test.service')
        for raw in ('MemoryPeak=1\n','MemoryPeak=1\nMemoryPeak=2\n'):
            with self.assertRaises(ValueError):S.properties(raw)
        with self.assertRaises(ValueError):S.validate_result(dict(data,ControlGroup='/wrong'),'test.service')

    def simulate(self,root,mode):
        seen=[]
        def invoke(args,stdout,**kwargs):
            seen.append(args);rc=0;raw='systemd test\n'
            if args[0]=='systemd-run' and '--version' not in args:
                self.assertIn('--expand-environment=no',args)
                self.assertIn('--service-type=oneshot',args)
                self.assertIn('--remain-after-exit',args)
                self.assertNotIn('--wait',args)
                self.assertNotIn('--scope',args)
                if mode=='timeout':raise S.subprocess.TimeoutExpired(args,1)
            elif args[0]=='systemctl' and 'show' in args:
                if args[-1]=='--property=LoadState' and '--property=ActiveState' not in args:
                    raw='LoadState=not-found\n';rc=1
                elif '--property=ActiveState' in args:
                    raw='ActiveState='+('active' if mode=='cleanup' else 'inactive')+'\nLoadState=loaded\n'
                else:
                    data=self.data(args[2])
                    if mode=='failure':data.update(Result='exit-code',ExecMainStatus='7',ActiveState='failed',SubState='failed')
                    raw='\n'.join(k+'='+v for k,v in data.items())+'\n'
            stdout.write(raw.encode());stdout.flush()
            return SimpleNamespace(returncode=rc)
        with patch.object(S.sys,'platform','linux'),patch.object(S.subprocess,'run',side_effect=invoke):
            result=S.run(['/usr/bin/python3','synthetic.py','$LITERAL'],root,root/'out',1)
        self.assertEqual(json.loads((root/'out/accounting.json').read_text()),result)
        self.assertFalse(result['resource_qualified'])
        self.assertTrue(any(args[:2]==['systemctl','stop'] for args in seen))
        return result

    def test_success_preserves_properties_and_stops_only_generated_unit(self):
        with tempfile.TemporaryDirectory() as d:
            result=self.simulate(Path(d),'success')
            self.assertEqual(result['memory_peak_bytes'],1048576)
            self.assertTrue(result['cleanup_verified'])
            self.assertFalse(result['hosted_startup_placement_verified'])

    def test_failure_and_timeout_preserve_reports_and_stop_unit(self):
        for mode in ('failure','timeout'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                result=self.simulate(Path(d),mode)
                self.assertEqual(result['status'],'FAILED')
                self.assertTrue(result['cleanup_verified'])

    def test_cleanup_failure_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as d:
            result=self.simulate(Path(d),'cleanup')
            self.assertEqual(result['status'],'CLEANUP_UNVERIFIED')
            self.assertFalse(result['cleanup_verified'])

    def test_invalid_arguments_fail_before_unit_or_output_creation(self):
        with tempfile.TemporaryDirectory() as d,patch.object(S.sys,'platform','linux'),patch.object(S.subprocess,'run') as invoke:
            root=Path(d)
            for command,timeout in [(['python'],1),([],1),(['/usr/bin/python3'],True)]:
                with self.assertRaises(ValueError):S.run(command,root,root/'out',timeout)
            invoke.assert_not_called();self.assertFalse((root/'out').exists())
