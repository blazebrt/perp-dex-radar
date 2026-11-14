"""Opt-in isolated cgroup accounting for trusted synthetic commands; no qualification."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


def number(path):
    raw=path.read_text().strip()
    if not re.fullmatch('[0-9]+',raw):raise ValueError('invalid kernel counter')
    return int(raw)


def events(path):
    result={}
    for line in path.read_text().splitlines():
        pair=line.split()
        if len(pair)!=2 or pair[0] in result or not re.fullmatch('[0-9]+',pair[1]):
            raise ValueError('invalid kernel events')
        result[pair[0]]=int(pair[1])
    return result


def validate_parent(parent):
    if not sys.platform.startswith('linux'):raise ValueError('Linux required')
    mount=Path('/sys/fs/cgroup');parent=Path(parent).resolve()
    if mount not in parent.parents:raise ValueError('explicit non-root delegated parent required')
    matches=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        left,sep,right=line.partition(' - ');fields=left.split();tail=right.split()
        if sep and len(fields)>=6 and fields[4]==str(mount) and tail and tail[0]=='cgroup2':matches.append(fields)
    if len(matches)!=1 or matches[0][3]!='/':raise ValueError('full-root cgroup2 mount required')
    if 'memory' not in (parent/'cgroup.subtree_control').read_text().split():
        raise ValueError('memory controller must already be delegated')
    return parent


def enter(group,expected,receipt,command):
    """Move this bootstrap before exec/fork; fail before workload on wrong membership."""
    (Path(group)/'cgroup.procs').write_text(str(os.getpid()))
    membership=Path('/proc/self/cgroup').read_text().splitlines()
    if [line for line in membership if line.startswith('0::')]!=['0::'+expected]:
        raise ValueError('bootstrap placement mismatch')
    with Path(receipt).open('x') as stream:
        json.dump(dict(pid=os.getpid(),group=expected),stream)
    os.execvpe(command[0],command,os.environ)


def membership_path(group):
    return '/'+str(group.relative_to('/sys/fs/cgroup'))


def run(parent,command,out,timeout):
    """Requires existing delegation; never enables controllers or changes parent limits.

    This is for trusted commands, not containment of adversarial processes. Bootstrap
    allocations before migration and the outer observer are excluded from the peak.
    """
    if not isinstance(command,list) or not command or any(type(x) is not str or not x or '\x00' in x for x in command):
        raise ValueError('nonempty command argument list required')
    if type(timeout) is not int or not 1<=timeout<=1800:raise ValueError('timeout must be 1..1800 seconds')
    parent=validate_parent(parent);out=Path(out).resolve()
    mount=Path('/sys/fs/cgroup')
    if out==parent or parent in out.parents or out==mount or mount in out.parents:
        raise ValueError('outputs must be outside cgroup filesystem')
    out.mkdir(parents=True,exist_ok=False)
    group=parent/('a6-synthetic-'+uuid.uuid4().hex)
    result=dict(schema='v9.a6-isolated-cgroup-run/1',status='FAILED',resource_qualified=False,
                promotion_authority=False,placement_verified=False,group_removed=False,
                exclusions=['OUTER_OBSERVER','BOOTSTRAP_ALLOCATIONS_BEFORE_MIGRATION','WORKLOAD_ESCAPING_CGROUP'])
    process=None;created=False;started=time.monotonic()
    try:
        group.mkdir();created=True
        expected=membership_path(group)
        result['group']=expected
        if (group/'cgroup.procs').read_text().strip() or events(group/'cgroup.events').get('populated')!=0:
            raise ValueError('new group must be empty')
        if number(group/'memory.peak')!=0:raise ValueError('new group has prior memory charges')
        initial=events(group/'memory.events')
        if not {'oom','oom_kill','high','max'}<=initial.keys() or any(initial.values()):
            raise ValueError('new group must have clean memory events')
        if not (group/'cgroup.kill').exists():raise ValueError('group-wide cleanup unavailable')
        receipt=out/'placement.json'
        with (out/'worker.log').open('xb') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--enter',str(group),expected,str(receipt),*command],
                                     stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:result['exit_code']=process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result['timed_out']=True;raise
        placed=json.loads(receipt.read_text())
        if placed!={'pid':process.pid,'group':expected}:raise ValueError('placement receipt mismatch')
        result['placement_verified']=True
        if events(group/'cgroup.events').get('populated')!=0:raise ValueError('workload left descendants alive')
        result['status']='MEASURED_DIAGNOSTIC' if process.returncode==0 else 'WORKLOAD_FAILED'
    except Exception as error:result['error_type']=type(error).__name__
    finally:
        if created:
            try:
                (group/'cgroup.kill').write_text('1')
            except Exception as error:
                result['cleanup_error_type']=type(error).__name__;result['status']='CLEANUP_OR_MEASUREMENT_FAILED'
            try:
                if process is not None:
                    if process.poll() is None:process.kill()  # Also covers failure before migration.
                    process.wait(timeout=5)
                deadline=time.monotonic()+5
                while events(group/'cgroup.events').get('populated')!=0:
                    if time.monotonic()>=deadline:raise TimeoutError('group remained populated')
                    time.sleep(.02)
                result['memory_peak_bytes']=number(group/'memory.peak')
                result['memory_events']=events(group/'memory.events')
                if result['memory_events'].get('oom',0) or result['memory_events'].get('oom_kill',0):
                    result['status']='OOM_OR_MEMORY_FAILURE'
            except Exception as error:
                result['cleanup_error_type']=type(error).__name__;result['status']='CLEANUP_OR_MEASUREMENT_FAILED'
            try:
                group.rmdir();result['group_removed']=True
            except OSError as error:
                result['removal_error_type']=type(error).__name__;result['status']='CLEANUP_OR_MEASUREMENT_FAILED'
        result['wall_seconds']=time.monotonic()-started
        with (out/'accounting.json').open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2)
    return result


if __name__=='__main__':
    if len(sys.argv)<6 or sys.argv[1]!='--enter':raise SystemExit('internal bootstrap only')
    enter(Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]),sys.argv[5:])
