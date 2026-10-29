"""Publish an already prepared A6 retention commit; never execute a study.

Call only after the reservation is durably established. Failure leaves local
objects intact for inspection. No force, merge, rebase or automatic retry.
"""
import os
from pathlib import Path
import re
import subprocess
from tools.v9.record_control_outcome import verify_ancestry

BRANCH='refs/heads/evidence-a6-outcome-results'


def publish(repo,reservation,commit,remote='origin'):
    if not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{40}',v) for v in (reservation,commit)):
        raise ValueError('full reservation and result commits required')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]*',remote):raise ValueError('configured remote name required')
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,GIT_TERMINAL_PROMPT='0')
    def git(*args):
        return subprocess.run(['git','--no-replace-objects','-c','safe.directory=*',
            '-c','core.hooksPath='+os.devnull,'-C',str(Path(repo).resolve()),*args],env=env,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
    urls=git('remote','get-url','--all',remote).decode().splitlines()
    pushurls=git('remote','get-url','--push','--all',remote).decode().splitlines()
    if len(urls)!=1 or urls!=pushurls or urls[0].startswith('-'):
        raise ValueError('one identical fetch/push destination required')
    url=urls[0]
    root,_=verify_ancestry(git,commit)
    if root!=reservation or git('rev-list','--parents','-n','1',commit).decode().split()!=[commit,reservation]:
        raise ValueError('result must be a direct child of the reservation')
    def tip():
        rows=git('ls-remote','--refs',url,BRANCH).decode().splitlines()
        if len(rows)!=1:raise ValueError('durable reservation branch missing or ambiguous')
        fields=rows[0].split()
        if len(fields)!=2 or fields[1]!=BRANCH:raise ValueError('unexpected remote response')
        return fields[0]
    before=tip()
    if before not in (reservation,commit):raise ValueError('remote tip changed; inspect without rerunning')
    if before==reservation:
        # Explicit URL/ref avoids configured push refspecs and mirror behavior.
        git('push','--porcelain','--no-follow-tags',url,commit+':'+BRANCH)
    if tip()!=commit:raise ValueError('published tip does not match retained result')
    git('fetch','--no-tags','--no-recurse-submodules',url,BRANCH)
    if git('rev-parse','FETCH_HEAD').decode().strip()!=commit:
        raise ValueError('remote result changed during verification')
    verify_ancestry(git,commit)
    return dict(status='RETAINED_COMMIT_FETCH_VERIFIED',commit=commit,reservation_commit=reservation,
                already_published=before==commit,promotion_authority=False)
