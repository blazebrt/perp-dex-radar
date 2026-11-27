"""Pure A5 quality-overlay transformations; no archive acceptance or replay.

Callers must bind and verify the complete evidence/artifact inventory before
using these helpers. This module deliberately provides no dataset writer yet.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath

FIELDS = ('o', 'h', 'l', 'c', 'qv', 'tbqv')
HOUR = 3600
BLOCK = 4 * HOUR
DAY = 24 * HOUR
RECORDS = (
    ('a5_trade_diagnostics.json', '4eaa3297b048621b4cd0931c95d408e51cd49aa497687953793903af0c1ba22e',
     'v9.a5-trade-diagnostics-record/1'),
    ('a5_quote_precision.json', '6dde68dab77446a81a1fd5400acf9887348f9231fa8664dbddffe23c7e7c0394',
     'v9.a5-quote-precision-record/1'),
    ('a5_boundary_continuity.json', 'cf24e659052f3f56beee178e08c3ad84a60bd4ba835170bdc0a096cd53c2ce04',
     'v9.a5-boundary-record/1'),
)


def bound_json(path, digest, schema):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('evidence hash changed: ' + str(path))
    doc = json.loads(raw)
    if doc['schema'] != schema or doc.get('accepted_dataset') is not False:
        raise ValueError('unexpected evidence schema/state')
    return doc


def verify_artifacts(root, inventory):
    """Stream every bound file; reject paths escaping the evidence directory."""
    root = Path(root).resolve()
    if not inventory:
        raise ValueError('empty artifact inventory')
    for name, expected in inventory.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('unsafe artifact path')
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError('artifact escapes evidence directory')
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('artifact hash changed: ' + name)


def load_evidence(records, trade_root, quote_root, boundary_root):
    """Verify all fixed protocol bindings before exposing decision inputs."""
    trade, quote, boundary = [bound_json(Path(records) / name, digest, schema)
                              for name, digest, schema in RECORDS]
    if trade['rejected_results_commit'] != '003ddccc825b5aeaec1beab834c56f21b8baa9a8':
        raise ValueError('rejected collection changed')
    for doc, schema in ((quote['diagnostic'], 'v9.a5-quote-precision/1'),
                        (boundary['diagnostic'], 'v9.a5-boundary-run/1')):
        if doc['schema'] != schema or doc['prior_record_sha256'] != RECORDS[0][1]:
            raise ValueError('diagnostic binding changed')
    if boundary['diagnostic']['failures']:
        raise ValueError('incomplete boundary batch')
    verify_artifacts(trade_root, trade['artifact_hashes'])
    verify_artifacts(quote_root, quote['artifacts_sha256'])
    verify_artifacts(boundary_root, boundary['diagnostic']['artifacts_sha256'])
    return trade, quote, boundary


def timestamp(value, step):
    if type(value) is not int or value < 0 or value % step:
        raise ValueError('invalid timestamp grid')
    return value


def values(fields):
    if set(fields) != set(FIELDS):
        raise ValueError('incomplete candle')
    try:
        v = {k: Decimal(str(fields[k])) for k in FIELDS}
    except (InvalidOperation, ValueError):
        raise ValueError('invalid numeric candle') from None
    if (not all(x.is_finite() for x in v.values()) or
            min(v[k] for k in FIELDS[:4]) <= 0 or
            v['l'] > min(v['o'], v['c']) or v['h'] < max(v['o'], v['c']) or
            not 0 <= v['tbqv'] <= v['qv']):
        raise ValueError('invalid candle bounds')
    return v


def decision(original, precision, boundary=None):
    """Join one already-bound block; never erase a previous internal ID gap."""
    t = timestamp(original['t'], BLOCK)
    if precision['t'] != t:
        raise ValueError('block identity changed')
    for key in ('id_gaps', 'bracketed', 'continuity_checked'):
        if precision[key] != original[key]:
            raise ValueError('precision changed continuity evidence')
    continuous = original['continuity_checked']
    if type(continuous) is not bool or type(original['bracketed']) is not bool:
        raise ValueError('invalid continuity flag')
    if continuous != (original['bracketed'] and not original['id_gaps']):
        raise ValueError('contradictory continuity evidence')
    if boundary is not None:
        if boundary['t'] != t or original['bracketed']:
            raise ValueError('unexpected boundary supplement')
        gaps = boundary['extended_id_gaps']
        if any(g not in gaps for g in original['id_gaps']):
            raise ValueError('boundary erased original gap')
        continuous = boundary['continuity_checked']
        if (type(continuous) is not bool or type(boundary['bracketed']) is not bool or
                continuous != (boundary['bracketed'] and not gaps)):
            raise ValueError('contradictory boundary evidence')
    comparisons = precision['volume_comparisons']
    if (len(comparisons) != 2 or {c['field'] for c in comparisons} != {'qv', 'tbqv'} or
            any(type(c['product_matches']) is not bool for c in comparisons)):
        raise ValueError('incomplete volume comparison')
    prices = [c for c in original['conflicts'] if c['field'] in FIELDS[:4]]
    if precision['price_conflicts'] != prices:
        raise ValueError('price conflicts changed')
    matching = not prices and all(c['product_matches'] for c in comparisons)
    if type(precision['product_aggregate_matches']) is not bool or precision['product_aggregate_matches'] != matching:
        raise ValueError('contradictory aggregate evidence')
    expected = list(range(t, t + BLOCK, HOUR))
    if ([h['t'] for h in original['hours']] != expected or
            [h['t'] for h in precision['hours']] != expected):
        raise ValueError('incomplete or unordered candidate hours')
    replacements = []
    if matching and continuous:
        for old, new in zip(original['hours'], precision['hours']):
            if (type(old['trades']) is not int or old['trades'] <= 0 or
                    new['trades'] != old['trades'] or new['observed'] is not True):
                raise ValueError('replacement lacks observed trades')
            fields = dict(old['fields'])
            fields.update(qv=new['product_qv'], tbqv=new['product_tbqv'])
            if values(fields)['qv'] <= 0:
                raise ValueError('replacement lacks positive volume')
            replacements.append(dict(t=old['t'], **fields))
    return dict(t=t, action='reconstruct' if matching and continuous else 'quarantine',
                aggregate_matches=matching, continuity_checked=continuous,
                replacement_rows=replacements)


def overlay(rows, decisions, first, end):
    """Return separate rows, complete before/after ledger and disjoint coverage.

    Rows are string-valued CSV dictionaries. Unaffected rows are copied without
    numeric conversion; quarantined rows are removed only from this result.
    """
    timestamp(first, HOUR); timestamp(end, HOUR)
    if end <= first:
        raise ValueError('empty segment')
    indexed = {}
    previous = None
    for row in rows:
        t = timestamp(int(row['t']), HOUR)
        if not first <= t < end or (previous is not None and t <= previous):
            raise ValueError('unordered, duplicate or outside segment hour')
        values({k: row[k] for k in FIELDS})
        indexed[t] = deepcopy(row)
        previous = t
    original_gaps = set(range(first, end, HOUR)) - indexed.keys()
    replacements, quarantine, seen, ledger = {}, set(), set(), []
    for d in decisions:
        t = timestamp(d['t'], BLOCK)
        hours = set(range(t, t + BLOCK, HOUR))
        if t < first or t + BLOCK > end or seen & hours:
            raise ValueError('duplicate/overlapping or outside segment block')
        seen.update(hours)
        if d['action'] == 'reconstruct':
            if (d['aggregate_matches'] is not True or d['continuity_checked'] is not True or
                    [r['t'] for r in d['replacement_rows']] != sorted(hours) or
                    not hours <= indexed.keys()):
                raise ValueError('unqualified or incomplete replacement')
            for row in d['replacement_rows']:
                if values({k: row[k] for k in FIELDS})['qv'] <= 0:
                    raise ValueError('replacement has no trading')
                replacements[row['t']] = {k: str(v) for k, v in row.items()}
        elif d['action'] == 'quarantine':
            if d['replacement_rows']:
                raise ValueError('quarantine has replacement rows')
            quarantine.update(hours)
        else:
            raise ValueError('unknown quality action')
        ledger.append(dict(t=t, action=d['action'], before=[deepcopy(indexed.get(h)) for h in sorted(hours)],
                           after=[deepcopy(replacements.get(h)) for h in sorted(hours)]))
    result = [replacements.get(t, row) for t, row in indexed.items() if t not in quarantine]
    return result, ledger, dict(original_missing_hours=len(original_gaps),
        quarantined_hours=len(quarantine), newly_unavailable_hours=len(quarantine - original_gaps),
        unavailable_union_hours=len(original_gaps | quarantine),
        reconstructed_hours=len(replacements), original_observed_hours=len(indexed),
        derived_observed_hours=len(result))


def embargo_days(days, quarantined_blocks):
    """Intersect half-open [day-7d, day) with [block, block+4h)."""
    days = list(days)
    if len(set(days)) != len(days) or days != sorted(days):
        raise ValueError('duplicate or unordered scheduled days')
    for day in days:
        timestamp(day, DAY)
    blocks = {timestamp(t, BLOCK) for t in quarantined_blocks}
    return [day for day in days if any(t < day and t + BLOCK > day - 7 * DAY for t in blocks)]


def schedule_overlay(schedule, quarantined_blocks):
    """Keep every original day and ordered member list; add a separate gate."""
    blocked = set(embargo_days([s['known_at'] for s in schedule], quarantined_blocks))
    return [dict(schedule=deepcopy(s), new_entries_allowed=s['known_at'] not in blocked)
            for s in schedule]
