"""Independent A6 artifact accounting, not a generator-population proof."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def integer(value):
    return type(value) is int and value >= 0


def load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            check(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON value: '+value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def verify(directory, plan, expected_provenance):
    """Trust anchors must come from source review, never from the output itself."""
    root = Path(directory)
    check(not root.is_symlink(), 'symlink result directory')
    expected_files = {'manifest.json'}
    raw_manifest = (root/'manifest.json').read_bytes()
    manifest = load(raw_manifest)
    check(manifest['schema'] == 'v9.a6-extraction/1', 'unknown schema')
    check(manifest['provenance'] == expected_provenance, 'source provenance mismatch')
    check(all(manifest[k] is False for k in ('full_matched_authority','promotion_authority','outcomes_computed')),
          'unsupported authority/outcomes')
    start, end = manifest['window']
    check(integer(start) and integer(end) and start <= end, 'invalid window')
    trials = manifest['trials']
    check([r['definition'] for r in trials] == plan['trials'], 'definition roster/order mismatch')
    ids = [r['trial_id'] for r in trials]
    check(len(set(ids)) == len(ids) and all(isinstance(t,str) and re.fullmatch('[0-9a-f]{64}',t) for t in ids),
          'duplicate/unsafe trial identity')
    totals = dict(extracted=0, failed=0, hourly_unavailable=0, retained_records=0, shards=0)
    for trial in trials:
        tid = trial['trial_id']
        check(tid == trial['definition']['trial_id'] and trial['promotion_authority'] is False, 'trial identity/authority mismatch')
        name = tid+'.json'
        expected_files.add(name)
        check(load((root/name).read_bytes()) == trial, 'trial record differs from manifest')
        requirement = trial['definition']['archive_requirement']
        if requirement == 'hourly':
            check(trial['status']=='UNAVAILABLE_HOURLY_POPULATION' and trial['population'] is None
                  and trial['shards']==[], 'hourly population invented')
            totals['hourly_unavailable'] += 1
            continue
        check(requirement=='4h' and trial['status'] in ('EXTRACTED','FAILED'), 'invalid trial disposition')
        previous = -1
        count = 0
        for index, shard in enumerate(trial['shards']):
            name = tid+'-%05d.jsonl.gz' % index
            check(shard['path']==name and name not in expected_files, 'shard order/identity mismatch')
            expected_files.add(name)
            path = root/name
            check(not path.is_symlink(), 'symlink shard')
            raw = path.read_bytes()
            check(digest(raw)==shard['sha256'] and len(raw)==shard['bytes'], 'shard byte/hash mismatch')
            check(integer(shard['records']) and 0 < shard['records'] <= 25000 and
                  integer(shard['uncompressed_bytes']) and shard['uncompressed_bytes'] <= 16*1024*1024,
                  'shard limit mismatch')
            size = records = 0
            with gzip.open(path,'rb') as stream:
                while True:
                    line = stream.readline(16*1024*1024+1)
                    if not line: break
                    size += len(line); records += 1
                    check(size <= 16*1024*1024 and records <= 25000 and line.endswith(b'\n'), 'unbounded/truncated shard')
                    row = load(line)
                    ordinal = row['source_ordinal']
                    check(integer(ordinal) and ordinal > previous, 'duplicate/reordered ordinal')
                    previous = ordinal
                    check(row['trial_id']==tid and isinstance(row['asset'],str) and row['asset'], 'signal identity mismatch')
                    check(integer(row['decision_time']) and start <= row['decision_time'] <= end
                          and row['decision_time'] % 14400 == 0 and type(row['direction']) is int
                          and row['direction'] in (-1,1), 'invalid signal decision')
                    identity=[tid,ordinal,row['asset'],row['decision_time'],row['direction']]
                    check(row['signal_id']==digest(json.dumps(identity,separators=(',',':')).encode()), 'signal digest mismatch')
                    check(row['promotion_authority'] is False and row['full_matched_authority'] is False,
                          'signal authority invented')
                    feature = row['features']
                    check(all(feature[k]==row[k] for k in ('asset','decision_time','direction')) and
                          type(row['original_eligible']) is bool and feature['eligible'] is row['original_eligible'],
                          'feature identity/eligibility mismatch')
                    check(all(feature[k] is False for k in ('promotion_authority','full_matched_authority','signal_quality_qualified'))
                          and row['history']['signal_quality_qualified'] is False, 'feature/history authority invented')
            check(records==shard['records'] and size==shard['uncompressed_bytes'], 'shard accounting mismatch')
            count += records
            totals['shards'] += 1
        check(integer(trial['retained_records']) and count==trial['retained_records'], 'trial count mismatch')
        totals['retained_records'] += count
        population = trial['population']
        if trial['status']=='FAILED':
            check(population is None and isinstance(trial['error']['message'],str), 'failed population fabricated')
            totals['failed'] += 1
        else:
            check(all(integer(population[k]) for k in ('generated','before_window','after_window','retained')),
                  'invalid population counts')
            check(population['retained']==count and population['generated']==count+population['before_window']+population['after_window']
                  and previous < population['generated'], 'population accounting mismatch')
            check(population['promotion_authority'] is False and population['full_matched_authority'] is False,
                  'population authority invented')
            totals['extracted'] += 1
    expected_status = 'PARTIAL' if totals['failed'] else 'COMPLETED_WITH_UNAVAILABLE_HOURLY_POPULATIONS'
    check(manifest['status']==expected_status, 'completion status mismatch')
    check(all(p.is_file() and not p.is_symlink() for p in root.iterdir()) and
          {p.name for p in root.iterdir()}==expected_files, 'unlisted/missing artifact')
    return dict(schema='v9.a6-artifact-verification/1', manifest_sha256=digest(raw_manifest),
                artifact_accounting_verified=True, generator_population_verified=False,
                source_feature_values_verified=False, promotion_authority=False, **totals)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--provenance', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = verify(args.directory, load(Path(args.plan).read_bytes()), load(Path(args.provenance).read_bytes()))
    with Path(args.out).open('x', encoding='utf8', newline='\n') as stream:
        stream.write(json.dumps(result,sort_keys=True,indent=2)+'\n')
