import copy
import hashlib
import json
import unittest
from pathlib import Path
import tempfile
from tools.v9 import control_resource_gate as G


def report(source='a'*40,input_hash='b'*64,protocol='c'*64):
    return dict(schema='v9.a6-resource-qualification/1',source_commit=source,input_manifest_sha256=input_hash,
        execution_protocol_sha256=protocol,runner_profile='synthetic-test-only',workload=dict(signals=4263580,definitions=199,assets=781),
        history_lengths_cover_bound_archive=True,measurement_mode='BOUNDED_COMBINED_PROCESS_AND_ALLOCATED_DISK',
        hosted_runner_verified=True,full_pipeline_verified=True,publication_limits_verified=True,failure_retention_verified=True,
        upper_bounds=dict(combined_memory_bytes=100,allocated_disk_bytes=200,wall_seconds=60),promotion_authority=False)


def capacity():return dict(runner_profile='synthetic-test-only',available_memory_bytes=200,free_disk_bytes=400,remaining_seconds=100)


class ResourceGate(unittest.TestCase):
    def verify(self,doc=None,cap=None,expected=None):
        raw=json.dumps(report() if doc is None else doc).encode()
        return G.verify(raw,expected or hashlib.sha256(raw).hexdigest(),'a'*40,'b'*64,'c'*64,capacity() if cap is None else cap)

    def test_exact_headroom_boundaries_and_no_authority(self):
        result=self.verify();self.assertEqual(result['status'],'RESOURCE_PREFLIGHT_PASSED')
        self.assertFalse(result['promotion_authority'])

    def test_live_capacity_below_budget_or_unknown_refuses(self):
        for key in ('available_memory_bytes','free_disk_bytes','remaining_seconds'):
            for value in (capacity()[key]-1,0,None,True):
                cap=capacity();cap[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.verify(cap=cap)

    def test_unbound_stale_wrong_profile_or_sampled_report_refuses(self):
        for key,value in [('source_commit','d'*40),('input_manifest_sha256','d'*64),('execution_protocol_sha256','d'*64),
                          ('runner_profile','different'),('measurement_mode','SAMPLED_LOWER_BOUND'),('schema','unknown')]:
            doc=report();doc[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.verify(doc)
        with self.assertRaises(ValueError):self.verify(expected='0'*64)

    def test_incomplete_workload_or_evidence_refuses(self):
        for key in ('signals','definitions','assets'):
            doc=report();doc['workload'][key]-=1
            with self.assertRaises(ValueError):self.verify(doc)
        for key in ('history_lengths_cover_bound_archive','hosted_runner_verified','full_pipeline_verified',
                    'publication_limits_verified','failure_retention_verified'):
            doc=report();doc[key]=False
            with self.assertRaises(ValueError):self.verify(doc)
        for value in (True,float('inf'),-1):
            doc=report();doc['upper_bounds']['combined_memory_bytes']=value
            with self.assertRaises(ValueError):self.verify(doc)

    def test_ambiguous_json_and_all_local_probe_reports_refuse(self):
        from pathlib import Path
        raw=b'{"schema":1,"schema":2}'
        with self.assertRaisesRegex(ValueError,'duplicate'):
            G.verify(raw,hashlib.sha256(raw).hexdigest(),'a'*40,'b'*64,'c'*64,capacity())
        root=Path(__file__).resolve().parents[1]/'research/v9'
        for name in ('a6_isolated_resource_probe.json','a6_allocated_publication_probe.json','a6_synthetic_pipeline_probe.json'):
            raw=(root/name).read_bytes()
            with self.subTest(name=name),self.assertRaises(ValueError):
                G.verify(raw,hashlib.sha256(raw).hexdigest(),'a'*40,'b'*64,'c'*64,capacity())


class MemoryCapacity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.proc=self.root/'proc';self.mount=self.root/'cgroup'
        (self.proc/'self').mkdir(parents=True);(self.mount/'parent/job').mkdir(parents=True)
        (self.proc/'meminfo').write_text('MemAvailable: 1000 kB\n')
        (self.proc/'self/cgroup').write_text('0::/parent/job\n')
        (self.proc/'self/mountinfo').write_text('1 0 0:1 / '+str(self.mount)+' rw - cgroup2 cgroup rw\n')
        for name in ('parent','parent/job'):
            (self.mount/name/'memory.max').write_text('max\n')
            (self.mount/name/'memory.current').write_text('100\n')

    def read(self):return G.memory_capacity(self.proc,self.mount)

    def test_ancestor_and_sibling_usage_limit_the_child(self):
        (self.mount/'parent/memory.max').write_text('1000')
        (self.mount/'parent/memory.current').write_text('850')
        (self.mount/'parent/job/memory.max').write_text('800')
        result=self.read()
        self.assertEqual(result['available_memory_bytes'],150)
        self.assertEqual(result['host_available_memory_bytes'],1024000)
        self.assertEqual([r['headroom_bytes'] for r in result['cgroup_memory_limits']],[700,150])
        cap=capacity();cap.update(result)
        with self.assertRaisesRegex(ValueError,'memory budget'):
            ResourceGate().verify(cap=cap)

    def test_host_and_unlimited_groups_and_root(self):
        self.assertEqual(self.read()['available_memory_bytes'],1024000)
        (self.proc/'self/cgroup').write_text('0::/\n')
        result=self.read();self.assertEqual(result['available_memory_bytes'],1024000)
        self.assertEqual(result['cgroup_memory_limits'],[])

    def test_exhausted_and_over_limit_never_become_negative(self):
        for value in ('0','100','99'):
            (self.mount/'parent/job/memory.max').write_text(value)
            self.assertEqual(self.read()['available_memory_bytes'],0)

    def test_missing_and_malformed_counters_fail_closed(self):
        target=self.mount/'parent/memory.max'
        for value in ('-1','1.0','NaN','MAX',''):
            target.write_text(value)
            with self.assertRaises(ValueError):self.read()
        target.unlink()
        with self.assertRaises(OSError):self.read()

    def test_ambiguous_membership_hidden_root_and_bad_host_data_refuse(self):
        target=self.proc/'self/cgroup'
        for value in ('0::/parent/job\n0::/parent\n','1:memory:/parent\n0::/parent/job\n','0::/../escape\n'):
            target.write_text(value)
            with self.assertRaises(ValueError):self.read()
        target.write_text('0::/parent/job\n')
        info=self.proc/'self/mountinfo';original=info.read_text()
        info.write_text(original.replace('0:1 / ','0:1 /hidden '))
        with self.assertRaises(ValueError):self.read()
        info.write_text(original)
        for value in ('MemAvailable: 1 MB\n','MemAvailable: -1 kB\n','MemAvailable: 1 kB\nMemAvailable: 2 kB\n'):
            (self.proc/'meminfo').write_text(value)
            with self.assertRaises(ValueError):self.read()
