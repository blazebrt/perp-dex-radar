"""Build a candidate hash lock from wheels; never grants environment qualification."""
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
import zipfile


def build(wheels,out):
    wheels=Path(wheels);out=Path(out)
    paths=sorted(wheels.iterdir());rows=[];seen=set()
    if not paths:raise ValueError('empty wheel collection')
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.suffix!='.whl':
            raise ValueError('regular wheels only')
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            names=[e.filename for e in entries]
            if len(names)!=len(set(names)):raise ValueError('duplicate wheel members')
            metadata=[e for e in entries if re.fullmatch('[^/]+[.]dist-info/METADATA',e.filename)]
            if len(metadata)!=1 or metadata[0].file_size>1024*1024:
                raise ValueError('one bounded metadata record required')
            info=BytesParser().parsebytes(archive.read(metadata[0]))
        names=info.get_all('Name') or [];versions=info.get_all('Version') or []
        if len(names)!=1 or len(versions)!=1:raise ValueError('ambiguous wheel identity')
        name,version=names[0],versions[0]
        if not re.fullmatch('[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?',name):
            raise ValueError('invalid wheel name')
        # Restrict candidates to ordinary numeric release/pre-release versions;
        # no requirements options, URLs, wildcards, whitespace or shell syntax.
        if not re.fullmatch('[0-9][A-Za-z0-9.!+_-]*',version):raise ValueError('unsafe wheel version')
        name=re.sub('[-_.]+','-',name).lower()
        if name in seen:raise ValueError('duplicate package in wheel collection')
        seen.add(name)
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        rows.append(dict(name=name,version=version,filename=path.name,sha256=digest.hexdigest(),bytes=path.stat().st_size))
    rows.sort(key=lambda row:row['name'])
    raw=''.join(r['name']+'=='+r['version']+' --hash=sha256:'+r['sha256']+'\n' for r in rows).encode()
    report=dict(schema='v9.a6-dependency-lock-candidate/1',status='CANDIDATE_REQUIRES_INSTALLATION_AND_REVIEW',
        wheels=rows,lock_sha256=hashlib.sha256(raw).hexdigest(),resource_qualified=False,promotion_authority=False)
    out.mkdir(parents=True,exist_ok=False)
    (out/'requirements.lock').write_bytes(raw)
    (out/'wheel-manifest.json').write_bytes((json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();build(args.wheels,args.out)
