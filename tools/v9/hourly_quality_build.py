"""Build a separate A5 candidate archive under the registered quality policy."""
import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.v9 import hourly_quality as Q

SOURCE = '003ddccc825b5aeaec1beab834c56f21b8baa9a8'
MANIFEST = '2f6af2c6ded2bca99c07b88cf9bc8d046261767a91afca4347e81da0fa613d09'
PROTOCOL = ROOT / 'docs/v9/phase-a5-quality-overlay.md'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, doc):
    Path(path).write_bytes((json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode())


def unique(items, key):
    result = {}
    for item in items:
        k = key(item)
        if k in result:
            raise ValueError('duplicate evidence identity')
        result[k] = item
    return result


def join_evidence(trade, quote, boundary, plan, manifest):
    """Require exact source/day/block/segment joins, including every conflict."""
    coins = unique(plan['fetch_coins'], lambda c: c['t'])
    original = unique(trade['diagnostics'], lambda d: (d['coin'], d['day']))
    precision = unique(quote['diagnostic']['results'], lambda d: (d['coin'], d['day']))
    supplements = unique(boundary['diagnostic']['results'], lambda d: (d['coin'], d['t']))
    if original.keys() != precision.keys():
        raise ValueError('diagnostic object sets differ')
    expected = {(coin, c['timestamp']) for coin, cov in manifest['coverage'].items()
                for c in cov.get('four_hour_conflicts', [])}
    decisions, used, used_supplements = {}, set(), set()
    for identity, d in original.items():
        coin, day = identity
        if coin not in coins:
            raise ValueError('unknown segment')
        c, p = coins[coin], precision[identity]
        filename = c['symbol'] + '-trades-' + day + '.zip'
        if d['source_filename'] != filename:
            raise ValueError('source symbol/date does not match segment')
        for field in ('source_filename', 'source_sha256', 'source_records'):
            if p[field] != d[field]:
                raise ValueError('quote source differs from original')
        if d['reference_sha256'] != plan['source_files_sha256']['h4/' + coin + '.csv.gz']:
            raise ValueError('four-hour reference changed')
        blocks = unique(d['blocks'], lambda b: b['t'])
        product = unique(p['blocks'], lambda b: b['t'])
        if blocks.keys() != product.keys():
            raise ValueError('block sets differ')
        for t, b in blocks.items():
            key = coin, t
            if (key in used or not c['first_bar'] <= t <= c['last_bar'] or
                    datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m-%d') != day):
                raise ValueError('invalid segment/block identity')
            supplement = supplements.get(key)
            if supplement:
                if (supplement['day'] != day or supplement['original_source_sha256'] != d['source_sha256'] or
                        supplement['original_checksum_sha256'] != d['checksum_sha256']):
                    raise ValueError('boundary source identity changed')
                used_supplements.add(key)
            elif not b['bracketed']:
                raise ValueError('missing boundary supplement')
            decision = Q.decision(b, product[t], supplement)
            decision['evidence'] = dict(coin=coin, day=day, source_sha256=d['source_sha256'],
                checksum_sha256=d['checksum_sha256'], reference_sha256=d['reference_sha256'],
                boundary_supplement=supplement is not None)
            decisions.setdefault(coin, []).append(decision)
            used.add(key)
    if used != expected or used_supplements != supplements.keys():
        raise ValueError('missing or extra conflict/boundary evidence')
    return {coin: sorted(ds, key=lambda d: d['t']) for coin, ds in decisions.items()}


def read_rows(path):
    with gzip.open(path, 'rt', encoding='utf8', newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ['t', *Q.FIELDS]:
            raise ValueError('unexpected hourly columns')
        return list(reader)


def write_rows(path, rows):
    with Path(path).open('wb') as f:
        with gzip.GzipFile(filename='', fileobj=f, mode='wb', mtime=0) as z:
            with io.TextIOWrapper(z, encoding='utf8', newline='') as text:
                writer = csv.DictWriter(text, fieldnames=['t', *Q.FIELDS], lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows)


def build_archive(source, out, plan, manifest, decisions):
    """Internal writer. Caller validates fixed evidence and source bindings first."""
    source, out = Path(source), Path(out)
    coins = unique(plan['fetch_coins'], lambda c: c['t'])
    if set(manifest['coverage']) != set(coins) or not set(decisions) <= set(coins):
        raise ValueError('segment coverage differs')
    expected = {'hourly_plan.json', 'universe.json'} | {
        folder + '/' + coin + '.csv.gz' for coin in coins for folder in ('h1', 'fund_bn')}
    if set(manifest['artifacts_sha256']) != expected:
        raise ValueError('incomplete source inventory')
    Q.verify_artifacts(source, manifest['artifacts_sha256'])
    out.mkdir(exist_ok=False)
    coverage, ledger = {}, []
    try:
        for folder in ('h1', 'fund_bn'):
            (out / folder).mkdir()
        for name in ('hourly_plan.json', 'universe.json'):
            shutil.copyfile(source / name, out / name)
        for coin, c in coins.items():
            path = 'h1/' + coin + '.csv.gz'
            original = read_rows(source / path)
            result, changes, cov = Q.overlay(original, decisions.get(coin, []), c['first_bar'], c['last_bar'] + Q.BLOCK)
            prior = manifest['coverage'][coin]
            if (cov['original_missing_hours'] != prior['missing_hours'] or
                    len(original) != prior['observed_hours'] or
                    sum(Q.values({k: r[k] for k in Q.FIELDS})['qv'] == 0 for r in original) != prior['zero_volume_hours']):
                raise ValueError('source coverage changed')
            cov['original_missing_intervals'] = prior['missing_intervals']
            cov['quarantined_intervals'] = [[d['t'], d['t'] + Q.BLOCK] for d in decisions.get(coin, [])
                                            if d['action'] == 'quarantine']
            cov['zero_volume_hours'] = sum(Q.values({k: r[k] for k in Q.FIELDS})['qv'] == 0 for r in result)
            if cov['zero_volume_hours'] != prior['zero_volume_hours']:
                raise ValueError('quality mask removed a zero-trade hour')
            if changes:
                write_rows(out / path, result)
            else:
                shutil.copyfile(source / path, out / path)
            funding = 'fund_bn/' + coin + '.csv.gz'
            if sha(source / funding) != prior['funding_source_sha256']:
                raise ValueError('funding binding changed')
            shutil.copyfile(source / funding, out / funding)
            coverage[coin] = cov
            for change, d in zip(changes, decisions.get(coin, [])):
                ledger.append(dict(coin=coin, **change, reason=d['action'], evidence=d['evidence'],
                    aggregate_matches=d['aggregate_matches'], continuity_checked=d['continuity_checked'],
                    source_hourly_sha256=manifest['artifacts_sha256'][path], derived_hourly_sha256=sha(out / path)))
        blocked = [d['t'] for ds in decisions.values() for d in ds if d['action'] == 'quarantine']
        schedule = Q.schedule_overlay(plan['days'], blocked)
        write_json(out / 'quality_schedule.json', schedule)
        write_json(out / 'quality_ledger.json', ledger)
        write_json(out / 'quality_coverage.json', dict(segments=coverage, scheduled_days=len(schedule),
            embargoed_days=[s['schedule']['known_at'] for s in schedule if not s['new_entries_allowed']],
            selection='retrospective source-quality selection; not historically known tradability'))
        return dict(schema='v9.a5-quality-candidate/1', source_result_commit=SOURCE,
            source_manifest_sha256=sha(source / 'rejected_manifest.json'),
            accepted_dataset=False, independent_verification_pending=True, replay_complete=False,
            promotion_authority=False, protocol_sha256=sha(PROTOCOL), builder_sha256=sha(__file__),
            transformation_sha256=sha(Q.__file__), evidence_records_sha256={n: h for n, h, _ in Q.RECORDS},
            artifacts_sha256={p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    except Exception as exc:
        write_json(out / 'failure.json', dict(error=str(exc), completed_segments=len(coverage), accepted_dataset=False))
        raise


def run(source, out, records, trades, quotes, boundaries):
    source, out = Path(source), Path(out)
    if sha(source / 'rejected_manifest.json') != MANIFEST:
        raise ValueError('wrong rejected archive')
    manifest = json.loads((source / 'rejected_manifest.json').read_bytes())
    plan = json.loads((source / 'hourly_plan.json').read_bytes())
    if manifest['schema'] != 'v9.hourly-archive-rejected/1' or manifest['source_reconciliation_passed'] is not False:
        raise ValueError('unexpected collection status')
    evidence = Q.load_evidence(records, trades, quotes, boundaries)
    decisions = join_evidence(*evidence, plan, manifest)
    flat = [d for ds in decisions.values() for d in ds]
    if len(flat) != 94 or sum(d['action'] == 'reconstruct' for d in flat) != 66:
        raise ValueError('registered block inventory does not reproduce')
    doc = build_archive(source, out, plan, manifest, decisions)
    # A build marker only; acceptance requires the separate independent verifier.
    write_json(out / 'quality_candidate_manifest.json', doc)
    return doc


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'out', 'records', 'trades', 'quotes', 'boundaries'):
        p.add_argument('--' + name, required=True)
    run(**vars(p.parse_args()))
