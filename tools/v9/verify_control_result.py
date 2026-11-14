"""Verify a retained A6 Git package without fetching the market archive again."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def require(ok, message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def inspect(read, digest, names, source_read, source, run_id):
    """Injected byte readers make package tampering testable without Git/network."""
    reservation=json.loads(read('reservation.json'))
    require(reservation['source_commit']==source and reservation['run_id']==str(run_id)
            and reservation['run_attempt']=='1' and reservation['status']=='RESERVED'
            and reservation['promotion_authority'] is False,'reservation mismatch')
    protocol=sha(source_read('docs/v9/phase-a6-publication.md'))
    require(reservation['preregistration_sha256']==protocol,'reservation protocol mismatch')
    base=dict(schema='v9.a6-retained-package-verification/1',source_commit=source,actions_run=str(run_id),
              promotion_authority=False,market_archive_reloaded_locally=False,
              original_generators_reexecuted_locally=False)
    if 'attempt.json' not in names:
        return dict(base,status='INCOMPLETE_NO_ATTEMPT_RECORD',package_complete=False,retained_files=len(names))
    attempt=json.loads(read('attempt.json'))
    require(attempt['source_commit']==source and attempt['preregistration_sha256']==protocol
            and attempt['publisher_sha256']==sha(source_read('tools/v9/control_publish.py')),'attempt source mismatch')
    require(all(attempt[k] is False for k in ('promotion_authority','outcomes_computed','complete_family_population_verified')),
            'attempt authority mismatch')
    if attempt['status']=='STARTED':
        return dict(base,status='INCOMPLETE_STARTED',package_complete=False,retained_files=len(names))
    require(attempt['status'] in ('FAILED_OR_PARTIAL','EXTRACTED_AND_AUDITED_WITH_SEVEN_UNAVAILABLE'),'unknown attempt status')
    hashes=attempt['artifacts_sha256']
    require(set(names)==set(hashes)|{'attempt.json','reservation.json'},'unexpected or missing package file')
    for name,want in hashes.items():require(digest(name)==want,'artifact hash mismatch: '+name)
    base.update(all_retained_artifact_hashes_verified=True,retained_files=len(names),status=attempt['status'],
                package_complete=True,extraction_exit=attempt['extraction_exit'],audit_exit=attempt['audit_exit'])
    if attempt['status']=='FAILED_OR_PARTIAL':
        base['available_failure_records']={name:json.loads(read(name)) for name in
            ('extraction/failure.json','audit/failure.json') if name in names}
        return base
    require(attempt['extraction_exit']==0 and attempt['audit_exit']==0 and attempt['error'] is None,'success exit mismatch')
    extraction=json.loads(read('extraction/manifest.json'))
    audit=json.loads(read('audit/audit.json'))
    plan_bytes=source_read('research/v9/census_replay_plan.json')
    plan=json.loads(plan_bytes)
    require(len(plan['trials'])==199 and [r['definition'] for r in extraction['trials']]==plan['trials'],'census mismatch')
    provenance=extraction['provenance']
    binding=json.loads(source_read('research/v9/probation_evidence.json'))['inputs']
    require(provenance['archive_commit']=='4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7'
        and provenance['source_commit']=='ad2374fa4d25f03c204ce7c0cdbecac95cba6246'
        and provenance['verified_candle_files']==781 and provenance['panel_sha256']==binding['dataset_sha256']
        and provenance['phase_b_evidence_sha256']==binding['evidence_sha256'],'market input binding mismatch')
    require(provenance['plan_sha256']==sha(plan_bytes)
        and provenance['inventory_sha256']==sha(source_read('research/v9/a6_source_inventory.json')),'inventory/plan binding mismatch')
    require(provenance['protocol_sha256']==sha(source_read('docs/v9/phase-a6-extraction-driver.md')),'extraction protocol mismatch')
    require(set(provenance['code_sha256'])=={'tools/v9/evidence.py','tools/v9/archive_fetch.py','tools/research/qdata.py',
            'tools/research/qstrat.py','tools/research/qind.py','tools/research/qsim.py'},'original code roster mismatch')
    require(set(provenance['adapter_sha256'])=={'control_extract.py','control_signals.py','control_sources.py','control_features.py'},
            'adapter roster mismatch')
    for name,want in provenance['code_sha256'].items():require(sha(source_read(name))==want,'original source mismatch')
    for name,want in provenance['adapter_sha256'].items():require(sha(source_read('tools/v9/'+name))==want,'adapter mismatch')
    for name,want in audit['verifier_sha256'].items():require(sha(source_read('tools/v9/'+name))==want,'auditor mismatch')
    require(set(audit['verifier_sha256'])=={'audit_control_extraction.py','verify_control_artifacts.py','verify_control_population.py'},
            'auditor roster mismatch')
    require(audit['extraction_source_commit']==source and audit['status']=='VERIFIED_AVAILABLE_TRIALS'
        and audit['verified_trials']==192 and audit['unavailable_or_failed_trials']==7,'audit status/count mismatch')
    require(extraction['status']=='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS'
        and extraction['window']==[1588204800,1790812800],'extraction status/window mismatch')
    require(all(extraction[k] is False for k in ('promotion_authority','full_matched_authority','outcomes_computed'))
        and all(audit[k] is False for k in ('promotion_authority','full_matched_authority','complete_family_population_verified',
                                          'original_generator_mathematics_verified')),'audit/extraction authority mismatch')
    artifact=audit['artifact_verification']
    require(artifact['manifest_sha256']==sha(read('extraction/manifest.json')) and artifact['artifact_accounting_verified'] is True,
            'audit references different manifest')
    require([r['trial_id'] for r in audit['trials']]==[r['trial_id'] for r in extraction['trials']],'audit trial identities mismatch')
    total=0;available=0;hourly=0
    for trial,report in zip(extraction['trials'],audit['trials']):
        require(json.loads(read('extraction/'+trial['trial_id']+'.json'))==trial,'trial sidecar mismatch')
        if trial['definition']['archive_requirement']=='hourly':
            require(trial['status']=='UNAVAILABLE_HOURLY_POPULATION' and report['status']=='NOT_VERIFIED_UNAVAILABLE_HOURLY_POPULATION',
                    'hourly availability mismatch')
            hourly+=1
        else:
            require(trial['status']=='EXTRACTED' and report['status']=='VERIFIED','available trial mismatch')
            for key,value in trial['population'].items():require(report[key]==value,'population audit mismatch')
            require(report['generator_array_projection_verified'] is True and report['source_feature_values_verified'] is True
                and report['externally_bound_inputs_verified'] is True and report['original_generator_mathematics_verified'] is False,
                'trial verification scope mismatch')
            require(trial['retained_records']==trial['population']['retained']==sum(s['records'] for s in trial['shards']),
                    'trial shard count mismatch')
            for shard in trial['shards']:require(hashes['extraction/'+shard['path']]==shard['sha256'],'shard manifest binding mismatch')
            total+=trial['retained_records'];available+=1
    require((available,hourly)==(192,7) and artifact['retained_records']==total and artifact['extracted']==192
            and artifact['hourly_unavailable']==7 and artifact['failed']==0,'aggregate audit mismatch')
    return dict(base,verified_available_trials=available,hourly_unavailable=hourly,retained_signals=total,
                retained_audit_source_and_counts_reconciled=True)


def verify(repo,commit,source,run_id,reservation):
    def command(*args):return ['git','-c','safe.directory=*','-C',str(repo),*args]
    def raw(name,ref=commit):return subprocess.check_output(command('show',ref+':'+name))
    require(subprocess.check_output(command('rev-parse',commit+'^')).decode().strip()==reservation,'result parent is not reservation')
    names=subprocess.check_output(command('ls-tree','-r','--name-only',commit)).decode().splitlines()
    def digest(name):
        process=subprocess.Popen(command('show',commit+':'+name),stdout=subprocess.PIPE)
        h=hashlib.sha256()
        for block in iter(lambda:process.stdout.read(1024*1024),b''):h.update(block)
        process.stdout.close();require(process.wait()==0,'unable to read retained blob')
        return h.hexdigest()
    result=inspect(raw,digest,names,lambda name:raw(name,source),source,run_id)
    result.update(result_commit=commit,reservation_commit=reservation)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','commit','source','run-id','reservation','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=verify(args.repo,args.commit,args.source,args.run_id,args.reservation)
    with Path(args.out).open('x',encoding='utf8',newline='\n') as stream:stream.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
