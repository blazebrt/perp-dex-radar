"""Preserve locally retained A6 commits in a self-contained Git bundle."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9.record_control_outcome import verify_ancestry


def backup(repo,work,bundle):
    report=Path(work)/'job.json';bundle=Path(bundle)
    if bundle.exists() or bundle.is_symlink():raise FileExistsError('preserve existing recovery bundle')
    if not report.is_file():return dict(status='NO_JOB_RECORD',promotion_authority=False)
    doc=json.loads(report.read_bytes());commit=doc.get('retained_commit') or doc.get('reservation_commit')
    if commit is None:return dict(status='NO_VERIFIED_COMMIT_RECORDED',promotion_authority=False)
    reservation=doc.get('reservation_commit')
    if not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{40}',v) for v in (commit,reservation)):
        raise ValueError('full recorded commit identities required')
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull)
    def git(*args):
        return subprocess.check_output(['git','--no-replace-objects','-c','safe.directory=*','-c','core.hooksPath='+os.devnull,
            '-C',str(Path(repo).resolve()),*args],env=env,stderr=subprocess.PIPE)
    root,_=verify_ancestry(git,commit)
    if root!=reservation:raise ValueError('backup reservation ancestry mismatch')
    bundle.parent.mkdir(parents=True,exist_ok=True)
    ref='refs/a6-local-backup/'+uuid.uuid4().hex
    git('update-ref',ref,commit,'0'*40)
    try:
        git('bundle','create',str(bundle.resolve()),ref)
        git('bundle','verify',str(bundle.resolve()))
    finally:git('update-ref','-d',ref,commit)
    return dict(status='LOCAL_RECOVERY_BUNDLE_VERIFIED',commit=commit,reservation_commit=reservation,
                bytes=bundle.stat().st_size,remote_backup_verified=False,promotion_authority=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--work',required=True);ap.add_argument('--bundle',required=True)
    args=ap.parse_args()
    try:result=backup(ROOT,args.work,args.bundle)
    except Exception as error:
        print(json.dumps(dict(status='BACKUP_FAILED',error_type=type(error).__name__)));raise SystemExit(1)
    print(json.dumps(result,sort_keys=True))
