"""Fail-closed A6 resource preflight over externally pinned qualification evidence."""
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
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


def memory_capacity(proc=Path('/proc'),mount=Path('/sys/fs/cgroup')):
    """Conservative snapshot for a hosted, full-root cgroup-v2 environment.

    Ancestor usage includes siblings. No reclaim or swap capacity is credited.
    This snapshot does not reserve memory or establish host/namespace identity.
    """
    proc=Path(proc);mount=Path(mount)
    rows=[line.split(':',1)[1].strip().split() for line in (proc/'meminfo').read_text().splitlines()
          if line.startswith('MemAvailable:')]
    require(len(rows)==1 and len(rows[0])==2 and rows[0][1]=='kB'
            and re.fullmatch('[0-9]+',rows[0][0]) is not None,'available-memory units unavailable')
    host=int(rows[0][0])*1024
    groups=(proc/'self/cgroup').read_text().splitlines()
    require(len(groups)==1 and groups[0].startswith('0::'),'unified-only cgroup membership required')
    group=groups[0][3:];parts=PurePosixPath(group).parts
    require(group.startswith('/') and '..' not in parts and '\\' not in group and '\x00' not in group,
            'unsafe cgroup membership')
    matches=[]
    for line in (proc/'self/mountinfo').read_text().splitlines():
        left,sep,right=line.partition(' - ');fields=left.split();tail=right.split()
        if sep and len(fields)>=6 and tail and tail[0]=='cgroup2' and fields[4]==str(mount):
            matches.append(fields)
    require(len(matches)==1 and matches[0][3]=='/','full-root cgroup2 mount required')
    base=mount.resolve(); current=base/group.lstrip('/')
    require(current.resolve()==current and current.is_dir(),'unsafe or missing cgroup directory')
    available=host;limits=[]
    while current!=base:
        raw=(current/'memory.max').read_text().strip()
        usage=(current/'memory.current').read_text().strip()
        require(re.fullmatch('[0-9]+',usage) is not None,'invalid cgroup memory usage')
        require(raw=='max' or re.fullmatch('[0-9]+',raw) is not None,'invalid cgroup memory limit')
        limit=None if raw=='max' else int(raw)
        headroom=None if limit is None else max(0,limit-int(usage))
        if headroom is not None:available=min(available,headroom)
        limits.append(dict(group='/'+current.relative_to(base).as_posix(),limit_bytes=limit,
                           current_bytes=int(usage),headroom_bytes=headroom))
        current=current.parent
    require((proc/'self/cgroup').read_text().splitlines()==groups,'cgroup membership changed during snapshot')
    return dict(available_memory_bytes=available,host_available_memory_bytes=host,
                cgroup_memory_limits=limits,memory_capacity_scope='CURRENT_GROUP_AND_VISIBLE_ANCESTORS_SNAPSHOT')


def live_capacity(path,runner_profile,remaining_seconds):
    require(sys.platform.startswith('linux'),'Linux capacity snapshot required')
    return dict(runner_profile=runner_profile,**memory_capacity(),
                free_disk_bytes=shutil.disk_usage(path).free,remaining_seconds=remaining_seconds)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('qualification','expected-sha','source-commit','input-hash','protocol-hash','runner-profile','scratch'):
        ap.add_argument('--'+key,required=True)
    ap.add_argument('--remaining-seconds',required=True,type=int);args=ap.parse_args()
    result=verify(Path(args.qualification).read_bytes(),args.expected_sha,args.source_commit,args.input_hash,args.protocol_hash,
                  live_capacity(args.scratch,args.runner_profile,args.remaining_seconds))
    print(json.dumps(result,sort_keys=True))
