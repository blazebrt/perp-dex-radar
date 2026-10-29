"""Reserve one A6 outcome attempt through an injected GitHub API transport.

No network adapter or workflow is activated here. The transport must use the
fixed repository, propagate all errors, and raise MissingRef only for a genuine
404 on the exact ref GET. POST refs is create-only; never substitute PATCH.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
from tools.v9 import control_resource_gate as G
from tools.v9 import control_outcome_publish as P

REPO='/repos/blazebrt/perp-dex-radar'
REF='refs/heads/evidence-a6-outcome-results'
REF_PATH=REPO+'/git/ref/heads/evidence-a6-outcome-results'


class MissingRef(Exception):
    """Transport-confirmed 404 for the requested branch ref only."""


def sha(raw):return hashlib.sha256(raw).hexdigest()


def reserve(api,source_read,source,run_id,run_attempt,qualification,qualification_hash,capacity):
    if not isinstance(source,str) or not re.fullmatch('[0-9a-f]{40}',source):raise ValueError('full source commit required')
    if type(run_id) is not str or not re.fullmatch('[1-9][0-9]*',run_id) or run_attempt!='1':
        raise ValueError('first Actions attempt and positive run ID required')
    execution=sha(source_read(source,P.PROTOCOL));publication=sha(source_read(source,P.PUBLICATION))
    guard=source_read(source,'tools/v9/control_resource_gate.py')
    if guard!=Path(G.__file__).read_bytes():raise ValueError('resource guard differs from pinned source')
    preflight=G.verify(qualification,qualification_hash,source,P.INPUT_HASH,execution,capacity)
    try:api('GET',REF_PATH,None)
    except MissingRef:pass
    else:raise ValueError('existing reservation blocks another attempt')
    reserved=dict(status='RESERVED',source_commit=source,run_id=run_id,run_attempt='1',
        input_commit=P.INPUT_COMMIT,input_manifest_sha256=P.INPUT_HASH,
        execution_protocol_sha256=execution,publication_protocol_sha256=publication,
        resource_gate_sha256=sha(guard),resource_qualification_sha256=qualification_hash,
        results_branch='evidence-a6-outcome-results',promotion_authority=False)
    raw=(json.dumps(reserved,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    tree=api('POST',REPO+'/git/trees',dict(tree=[dict(path='reservation.json',mode='100644',type='blob',content=raw.decode())]))['sha']
    commit=api('POST',REPO+'/git/commits',dict(message='Reserve registered A6 outcome attempt',tree=tree,parents=[]))['sha']
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('invalid reservation commit response')
    # Atomic create-only operation: a concurrent creator must fail here.
    api('POST',REPO+'/git/refs',dict(ref=REF,sha=commit))
    observed=api('GET',REF_PATH,None)
    if observed.get('ref')!=REF or observed.get('object',{}).get('sha')!=commit:
        raise ValueError('remote reservation tip mismatch')
    saved=api('GET',REPO+'/git/commits/'+commit,None)
    if saved.get('parents')!=[] or saved.get('tree',{}).get('sha')!=tree:
        raise ValueError('reservation must be an orphan root')
    contents=api('GET',REPO+'/git/trees/'+tree,None)
    entries=contents.get('tree',[])
    if contents.get('truncated') is not False or len(entries)!=1 or any(entries[0].get(k)!=v for k,v in
        dict(path='reservation.json',mode='100644',type='blob').items()):
        raise ValueError('unexpected reservation tree')
    blob=api('GET',REPO+'/git/blobs/'+entries[0]['sha'],None)
    if blob.get('encoding')!='base64' or base64.b64decode(''.join(blob['content'].split()),validate=True)!=raw:
        raise ValueError('reservation bytes mismatch')
    return dict(status='RESERVATION_CREATED_AND_READ_BACK',reservation_commit=commit,
        reservation_bytes=raw,preflight=preflight,promotion_authority=False)
