"""Local synthetic Git-retention overhead, without remotes or network writes."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time


def retain(root):
    root=Path(root);checkout=root/'publication'
    checkout.mkdir()  # Never reuse or modify an existing checkout.
    started=time.perf_counter();expected={}
    for folder in ('outcomes','audit'):
        for source in sorted((root/folder).rglob('*')):
            if source.is_file():
                name=source.relative_to(root).as_posix();target=checkout/name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
                expected[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null')
    def git(*args):
        return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',
            '-c','user.name=Synthetic probe','-c','user.email=synthetic@example.invalid','-C',str(checkout),*args],stderr=subprocess.STDOUT,env=env)
    git('init','--quiet','--template=');git('add','--all');git('commit','--quiet','-m','synthetic retention probe')
    git('repack','-ad')
    for name,digest in expected.items():
        if hashlib.sha256(git('show','HEAD:'+name)).hexdigest()!=digest:raise ValueError('retained Git bytes changed')
    tracked=git('ls-tree','-r','--name-only','HEAD').decode().splitlines()
    if set(tracked)!=set(expected):raise ValueError('Git retention inventory mismatch')
    files=[p for p in checkout.rglob('*') if p.is_file()]
    return dict(status='LOCAL_SYNTHETIC_GIT_BYTES_VERIFIED',files=len(expected),
        retained_payload_bytes=sum((checkout/n).stat().st_size for n in expected),
        git_metadata_bytes=sum(p.stat().st_size for p in (checkout/'.git').rglob('*') if p.is_file()),
        checkout_logical_bytes=sum(p.stat().st_size for p in files),
        elapsed_seconds=time.perf_counter()-started,network_used=False,
        remote_reservation_verified=False,remote_publication_verified=False,promotion_authority=False)
