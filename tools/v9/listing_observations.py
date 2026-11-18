"""Offline, source-bound listing observations. No inferred listing dates or trade authority."""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

MAX_BYTES = 16 * 1024 * 1024
MAX_CAPTURES = 1000
MAX_MARKETS = 20000
SOURCES = {
    'BINANCE_USDM_EXCHANGE_INFO': ('https://fapi.binance.com/fapi/v1/exchangeInfo',),
    'UPBIT_KR_MARKETS': ('https://api.upbit.com/v1/market/all',
                        'https://api.upbit.com/v1/market/all?is_details=true'),
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    out = {}
    for key, value in items:
        require(key not in out, 'duplicate JSON key')
        out[key] = value
    return out


def decode(raw):
    def invalid(_):
        raise ValueError('nonfinite JSON')
    def finite(text):
        value = float(text)
        require(math.isfinite(value), 'nonfinite JSON')
        return value
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite)


def read(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, 'input byte limit exceeded')
    return raw


def timestamp(value):
    return type(value) is int and 0 < value < 8640000000000


def normalize(source, payload, retrieved_at):
    require(source in SOURCES and timestamp(retrieved_at), 'invalid normalization source or time')
    if source == 'BINANCE_USDM_EXCHANGE_INFO':
        require(isinstance(payload, dict), 'invalid Binance response envelope')
        rows = payload.get('symbols')
    else:
        rows = payload
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_MARKETS, 'empty or invalid market inventory')
    result = {}
    for row in rows:
        require(isinstance(row, dict), 'invalid market row')
        if source == 'BINANCE_USDM_EXCHANGE_INFO':
            fields = ('symbol', 'baseAsset', 'quoteAsset', 'contractType', 'status')
            require(all(isinstance(row.get(k), str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}', row[k]) for k in fields),
                    'invalid Binance market identity or status')
            market = row['symbol']
            record = dict(base_asset_label=row['baseAsset'], quote_asset_label=row['quoteAsset'],
                          contract_type=row['contractType'], reported_status=row['status'])
            onboard = row.get('onboardDate')
            valid = type(onboard) is int and 0 < onboard < 8640000000000000
            record.update(reported_onboard_ms=onboard if valid else None,
                          onboard_state=('SCHEDULED_METADATA' if onboard > retrieved_at * 1000 else 'REPORTED_METADATA')
                          if valid else 'UNAVAILABLE')
        else:
            market = row.get('market')
            require(isinstance(market, str) and re.fullmatch(r'[A-Z0-9]{1,20}-[A-Z0-9]{1,80}', market),
                    'invalid Upbit market identity')
            quote, base = market.split('-')
            record = dict(base_asset_label=base, quote_asset_label=quote, contract_type='SPOT',
                          reported_status='MARKET_LIST_MEMBER', reported_onboard_ms=None, onboard_state='UNAVAILABLE')
        require(market not in result, 'duplicate market identity')
        result[market] = record
    return result


def audit(manifest, root, as_of):
    require(timestamp(as_of), 'invalid audit cutoff')
    require(isinstance(manifest, dict) and manifest.get('schema') == 'v9.listing-observation-input/1', 'invalid manifest')
    captures = manifest.get('captures')
    require(isinstance(captures, list) and 0 < len(captures) <= MAX_CAPTURES, 'invalid capture count')
    root = Path(root).resolve()
    loaded, paths, times = [], set(), set()
    total_bytes = 0
    for ref in captures:
        require(isinstance(ref, dict), 'invalid capture reference')
        source, stamp, name = ref.get('source'), ref.get('retrieved_at'), ref.get('path')
        require(isinstance(source, str) and source in SOURCES, 'unsupported source')
        require(ref.get('request_url') in SOURCES[source] and type(ref.get('http_status')) is int
                and ref['http_status'] == 200, 'source request contract mismatch')
        require(timestamp(stamp) and stamp <= as_of, 'invalid or future capture time')
        require((source, stamp) not in times, 'ambiguous capture time')
        times.add((source, stamp))
        require(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'unsafe source path')
        rel = PurePosixPath(name)
        require(not rel.is_absolute() and '..' not in rel.parts and str(rel) == name, 'unsafe source path')
        path = (root / name).resolve()
        require(path.is_relative_to(root) and name not in paths, 'source escape or duplicate path')
        paths.add(name)
        require(type(ref.get('bytes')) is int and 0 < ref['bytes'] <= MAX_BYTES, 'invalid byte binding')
        require(isinstance(ref.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', ref['sha256']), 'invalid hash binding')
        total_bytes += ref['bytes']
        require(total_bytes <= 128 * 1024 * 1024, 'aggregate source byte limit exceeded')
        raw = read(path)
        require(len(raw) == ref['bytes'] and sha(raw) == ref['sha256'], 'source binding mismatch')
        records = normalize(source, decode(raw), stamp)
        loaded.append((source, stamp, dict(ref), records))
    loaded.sort(key=lambda x: (x[0], x[1]))
    previous, seen, output = {}, {}, []
    for source, stamp, ref, records in loaded:
        prev = previous.get(source)
        known = seen.setdefault(source, {})
        additions, removals, changes = [], [], []
        old = prev[1] if prev else {}
        for market in sorted(records):
            if market not in old:
                kind = 'BASELINE_MEMBER' if prev is None else 'REOBSERVED_MEMBER' if market in known else 'NEWLY_OBSERVED_MEMBER'
                additions.append(dict(market=market, observation_kind=kind,
                                      previous_capture_at=prev[0] if prev else None,
                                      first_known_in_this_series_at=known.get(market, stamp),
                                      observed_at=stamp, listing_time=None, identity_verified=False,
                                      metadata=records[market]))
            elif records[market] != old[market]:
                changes.append(dict(market=market, before=old[market], after=records[market]))
        if prev:
            removals = [dict(market=m, observation_kind='ABSENT_FROM_RESPONSE', observed_at=stamp,
                             delisting_time=None) for m in sorted(set(old) - set(records))]
        for market in records:
            known.setdefault(market, stamp)
        output.append(dict(source=source, retrieved_at=stamp, source_ref=ref, markets=len(records),
                           previous_capture_at=prev[0] if prev else None,
                           observation_gap_s=stamp-prev[0] if prev else None,
                           additions=additions, absences=removals, metadata_changes=changes))
        previous[source] = (stamp, records)
    return dict(schema='v9.listing-observation-audit/1', as_of=as_of,
                manifest_sha256=sha(canonical(manifest)), status='CONTENT_BINDINGS_VERIFIED',
                capture_count=len(output), captures=output,
                historical_listing_coverage='UNVERIFIED', verified_listing_events=0,
                listing_study_eligible=False, trade_authorization=False,
                limitations=['Hashes verify supplied content, not endpoint authenticity, capture time or upstream completeness.',
                             'First presence and response absence are observations, not listing or delisting events.',
                             'onboardDate is reported metadata available only at capture time, not independently verified inception.',
                             'No global asset mapping, symbol-reuse resolution, announcement authentication or outcome study.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--as-of', required=True, type=int)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    # Inputs are immutable: also prevent replacing a source with the report.
    root = args.root.resolve()
    require(not args.out.resolve().is_relative_to(root) and args.out.resolve() != args.manifest.resolve(),
            'report must be outside the source root and distinct from manifest')
    result = audit(decode(read(args.manifest)), root, args.as_of)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an earlier observation report.
    with args.out.open('xb') as stream:
        stream.write(canonical(result) + b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
