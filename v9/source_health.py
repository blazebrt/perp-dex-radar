"""Read-only monitoring of all active v9 market sources; no decision authority."""
import argparse
import html
import json
import math
import os
from pathlib import Path
import time

SOURCES = ('hl.ctx', 'hl.predicted', 'hl.oicap', 'deribit.dvol.btc',
           'deribit.dvol.eth', 'alt.fng', 'llama.stable', 'cb.btc', 'bn.btc',
           'upbit.btc', 'fx.usd', 'bfx.longs', 'bfx.shorts', 'farside.etf',
           'cg.global', 'gate.stats')
FETCH_MAX_AGE = 7200
CLOCK_SKEW = 300
# Operational observation-age budgets, not statistical or trading thresholds.
OBSERVATIONS = {
    'deribit.dvol.btc': (('volatility', 'btc_dvol', 'as_of'), 7200),
    'deribit.dvol.eth': (('volatility', 'eth_dvol', 'as_of'), 7200),
    'alt.fng': (('sentiment', 'as_of'), 172800),
    'llama.stable': (('stablecoins', 'as_of'), 172800),
    'cg.global': (('global', 'as_of'), 7200),
    'bfx.longs': (('btc_margin', 'longs', 'as_of'), 7200),
    'bfx.shorts': (('btc_margin', 'shorts', 'as_of'), 7200),
    # Calendar-day allowance includes weekends/holidays; no business-day claim.
    'farside.etf': (('etf_flows', 'last_date'), 7 * 86400),
}


def number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def age_issue(stamp, now, budget):
    if not number(stamp) or stamp <= 0:
        return 'TIME_UNKNOWN'
    if stamp > now + CLOCK_SKEW:
        return 'FUTURE_TIME'
    if now - stamp > budget:
        return 'STALE'
    return None


def at(doc, keys):
    for key in keys:
        doc = doc.get(key) if isinstance(doc, dict) else None
    return doc


def evaluate(doc, now, collection_status="success"):
    if not number(now) or now <= 0:
        raise ValueError('invalid monitor time')
    issues = []
    if collection_status != "success":
        issues.append("COLLECTOR_NOT_SUCCESSFUL")
    if not isinstance(doc, dict) or doc.get('schema') != 'v9.market/1':
        doc = {}
        issues.append('INVALID_DOCUMENT')
    issue = age_issue(doc.get('as_of'), now, FETCH_MAX_AGE)
    if issue:
        issues.append('DOCUMENT_' + issue)
    expiry = doc.get('fresh_until')
    if not number(expiry) or not number(doc.get('as_of')) or not doc['as_of'] < expiry <= doc['as_of'] + FETCH_MAX_AGE:
        issues.append('INVALID_EXPIRY')
    elif now > expiry:
        issues.append('DOCUMENT_EXPIRED')
    sources = doc.get('sources')
    if not isinstance(sources, dict):
        sources = {}
        issues.append('INVALID_SOURCE_INVENTORY')
    rows = []
    for sid in sorted(set(SOURCES) | set(sources)):
        row = sources.get(sid)
        faults = []
        coverage = 'FETCH_ONLY'
        if sid not in SOURCES:
            faults.append('UNREGISTERED_SOURCE')
        if not isinstance(row, dict):
            row = {}
            faults.append('MISSING_SOURCE')
        status = row.get('status')
        optional = sid == 'cg.global' and status == 'MISSING_KEY'
        if not optional:
            if status != 'OK':
                faults.append('SOURCE_UNAVAILABLE')
            issue = age_issue(row.get('fetched_at'), now, FETCH_MAX_AGE)
            if issue:
                faults.append('FETCH_' + issue)
            if status == 'OK' and sid in OBSERVATIONS:
                path, budget = OBSERVATIONS[sid]
                coverage = 'OBSERVATION_AND_FETCH'
                issue = age_issue(at(doc.get('regime'), path), now, budget)
                if issue:
                    faults.append('OBSERVATION_' + issue)
            if status == 'OK' and sid == 'gate.stats':
                coverage = 'OBSERVATION_AND_FETCH'
                requested, answered = row.get('requested'), row.get('answered')
                if type(requested) is not int or type(answered) is not int or not 0 < answered <= requested:
                    faults.append('INVALID_COVERAGE')
                elif answered != requested:
                    faults.append('PARTIAL_COVERAGE')
                assets = doc.get('assets')
                observations = [v['gate'] for v in assets.values()
                                if isinstance(v, dict) and isinstance(v.get('gate'), dict)] if isinstance(assets, dict) else []
                if not observations or len(observations) != answered:
                    faults.append('OBSERVATION_COVERAGE_MISMATCH')
                for observation in observations:
                    issue = age_issue(observation.get('as_of'), now, 7200)
                    if issue:
                        faults.append('OBSERVATION_' + issue)
        rows.append(dict(source=sid, state='NOT_CONFIGURED' if optional else 'ALERT' if faults else 'OK',
                         coverage='NOT_CONFIGURED' if optional else coverage, issues=sorted(set(faults))))
    return dict(schema='v9.source-health/1', checked_at=now,
                status='ALERT' if issues or any(r['issues'] for r in rows) else 'OK',
                document_issues=issues, sources=rows, decision_authority=False,
                limitations=['FETCH_ONLY sources lack independently retained upstream observation times.',
                             'Monitoring checks timestamps and reported availability, not price accuracy.',
                             'No monitor can run when the workflow itself does not execute.'])


def escape_command(text):
    return str(text).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def emit(report):
    if report['document_issues']:
        print('::warning title=Market context monitor::' + ', '.join(report['document_issues']))
    for row in report['sources']:
        if row['issues']:
            print('::warning title=Market source monitor::' + escape_command(row['source'] + ': ' + ', '.join(row['issues'])))
    print('Market source monitor: ' + report['status'])
    lines = ['## Market source health', '', 'Result: **' + report['status'] + '**', '',
             '| Source | State | Coverage | Issues |', '|---|---|---|---|']
    def safe(value):
        return html.escape(str(value)).replace('|', '&#124;').replace('\r', ' ').replace('\n', ' ')
    for row in report['sources']:
        lines.append('| ' + ' | '.join(safe(v) for v in (row['source'], row['state'], row['coverage'], ', '.join(row['issues']) or 'none')) + ' |')
    lines += ['', 'Document issues: ' + (', '.join(report['document_issues']) or 'none'), '',
              *report['limitations'], '']
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines))


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--collection-status', default='success')
    args = parser.parse_args(argv)
    try:
        raw = Path(args.input).read_text(encoding='utf-8')
        doc = json.loads(raw, object_pairs_hook=strict_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except (OSError, UnicodeError, ValueError):
        doc = None
    report = evaluate(doc, int(time.time()), args.collection_status)
    Path(args.out).write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    emit(report)
    return int(report['status'] != 'OK')


if __name__ == '__main__':
    raise SystemExit(main())
