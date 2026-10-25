"""Fail-closed A6 resource preflight over externally pinned qualification evidence."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import sys


def require(ok,message):
    if not ok:raise ValueError(message)


def positive(value):return type(value) is int and value>0


def verify(raw,expected_sha,source_commit,input_hash,protocol_hash,capacity):
    for value,size in ((expected_sha,64),(source_commit,40),(input_hash,64),(protocol_hash,64)):
        require(type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}',value) is not None,'invalid resource binding')
    require(hashlib.sha256(raw).hexdigest()==expected_sha,'resource qualification hash mismatch')
    def unique(items):
        result={}
        for key,value in items:
            require(key not in result,'duplicate qualification key');result[key]=value
        return result
    def invalid(value):raise ValueError('nonfinite qualification JSON')
    report=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    require(report.get('schema')=='v9.a6-resource-qualification/1','unsupported resource qualification')
    require(report.get('source_commit')==source_commit and report.get('input_manifest_sha256')==input_hash
            and report.get('execution_protocol_sha256')==protocol_hash,'resource qualification binding mismatch')
    require(type(capacity.get('runner_profile')) is str and bool(capacity['runner_profile']) and
            report.get('runner_profile')==capacity['runner_profile'],'runner profile mismatch')
    for key in ('available_memory_bytes','free_disk_bytes','remaining_seconds'):
        require(positive(capacity.get(key)),'invalid live capacity: '+key)
    required=dict(signals=4263580,definitions=199,assets=781)
    workload=report.get('workload',{})
    require(all(positive(workload.get(k)) and workload[k]>=v for k,v in required.items()),'unrepresentative resource workload')
    require(report.get('history_lengths_cover_bound_archive') is True,'unqualified source history lengths')
    require(report.get('measurement_mode')=='BOUNDED_COMBINED_PROCESS_AND_ALLOCATED_DISK',
            'sampled/lower-bound resources cannot qualify')
    for key in ('hosted_runner_verified','full_pipeline_verified','publication_limits_verified','failure_retention_verified'):
        require(report.get(key) is True,'missing qualification: '+key)
    measured=report.get('upper_bounds',{})
    for key in ('combined_memory_bytes','allocated_disk_bytes','wall_seconds'):
        require(positive(measured.get(key)),'invalid resource bound: '+key)
    require(2*measured['combined_memory_bytes']<=capacity['available_memory_bytes'],'memory budget exceeded')
    require(2*measured['allocated_disk_bytes']<=capacity['free_disk_bytes'],'disk budget exceeded')
    require(5*measured['wall_seconds']<=3*capacity['remaining_seconds'],'time budget exceeded')
    require(report.get('promotion_authority') is False,'resource report invents authority')
    return dict(status='RESOURCE_PREFLIGHT_PASSED',qualification_sha256=expected_sha,
                source_commit=source_commit,capacity=capacity,upper_bounds=measured,promotion_authority=False)


def live_capacity(path,runner_profile,remaining_seconds):
    require(sys.platform.startswith('linux'),'Linux capacity snapshot required')
    fields={line.split(':',1)[0]:line.split(':',1)[1].strip().split() for line in Path('/proc/meminfo').read_text().splitlines()}
    require(fields.get('MemAvailable',[None,None])[1]=='kB','available-memory units unavailable')
    return dict(runner_profile=runner_profile,available_memory_bytes=int(fields['MemAvailable'][0])*1024,
                free_disk_bytes=shutil.disk_usage(path).free,remaining_seconds=remaining_seconds)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('qualification','expected-sha','source-commit','input-hash','protocol-hash','runner-profile','scratch'):
        ap.add_argument('--'+key,required=True)
    ap.add_argument('--remaining-seconds',required=True,type=int);args=ap.parse_args()
    result=verify(Path(args.qualification).read_bytes(),args.expected_sha,args.source_commit,args.input_hash,args.protocol_hash,
                  live_capacity(args.scratch,args.runner_profile,args.remaining_seconds))
    print(json.dumps(result,sort_keys=True))
