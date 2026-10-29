"""Prepare a single reservation-child retention commit; never push or move refs.

The caller must freshly observe the remote tip and publish with a normal
fast-forward update. This helper cannot establish remote durability or prevent
a concurrent writer; a changed tip requires inspection, not another study run.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
from tools.v9.record_control_outcome import verify_ancestry


def prepare(repo,reservation_commit,observed_tip,attempt,identity):
    if not re.fullmatch('[0-9a-f]{40}',reservation_commit):raise ValueError('full reservation commit required')
    if observed_tip!=reservation_commit:raise ValueError('reservation tip changed; inspect without rerunning')
    if len(identity)!=2 or not all(isinstance(v,str) and v.strip() and '\n' not in v and '\r' not in v for v in identity):
        raise ValueError('explicit commit identity required')
    repo=Path(repo).resolve();attempt=Path(attempt)
    if attempt.is_symlink() or not attempt.is_dir():raise ValueError('regular attempt directory required')
    attempt=attempt.resolve()
    # Keep the private index outside both the repository and retained payload.
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,
        GIT_AUTHOR_NAME=identity[0],GIT_AUTHOR_EMAIL=identity[1],
        GIT_COMMITTER_NAME=identity[0],GIT_COMMITTER_EMAIL=identity[1])
    def git(*args,data=None):
        return subprocess.run(['git','--no-replace-objects','-c','safe.directory=*',
            '-c','core.hooksPath='+os.devnull,'-c','commit.gpgsign=false','-C',str(repo),*args],
            input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,check=True).stdout
    root,raw=verify_ancestry(git,reservation_commit)
    if root!=reservation_commit:raise ValueError('retention requires the original reservation root')
    if (attempt/'reservation.json').is_symlink() or (attempt/'reservation.json').read_bytes()!=raw:
        raise ValueError('attempt reservation differs from durable reservation')
    entries=[]
    for directory,dirs,files in os.walk(attempt,followlinks=False):
        for name in dirs+files:
            path=Path(directory)/name
            if path.is_symlink():raise ValueError('symlink payload refused')
        for name in files:
            path=Path(directory)/name
            if not path.is_file():raise ValueError('nonregular payload refused')
            relative=path.relative_to(attempt).as_posix()
            if any(c in relative for c in ('\\',':','\n','\r','\t')) or any(part.lower()=='.git' for part in path.relative_to(attempt).parts):
                raise ValueError('unsafe payload path')
            entries.append((relative,path))
    with tempfile.TemporaryDirectory(prefix='a6-retention-index-') as scratch:
        env['GIT_INDEX_FILE']=str(Path(scratch)/'index')
        git('read-tree','--empty')
        records=[]
        for name,path in sorted(entries):
            # Git hashes bytes directly: attributes/filters cannot rewrite evidence.
            blob=git('hash-object','-w','--no-filters',str(path)).decode().strip()
            records.append(('100644 '+blob+'\t'+name).encode()+b'\0')
        git('update-index','-z','--index-info',data=b''.join(records))
        tree=git('write-tree').decode().strip()
        if git('show',tree+':reservation.json')!=raw:raise ValueError('reservation changed during packaging')
        commit=git('commit-tree',tree,'-p',reservation_commit,'-m','Retain registered A6 outcome attempt').decode().strip()
        verify_ancestry(git,commit)
    return dict(commit=commit,reservation_commit=reservation_commit,files=len(entries),
        remote_publication_verified=False,promotion_authority=False)
