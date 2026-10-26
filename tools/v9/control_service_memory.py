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
    if (data['ActiveState'],data['SubState'],data['Result'],data['ExecMainCode'],data['ExecMainStatus'])!=('active','exited','success','1','0'):
        raise ValueError('workload did not complete successfully')
    return int(value)


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
    result=dict(schema='v9.a6-service-memory/1',unit=unit,status='FAILED',resource_qualified=False,
                promotion_authority=False,cleanup_verified=False,hosted_startup_placement_verified=False,
                exclusions=['SYSTEM_SERVICE_MANAGER','OUTER_ORCHESTRATOR','WORKLOAD_ESCAPING_CGROUP'])
    started=time.monotonic();attempted=False
    def invoke(args,name,seconds):
        with (out/name).open('xb') as log:
            return subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=seconds,check=False)
    try:
        invoke(['systemd-run','--version'],'manager-version.log',10)
        preflight=invoke(['systemctl','show',unit,'--property=LoadState'],'preflight.log',10)
        if preflight.returncode not in (0,1) or (out/'preflight.log').read_text().strip()!='LoadState=not-found':
            raise ValueError('fresh service name not verified')
        # oneshot startup completes only after the workload exits; remain-after-exit
        # keeps its accounting available until the explicit stop below. No --wait.
        args=['systemd-run','--system','--unit='+unit,'--service-type=oneshot','--remain-after-exit',
              '--expand-environment=no','--working-directory='+str(cwd),
              '--property=MemoryAccounting=yes','--property=KillMode=control-group',
              '--property=TimeoutStartSec='+str(timeout),'--property=TimeoutStopSec=5s',
              '--property=StandardOutput=append:'+str(out/'worker.log'),
              '--property=StandardError=append:'+str(out/'worker.log'),'--',*command]
        attempted=True
        launch=invoke(args,'launch.log',timeout+15)
        result['launch_returncode']=launch.returncode
        query=invoke(['systemctl','show',unit,'--property='+','.join(PROPERTIES)],'properties.log',10)
        if query.returncode:raise ValueError('service properties unavailable')
        data=properties((out/'properties.log').read_text());result['service_properties']=data
        result['memory_peak_bytes']=validate_result(data,unit)
        if launch.returncode:raise ValueError('service launch failed')
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
