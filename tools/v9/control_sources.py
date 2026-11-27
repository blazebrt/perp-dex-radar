"""Bind A6 known disputes and original broad-universe files; no market matching."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess

ARCHIVE = '4828a2dbf69e0f7e66c97af7fbc0c9a1f24cccc7'
AUDIT = '003ddccc825b5aeaec1beab834c56f21b8baa9a8'
QUALITY = '0859e683910a7eea7ef446b27cf9773f33d9e9f8'
AUDIT_HASH = '2f6af2c6ded2bca99c07b88cf9bc8d046261767a91afca4347e81da0fa613d09'
QUALITY_HASH = 'd9eaba6b1a190d86529b01362a665f83c1c52d2a88e04f4cd71f4d333e8527b2'
BAR = 14400


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bound(data, expected):
    require(sha(data) == expected, 'source hash mismatch')
    return data


def safe_asset(asset):
    return isinstance(asset, str) and asset and asset not in ('.', '..') and '/' not in asset and '\\' not in asset


def build(manifest, plan, ledger):
    require(manifest['archive_commit'] == plan['archive_commit'] == ARCHIVE, 'wrong source archive')
    coins = {row['t']: row for row in plan['fetch_coins']}
    require(len(coins) == len(plan['fetch_coins']), 'duplicate segment metadata')
    source_files = plan['source_files_sha256']
    require('universe.json' in source_files and all(name == 'universe.json' or
            (name.startswith('h4/') and name.endswith('.csv.gz') and safe_asset(name[3:-7]))
            for name in source_files), 'unsafe source inventory')
    conflicts = {}
    fields = 0
    for asset, coverage in manifest['coverage'].items():
        require(asset in coins and safe_asset(asset), 'unknown audited segment')
        for row in coverage.get('four_hour_conflicts', []):
            t = row['timestamp']
            require(type(t) is int and t >= 0 and t % BAR == 0, 'invalid disputed time')
            require(coins[asset]['first_bar'] <= t <= coins[asset]['last_bar'], 'dispute outside segment')
            key = (asset, t)
            fields += 1
            conflicts.setdefault(key, set())
            require(row['field'] not in conflicts[key], 'duplicate conflict field')
            conflicts[key].add(row['field'])
    corroborated = {}
    for row in ledger:
        key = (row['coin'], row['t'])
        require(key not in corroborated, 'duplicate quality-ledger block')
        corroborated[key] = row
    require(set(corroborated) == set(conflicts), 'audit and quality-ledger identities differ')
    require(len(conflicts) == 94 and len({a for a, _ in conflicts}) == 87 and fields == 189,
            'original audit counts differ')
    require(manifest['source_conflict_count'] == fields, 'audit field count differs')
    rows = []
    for (asset, t), names in sorted(conflicts.items()):
        metadata = coins[asset]
        expected = source_files['h4/' + asset + '.csv.gz']
        evidence = corroborated[(asset, t)]['evidence']
        require(evidence['coin'] == asset and evidence['reference_sha256'] == expected,
                'quality ledger references different four-hour source')
        rows.append(dict(asset=asset, source_symbol=metadata['symbol'], open=t,
                         fields=sorted(names), source_file_sha256=expected))
    return dict(schema='v9.a6-source-inventory/1', archive_commit=ARCHIVE,
                audit_commit=AUDIT, corroborating_quality_commit=QUALITY,
                disputed_blocks=rows, disputed_block_count=94, disputed_segment_count=87,
                disputed_field_count=189, source_files_sha256=source_files,
                quality_scope='KNOWN_DISPUTES_ONLY_NOT_EXHAUSTIVE',
                full_matched_authority=False, promotion_authority=False)


def retained_inventory(repo):
    inputs = {}
    def read(commit, name, expected):
        data = subprocess.check_output(['git', '-c', 'safe.directory=*', '-C', str(repo), 'show', commit+':'+name])
        bound(data, expected)
        inputs[commit+':'+name] = sha(data)
        return json.loads(data)
    audit = read(AUDIT, 'rejected_manifest.json', AUDIT_HASH)
    plan = read(AUDIT, 'hourly_plan.json', audit['artifacts_sha256']['hourly_plan.json'])
    quality = read(QUALITY, 'quality_candidate_manifest.json', QUALITY_HASH)
    ledger = read(QUALITY, 'quality_ledger.json', quality['artifacts_sha256']['quality_ledger.json'])
    result = build(audit, plan, ledger)
    result['input_sha256'] = inputs
    result['builder_sha256'] = sha(Path(__file__).read_bytes())
    return result


def load_universe(directory, inventory):
    require(inventory['archive_commit'] == ARCHIVE, 'wrong archive identity')
    root = Path(directory)
    doc = json.loads(bound((root/'universe.json').read_bytes(), inventory['source_files_sha256']['universe.json']))
    rows = doc['coins']
    require(len({r['t'] for r in rows}) == len(rows), 'duplicate universe segment')
    coins = {r['t']: r for r in rows if not r['excluded']}
    require(all(safe_asset(a) for a in coins), 'unsafe universe segment')
    expected = {'h4/'+a+'.csv.gz' for a in coins}
    require(expected == set(inventory['source_files_sha256']) - {'universe.json'}, 'broad universe mismatch')
    require({p.name for p in (root/'h4').iterdir()} == {a+'.csv.gz' for a in coins}, 'source file inventory mismatch')
    return coins


def load_segment(directory, inventory, metadata):
    asset = metadata['t']
    require(safe_asset(asset), 'unsafe segment identity')
    name = 'h4/'+asset+'.csv.gz'
    raw = bound((Path(directory)/name).read_bytes(), inventory['source_files_sha256'][name])
    reader = csv.DictReader(io.StringIO(gzip.decompress(raw).decode('utf8')))
    require(reader.fieldnames is not None and {'t', 'qv'} <= set(reader.fieldnames), 'missing source columns')
    times, volumes = [], []
    for row in reader:
        t, v = int(row['t']), float(row['qv'])
        require(t >= 0 and t % BAR == 0 and (not times or t > times[-1]), 'invalid source time/order')
        require(math.isfinite(v) and v >= 0, 'invalid quote volume')
        times.append(t); volumes.append(v)
    require(times and times[0] == metadata['first_bar'] and times[-1] == metadata['last_bar']
            and len(times) == metadata['bars'], 'segment bounds/count mismatch')
    return dict(segment=dict(asset=asset, source_symbol=metadata['symbol'], first_bar=times[0]),
                times=times, volumes=volumes,
                disputed_opens=[r['open'] for r in inventory['disputed_blocks'] if r['asset'] == asset],
                source_sha256=sha(raw))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    result = retained_inventory(args.repo)
    with Path(args.out).open('x', encoding='utf8', newline='\n') as f:
        f.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
