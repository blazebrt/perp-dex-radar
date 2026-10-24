"""Measure isolated Linux synthetic A6 processes; no market qualification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def visible_bytes(root):
    total=0
    for path in Path(root).rglob('*'):
        try:
            if path.is_file():total+=path.stat().st_size
        except FileNotFoundError:pass  # A temporary index can disappear between scan and stat.
    return total


def measure(kind,signals,bars):
    if not sys.platform.startswith('linux'):raise RuntimeError('Linux required for ru_maxrss KiB semantics')
    if kind not in ('full','mixed','sparse','interrupted'):raise ValueError('unknown scenario')
    if type(signals) is not int or not 3<=signals<=100:raise ValueError('signals must be 3..100')
    if type(bars) is not int or not 400<=bars<=4000:raise ValueError('bars must be 400..4000')
    with tempfile.TemporaryDirectory(prefix='a6-measure-') as directory:
        root=Path(directory);result=root/'result.json'
        env=dict(os.environ,TMPDIR=directory,TEMP=directory,TMP=directory,SQLITE_TMPDIR=directory)
        command=[sys.executable,str(Path(__file__).resolve()),'--worker',kind,'--signals',str(signals),'--bars',str(bars),'--out',str(result)]
        started=time.perf_counter();peak=0;samples=0
        with (root/'worker.log').open('wb') as log:
            process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                while True:
                    peak=max(peak,visible_bytes(root));samples+=1
                    if process.poll() is not None:break
                    time.sleep(.05)
            except BaseException:
                process.terminate();process.wait();raise
        elapsed=time.perf_counter()-started
        if process.returncode!=0:raise RuntimeError('synthetic worker failed: '+(root/'worker.log').read_text()[-4000:])
        data=json.loads(result.read_text())
        data.update(wall_seconds=elapsed,sampled_visible_peak_bytes=peak,disk_samples=samples,
                    sampling_interval_seconds=.05,worker_exit=process.returncode)
        return data


def probe():
    cases=[measure(kind,signals,bars) for signals,bars in ((8,1000),(32,4000))
           for kind in ('full','mixed','sparse','interrupted')]
    import hashlib
    return dict(schema='v9.a6-isolated-resource-probe/1',status='NOT_RESOURCE_QUALIFIED',synthetic_only=True,
        market_data_loaded=False,platform=sys.platform,cases=cases,
        observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        memory_measurement='LINUX_PROCESS_LIFETIME_PEAK_RSS_IN_BYTES_INCLUDES_IMPORTS',
        disk_measurement='SAMPLED_VISIBLE_LOGICAL_FILE_BYTES_LOWER_BOUND_NOT_ALLOCATED_OR_UNLINKED_OPEN_FILES',
        exclusions=['REAL_ARCHIVE_PREPARATION','GIT_PUBLICATION','HOSTED_RUNNER_QUALIFICATION','FULL_MARKET_SCALE'],
        promotion_authority=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True)
    ap.add_argument('--worker',choices=('full','mixed','sparse','interrupted'))
    ap.add_argument('--signals',type=int,default=8);ap.add_argument('--bars',type=int,default=1000)
    args=ap.parse_args();path=Path(args.out)
    if path.exists():raise FileExistsError('preserve previous resource measurement')
    if args.worker:
        if not sys.platform.startswith('linux'):raise RuntimeError('Linux worker required')
        import resource
        from tools.v9 import control_pipeline_probe as P
        from tools.v9 import control_extract as X
        data=dict(pipeline=P.scenario(args.worker,args.signals,args.bars),
                  peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  pipeline_probe_sha256=X.sha(Path(P.__file__)))
    else:data=probe()
    with path.open('x',encoding='utf8',newline='\n') as stream:stream.write(json.dumps(data,sort_keys=True,indent=2)+'\n')
