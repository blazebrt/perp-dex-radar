"""Persistent local synthetic claims; never release/retry uncertain computation."""
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid
from tools.v9 import control_partition_execute as E, control_partition_merge as M
from tools.v9 import control_partition_plan as P, verify_control_partitions as V
from tools.v9 import verify_control_outcomes as O


def digest(value):return hashlib.sha256(E.canonical(value)).hexdigest()


def code_bindings():
    return {p.name:E.X.sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def connection(root):
    path=Path(root)/'ledger.sqlite'
    O.require(path.is_file() and not path.is_symlink(),'missing or unsafe ledger')
    db=sqlite3.connect(path,timeout=30)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA synchronous=EXTRA')
    return db


def initialize(root,source,plan,input_hash):
    root,source=Path(root).resolve(),Path(source).resolve()
    O.require(input_hash!=P.INPUT_SHA,'registered market coordination remains disabled')
    O.require(root!=source and root not in source.parents and source not in root.parents,'reservation overlaps source')
    O.require(E.canonical(P.build((source/'manifest.json').read_bytes(),input_hash))==E.canonical(plan),'plan mismatch')
    manifest=O.load((source/'manifest.json').read_bytes())
    O.require(manifest.get('provenance',{}).get('synthetic') is True,'synthetic source required')
    reservation=dict(schema='v9.a6-local-reservation/1',input_manifest_sha256=input_hash,plan=plan,
        protocol_sha256=E.X.sha(M.O.ROOT/'docs/v9/phase-a6-execution-inference.md'),
        implementation_sha256=code_bindings(),synthetic_only=True,execution_authorized=False,resource_qualified=False)
    root.mkdir(exist_ok=False)
    db=sqlite3.connect(root/'ledger.sqlite',timeout=30)
    try:
        db.execute('PRAGMA journal_mode=DELETE');db.execute('PRAGMA synchronous=EXTRA')
        db.executescript("CREATE TABLE reservation(payload BLOB NOT NULL,sha256 TEXT NOT NULL);"
                         "CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT NOT NULL,state TEXT NOT NULL,token TEXT,artifact_hash TEXT,error_type TEXT);")
        with db:
            db.execute('INSERT INTO reservation VALUES(?,?)',(E.canonical(reservation),digest(reservation)))
            db.executemany('INSERT INTO jobs VALUES(?,?,?,NULL,NULL,NULL)',
                           [(u['unit_id'],'unit','PENDING') for u in plan['units']]+[('__merge__','merge','PENDING')])
    finally:db.close()
    flush_tree(root)
    return dict(status='LOCAL_SYNTHETIC_RESERVATION_CREATED',units=len(plan['units']),execution_authorized=False)


def bound(db,source):
    rows=db.execute('SELECT payload,sha256 FROM reservation').fetchall()
    O.require(len(rows)==1,'reservation inventory')
    raw=bytes(rows[0]['payload']);r=O.load(raw)
    O.require(hashlib.sha256(raw).hexdigest()==rows[0]['sha256'],'reservation hash mismatch')
    O.require(r.get('schema')=='v9.a6-local-reservation/1' and r.get('synthetic_only') is True
              and r.get('execution_authorized') is False and r.get('resource_qualified') is False,'reservation authority')
    O.require(r['input_manifest_sha256']!=P.INPUT_SHA and O.sha(Path(source)/'manifest.json')==r['input_manifest_sha256'],'reservation input mismatch')
    O.require(r['implementation_sha256']==code_bindings() and
              r['protocol_sha256']==E.X.sha(M.O.ROOT/'docs/v9/phase-a6-execution-inference.md'),'reservation implementation changed')
    jobs=db.execute('SELECT id,kind,state FROM jobs').fetchall()
    expected={(u['unit_id'],'unit') for u in r['plan']['units']}|{('__merge__','merge')}
    O.require({(j['id'],j['kind']) for j in jobs}==expected and
              all(j['state'] in ('PENDING','CLAIMED','RECORDED','FAILED') for j in jobs),'job inventory/state mismatch')
    return r


def output(root,job):
    root=Path(root)
    O.require(not root.is_symlink(),'unsafe reservation root')
    if job=='__merge__':
        path=root/'merged'
        O.require(not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),'unsafe merge output')
        return path
    db=connection(root)
    try:
        rows=db.execute('SELECT payload FROM reservation').fetchall()
        O.require(len(rows)==1,'reservation inventory')
        ids=[u['unit_id'] for u in O.load(bytes(rows[0]['payload']))['plan']['units']]
        O.require(job in ids,'unknown unit output')
        path=root/'units'/f'{ids.index(job):05d}'
        O.require(not (root/'units').is_symlink() and not path.is_symlink()
                  and path.resolve().is_relative_to(root.resolve()),'unsafe unit output')
        return path
    finally:db.close()


def claim(root,source,job):
    db=connection(root)
    try:
        db.execute('BEGIN IMMEDIATE');reservation=bound(db,source)
        row=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        O.require(row is not None and row['state']=='PENDING','unit already claimed, failed or recorded')
        if job=='__merge__':
            O.require(db.execute("SELECT count(*) FROM jobs WHERE kind='unit' AND state!='RECORDED'").fetchone()[0]==0,'units not durably recorded')
        O.require(not output(root,job).exists(),'unclaimed output already exists')
        token=uuid.uuid4().hex
        db.execute("UPDATE jobs SET state='CLAIMED',token=? WHERE id=?",(token,job));db.commit()
        return reservation,token
    except BaseException:
        db.rollback();raise
    finally:db.close()


def flush_tree(root):
    root=Path(root)
    for p in root.rglob('*'):
        O.require(not p.is_symlink(),'unsafe retained output')
        if p.is_file():
            with p.open('r+b') as stream:os.fsync(stream.fileno())
    if os.name!='nt':
        for p in [*sorted((p for p in root.rglob('*') if p.is_dir()),reverse=True),root,root.parent]:
            fd=os.open(p,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)


def worker_bindings():
    return {p.name:E.X.sha(p) for p in (Path(E.__file__),Path(P.__file__),Path(E.A.__file__),
            Path(E.A.P.__file__),Path(E.A.E.__file__),Path(E.W.__file__))}


def record_unit(root,source,job):
    """Recover a complete retained receipt only; never recompute a claimed unit."""
    db=connection(root)
    try:
        db.execute('BEGIN IMMEDIATE');r=bound(db,source)
        row=db.execute('SELECT * FROM jobs WHERE id=? AND kind=?',(job,'unit')).fetchone()
        O.require(row is not None and row['state'] in ('CLAIMED','RECORDED'),'unit not recoverable')
        path=output(root,job)
        V.verify(source,r['plan'],[path],r['input_manifest_sha256'],worker_bindings(),r['protocol_sha256'],only_unit=job)
        flush_tree(path)
        if os.name!='nt':
            fd=os.open(Path(root),os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        sha=O.sha(path/'receipt.json')
        if row['state']=='RECORDED':O.require(row['artifact_hash']==sha,'recorded receipt changed')
        else:db.execute("UPDATE jobs SET state='RECORDED',artifact_hash=? WHERE id=?",(sha,job))
        db.commit()
        return dict(status='UNIT_RECEIPT_RECORDED',unit_id=job,sha256=sha,execution_authorized=False)
    except BaseException:
        db.rollback();raise
    finally:db.close()


def fail(root,job,token,error):
    db=connection(root)
    try:
        with db:
            db.execute("UPDATE jobs SET state='FAILED',error_type=? WHERE id=? AND token=? AND state='CLAIMED'",(type(error).__name__,job,token))
    finally:db.close()


def run_one(root,source,job,prepare,**limits):
    O.require(job!='__merge__','use merge entry point')
    r,token=claim(root,source,job)
    try:
        result=E.run_unit(source,output(root,job),r['plan'],job,prepare,r['input_manifest_sha256'],**limits)
        if result['status']!='COMPLETED_SYNTHETIC_UNIT':
            fail(root,job,token,RuntimeError('worker failed'));return result
    except BaseException as error:
        fail(root,job,token,error);raise
    # A recording interruption leaves the claim available for read-only recovery.
    return record_unit(root,source,job)


def snapshot(root):
    db=connection(root)
    try:
        return [dict(row) for row in db.execute('SELECT id,kind,state,artifact_hash,error_type FROM jobs ORDER BY id')]
    finally:db.close()


def unit_paths(db,root,r):
    rows={row['id']:row for row in db.execute("SELECT * FROM jobs WHERE kind='unit'")}
    paths=[]
    for unit in r['plan']['units']:
        row=rows[unit['unit_id']];path=output(root,unit['unit_id'])
        O.require(row['state']=='RECORDED' and O.sha(path/'receipt.json')==row['artifact_hash'],'unit retention changed')
        paths.append(path)
    return paths


def record_merge(root,source,*,load_unit=None):
    db=connection(root)
    try:
        db.execute('BEGIN IMMEDIATE');r=bound(db,source)
        row=db.execute("SELECT * FROM jobs WHERE id='__merge__'").fetchone()
        O.require(row['state'] in ('CLAIMED','RECORDED'),'merge not recoverable')
        O.require(load_unit is None or callable(load_unit),'invalid unit loader')
        if load_unit is None:
            paths=unit_paths(db,root,r)
            verified=V.verify(source,r['plan'],paths,r['input_manifest_sha256'],worker_bindings(),r['protocol_sha256'])
        else:
            verified=[]
            if not r['plan']['units']:
                V.verify(source,r['plan'],[],r['input_manifest_sha256'],worker_bindings(),r['protocol_sha256'])
            for unit in r['plan']['units']:
                recorded=db.execute("SELECT * FROM jobs WHERE id=? AND kind='unit'",(unit['unit_id'],)).fetchone()
                O.require(recorded is not None and recorded['state']=='RECORDED','units not recorded')
                with load_unit(unit,output(root,unit['unit_id'])) as path:
                    O.require(O.sha(path/'receipt.json')==recorded['artifact_hash'],'unit retention changed')
                    verified.extend(V.verify(source,r['plan'],[path],r['input_manifest_sha256'],worker_bindings(),
                                              r['protocol_sha256'],only_unit=unit['unit_id']))
        out=output(root,'__merge__');manifest=O.load((out/'manifest.json').read_bytes())
        expected={p.name:E.X.sha(p) for p in (Path(M.O.__file__),Path(E.A.__file__),Path(E.A.P.__file__),
                  Path(E.A.E.__file__),Path(M.O.S.__file__),Path(E.W.__file__),Path(E.__file__),Path(P.__file__),Path(M.__file__),Path(V.__file__))}
        bindings=dict(input_commit=M.O.INPUT_COMMIT,provenance=O.load((Path(source)/'manifest.json').read_bytes())['provenance'],
                      implementation_sha256=expected,protocol_sha256=r['protocol_sha256'])
        O.verify(out,source,r['input_manifest_sha256'],bindings)
        transport=manifest.get('partition_transport',{})
        O.require(transport.get('schema')=='v9.a6-synthetic-partition-transport/1' and transport.get('synthetic_only') is True
                  and transport.get('resource_qualified') is False and transport.get('execution_authorized') is False
                  and transport.get('plan_sha256')==digest(r['plan']) and transport.get('receipts')==
                  [dict(unit_id=v['receipt']['unit_id'],sha256=v['receipt_sha256']) for v in verified],'merge receipt binding mismatch')
        flush_tree(out);sha=O.sha(out/'manifest.json')
        if row['state']=='RECORDED':O.require(row['artifact_hash']==sha,'recorded merge changed')
        else:db.execute("UPDATE jobs SET state='RECORDED',artifact_hash=? WHERE id='__merge__'",(sha,))
        db.commit()
        return dict(status='MERGE_ACCOUNTING_RECORDED_NOT_PRICE_AUDITED',sha256=sha,execution_authorized=False)
    except BaseException:
        db.rollback();raise
    finally:db.close()


def merge_once(root,source,context):
    r,token=claim(root,source,'__merge__')
    try:
        db=connection(root)
        try:paths=unit_paths(db,root,r)
        finally:db.close()
        result=M.merge(source,output(root,'__merge__'),r['plan'],paths,context,r['input_manifest_sha256'])
        if result['status']!='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE':
            fail(root,'__merge__',token,RuntimeError('merge failed'));return result
    except BaseException as error:
        fail(root,'__merge__',token,error);raise
    return record_merge(root,source)
