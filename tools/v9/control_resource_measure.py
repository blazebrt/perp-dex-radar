"""Measure isolated Linux synthetic A6 processes; no market qualification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import stat
import signal
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_probe_shape as Shape


def paths_below(root):
    def failed(error):
        if not isinstance(error,FileNotFoundError):raise error
    for folder,dirs,files in os.walk(root,onerror=failed):
        for name in dirs+files:yield Path(folder)/name


def visible_bytes(root):
    total=0
    for path in paths_below(root):
        try:
            if path.is_file():total+=path.stat().st_size
        except FileNotFoundError:pass  # A temporary index can disappear between scan and stat.
    return total


def session_rss(session_id,proc=Path('/proc'),page_size=None):
    """Sample summed RSS in the worker's private session, not a physical-memory bound.

    Shared pages can be counted repeatedly. Short-lived or session-escaping children
    can be missed. Report scan gaps rather than treating unreadable processes as zero.
    """
    page_size=os.sysconf('SC_PAGE_SIZE') if page_size is None else page_size
    if type(session_id) is not int or session_id<=0 or type(page_size) is not int or page_size<=0:
        raise ValueError('positive session and page size required')
    result=dict(rss_bytes=0,processes=0,read_errors=0,vanished_processes=0,scan_complete=True)
    try:entries=list(Path(proc).iterdir())
    except OSError:
        result.update(read_errors=1,scan_complete=False);return result
    for entry in entries:
        if not entry.name.isdecimal():continue
        try:
            raw=(entry/'stat').read_text()
            # comm may contain spaces and parentheses; fields after its final ')' are fixed.
            end=raw.rfind(')');fields=raw[end+2:].split()
            if end<0 or len(fields)<22:raise ValueError('malformed proc stat')
            sid=int(fields[3]);rss=int(fields[21])
            if rss<0:raise ValueError('negative RSS')
            if sid==session_id:
                result['rss_bytes']+=rss*page_size;result['processes']+=1
        except FileNotFoundError:result['vanished_processes']+=1
        except (OSError,ValueError):result['read_errors']+=1
    result['scan_complete']=not (result['read_errors'] or result['vanished_processes'])
    return result


def allocated_bytes(root,pid=None,coverage=None):
    """Sample blocks once per inode, including worker's open deleted scratch files."""
    root=Path(root).resolve();seen={};paths=list(paths_below(root))+[root]
    if pid is not None:
        # Only this worker's descriptors; Git subprocess peaks remain sampled by path.
        try:
            for fd in (Path('/proc')/str(pid)/'fd').iterdir():
                try:
                    target=os.readlink(fd)
                    if target.startswith(str(root)+'/'):paths.append(fd)
                except FileNotFoundError:pass
        except FileNotFoundError:pass
        except PermissionError:
            if coverage is None:raise
            coverage['fd_access_denied_samples']+=1
    for path in paths:
        try:
            info=path.stat()
            if stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode):
                seen[(info.st_dev,info.st_ino)]=info.st_blocks*512
        except FileNotFoundError:pass
    return sum(seen.values())


def stop_worker_group(process,grace_seconds=2):
    """Stop this probe's private process group, even if its leader exits first.

    Children that deliberately change process groups/sessions are outside this
    cleanup contract, just as escaping children are outside the RSS sample.
    """
    if type(grace_seconds) not in (int,float) or not 0<grace_seconds<=10:
        raise ValueError('cleanup grace must be positive and at most ten seconds')
    def send(sig):
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:pass  # The private group has already exited.
    send(signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # The leader can exit while a child ignores SIGTERM. Always kill the
        # remaining group rather than inferring cleanup from the leader alone.
        send(signal.SIGKILL)
    process.wait(timeout=5)


def measure(kind,signals,bars,*,assets=61,definitions=3,unavailable=1,shard_rows=4):
    if not sys.platform.startswith('linux'):raise RuntimeError('Linux required for ru_maxrss KiB semantics')
    if kind not in ('full','mixed','sparse','interrupted'):raise ValueError('unknown scenario')
    Shape.validate(signals,bars,assets,definitions,unavailable)
    Shape.shard_limit(shard_rows)
    with tempfile.TemporaryDirectory(prefix='a6-measure-') as directory:
        root=Path(directory);result=root/'result.json'
        env=dict(os.environ,TMPDIR=directory,TEMP=directory,TMP=directory,SQLITE_TMPDIR=directory)
        command=[sys.executable,str(Path(__file__).resolve()),'--worker',kind,'--signals',str(signals),'--bars',str(bars),'--out',str(result),'--assets',str(assets),'--definitions',str(definitions),'--unavailable',str(unavailable),'--shard-rows',str(shard_rows)]
        started=time.perf_counter();peak=0;allocated_peak=0;samples=0
        memory_peak=0;process_peak=0;memory_gaps=0;memory_errors=0;memory_vanished=0
        coverage={'fd_access_denied_samples':0}
        with (root/'worker.log').open('wb') as log:
            process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while True:
                    peak=max(peak,visible_bytes(root));samples+=1
                    allocated_peak=max(allocated_peak,allocated_bytes(root,process.pid,coverage))
                    memory=session_rss(process.pid)
                    memory_peak=max(memory_peak,memory['rss_bytes']);process_peak=max(process_peak,memory['processes'])
                    memory_gaps+=not memory['scan_complete'];memory_errors+=memory['read_errors']
                    memory_vanished+=memory['vanished_processes']
                    if process.poll() is not None:break
                    time.sleep(.05)
            except BaseException:
                stop_worker_group(process);raise
        elapsed=time.perf_counter()-started
        if process.returncode!=0:raise RuntimeError('synthetic worker failed: '+(root/'worker.log').read_text()[-4000:])
        data=json.loads(result.read_text())
        data.update(wall_seconds=elapsed,sampled_visible_peak_bytes=peak,sampled_allocated_peak_bytes=allocated_peak,disk_samples=samples,
                    sampled_session_rss_peak_bytes=memory_peak,sampled_session_process_peak=process_peak,
                    session_scan_gap_samples=memory_gaps,session_scan_read_errors=memory_errors,
                    session_scan_vanished_processes=memory_vanished,
                    sampling_interval_seconds=.05,worker_exit=process.returncode,**coverage)
        return data


def probe(signals=None,bars=None,*,assets=61,definitions=3,unavailable=1,shard_rows=4):
    if (signals is None)!=(bars is None):
        raise ValueError('signals and bars must be supplied together')
    Shape.validate(8 if signals is None else signals,1000 if bars is None else bars,assets,definitions,unavailable)
    Shape.shard_limit(shard_rows)
    scales=((8,1000),(32,4000)) if signals is None else ((signals,bars),)
    from tools.v9.control_cgroup_memory import snapshot
    cgroup_before=snapshot()
    cases=[measure(kind,signals,bars,assets=assets,definitions=definitions,unavailable=unavailable,shard_rows=shard_rows) for signals,bars in scales
           for kind in ('full','mixed','sparse','interrupted')]
    import hashlib
    return dict(schema='v9.a6-isolated-resource-probe/3',status='NOT_RESOURCE_QUALIFIED',synthetic_only=True,
        market_data_loaded=False,platform=sys.platform,cases=cases,outcome_shard_max_rows=shard_rows,
        requested_scales=[Shape.validate(n,b,assets,definitions,unavailable) for n,b in scales],
        cgroup_capability_before=cgroup_before,cgroup_capability_after=snapshot(),
        observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        population_shape_sha256=hashlib.sha256(Path(Shape.__file__).read_bytes()).hexdigest(),
        memory_measurement='LINUX_PROCESS_LIFETIME_PEAK_RSS_IN_BYTES_INCLUDES_IMPORTS',
        combined_memory_measurement='SAMPLED_PRIVATE_SESSION_SUM_RSS_SHARED_PAGES_MAY_REPEAT_NOT_A_BOUND',
        combined_memory_exclusions=['OBSERVER_PROCESS','BETWEEN_SAMPLE_PEAKS','CHILDREN_ESCAPING_SESSION'],
        disk_measurement='SAMPLED_LOGICAL_AND_ALLOCATED_BLOCKS_WITH_WORKER_OPEN_DELETED_FILES_LOWER_BOUND',
        exclusions=['REAL_ARCHIVE_PREPARATION','REMOTE_GIT_PUBLICATION','HOSTED_RUNNER_QUALIFICATION','FULL_MARKET_SCALE'],
        promotion_authority=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True)
    ap.add_argument('--worker',choices=('full','mixed','sparse','interrupted'))
    ap.add_argument('--signals',type=int);ap.add_argument('--bars',type=int)
    ap.add_argument('--assets',type=int,default=61);ap.add_argument('--definitions',type=int,default=3)
    ap.add_argument('--unavailable',type=int,default=1)
    ap.add_argument('--shard-rows',type=int,default=4)
    args=ap.parse_args();path=Path(args.out)
    if path.exists():raise FileExistsError('preserve previous resource measurement')
    if args.worker:
        if not sys.platform.startswith('linux'):raise RuntimeError('Linux worker required')
        import resource
        from tools.v9 import control_pipeline_probe as P
        from tools.v9 import control_extract as X, control_publication_probe as G
        data=dict(pipeline=P.scenario(args.worker,8 if args.signals is None else args.signals,1000 if args.bars is None else args.bars,retain=G.retain,assets=args.assets,definitions=args.definitions,unavailable=args.unavailable,shard_rows=args.shard_rows),
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  pipeline_probe_sha256=X.sha(Path(P.__file__)),publication_probe_sha256=X.sha(Path(G.__file__)))
    else:data=probe(args.signals,args.bars,assets=args.assets,definitions=args.definitions,unavailable=args.unavailable,shard_rows=args.shard_rows)
    with path.open('x',encoding='utf8',newline='\n') as stream:stream.write(json.dumps(data,sort_keys=True,indent=2)+'\n')
