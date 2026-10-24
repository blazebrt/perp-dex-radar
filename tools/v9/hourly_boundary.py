"""Check the five missing day-boundary brackets without altering trade candles."""
from datetime import datetime, timedelta, timezone
import re

from tools.v9 import hourly_trades as T


def checked(raw, checksum, filename, day):
    if not re.fullmatch(r'[A-Z0-9_]+USDT-trades-'+re.escape(day)+r'\.zip',filename):
        raise ValueError('wrong daily source identity')
    tokens=checksum.decode('ascii').split()
    if len(tokens)!=2 or tokens[0].lower()!=T.sha(raw) or tokens[1].lstrip('*')!=filename:
        raise ValueError('checksum mismatch')
    yield from T.records(raw,day)


def scan(rows, t):
    before=after=first=last=None
    gaps=[]
    selected=total=0
    for r in rows:
        total+=1
        ident,stamp=r[:2]
        point=[ident,stamp]
        if stamp<t*1000000:
            before=point
        elif stamp<(t+14400)*1000000:
            if first is None:first=point
            if last and ident!=last[0]+1:gaps.append([last[0]+1,ident])
            last=point;selected+=1
        elif after is None:
            after=point
    if not total or not selected:
        raise ValueError('empty source or target block')
    return dict(before=before,after=after,first=first,last=last,internal_gaps=gaps,
                selected_records=selected,source_records=total)


def joins(s):
    gaps=list(s['internal_gaps'])
    for left,right in ((s['before'],s['first']),(s['last'],s['after'])):
        if left is None or right is None:continue
        if left[0]>=right[0] or left[1]>right[1]:
            raise ValueError('nonchronological boundary or overlapping IDs')
        if right[0]!=left[0]+1:gaps.append([left[0]+1,right[0]])
    return sorted(gaps)


def audit(raw, checksum, filename, previous, block, adjacent):
    """Adjacent maps before/after to (raw, checksum, filename, UTC day)."""
    if T.sha(raw)!=previous['source_sha256'] or T.sha(checksum)!=previous['checksum_sha256']:
        raise ValueError('original source changed')
    if filename!=previous['source_filename']:
        raise ValueError('original identity changed')
    day=previous['day'];t=block['t']
    s=scan(checked(raw,checksum,filename,day),t)
    if (s['source_records']!=previous['source_records'] or s['selected_records']!=sum(h['trades'] for h in block['hours'])
            or joins(s)!=block['id_gaps'] or bool(s['before'] and s['after'])!=block['bracketed']):
        raise ValueError('original continuity diagnostic does not reproduce')
    missing={side for side in ('before','after') if s[side] is None}
    if not missing or set(adjacent)!=missing:
        raise ValueError('supply exactly the missing boundary days')
    original=dict(s)
    sources=[]
    symbol=filename.split('-trades-')[0]
    for side in sorted(missing):
        raw2,sum2,name2,day2=adjacent[side]
        expected=(datetime.strptime(day,'%Y-%m-%d')+timedelta(days=-1 if side=='before' else 1)).strftime('%Y-%m-%d')
        if day2!=expected or name2!=symbol+'-trades-'+day2+'.zip':
            raise ValueError('adjacent source must be same symbol and immediate UTC day')
        candidate=None;count=0
        for row in checked(raw2,sum2,name2,day2):
            count+=1
            if side=='before' or candidate is None:candidate=list(row[:2])
        if candidate is None:raise ValueError('empty adjacent trade file')
        s[side]=candidate
        sources.append(dict(side=side,day=day2,filename=name2,sha256=T.sha(raw2),checksum_sha256=T.sha(sum2),records=count))
    gaps=joins(s)
    return dict(schema='v9.a5-boundary-diagnostic/1',coin=previous['coin'],day=day,t=t,
                original_source_sha256=T.sha(raw),original_checksum_sha256=T.sha(checksum),
                original=original,extended=s,adjacent_sources=sources,extended_id_gaps=gaps,
                bracketed=bool(s['before'] and s['after']),continuity_checked=not gaps,
                accepted_dataset=False,replay_complete=False,promotion_authority=False)
