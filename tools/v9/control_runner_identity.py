"""Collect runner image claims without treating agreement as attestation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys


def unique(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('duplicate identity key')
        result[key]=value
    return result


def image_fields(raw):
    """Parse actions/runner-images configure-image-data.sh's group/detail format."""
    data=json.loads(raw,object_pairs_hook=unique)
    if type(data) is not list or any(type(row) is not dict for row in data):
        raise ValueError('image record list required')
    rows=[r for r in data if r.get('group')=='Runner Image']
    if len(rows)!=1 or type(rows[0].get('detail')) is not str:
        raise ValueError('one runner image detail required')
    fields={}
    for line in rows[0]['detail'].splitlines():
        key,sep,value=line.partition(': ')
        if not sep or key not in ('Image','Version','Included Software','Image Release') or key in fields or not value:
            raise ValueError('invalid runner image detail')
        fields[key]=value
    if set(fields)!={'Image','Version','Included Software','Image Release'}:
        raise ValueError('incomplete runner image detail')
    if not re.fullmatch('ubuntu-[0-9]+[.][0-9]+(?:-arm)?',fields['Image']) or not re.fullmatch('[0-9]{8}[.][0-9]+[.][0-9]+',fields['Version']):
        raise ValueError('unsupported runner image identity')
    return fields


def environment_fields(raw):
    result={}
    for line in raw.decode('utf-8').splitlines():
        key,sep,value=line.partition('=');key=key.strip()
        if sep and key in ('ImageOS','ImageVersion'):
            if key in result:raise ValueError('duplicate environment identity')
            value=value.strip()
            if value[:1] in ('"',"'"):
                if len(value)<2 or value[-1]!=value[0]:raise ValueError('unbalanced identity quotes')
                value=value[1:-1]
            if not value:raise ValueError('empty environment identity')
            result[key]=value
    if set(result)!={'ImageOS','ImageVersion'}:raise ValueError('incomplete environment identity')
    return result


def collect(env,root=Path('/')):
    report=dict(schema='v9.a6-runner-identity/2',source_commit=env.get('GITHUB_SHA'),run_id=env.get('GITHUB_RUN_ID'),
        run_attempt=env.get('GITHUB_RUN_ATTEMPT'),environment={k:env.get(k) for k in ('ImageOS','ImageVersion','RUNNER_ENVIRONMENT','RUNNER_OS','RUNNER_ARCH')},
        python=sys.version,platform=platform.platform(),files={},status='UNAVAILABLE',
        resource_qualified=False,promotion_authority=False)
    for name,parser in [('etc/environment',environment_fields),('imagegeneration/imagedata.json',image_fields)]:
        try:
            with (Path(root)/name).open('rb') as stream:raw=stream.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('identity file too large')
            receipt=dict(sha256=hashlib.sha256(raw).hexdigest(),status='READ')
            report['files']['/'+name]=receipt
            receipt['selected_fields']=parser(raw)
        except (OSError,ValueError) as error:
            receipt=report['files'].setdefault('/'+name,{})
            receipt.update(status='UNAVAILABLE',error_type=type(error).__name__)
    if all(r['status']=='READ' for r in report['files'].values()):
        saved=report['files']['/etc/environment']['selected_fields']
        image=report['files']['/imagegeneration/imagedata.json']['selected_fields']
        report['version_claims']=dict(environment=env.get('ImageVersion'),etc_environment=saved['ImageVersion'],imagedata=image['Version'])
        versions=list(report['version_claims'].values())
        # This probe targets the existing Ubuntu 24.04 x64 profile only.
        profile=(env.get('ImageOS')==saved['ImageOS']=='ubuntu24' and image['Image']=='ubuntu-24.04'
                 and env.get('RUNNER_OS')=='Linux' and env.get('RUNNER_ARCH')=='X64')
        report['status']='CONSISTENT_CLAIMS_NOT_ATTESTED' if profile and len(set(versions))==1 else 'CONFLICTING_IDENTITY_CLAIMS'
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);args=parser.parse_args()
    with Path(args.out).open('x',encoding='utf-8') as stream:json.dump(collect(os.environ),stream,sort_keys=True,indent=2)
