"""Separate offline prospective paper ledger. No orders or production activation."""
import argparse
from contextlib import closing
from decimal import Decimal, localcontext
import json
from pathlib import Path
import re
import sqlite3

from v9 import paper_history as H

CONTRACT = 'v9.prospective-paper/1'
MAX_EVENT = 4 * 1024 * 1024
MAX_EVENTS = 10000
QUOTE_MAX_AGE = 30
PATHS = ('data/v8/audit_latest.json', 'data/v8/decision.json', 'data/quant_journal.json')


def stamp(value):
    H.require(type(value) is int and 0 < value < 100000000000, 'invalid UTC seconds')
    return value


def number(value):
    H.require(isinstance(value, str) and re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,18})?', value),
              'invalid positive decimal')
    result = Decimal(value)
    H.require(result > 0, 'nonpositive price')
    return result


def decision(sources, candidate_id, now):
    H.require(isinstance(sources, dict) and set(sources) == set(PATHS)
              and all(isinstance(x, str) for x in sources.values()), 'invalid sources')
    raw = {k: v.encode('utf-8') for k, v in sources.items()}
    # Reuse exact audit/decision/journal source binding; never trust a tier alone.
    H.package_sources(raw)
    audit, doc = H.decode(raw[PATHS[0]]), H.decode(raw[PATHS[1]])
    H.require(stamp(doc['as_of']) <= stamp(audit['manifest']['ts']) <= now,
              'decision or audit after observation')
    H.require(now < stamp(doc.get('valid_until')), 'expired decision')
    for key in ('policy_hash', 'implementation_hash'):
        H.require(isinstance(doc.get(key), str) and re.fullmatch('[a-f0-9]{64}', doc[key]),
                  'missing policy or implementation binding')
    candidates = doc.get('candidates')
    H.require(isinstance(candidates, list) and all(isinstance(c, dict) for c in candidates),
              'invalid candidates')
    matches = [c for c in candidates if c.get('id') == candidate_id]
    H.require(len(matches) == 1, 'ambiguous or missing candidate')
    c = matches[0]
    H.require(c.get('type') == 'DIRECTIONAL_STRATEGY' and c.get('state') == 'TRADE'
              and c.get('authority_tier') in ('FULL', 'PROBATION'), 'candidate not trade-ready')
    H.require(type(c.get('direction')) is int and c['direction'] in (-1, 1), 'invalid direction')
    H.require(all(isinstance(c.get(k), str) and c[k] for k in ('asset', 'strategy', 'id')),
              'invalid identity')
    H.require(now < stamp(c.get('valid_until')), 'expired candidate')
    trace = c.get('trace')
    H.require(isinstance(trace, list) and all(isinstance(g, dict) for g in trace), 'missing trace')
    H.require(not any(g.get('result') in ('FAIL', 'MISSING', 'CAP') for g in trace), 'contradictory failed gate')
    signals = [g for g in trace if g.get('step') == 'SIGNAL']
    H.require(len(signals) == 1 and signals[0].get('result') == 'PASS', 'missing signal gate')
    bar = stamp(signals[0]['input'].get('bar_close_t'))
    H.require(bar <= doc['as_of'], 'future signal')
    plan = c.get('proposal')
    H.require(isinstance(plan, dict), 'missing plan')
    mark, stop = number(str(plan.get('mark'))), number(str(plan.get('stop')))
    H.require(number(str(plan.get('risk_fraction'))) <= 1, 'invalid risk fraction')
    H.require((mark-stop)*c['direction'] > 0, 'invalid stop geometry')
    hold = plan.get('hold_hours_remaining')
    H.require(type(hold) is int and 0 < hold <= 8760, 'invalid holding period')
    key = H.sha(H.canonical([c['id'], bar]))
    return dict(key=key, candidate=c, signal_time=bar, decision_time=doc['as_of'],
                policy_hash=doc['policy_hash'], implementation_hash=doc['implementation_hash'],
                decision_sha256=H.sha(raw[PATHS[1]]),
                expires=min(doc['valid_until'], c['valid_until']))


def quote(raw, item, now, after):
    H.require(isinstance(raw, str), 'missing exact quote source')
    q = H.decode(raw.encode('utf-8'))
    H.require(isinstance(q, dict) and q.get('schema') == 'v9.paper-quote/1', 'invalid quote schema')
    H.require(q.get('venue') == item['venue'] and q.get('instrument') == item['instrument']
              and q.get('asset') == item['candidate']['asset'], 'quote identity mismatch')
    t, received = stamp(q.get('as_of')), stamp(q.get('received_at'))
    H.require(after < t <= received <= now and now-t <= QUOTE_MAX_AGE, 'noncausal or stale quote')
    bid, ask = number(q.get('bid')), number(q.get('ask'))
    H.require(bid <= ask, 'crossed quote')
    return q, bid, ask


def transition(state, event):
    """Replay exact inputs; derived state is never trusted from storage."""
    H.require(isinstance(event, dict) and event.get('contract') == CONTRACT, 'invalid event')
    now = stamp(event.get('at'))
    H.require(now >= state['last_at'], 'event time moved backwards')
    action = event.get('action')
    if action == 'authorize':
        item = decision(event.get('sources'), event.get('candidate'), now)
        key = item['key']
        H.require(key not in state['entries'], 'signal already registered')
        for field in ('venue', 'instrument'):
            H.require(isinstance(event.get(field), str) and 0 < len(event[field]) <= 128,
                      'missing explicit instrument mapping')
            item[field] = event[field]
        item.update(status='PENDING', authorized_at=now, entry=None, exit=None,
                    net_R=None, funding=None, actual_costs=None,
                    entry_authority='CAPTURED_DECISION_NOT_INDEPENDENTLY_QUALIFIED')
        state['entries'][key] = item
    else:
        key = event.get('key')
        H.require(key in state['entries'], 'unknown authorization')
        item = state['entries'][key]
        if action == 'cancel':
            H.require(item['status'] == 'PENDING', 'entry is not pending')
            H.require(event.get('reason') in ('EXPIRED', 'DEMOTED', 'MISSING_PRICE', 'OPERATOR_CANCELLED'),
                      'invalid cancellation reason')
            H.require(event['reason'] != 'EXPIRED' or now >= item['expires'], 'not expired')
            item.update(status='CANCELLED', cancelled_at=now, cancellation_reason=event['reason'])
        elif action == 'enter':
            H.require(item['status'] == 'PENDING' and now < item['expires'], 'not pending or expired')
            fresh = decision(event.get('sources'), item['candidate']['id'], now)
            H.require(fresh['key'] == key and fresh['decision_time'] >= item['decision_time']
                      and all(fresh[k] == item[k] for k in ('policy_hash', 'implementation_hash'))
                      and fresh['candidate']['authority_tier'] == item['candidate']['authority_tier'],
                      'authority changed before entry')
            H.require(all(fresh['candidate'][k] == item['candidate'][k] for k in ('asset', 'strategy', 'direction')),
                      'candidate identity changed')
            q, bid, ask = quote(event.get('quote'), item, now, item['authorized_at'])
            H.require(q['as_of'] >= fresh['decision_time'], 'quote predates authority recheck')
            direction = item['candidate']['direction']
            price = ask if direction == 1 else bid
            stop = number(str(item['candidate']['proposal']['stop']))
            H.require((price-stop)*direction > 0, 'quote has crossed the registered stop')
            item.update(status='OPEN', entry=dict(at=now, quote_time=q['as_of'], price=str(price),
                        quote_sha256=H.sha(event['quote'].encode()), tier=item['candidate']['authority_tier'],
                        authorization_time=item['authorized_at'], signal_time=item['signal_time']),
                        last_quote_time=q['as_of'],
                        deadline=now+item['candidate']['proposal']['hold_hours_remaining']*3600)
        elif action == 'observe':
            H.require(item['status'] == 'OPEN', 'entry is not open')
            q, bid, ask = quote(event.get('quote'), item, now, item['last_quote_time'])
            direction = item['candidate']['direction']
            price = bid if direction == 1 else ask
            stop = number(str(item['candidate']['proposal']['stop']))
            reason = 'OBSERVED_STOP' if (price-stop)*direction <= 0 else ('OBSERVED_TIME_EXIT' if now >= item['deadline'] else None)
            item['last_quote_time'] = q['as_of']
            if reason:
                item.update(status='CLOSED', exit=dict(at=now, quote_time=q['as_of'], price=str(price),
                            reason=reason, quote_sha256=H.sha(event['quote'].encode())))
                with localcontext() as ctx:
                    ctx.prec = 80
                    item['gross_price_return'] = str(direction*(price/Decimal(item['entry']['price'])-1))
        else:
            raise ValueError('unknown action')
    state['last_at'] = now
    return key


def replay(connection):
    count, total = connection.execute('SELECT count(*), coalesce(sum(length(body)), 0) FROM events').fetchone()
    H.require(count <= MAX_EVENTS and total <= 64*1024*1024, 'ledger retention limit exceeded')
    rows = connection.execute('SELECT seq, body, previous, digest FROM events ORDER BY seq')
    state = dict(last_at=0, entries={})
    previous = '0'*64
    for seq, body, prior, digest in rows:
        H.require(seq == state.get('count', 0)+1 and isinstance(body, bytes) and len(body) <= MAX_EVENT,
                  'invalid event inventory')
        H.require(prior == previous and digest == H.sha(previous.encode()+body), 'event chain mismatch')
        transition(state, H.decode(body))
        state['count'] = seq
        previous = digest
    return state, previous, count


def apply(path, event):
    """Atomic local retention before returning success; identical retries are no-ops."""
    body = H.canonical(event)
    H.require(len(body) <= MAX_EVENT, 'event too large')
    with closing(sqlite3.connect(path, timeout=30)) as db, db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, body BLOB NOT NULL UNIQUE, previous TEXT NOT NULL, digest TEXT NOT NULL UNIQUE)')
        db.execute('BEGIN IMMEDIATE')
        state, previous, count = replay(db)
        if db.execute('SELECT 1 FROM events WHERE body=?', (body,)).fetchone():
            return dict(status='ALREADY_RETAINED', events=count, entries=state['entries'], trade_authorization=False)
        H.require(count < MAX_EVENTS, 'ledger event limit exceeded')
        total = db.execute('SELECT coalesce(sum(length(body)), 0) FROM events').fetchone()[0]
        H.require(total+len(body) <= 64*1024*1024, 'ledger retention limit exceeded')
        key = transition(state, event)
        db.execute('INSERT INTO events VALUES (?, ?, ?, ?)', (count+1, body, previous, H.sha(previous.encode()+body)))
    return dict(status='RETAINED', key=key, events=count+1, entry=state['entries'][key], trade_authorization=False)


def inspect(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')  # Pin count, byte budget and events to one concurrent-reader snapshot.
        state, digest, count = replay(db)
    return dict(schema=CONTRACT, events=count, head=digest, entries=state['entries'],
                trade_authorization=False, production_qualified=False, historical_completeness_verified=False,
                limitations=['Caller-supplied capture times and instrument mappings are not independently authenticated.',
                             'Quotes are observed paper prices, not fills or continuous stop monitoring.',
                             'Fees, slippage and funding are unknown; no net return or qualified performance is reported.',
                             'Local atomic retention is not remote durability or production qualification.'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True)
    p.add_argument('--event', help='Exact event JSON; omit for read-only verification')
    args = p.parse_args(argv)
    if args.event:
        with Path(args.event).open('rb') as stream:
            raw = stream.read(MAX_EVENT+1)
        H.require(len(raw) <= MAX_EVENT, 'event too large')
        result = apply(args.ledger, H.decode(raw))
    else:
        result = inspect(args.ledger)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
