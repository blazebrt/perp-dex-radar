"""Build an A6 history record from a retained reservation/attempt, without reruns."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import subprocess

INPUT='eb785a908dce572958336649291b8feeb4ee9575'
INPUT_HASH='ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e'
DATASET='cd4651ebb5d6a9e4f0561ef578cd3a4f0fbd1e0dddf47b8743dc6acca2994ed2'
EXECUTION='docs/v9/phase-a6-execution-inference.md'
PUBLICATION='docs/v9/phase-a6-outcome-publication.md'


def check(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def inspect(read,digest,names,source_read,result_commit,reservation_commit,reservation_bytes,ran_at):
    check(all(re.fullmatch('[0-9a-f]{40}',s) for s in (result_commit,reservation_commit)),'invalid retained commit')
    reserved_raw=read('reservation.json');reserved=json.loads(reserved_raw)
    check(reserved_raw==reservation_bytes,'reservation changed after creation')
    source=reserved['source_commit'];check(re.fullmatch('[0-9a-f]{40}',source),'invalid source commit')
    protocols={p:sha(source_read(p)) for p in (EXECUTION,PUBLICATION,
        'docs/v9/phase-a6-control-design.md','docs/v9/phase-a6-feature-quality.md',
        'docs/v9/phase-a6-source-binding.md','docs/v9/phase-a6-signal-population.md',
        'docs/v9/phase-a6-extraction-driver.md','docs/v9/phase-a6-independent-audit.md')}
    check(reserved['status']=='RESERVED' and reserved['run_attempt']=='1' and
          str(reserved['run_id']).isdigit() and reserved['input_commit']==INPUT and reserved['input_manifest_sha256']==INPUT_HASH and
          reserved['execution_protocol_sha256']==protocols[EXECUTION] and reserved['publication_protocol_sha256']==protocols[PUBLICATION]
          and reserved['results_branch']=='evidence-a6-outcome-results' and reserved['promotion_authority'] is False,
          'reservation binding mismatch')
    hashes={}
    check(len(set(names))==len(names),'duplicate retained paths')
    for name in names:
        p=PurePosixPath(name)
        check(p.as_posix()==name and not p.is_absolute() and not any(x in ('.','..') for x in p.parts) and
              '\\' not in name and ':' not in name,'unsafe retained path')
        hashes[name]=digest(name)
    check('reservation.json' in hashes and hashes['reservation.json']==sha(reserved_raw),'reservation hash mismatch')
    status='INCOMPLETE_RESERVED';evidence='reservation.json';report='reservation.json';trades=None
    if 'attempt.json' in hashes:
        evidence='attempt.json';attempt=json.loads(read(evidence))
        check(attempt['schema']=='v9.a6-outcome-attempt/1' and attempt['source_commit']==source and
              attempt['input_commit']==INPUT and attempt['input_manifest_sha256']==INPUT_HASH and
              attempt['run_id']==str(reserved['run_id']) and attempt['run_attempt']=='1' and
              attempt['reservation_sha256']==sha(reserved_raw) and attempt['execution_protocol_sha256']==protocols[EXECUTION] and
              attempt['publication_protocol_sha256']==protocols[PUBLICATION] and
              attempt['publisher_sha256']==sha(source_read('tools/v9/control_outcome_publish.py')) and
              all(attempt[k] is False for k in ('net_inference_available','full_matched_authority','promotion_authority')),
              'attempt binding/authority mismatch')
        status=attempt['status']
        check(status in ('STARTED','FAILED_OR_PARTIAL','PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE'),'unknown attempt state')
        if status!='STARTED':
            check(attempt['artifacts_sha256']=={n:h for n,h in hashes.items() if n!='attempt.json'},'attempt artifact inventory mismatch')
        report=next((p for p in ('audit/audit.json','audit/failure.json','outcomes/manifest.json') if p in hashes),'attempt.json')
        trades='outcomes/manifest.json' if 'outcomes/manifest.json' in hashes else None
        if status=='PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE':
            check(attempt['outcome_exit']==0 and attempt['audit_exit']==0 and report=='audit/audit.json' and trades is not None,
                  'successful attempt lacks results')
            audit=json.loads(read(report))
            check(audit['status']=='VERIFIED_REGISTERED_PRICE_DIAGNOSTICS' and
                  audit['outcome_manifest_sha256']==hashes[trades] and audit['input_manifest_sha256']==INPUT_HASH and
                  audit['promotion_authority'] is False and audit['net_inference_available'] is False,'audit binding mismatch')
    return dict(schema='v9.evidence-runs/1',study='A6',results_branch='evidence-a6-outcome-results',
        results_commit=result_commit,source_branch='v9/census-evidence',source_commit=source,ran_at=ran_at,
        ran_at_basis='RETAINED_COMMIT_TIME_NOT_EXECUTION_START',evidence_schema='v9.a6-outcome-history/1',
        dataset_sha256=DATASET,files=dict(evidence=hashes[evidence],report=hashes[report],trades=hashes[trades] if trades else None),
        file_paths=dict(evidence=evidence,report=report,trades=trades),retained_files_sha256=hashes,
        status=status,confirmed=[],preregistration=EXECUTION,preregistration_sha256=protocols[EXECUTION],
        preregistrations_sha256=protocols,extra_inputs=dict(input_commit=INPUT,input_manifest_sha256=INPUT_HASH,
            reservation_commit=reservation_commit,run_id=str(reserved['run_id']),run_attempt='1'),
        net_inference_available=False,full_matched_authority=False,promotion_authority=False,
        retained_result_independently_verified=False)


def build(repo,ref):
    def git(*args):return subprocess.check_output(['git','-c','safe.directory=*','-C',str(repo),*args])
    result=git('rev-parse',ref).decode().strip()
    roots=git('rev-list','--max-parents=0',result).decode().split()
    check(len(roots)==1,'ambiguous reservation ancestry')
    reservation=roots[0]
    read=lambda name:git('show',result+':'+name)
    raw=read('reservation.json');source=json.loads(raw)['source_commit']
    names=git('ls-tree','-r','--name-only',result).decode().splitlines()
    def digest(name):
        process=subprocess.Popen(['git','-c','safe.directory=*','-C',str(repo),'show',result+':'+name],stdout=subprocess.PIPE)
        h=hashlib.sha256()
        try:
            for block in iter(lambda:process.stdout.read(1048576),b''):h.update(block)
        finally:process.stdout.close()
        check(process.wait()==0,'retained blob read failed')
        return h.hexdigest()
    return inspect(read,digest,names,lambda name:git('show',source+':'+name),result,reservation,
                   git('show',reservation+':reservation.json'),git('show','-s','--format=%cI',result).decode().strip())
