"""Synthetic local-bare-Git transport: shared claims, retained failures, recovery.

No network URL, market activation, automatic computation retry or force push.
Git ref updates arbitrate claims; SQLite is only the checked-out state format.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
from tools.v9 import control_partition_coordinator as C
from tools.v9 import control_partition_objects as B

BRANCH='synthetic-reservation'
MAX_BYTES=512*1024*1024


def git(directory,*args):
    return subprocess.check_output(['git','-c','safe.directory=*','-c','core.autocrlf=false',
        '-c','commit.gpgsign=false','-c','user.name=Synthetic transport',
        '-c','user.email=synthetic@example.invalid','-C',str(directory),*args],stderr=subprocess.PIPE)


def remote_path(remote):
    # Deliberately no HTTP/SSH/URL support or implicit creation of a shared store.
    path=Path(remote)
    C.O.require(path.is_absolute() and path.is_dir() and not path.is_symlink(),'local bare repository required')
    C.O.require(git(path,'rev-parse','--is-bare-repository').strip()==b'true','bare repository required')
    return path.resolve()


def checkout(remote,destination,*,empty=False):
    remote=remote_path(remote);destination=Path(destination).resolve()
    C.O.require(not destination.exists() and remote not in destination.parents
                and destination not in remote.parents,'new separate checkout required')
    destination.mkdir()
    git(destination,'init','-q')
    git(destination,'remote','add','origin',str(remote))
    if not empty:
        git(destination,'fetch','-q','origin','refs/heads/'+BRANCH)
        git(destination,'checkout','-q','--detach','FETCH_HEAD')
    return destination


def push(workspace,message):
    git(workspace,'add','--','reservation')
    git(workspace,'commit','-qm',message)
    # Sibling commits cannot fast-forward the shared ref. Never force or rebase a claim.
    git(workspace,'push','--porcelain','origin','HEAD:refs/heads/'+BRANCH)
    return git(workspace,'rev-parse','HEAD').decode().strip()


def mode(root,objects):
    path=Path(root)/'object-transport.json'
    if path.exists():
        C.O.require(not path.is_symlink() and C.O.load(path.read_bytes())==dict(schema='v9.a6-object-transport/1'),
                    'object transport configuration')
        C.O.require(isinstance(objects,B.LocalObjects),'local object store required')
        other=objects.root;root=Path(root).resolve()
        C.O.require(other!=root and root not in other.parents and other not in root.parents,'object store overlaps reservation')
    else:C.O.require(objects is None,'reservation is not object-backed')


def reference(root,job):
    output=C.output(root,job)
    name='merge' if job=='__merge__' else output.name
    return Path(root)/'object-refs'/(name+'.json')


def hydrate(root,job,objects):
    mode(root,objects)
    if objects is None:return
    ref=reference(root,job);out=C.output(root,job)
    if ref.exists():
        C.O.require(not ref.is_symlink(),'unsafe object reference')
        B.restore(C.O.load(ref.read_bytes()),objects,out)


def offload(root,job,objects):
    out=C.output(root,job)
    if out.exists():
        bundle=B.pack(out,objects)
        C.O.require({r['path']:r['sha256'] for r in bundle['files']}==inventory(out),'output changed during offload')
        ref=reference(root,job);ref.parent.mkdir(exist_ok=True)
        with ref.open('xb') as stream:stream.write(C.E.canonical(bundle))
        shutil.rmtree(out)


def hydrate_units(root,reservation,objects):
    if objects is not None:
        for unit in reservation['plan']['units']:hydrate(root,unit['unit_id'],objects)


def remove_hydrated(root,reservation):
    # Only validated output paths in the fresh, disposable publication checkout.
    for job in [u['unit_id'] for u in reservation['plan']['units']]+['__merge__']:
        out=C.output(root,job)
        if out.exists():shutil.rmtree(out)


def initialize(remote,workspace,source,plan,input_hash,*,objects=None):
    remote=remote_path(remote)
    C.O.require(not git(remote,'for-each-ref').strip(),'new empty shared store required')
    workspace=checkout(remote,workspace,empty=True)
    C.initialize(workspace/'reservation',source,plan,input_hash)
    if objects is not None:
        (workspace/'reservation/object-transport.json').write_bytes(C.E.canonical(dict(schema='v9.a6-object-transport/1')))
    mode(workspace/'reservation',objects)
    return push(workspace,'Initialize synthetic reservation')


def claim(remote,workspace,source,job,*,objects=None):
    workspace=checkout(remote,workspace)
    mode(workspace/'reservation',objects)
    reservation,token=C.claim(workspace/'reservation',source,job)
    commit=push(workspace,'Claim synthetic work')
    # An ambiguous/failed push raises before callers can invoke computation.
    return reservation,token,commit


def row(root,source,job):
    db=C.connection(root)
    try:
        reservation=C.bound(db,source)
        result=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        C.O.require(result is not None,'unknown job')
        return reservation,dict(result)
    finally:db.close()


def inventory(path):
    path=Path(path)
    C.O.require(path.is_dir() and not path.is_symlink(),'regular retained directory required')
    result={};total=0
    for p in sorted(path.rglob('*')):
        C.O.require(not p.is_symlink(),'unsafe retained file')
        if p.is_dir():continue
        C.O.require(p.is_file(),'regular retained file required')
        total+=p.stat().st_size
        C.O.require(total<=MAX_BYTES,'synthetic transport byte limit')
        result[p.relative_to(path).as_posix()]=C.O.sha(p)
    return result


def publish(remote,workspace,source,job,token,*,failed=False,objects=None):
    """Retry only retention bookkeeping; never invoke a worker or merge.

    Every attempt starts at the latest shared head. Concurrent unrelated claims or
    records are preserved. An accepted push with a lost response is idempotent.
    """
    root=Path(workspace)/'reservation'
    mode(root,objects)
    reservation,local=row(root,source,job)
    C.O.require(local['token']==token and local['state']=='CLAIMED','local claim token mismatch')
    artifact=C.output(root,job)
    files=inventory(artifact) if artifact.exists() else None
    C.O.require(failed or files is not None,'missing completed output')
    wanted='FAILED' if failed else 'RECORDED'
    last=None
    for _ in range(4):
        with tempfile.TemporaryDirectory(prefix='v9-transport-') as temporary:
            current=checkout(remote,Path(temporary)/'checkout');target=current/'reservation'
            mode(target,objects)
            shared,record=row(target,source,job)
            C.O.require(C.digest(shared)==C.digest(reservation),'shared reservation mismatch')
            C.O.require(record['token']==token,'shared claim token mismatch')
            destination=C.output(target,job)
            if record['state']==wanted:
                hydrate(target,job,objects)
                retained=inventory(destination) if destination.exists() else None
                C.O.require(retained==files,'retained terminal output differs')
                return git(current,'rev-parse','HEAD').decode().strip()
            C.O.require(record['state']=='CLAIMED','shared job cannot transition')
            C.O.require(not destination.exists(),'unrecorded shared output exists')
            if files is not None:
                shutil.copytree(artifact,destination)
                C.O.require(inventory(destination)==files and inventory(artifact)==files,'output changed during transfer')
                C.flush_tree(destination)
            if failed:
                C.fail(target,job,token,RuntimeError('retained worker failure'))
            elif job=='__merge__':
                hydrate_units(target,shared,objects)
                C.record_merge(target,source)
            else:C.record_unit(target,source,job)
            if objects is not None:
                offload(target,job,objects)
                remove_hydrated(target,shared)
            try:return push(current,'Retain synthetic result')
            except subprocess.CalledProcessError as error:last=error
    # Original workspace remains intact for an explicit later retention recovery.
    raise last


def run_one(remote,workspace,source,job,prepare,*,objects=None,**limits):
    C.O.require(job!='__merge__','use merge entry point')
    r,token,_=claim(remote,workspace,source,job,objects=objects)
    out=C.output(Path(workspace)/'reservation',job)
    try:
        result=C.E.run_unit(source,out,r['plan'],job,prepare,r['input_manifest_sha256'],**limits)
    except BaseException:
        publish(remote,workspace,source,job,token,failed=True,objects=objects)
        raise
    failed=result['status']!='COMPLETED_SYNTHETIC_UNIT'
    commit=publish(remote,workspace,source,job,token,failed=failed,objects=objects)
    return dict(status='RETAINED_FAILED' if failed else 'RETAINED_SYNTHETIC_UNIT',commit=commit,execution_authorized=False)


def merge_once(remote,workspace,source,context,*,objects=None):
    r,token,_=claim(remote,workspace,source,'__merge__',objects=objects)
    root=Path(workspace)/'reservation'
    try:
        hydrate_units(root,r,objects)
        units=[C.output(root,u['unit_id']) for u in r['plan']['units']]
        result=C.M.merge(source,C.output(root,'__merge__'),r['plan'],units,context,r['input_manifest_sha256'])
    except BaseException:
        publish(remote,workspace,source,'__merge__',token,failed=True,objects=objects)
        raise
    failed=result['status']!='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE'
    commit=publish(remote,workspace,source,'__merge__',token,failed=failed,objects=objects)
    return dict(status='RETAINED_FAILED' if failed else 'RETAINED_MERGE_NOT_PRICE_AUDITED',commit=commit,execution_authorized=False)


def verify_retained(remote,workspace,source,*,objects=None):
    """Independent checkout verification; does not schedule or recompute anything."""
    workspace=checkout(remote,workspace);root=workspace/'reservation'
    mode(root,objects)
    db=C.connection(root)
    try:C.bound(db,source)
    finally:db.close()
    rows=C.snapshot(root)
    for item in rows:
        hydrate(root,item['id'],objects)
        if item['kind']=='unit' and item['state']=='RECORDED':C.record_unit(root,source,item['id'])
    if next(item for item in rows if item['kind']=='merge')['state']=='RECORDED':C.record_merge(root,source)
    return dict(status='RETAINED_SYNTHETIC_STATE_VERIFIED',jobs=rows,
                commit=git(workspace,'rev-parse','HEAD').decode().strip(),execution_authorized=False)
