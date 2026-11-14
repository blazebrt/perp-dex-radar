"""Read cgroup v2 memory capabilities without changing groups or claiming isolation."""
from pathlib import Path, PurePosixPath
import re


def snapshot(proc=Path('/proc'),mount=Path('/sys/fs/cgroup')):
    """Only support a verified full-root cgroup2 mount; other layouts stay unavailable.

    Counters belong to the existing group and descendants, including earlier or
    unrelated work. A successful read is not a measurement of this particular run.
    """
    result=dict(schema='v9.a6-cgroup-memory-capability/1',status='UNAVAILABLE',
                isolated_run_verified=False,resource_qualified=False,promotion_authority=False)
    try:
        groups=(Path(proc)/'self/cgroup').read_text().splitlines()
        unified=[line[3:] for line in groups if line.startswith('0::')]
        if len(unified)!=1:raise ValueError('unambiguous unified membership required')
        group=unified[0];parts=PurePosixPath(group).parts
        if not group.startswith('/') or '..' in parts or '\\' in group or '\x00' in group:
            raise ValueError('unsafe cgroup membership')
        matches=[]
        for line in (Path(proc)/'self/mountinfo').read_text().splitlines():
            left,sep,right=line.partition(' - ');fields=left.split();tail=right.split()
            if sep and len(fields)>=6 and tail and tail[0]=='cgroup2' and fields[4]==str(mount):
                matches.append(fields)
        if len(matches)!=1 or matches[0][3]!='/':
            raise ValueError('verified full-root cgroup2 mount required')
        base=Path(mount).resolve();path=(base/group.lstrip('/')).resolve()
        if path!=base and base not in path.parents:raise ValueError('cgroup path escaped mount')
        result['group']=group
        values={}
        for name in ('memory.current','memory.peak','memory.max','memory.swap.current','memory.swap.max'):
            raw=(path/name).read_text().strip()
            if raw=='max' and name in ('memory.max','memory.swap.max'):values[name]=None
            elif re.fullmatch('[0-9]+',raw):values[name]=int(raw)
            else:raise ValueError('invalid memory counter')
        events={}
        for line in (path/'memory.events').read_text().splitlines():
            fields=line.split()
            if len(fields)!=2 or fields[0] in events or not re.fullmatch('[0-9]+',fields[1]):
                raise ValueError('invalid memory events')
            events[fields[0]]=int(fields[1])
        if not {'oom','oom_kill','max','high'}<=events.keys():raise ValueError('incomplete memory events')
        result.update(status='SHARED_GROUP_COUNTERS_ONLY',counters=values,events=events,
                      peak_scope='GROUP_AND_DESCENDANTS_SINCE_CREATION_OR_FD_RESET_NOT_THIS_RUN')
    except (OSError,ValueError) as error:
        result['error_type']=type(error).__name__
    return result
