"""Small synthetic Actions artifact handoff; no market input, secrets or remote Git writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9 import control_partition_transport as T, control_partition_objects as B
from tests import test_v9_control_extract as F, test_v9_control_outcomes as Outcomes

MAX_TRANSFER=8*1024*1024


def environment(commit,run,attempt):
    T.C.O.require(re.fullmatch('[0-9a-f]{40}',commit) and run.isdigit() and attempt.isdigit(),'invalid hosted identity')
    boot=Path('/proc/sys/kernel/random/boot_id')
    return dict(source_commit=commit,run_id=run,run_attempt=attempt,
                boot_sha256=hashlib.sha256(boot.read_bytes()).hexdigest() if boot.is_file() else None,
                runner_os=os.environ.get('RUNNER_OS'),runner_arch=os.environ.get('RUNNER_ARCH'))


def file_inventory(root):
    hashes=T.inventory(root)
    result={p:dict(sha256=h,bytes=(Path(root)/p).stat().st_size) for p,h in hashes.items()}
    T.C.O.require(sum(r['bytes'] for r in result.values())<=MAX_TRANSFER,'transfer exceeds synthetic limit')
    return result


def produce(out,identity):
    out=Path(out);out.mkdir(exist_ok=False)
    transfer=out/'transfer';transfer.mkdir();scratch=out/'scratch';scratch.mkdir()
    fixture=F.Extraction();fixture.setUp();context=fixture.context(count=5)
    source=transfer/'signals';T.C.E.X.extract(source,lambda:context)
    digest=T.C.O.sha(source/'manifest.json');plan=T.C.P.build((source/'manifest.json').read_bytes(),digest)
    remote=scratch/'shared.git';remote.mkdir();T.git(remote,'init','--bare','-q')
    (transfer/'objects').mkdir();objects=B.LocalObjects((transfer/'objects').resolve())
    T.initialize(remote.resolve(),scratch/'initial',source,plan,digest,objects=objects)
    class Adapter:
        calls=0
        match=Outcomes.Outcomes.match
    units=[u['unit_id'] for u in plan['units']]
    T.C.O.require(len(units)==4,'fixed synthetic fixture changed')
    T.run_one(remote.resolve(),scratch/'complete',source,units[0],lambda:(context,Adapter()),objects=objects)
    def failed():raise RuntimeError('synthetic retained failure')
    T.run_one(remote.resolve(),scratch/'failed',source,units[1],failed,objects=objects)
    T.claim(remote.resolve(),scratch/'uncertain',source,units[2],objects=objects)
    tip=T.git(remote,'rev-parse','refs/heads/'+T.BRANCH).decode().strip()
    T.git(remote,'bundle','create',str((transfer/'state.bundle').resolve()),'refs/heads/'+T.BRANCH)
    states={units[0]:'RECORDED',units[1]:'FAILED',units[2]:'CLAIMED',units[3]:'PENDING','__merge__':'PENDING'}
    manifest=dict(schema='v9.a6-hosted-transfer/1',identity=identity,tip=tip,input_sha256=digest,states=states,
        files=file_inventory(transfer),synthetic_only=True,resource_qualified=False,execution_authorized=False)
    raw=T.C.E.canonical(manifest);(transfer/'transfer.json').write_bytes(raw)
    # Only transfer survives. It contains no original worker checkout or open SQLite database.
    shutil.rmtree(scratch)
    return hashlib.sha256(raw).hexdigest()


def recover(transfer,out,expected_digest,identity,*,require_distinct_boot=True):
    transfer=Path(transfer);out=Path(out)
    manifest_path=T.C.O.safe(transfer,'transfer.json')
    T.C.O.require(manifest_path.stat().st_size<=1024*1024,'transfer manifest limit')
    raw=manifest_path.read_bytes()
    T.C.O.require(hashlib.sha256(raw).hexdigest()==expected_digest,'transfer manifest mismatch')
    manifest=T.C.O.load(raw)
    T.C.O.require(manifest.get('schema')=='v9.a6-hosted-transfer/1' and manifest.get('synthetic_only') is True
                  and manifest.get('resource_qualified') is False and manifest.get('execution_authorized') is False,'transfer authority/schema')
    producer=manifest['identity']
    T.C.O.require(all(producer[k]==identity[k] for k in ('source_commit','run_id','run_attempt')),'hosted identity mismatch')
    if require_distinct_boot:
        T.C.O.require(producer['boot_sha256'] and identity['boot_sha256'] and producer['boot_sha256']!=identity['boot_sha256'],
                      'separate runner boot not demonstrated')
    actual=file_inventory(transfer);actual.pop('transfer.json')
    T.C.O.require(actual==manifest['files'],'transfer inventory/hash mismatch')
    out.mkdir(exist_ok=False);remote=out/'restored.git';remote.mkdir();T.git(remote,'init','--bare','-q')
    T.git(remote,'fetch',str((transfer/'state.bundle').resolve()),'refs/heads/'+T.BRANCH+':refs/heads/'+T.BRANCH)
    T.C.O.require(T.git(remote,'rev-parse','refs/heads/'+T.BRANCH).decode().strip()==manifest['tip'],'restored head mismatch')
    source=transfer/'signals';T.C.O.require(T.C.O.sha(source/'manifest.json')==manifest['input_sha256'],'source binding mismatch')
    objects=B.LocalObjects((transfer/'objects').resolve())
    with patch.object(T.C.E,'run_unit',side_effect=AssertionError('recomputation forbidden')), \
         patch.object(T.C.M,'merge',side_effect=AssertionError('reconstruction forbidden')):
        report=T.verify_retained(remote.resolve(),out/'verified',source,objects=objects)
        states={r['id']:r['state'] for r in report['jobs']}
        T.C.O.require(states==manifest['states'],'recovered states mismatch')
        refused=0
        for i,(job,state) in enumerate(states.items()):
            if state not in ('RECORDED','FAILED','CLAIMED'):continue
            try:T.run_one(remote.resolve(),out/f'refused-{i}',source,job,lambda:None,objects=objects)
            except ValueError:refused+=1
            else:raise ValueError('terminal/uncertain unit restarted')
    T.C.O.require(refused==3,'retry refusal coverage')
    result=dict(schema='v9.a6-hosted-recovery/1',status='SYNTHETIC_TRANSFER_RECOVERY_VERIFIED',
        transfer_manifest_sha256=expected_digest,producer=producer,consumer=identity,states=states,
        refused_recomputations=refused,transferred_bytes=sum(r['bytes'] for r in actual.values()),
        independent_boot_verified=bool(require_distinct_boot),synthetic_only=True,
        resource_qualified=False,long_term_retention_qualified=False,execution_authorized=False)
    (out/'report.json').write_bytes(T.C.E.canonical(result))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['produce','recover']);parser.add_argument('--out',required=True)
    parser.add_argument('--transfer');parser.add_argument('--expected-digest')
    args=parser.parse_args()
    identity=environment(os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'])
    if args.mode=='produce':
        digest=produce(args.out,identity)
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as stream:stream.write('transfer_digest='+digest+'\n')
        print('Synthetic transfer manifest SHA-256: '+digest)
    else:
        result=recover(args.transfer,args.out,args.expected_digest,identity)
        print('A6_HOSTED_RECOVERY_REPORT='+json.dumps(result,sort_keys=True,separators=(',',':')))
