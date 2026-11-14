"""Transient-service accounting for trusted synthetic workloads, before Python startup."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

PROPERTIES=('LoadState','ActiveState','SubState','Result','ExecMainCode','ExecMainStatus',
            'MemoryAccounting','MemoryPeak','ControlGroup')


def properties(raw):
    result={}
    for line in raw.splitlines():
        key,sep,value=line.partition('=')
        if not sep or key in result or key not in PROPERTIES:raise ValueError('invalid service properties')
        result[key]=value
    if set(result)!=set(PROPERTIES):raise ValueError('incomplete service properties')
    return result


def validate_result(data,unit):
    if data['LoadState']!='loaded' or data['MemoryAccounting']!='yes':raise ValueError('accounting unavailable')
    if data['ControlGroup']!='/system.slice/'+unit:raise ValueError('unexpected service group')
    value=data['MemoryPeak']
    if not re.fullmatch('[0-9]+',value) or not 0<int(value)<2**64-1:
        raise ValueError('missing or invalid peak')
    if (data['ActiveState'],data['SubState'],data['Result'])!=('active','running','success'):
        raise ValueError('measurement holder is not running')
    return int(value)


def hold(command,done,release,timeout):
    """Keep the service cgroup populated until the outer collector finishes reading."""
    completed=subprocess.run(command,check=False,timeout=timeout)
    # Rename gives the collector a complete receipt, not a partially written JSON file.
    temporary=done.with_suffix('.tmp')
    with temporary.open('x') as stream:json.dump({'exit_code':completed.returncode},stream)
    temporary.rename(done)
    deadline=time.monotonic()+60
    while not release.exists():
        if time.monotonic()>=deadline:raise TimeoutError('collector did not release holder')
        time.sleep(.05)
    return completed.returncode


def run(command,cwd,out,timeout):
    """No persistent unit, fallback, credential forwarding or production invocation.

    The manager starts the command inside its service group; no Python migration
    bootstrap is used. Manager and orchestration overhead remain outside this group.
    Real startup placement must be checked with a hosted workload receipt.
    """
    if not sys.platform.startswith('linux'):raise ValueError('Linux required')
    if type(command) is not list or not command or any(type(v) is not str or not v or '\x00' in v for v in command):
        raise ValueError('command argument list required')
    if not Path(command[0]).is_absolute():raise ValueError('absolute executable required')
    if type(timeout) is not int or not 1<=timeout<=1800:raise ValueError('timeout must be 1..1800 seconds')
    cwd=Path(cwd).resolve();out=Path(out).resolve()
    if not cwd.is_dir():raise ValueError('working directory missing')
    if any(c in str(out)+str(cwd) for c in ('\n','\r','\x00','%')):raise ValueError('unsafe unit path')
    out.mkdir(parents=True,exist_ok=False)
    unit='a6-synthetic-'+uuid.uuid4().hex+'.service'
    result=dict(schema='v9.a6-service-memory/2',unit=unit,status='FAILED',resource_qualified=False,
                promotion_authority=False,cleanup_verified=False,hosted_startup_placement_verified=False,
                peak_scope='THROUGH_WORKLOAD_COMPLETION_BEFORE_HOLDER_SHUTDOWN',
                exclusions=['SYSTEM_SERVICE_MANAGER','OUTER_ORCHESTRATOR','HOLDER_SHUTDOWN_AFTER_SNAPSHOT','WORKLOAD_ESCAPING_CGROUP'])
    started=time.monotonic();attempted=False
    def invoke(args,name,seconds):
        with (out/name).open('xb') as log:
            return subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=seconds,check=False)
    try:
        invoke(['systemd-run','--version'],'manager-version.log',10)
        preflight=invoke(['systemctl','show',unit,'--property=LoadState'],'preflight.log',10)
        if preflight.returncode not in (0,1) or (out/'preflight.log').read_text().strip()!='LoadState=not-found':
            raise ValueError('fresh service name not verified')
        done=out/'completed.json';release=out/'release'
        # Exec returns after the holder starts. The holder remains alive after its
        # child exits so systemd cannot discard the cgroup before collection.
        wrapped=[sys.executable,str(Path(__file__).resolve()),'--hold',str(done),str(release),str(timeout),*command]
        args=['systemd-run','--system','--unit='+unit,'--service-type=exec','--remain-after-exit',
              '--expand-environment=no','--working-directory='+str(cwd),
              '--property=MemoryAccounting=yes','--property=KillMode=control-group',
              '--property=TimeoutStartSec=15s','--property=RuntimeMaxSec='+str(timeout+75),'--property=TimeoutStopSec=5s',
              '--property=StandardOutput=append:'+str(out/'worker.log'),
              '--property=StandardError=append:'+str(out/'worker.log'),'--',*wrapped]
        attempted=True
        launch=invoke(args,'launch.log',20)
        result['launch_returncode']=launch.returncode
        if launch.returncode:raise ValueError('service launch failed')
        deadline=time.monotonic()+timeout+5
        while not done.exists():
            if time.monotonic()>=deadline:raise TimeoutError('workload completion unavailable')
            time.sleep(.1)
        completion=json.loads(done.read_text())
        if set(completion)!= {'exit_code'} or type(completion['exit_code']) is not int:
            raise ValueError('invalid completion receipt')
        result['workload_exit_code']=completion['exit_code']
        query=invoke(['systemctl','show',unit,'--property='+','.join(PROPERTIES)],'properties.log',10)
        if query.returncode:raise ValueError('service properties unavailable')
        data=properties((out/'properties.log').read_text());result['service_properties']=data
        result['memory_peak_bytes']=validate_result(data,unit)
        release.touch(exist_ok=False)
        if completion['exit_code']!=0:raise ValueError('workload failed')
        result['status']='MEASURED_DIAGNOSTIC_PENDING_HOSTED_PLACEMENT_CHECK'
    except Exception as error:
        result['error_type']=type(error).__name__
    finally:
        if attempted:
            try:
                stop=invoke(['systemctl','stop',unit],'stop.log',15)
                # Stopping only this UUID unit kills remaining descendants. Check
                # systemd state rather than assuming a successful stop proves it.
                check=invoke(['systemctl','show',unit,'--property=ActiveState','--property=LoadState'],
                             'cleanup.log',10)
                lines=(out/'cleanup.log').read_text().splitlines()
                state=dict(line.split('=',1) for line in lines)
                result['cleanup_state']=state
                result['cleanup_verified']=(stop.returncode==0 and check.returncode in (0,1)
                    and set(state)=={'ActiveState','LoadState'} and state['ActiveState']=='inactive'
                    and state['LoadState'] in ('loaded','not-found'))
                if not result['cleanup_verified']:result['status']='CLEANUP_UNVERIFIED'
            except Exception as error:
                result['cleanup_error_type']=type(error).__name__;result['status']='CLEANUP_UNVERIFIED'
        result['wall_seconds']=time.monotonic()-started
        with (out/'accounting.json').open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2)
    return result


if __name__=='__main__':
    if len(sys.argv)<6 or sys.argv[1]!='--hold':raise SystemExit('internal holder only')
    raise SystemExit(hold(sys.argv[5:],Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4])))
