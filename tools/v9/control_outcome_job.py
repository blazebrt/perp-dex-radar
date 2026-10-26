"""Coordinate one reserved outcome job; no CLI or active workflow is installed.

Call from a pinned, clean checkout with an authenticated API client and a live
capacity callback. Input preparation runs only after reservation verification.
Failures retain local files for an outer workflow's always-run backup step.
SIGKILL/runner loss cannot be recovered here: the remote reservation blocks reruns.
"""
import os
from pathlib import Path
import subprocess
import shutil
from tools.v9 import control_reservation as R
from tools.v9 import control_outcome_publish as P
from tools.v9 import control_retention_commit as C
from tools.v9 import control_retention_remote as U
from tools.v9.record_control_outcome import verify_ancestry


def git(repo,*args):
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['git','--no-replace-objects','-c','safe.directory=*','-C',str(repo),*args],stderr=subprocess.PIPE,env=env)


def checkout(repo,source):
    if Path(repo).resolve()!=P.ROOT.resolve():raise ValueError('job must use its executing source checkout')
    if git(repo,'rev-parse','HEAD').decode().strip()!=source or git(repo,'status','--porcelain','--untracked-files=all').strip():
        raise ValueError('clean pinned source checkout required')
    expected=['https://github.com/blazebrt/perp-dex-radar.git']
    if git(repo,'remote','get-url','--all','origin').decode().splitlines()!=expected or git(repo,'remote','get-url','--push','--all','origin').decode().splitlines()!=expected:
        raise ValueError('origin must match the fixed reservation repository')


def fetch_reservation(repo,commit,raw):
    # Fixed repository agrees with the API transport, independent of remote config.
    git(repo,'fetch','--no-tags','--no-recurse-submodules','https://github.com/blazebrt/perp-dex-radar.git',U.BRANCH)
    if git(repo,'rev-parse','FETCH_HEAD').decode().strip()!=commit:raise ValueError('reservation changed before execution')
    root,saved=verify_ancestry(lambda *args:git(repo,*args),commit)
    if root!=commit or saved!=raw:raise ValueError('fetched reservation mismatch')


def run(repo,work,md,evidence,signals,source,run_id,run_attempt,qualification,qualification_hash,api,capacity,identity,prepare_inputs):
    repo=Path(repo).resolve();work=Path(work).resolve()
    for item in (repo,md,evidence,signals,qualification):
        other=Path(item).resolve()
        if other==work or work in other.parents or other in work.parents:raise ValueError('job workspace overlaps source/input')
    for item in (md,evidence,signals):
        if Path(item).exists() or Path(item).is_symlink():raise FileExistsError('inputs must be prepared after reservation')
    checkout(repo,source)
    work.mkdir(parents=True,exist_ok=False)  # Recovery must inspect, never reexecute in place.
    report=dict(status='RESERVATION_UNVERIFIED_NO_EXECUTION',reservation_verified=False,
                publication_verified=False,error_type=None,promotion_authority=False)
    def finish():
        P.write(work/'job.json',report)
        return report
    try:
        reserved=R.reserve(api,lambda commit,path:git(repo,'show',commit+':'+path),source,run_id,run_attempt,
                           Path(qualification).read_bytes(),qualification_hash,capacity())
    except Exception as error:
        report['error_type']=type(error).__name__
        return finish()  # A remote create may have succeeded; never infer absence or retry.
    commit=reserved['reservation_commit'];raw=reserved['reservation_bytes']
    report.update(reservation_verified=True,reservation_commit=commit)
    reservation=work/'reservation.json';reservation.write_bytes(raw);attempt=work/'attempt'
    execution=None
    preparation_log=work/'input-preparation.log'
    preparation_complete=False
    try:
        fetch_reservation(repo,commit,raw)
        prepare_inputs(Path(md),Path(evidence),Path(signals),preparation_log)
        if preparation_log.is_symlink() or not preparation_log.is_file():raise ValueError('regular input preparation log required')
        if not Path(md).is_dir() or not Path(evidence).is_file() or not Path(signals).is_dir():raise ValueError('input preparation incomplete')
        preparation_complete=True
        execution=P.retain(md,evidence,signals,attempt,source,reservation,
                           qualification=qualification,capacity=capacity(),preparation_log=preparation_log)
    except (Exception,KeyboardInterrupt) as error:
        report['error_type']=type(error).__name__
        attempt.mkdir(exist_ok=True)
        if not (attempt/'reservation.json').exists():(attempt/'reservation.json').write_bytes(raw)
        if not preparation_complete:
            if preparation_log.is_file() and not preparation_log.is_symlink():shutil.copyfile(preparation_log,attempt/'input-preparation.log')
            P.write(attempt/'preparation-failure.json',dict(error_type=type(error).__name__,execution_started=False))
        # Outside the inventoried attempt, to avoid rewriting an existing artifact inventory.
        P.write(work/'execution-error.json',dict(error_type=type(error).__name__))
    try:
        prepared=C.prepare(repo,commit,commit,attempt,identity)
        report['retained_commit']=prepared['commit']
        published=U.publish(repo,commit,prepared['commit'])
        if published.get('status')!='RETAINED_COMMIT_FETCH_VERIFIED' or published.get('commit')!=prepared['commit']:
            raise ValueError('publication receipt mismatch')
        report['publication_verified']=True
        report['status']='RETAINED_DIAGNOSTICS' if execution and execution.get('status')=='PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE' else 'FAILED_OR_PARTIAL_RETAINED'
    except Exception as error:
        report.update(status='PUBLICATION_FAILED_LOCAL_FILES_RETAINED',error_type=type(error).__name__)
    return finish()
