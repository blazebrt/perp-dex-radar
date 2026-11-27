"""Offline directory-chain verification; listing is not historical eligibility."""
import base64
import re
from urllib.parse import urlsplit, parse_qsl
import xml.etree.ElementTree as ET
from .listing_observations import require, sha, canonical, timestamp

PREFIX = 'data/futures/um/daily/premiumIndexKlines/'
NS = '{http://s3.amazonaws.com/doc/2006-03-01/}'


def audit(records):
    require(isinstance(records,list) and 0 < len(records) <= 20, 'invalid page count')
    expected_marker = ''
    prefixes, pages, prior_completion = [], [], 0
    for index, record in enumerate(records):
        require(isinstance(record,dict) and record.get('status') == 200, 'unsuccessful page')
        start, end = record.get('requested_at'), record.get('completed_at')
        require(timestamp(start) and timestamp(end) and prior_completion <= start <= end, 'invalid capture sequence')
        prior_completion = end
        url = urlsplit(record.get('url',''))
        require(url.scheme == 'https' and url.netloc == 's3-ap-northeast-1.amazonaws.com'
                and url.path == '/data.binance.vision' and not url.fragment, 'wrong listing endpoint')
        pairs = parse_qsl(url.query,keep_blank_values=True,strict_parsing=True)
        query = dict(pairs)
        require(len(query)==len(pairs) and set(query) <= {'prefix','delimiter','marker'}
                and query.get('prefix')==PREFIX and query.get('delimiter')=='/'
                and query.get('marker','')==expected_marker, 'wrong query or marker')
        encoded = record.get('body_base64')
        require(isinstance(encoded,str) and len(encoded)<=6*1024*1024, 'invalid response size')
        raw = base64.b64decode(encoded,validate=True)
        require(0 < len(raw) <= 4*1024*1024 and type(record.get('bytes')) is int
                and len(raw)==record['bytes'] and sha(raw)==record.get('sha256'), 'response binding mismatch')
        require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'unsupported XML declarations')
        root = ET.fromstring(raw)
        require(root.tag==NS+'ListBucketResult', 'wrong listing document')
        def one(name, optional=False):
            values=root.findall(NS+name)
            require(len(values)==1 or (optional and not values), 'ambiguous listing field')
            return (values[0].text or '') if values else None
        require(one('Name')=='data.binance.vision' and one('Prefix')==PREFIX
                and one('Delimiter')=='/' and one('Marker')==expected_marker, 'listing contract mismatch')
        require(not root.findall(NS+'Contents'), 'unexpected direct objects')
        truncated=one('IsTruncated')
        require(truncated in ('true','false'), 'invalid truncation flag')
        current=[]
        for element in root.findall(NS+'CommonPrefixes'):
            children=list(element)
            require(len(children)==1 and children[0].tag==NS+'Prefix', 'invalid common prefix')
            value=children[0].text
            require(isinstance(value,str) and value.startswith(PREFIX) and value.endswith('/'), 'wrong source prefix')
            symbol=value[len(PREFIX):-1]
            require(symbol and '/' not in symbol and all(ord(c)>=32 for c in symbol), 'invalid source symbol')
            current.append(value)
        require(all(a.encode('utf-8') < b.encode('utf-8') for a,b in zip(current,current[1:])), 'unordered or duplicate prefixes')
        require(not current or current[0].encode('utf-8') > expected_marker.encode('utf-8'), 'overlapping pages')
        if truncated=='true':
            marker=one('NextMarker')
            require(current and marker==current[-1] and index+1 < len(records), 'incomplete page chain')
            expected_marker=marker
        else:
            require(index==len(records)-1 and not one('NextMarker',True), 'pages after terminal response')
        prefixes.extend(current)
        pages.append(dict(sha256=sha(raw),count=len(current),requested_at=start,completed_at=end))
    symbols=[p[len(PREFIX):-1] for p in prefixes]
    require(len(set(symbols))==len(symbols), 'duplicate source symbols')
    unsupported=[s for s in symbols if re.fullmatch('[A-Z0-9_]{1,80}',s) is None]
    return dict(schema='v9.premium-directory-audit/1',status='TERMINAL_PAGE_CHAIN_VERIFIED',
                response_bundle_sha256=sha(canonical(records)),pages=pages,prefix_count=len(symbols),
                symbols=symbols,importer_unsupported_symbols=unsupported,
                atomic_snapshot=False,historical_population_accepted=False,coverage_verified=False,
                study_eligible=False,trade_authorization=False,
                limitations=['Listing pages were captured at different times; intervening changes cannot be ruled out.',
                             'Directory presence is not instrument identity, trading eligibility or historical bar coverage.',
                             'Hashes bind retained bytes; they do not independently authenticate upstream provenance.'])
