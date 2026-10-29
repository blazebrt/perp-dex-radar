"""Export registered A6 inputs after reservation; invoke only in a qualified job.

No CLI or workflow is installed. Exports raw Git blobs without archive filters,
refusing unsafe paths and links. Logs remain on failure; no output is overwritten.
"""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
from tools.v9 import control_outcome_publish as P

ARCHIVE='4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7'
EVIDENCE='e4c0f0d8a5926ab54dd17da9ba7309518c77f611'
ORIGINAL='ad2374fa4d25f03c204ce7c0cdbecac95cba6246'
EVIDENCE_HASH='d113242ca49f73410e00cab24ea77d64e3d039a84031c1e584f262f08137e445'
URL='https://github.com/blazebrt/perp-dex-radar.git'


def git(repo,*args,output=None):
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull,GIT_TERMINAL_PROMPT='0')
    return subprocess.run(['git','--no-replace-objects','-c','safe.directory=*','-c','core.hooksPath='+os.devnull,
        '-C',str(repo),*args],stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,env=env,check=True).stdout


def entries(raw):
    result=[];seen=set()
    for row in raw.split(b'\0'):
        if not row:continue
        meta,name=row.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode('utf-8')
        p=PurePosixPath(name)
        if mode!='100644' or kind!='blob' or not re.fullmatch('[0-9a-f]{40}',oid):raise ValueError('regular Git blobs required')
        if not name or p.is_absolute() or p.as_posix()!=name or any(part in ('.','..') or part.lower()=='.git' for part in p.parts) or any(c in name for c in ('\\',':','\n','\r','\t')):
            raise ValueError('unsafe exported path')
        if name in seen:raise ValueError('duplicate exported path')
        seen.add(name);result.append((name,oid))
    if not result:raise ValueError('empty input tree')
    return result


def blob(repo,oid,target):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as out:git(repo,'cat-file','blob',oid,output=out)
    size=target.stat().st_size;object_hash=hashlib.sha1(('blob '+str(size)+'\0').encode());digest=hashlib.sha256()
    with target.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):object_hash.update(block);digest.update(block)
    if object_hash.hexdigest()!=oid:raise ValueError('exported Git blob mismatch')
    return dict(bytes=size,sha256=digest.hexdigest())


def export(repo,commit,subtree,out,record):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('full input commit required')
    spec=commit+(':'+subtree if subtree else '')
    files=entries(git(repo,'ls-tree','-rz',spec))
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    for name,oid in files:
        info=blob(repo,oid,out/name);record(dict(stage='export',commit=commit,subtree=subtree,path=name,**info))


def prepare(repo,md,evidence,signals,log):
    paths=[Path(x).resolve() for x in (md,evidence,signals,log)]
    for i,path in enumerate(paths):
        if path.exists() or path.is_symlink():raise FileExistsError('preserve existing preparation paths')
        for other in paths[i+1:]:
            if path==other or path in other.parents or other in path.parents:raise ValueError('preparation paths overlap')
    md,evidence,signals,log=paths;log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('x',encoding='utf-8',newline='\n') as stream:
        def record(value):stream.write(json.dumps(value,sort_keys=True,allow_nan=False)+'\n');stream.flush()
        try:
            for commit in (ARCHIVE,EVIDENCE,P.INPUT_COMMIT,ORIGINAL):
                record(dict(stage='fetch_start',commit=commit))
                git(repo,'fetch','--no-tags','--no-recurse-submodules',URL,commit)
                if git(repo,'rev-parse',commit+'^{commit}').decode().strip()!=commit:raise ValueError('input commit mismatch')
                record(dict(stage='fetch_verified',commit=commit))
            export(repo,ARCHIVE,'',md,record)
            oid=git(repo,'rev-parse',EVIDENCE+':evidence.json').decode().strip()
            info=blob(repo,oid,evidence)
            if info['sha256']!=EVIDENCE_HASH:raise ValueError('phase B evidence mismatch')
            record(dict(stage='evidence_verified',commit=EVIDENCE,**info))
            export(repo,P.INPUT_COMMIT,'extraction',signals,record)
            if P.sha(signals/'manifest.json')!=P.INPUT_HASH:raise ValueError('signal manifest mismatch')
            record(dict(stage='PREPARED_PINNED_INPUTS',promotion_authority=False))
        except Exception as error:
            record(dict(stage='FAILED_PARTIAL_INPUTS_PRESERVED',error_type=type(error).__name__))
            raise
