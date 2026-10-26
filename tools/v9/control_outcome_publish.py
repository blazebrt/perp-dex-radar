"""Retain a reserved A6 outcome attempt and its separate audit, including failure."""
import argparse
import json
from pathlib import Path
import re
import sys
import shutil

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.v9.control_publish import command,sha,write
from tools.v9 import control_resource_gate as G

INPUT_COMMIT='eb785a908dce572958336649291b8feeb4ee9575'
INPUT_HASH='ea45d68a337ab682406748f2b94c833a5ca00b8e495aa7bdd38fe9b1f5d02a5e'
PROTOCOL='docs/v9/phase-a6-execution-inference.md'
PUBLICATION='docs/v9/phase-a6-outcome-publication.md'


def retain(md,evidence,signals,out,source_commit,reservation,execute=command,qualification=None,capacity=None,preparation_log=None):
    out=Path(out).resolve()
    if out.exists():raise FileExistsError('preserve previous outcome attempt')
    if not re.fullmatch('[0-9a-f]{40}',source_commit):raise ValueError('full outcome source commit required')
    extra=((qualification,) if qualification is not None else ())+((preparation_log,) if preparation_log is not None else ())
    if preparation_log is not None and (Path(preparation_log).is_symlink() or not Path(preparation_log).is_file()):
        raise ValueError('regular preparation log required')
    for path in (md,evidence,signals,reservation)+extra:
        other=Path(path).resolve()
        if other==out or out in other.parents or other in out.parents:raise ValueError('attempt overlaps inputs')
    raw=Path(reservation).read_bytes();reserved=json.loads(raw)
    required=dict(status='RESERVED',source_commit=source_commit,run_attempt='1',
        input_commit=INPUT_COMMIT,input_manifest_sha256=INPUT_HASH,
        execution_protocol_sha256=sha(ROOT/PROTOCOL),publication_protocol_sha256=sha(ROOT/PUBLICATION),
        results_branch='evidence-a6-outcome-results',resource_gate_sha256=sha(Path(G.__file__)),promotion_authority=False)
    if any(reserved.get(k)!=v for k,v in required.items()) or not re.fullmatch('[0-9]+',str(reserved.get('run_id',''))):
        raise ValueError('invalid outcome reservation')
    if not re.fullmatch('[0-9a-f]{64}',str(reserved.get('resource_qualification_sha256',''))):
        raise ValueError('resource qualification must be pinned in reservation')
    out.mkdir(parents=True)
    (out/'reservation.json').write_bytes(raw)
    if preparation_log is not None:shutil.copyfile(preparation_log,out/'input-preparation.log')
    result=dict(schema='v9.a6-outcome-attempt/1',status='STARTED',source_commit=source_commit,
        input_commit=INPUT_COMMIT,input_manifest_sha256=INPUT_HASH,run_id=str(reserved['run_id']),run_attempt='1',
        reservation_sha256=sha(out/'reservation.json'),execution_protocol_sha256=required['execution_protocol_sha256'],
        publication_protocol_sha256=required['publication_protocol_sha256'],publisher_sha256=sha(Path(__file__)),
        outcome_exit=None,audit_exit=None,error=None,net_inference_available=False,
        full_matched_authority=False,promotion_authority=False)
    write(out/'attempt.json',result)
    try:
        if qualification is None or capacity is None:raise ValueError('resource qualification and live capacity required')
        resource_raw=Path(qualification).read_bytes()
        (out/'resource-qualification.json').write_bytes(resource_raw)
        preflight=G.verify(resource_raw,reserved['resource_qualification_sha256'],source_commit,INPUT_HASH,
                           required['execution_protocol_sha256'],capacity)
        write(out/'resource-preflight.json',preflight)
        if sha(Path(signals)/'manifest.json')!=INPUT_HASH:raise ValueError('unregistered signal inventory')
        result['outcome_exit']=execute(['tools/v9/control_outcomes.py','--md',str(Path(md).resolve()),
            '--phase-b-evidence',str(Path(evidence).resolve()),'--signals',str(Path(signals).resolve()),
            '--out',str(out/'outcomes')],out/'outcomes.log')
        if (out/'outcomes/manifest.json').is_file():
            result['audit_exit']=execute(['tools/v9/audit_control_outcomes.py','--md',str(Path(md).resolve()),
                '--evidence',str(Path(evidence).resolve()),'--source-commit',source_commit,
                '--signals',str(Path(signals).resolve()),'--directory',str(out/'outcomes'),
                '--out',str(out/'audit')],out/'audit.log')
        result['status']='FAILED_OR_PARTIAL'
        if result['outcome_exit']==0 and result['audit_exit']==0:
            manifest=json.loads((out/'outcomes/manifest.json').read_bytes())
            audit=json.loads((out/'audit/audit.json').read_bytes())
            ok=(manifest['status']=='COMPLETED_PRICE_DIAGNOSTICS_NET_UNAVAILABLE' and
                manifest['processed_signals']==4263580 and len(manifest['completed_trials'])==199 and
                sum(r['status']=='UNAVAILABLE_HOURLY_POPULATION' for r in manifest['completed_trials'])==7 and
                audit['status']=='VERIFIED_REGISTERED_PRICE_DIAGNOSTICS' and
                audit['signals']==audit['candidate_paths']==audit['accounting']['signals']==audit['statistics']['signals']==4263580 and
                audit['accounting']['sides']==398 and audit['input_manifest_sha256']==INPUT_HASH and
                audit['outcome_manifest_sha256']==sha(out/'outcomes/manifest.json') and
                audit['source_bound_selection_verified'] is True and audit['source_bound_price_paths_verified'] is True and
                all(audit['statistics'][k] is True for k in ('descriptive_statistics_verified','day_aggregates_verified','control_reuse_verified')) and
                all(audit[k] is False for k in ('net_inference_available','full_matched_authority','promotion_authority')))
            if ok:result['status']='PRICE_DIAGNOSTICS_INDEPENDENTLY_AUDITED_NET_UNAVAILABLE'
    except Exception as error:
        result.update(status='FAILED_OR_PARTIAL',error=dict(type=type(error).__name__,message=str(error)))
    result['artifacts_sha256']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
                              if p.is_file() and p!=out/'attempt.json'}
    write(out/'attempt.json',result)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('md','evidence','signals','out','source-commit','reservation'):ap.add_argument('--'+name,required=True)
    ap.add_argument('--qualification',required=True);ap.add_argument('--runner-profile',required=True)
    ap.add_argument('--remaining-seconds',required=True,type=int)
    args=ap.parse_args()
    print(retain(args.md,args.evidence,args.signals,args.out,args.source_commit,args.reservation,qualification=args.qualification,
                 capacity=G.live_capacity(Path(args.out).resolve().parent,args.runner_profile,args.remaining_seconds))['status'])
    # Outer workflow must durably publish before reporting failed/partial status.
