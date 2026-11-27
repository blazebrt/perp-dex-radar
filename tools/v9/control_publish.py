"""Retain one A6 extraction/audit attempt, including failed and partial files."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL='docs/v9/phase-a6-publication.md'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(path,value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('x',encoding='utf8',newline='\n') as stream:
        stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)


def command(args, log):
    with log.open('xb') as stream:
        return subprocess.run([sys.executable,*args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT).returncode


def retain(md,evidence,out,source_commit,execute=command):
    out=Path(out).resolve()
    if out.exists():raise FileExistsError('preserve earlier attempt')
    if not re.fullmatch('[0-9a-f]{40}',source_commit):raise ValueError('full extraction source commit required')
    out.mkdir(parents=True)
    result=dict(schema='v9.a6-attempt/1',status='STARTED',source_commit=source_commit,
        preregistration_sha256=sha(ROOT/PROTOCOL),publisher_sha256=sha(Path(__file__)),
        extraction_exit=None,audit_exit=None,error=None,promotion_authority=False,
        outcomes_computed=False,complete_family_population_verified=False)
    write(out/'attempt.json',result)
    try:
        result['extraction_exit']=execute(['tools/v9/control_extract.py','--md',str(Path(md).resolve()),
            '--phase-b-evidence',str(Path(evidence).resolve()),'--out',str(out/'extraction')],out/'extraction.log')
        if (out/'extraction/manifest.json').is_file():
            result['audit_exit']=execute(['tools/v9/audit_control_extraction.py','--md',str(Path(md).resolve()),
                '--evidence',str(Path(evidence).resolve()),'--source-commit',source_commit,
                '--directory',str(out/'extraction'),'--out',str(out/'audit')],out/'audit.log')
        result['status']='FAILED_OR_PARTIAL'
        if result['extraction_exit']==0 and result['audit_exit']==0:
            extraction=json.loads((out/'extraction/manifest.json').read_bytes())
            audit=json.loads((out/'audit/audit.json').read_bytes())
            if (extraction['status']=='COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS'
                and audit['status']=='VERIFIED_AVAILABLE_TRIALS' and audit['verified_trials']==192
                and audit['unavailable_or_failed_trials']==7 and audit['promotion_authority'] is False):
                result['status']='EXTRACTED_AND_AUDITED_WITH_SEVEN_UNAVAILABLE'
    except Exception as error:
        result['status']='FAILED_OR_PARTIAL'
        result['error']=dict(type=type(error).__name__,message=str(error))
    result['artifacts_sha256']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*'))
                              if p.is_file() and p.name!='attempt.json'}
    write(out/'attempt.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('md','evidence','out','source-commit'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(retain(args.md,args.evidence,args.out,args.source_commit)['status'])
    # The workflow reports failed/partial status only after durable publication.
