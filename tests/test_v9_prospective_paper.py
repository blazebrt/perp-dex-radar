"""Synthetic prospective lifecycle; no market data, publication or orders."""
from contextlib import closing
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest

from v9 import prospective_paper as P
from v9 import paper_history as H


def sources(at=100, state='TRADE', tier='PROBATION', direction=1):
    candidate = dict(id='candidate', type='DIRECTIONAL_STRATEGY', state=state,
                     asset='BTC', strategy='X', direction=direction, authority_tier=tier,
                     valid_until=300, proposal=dict(mark=100, stop=90 if direction == 1 else 110,
                                                  hold_hours_remaining=1, risk_fraction=0.005),
                     trace=[dict(step='SIGNAL', result='PASS', input=dict(bar_close_t=90))])
    decision = dict(schema='v8.decision/1', as_of=at, valid_until=300, strategy_tiers={},
                    policy_hash='a'*64, implementation_hash='b'*64, candidates=[candidate])
    raw = {P.PATHS[1]: H.canonical(decision), P.PATHS[2]: H.canonical(dict(open=[], closed=[]))}
    ref = lambda path: dict(path=path, bytes=len(raw[path]), sha256=H.sha(raw[path]))
    raw[P.PATHS[0]] = H.canonical(dict(manifest=dict(ts=at, decision=dict(status='OK', file=ref(P.PATHS[1]))),
                                     legacy_output_refs=[ref(P.PATHS[2])]))
    return {k: v.decode() for k, v in raw.items()}


def auth(**kwargs):
    return dict(contract=P.CONTRACT, action='authorize', at=100, candidate='candidate',
                sources=sources(**kwargs), venue='synthetic', instrument='BTC-PERP')


def quote(at, bid='99', ask='101', **kwargs):
    return H.canonical(dict(schema='v9.paper-quote/1', as_of=at, received_at=at,
                            venue='synthetic', instrument='BTC-PERP', asset='BTC',
                            bid=bid, ask=ask, **kwargs)).decode()


def event(action, key, at, **kwargs):
    return dict(contract=P.CONTRACT, action=action, key=key, at=at, **kwargs)


class ProspectiveLedger(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ledger.sqlite'

    def enter(self, direction=1):
        key = P.apply(self.path, auth(direction=direction))['key']
        e = event('enter', key, 110, sources=sources(at=105, direction=direction), quote=quote(109))
        result = P.apply(self.path, e)
        return key, e, result

    def test_lifecycle_exact_retry_reopen_exit_and_unknown_net(self):
        key, entered, result = self.enter()
        self.assertEqual(result['entry']['entry']['price'], '101')
        self.assertEqual(result['entry']['entry']['tier'], 'PROBATION')
        self.assertGreater(result['entry']['entry']['at'], result['entry']['authorized_at'])
        self.assertEqual(P.apply(self.path, entered)['status'], 'ALREADY_RETAINED')
        P.apply(self.path, event('observe', key, 120, quote=quote(120)))
        P.apply(self.path, event('observe', key, 130, quote=quote(130, '88', '90')))
        report = P.inspect(self.path)
        self.assertEqual(report['events'], 4)
        item = report['entries'][key]
        self.assertEqual(item['exit']['reason'], 'OBSERVED_STOP')
        self.assertEqual(item['exit']['price'], '88')  # gap executes at observed price, never at stop
        for field in ('net_R', 'funding', 'actual_costs'):
            self.assertIsNone(item[field])
        self.assertFalse(report['production_qualified'])
        self.assertFalse(report['trade_authorization'])
        self.assertEqual(P.apply(self.path, entered)['status'], 'ALREADY_RETAINED')
        self.assertEqual(P.inspect(self.path)['entries'][key]['status'], 'CLOSED')

    def test_short_and_time_exit_without_claiming_continuous_monitoring(self):
        key, _, result = self.enter(direction=-1)
        self.assertEqual(result['entry']['entry']['price'], '99')
        P.apply(self.path, event('observe', key, 3710, quote=quote(3710, '95', '97')))
        item = P.inspect(self.path)['entries'][key]
        self.assertEqual(item['exit']['reason'], 'OBSERVED_TIME_EXIT')
        self.assertEqual(item['exit']['price'], '97')

    def test_bad_authority_sources_and_ambiguous_candidate_never_retained(self):
        for kwargs in (dict(state='WATCH'), dict(tier='LEGACY'), dict(at=101)):
            with self.assertRaises(ValueError): P.apply(self.path, auth(**kwargs))
        bad = auth(); bad['sources'][P.PATHS[1]] += ' '
        with self.assertRaisesRegex(ValueError, 'binding'): P.apply(self.path, bad)
        bad = auth(); bad['sources'][P.PATHS[2]] = '{}'
        with self.assertRaises(ValueError): P.apply(self.path, bad)
        self.assertEqual(P.inspect(self.path)['events'], 0)

    def test_future_stale_crossed_wrong_instrument_and_replayed_quotes(self):
        key = P.apply(self.path, auth())['key']
        for raw in (quote(100), quote(112), quote(109, '102', '101'), quote(109, '0', '101'),
                    quote(109).replace('BTC-PERP', 'OTHER')):
            with self.assertRaises(ValueError):
                P.apply(self.path, event('enter', key, 110, sources=sources(), quote=raw))
        with self.assertRaises(ValueError):
            P.apply(self.path, event('enter', key, 150, sources=sources(), quote=quote(109)))
        self.assertEqual(P.inspect(self.path)['events'], 1)
        P.apply(self.path, event('enter', key, 110, sources=sources(), quote=quote(109)))
        with self.assertRaises(ValueError):
            P.apply(self.path, event('observe', key, 111, quote=quote(109)))

    def test_demotion_expiry_cancel_duplicate_signal_and_atomic_failure(self):
        key = P.apply(self.path, auth())['key']
        for kwargs in (dict(state='AVOID'), dict(tier='FULL')):
            with self.assertRaises(ValueError):
                P.apply(self.path, event('enter', key, 110, sources=sources(**kwargs), quote=quote(109)))
        with self.assertRaises(ValueError):
            P.apply(self.path, event('cancel', key, 110, reason='EXPIRED'))
        with self.assertRaises(ValueError):
            P.apply(self.path, event('enter', key, 300, sources=sources(), quote=quote(299)))
        P.apply(self.path, event('cancel', key, 300, reason='EXPIRED'))
        again = auth(); again['at'] = 301
        with self.assertRaises(ValueError): P.apply(self.path, again)
        self.assertEqual(P.inspect(self.path)['events'], 2)
        self.assertEqual(P.inspect(self.path)['entries'][key]['status'], 'CANCELLED')

    def test_chain_tampering_refused_and_read_only_inspection_does_not_create(self):
        self.enter()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE events SET body=? WHERE seq=1', (b'{}',))
        with self.assertRaisesRegex(ValueError, 'chain'): P.inspect(self.path)
        with self.assertRaises(ValueError): P.apply(self.path, auth())
        missing = Path(self.temp.name)/'missing.sqlite'
        with self.assertRaises(sqlite3.OperationalError): P.inspect(missing)
        self.assertFalse(missing.exists())

    def test_backwards_events_limits_and_missing_price_cancellation(self):
        key = P.apply(self.path, auth())['key']
        with self.assertRaises(ValueError): P.apply(self.path, event('cancel', key, 99, reason='MISSING_PRICE'))
        P.apply(self.path, event('cancel', key, 101, reason='MISSING_PRICE'))
        self.assertEqual(P.inspect(self.path)['entries'][key]['cancellation_reason'], 'MISSING_PRICE')
        with self.assertRaises(ValueError): P.number('1e100000000')

    def test_concurrent_retry_and_failed_transaction_keep_one_complete_event(self):
        P.apply(self.path, auth())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: P.apply(self.path, auth()), range(2)))
        self.assertTrue(all(r['status'] == 'ALREADY_RETAINED' for r in results))
        key = next(iter(P.inspect(self.path)['entries']))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            P.apply(self.path, event('cancel', key, 101, reason='MISSING_PRICE'))
        report = P.inspect(self.path)
        self.assertEqual(report['events'], 1)
        self.assertEqual(report['entries'][key]['status'], 'PENDING')


if __name__ == '__main__':
    unittest.main()
