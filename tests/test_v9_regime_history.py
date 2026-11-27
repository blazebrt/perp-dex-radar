"""Prospective history timing and all-feature disposition, synthetic only."""
import copy
import unittest
from unittest.mock import patch
from v9 import market as M
from v9.paper_history import canonical
from tools.v9 import regime_history as H, regime_research as R

D=R.DAY


def fixture():
    return dict(schema='v9.market-history/1',as_of=40*D,captured_at=40*D+10,
                source_status={s:'OK' for s in H.SOURCES.values()},
                source_fetched_at={s:40*D+5 for s in H.SOURCES.values()},
                regime=dict(sentiment=dict(value=60,as_of=40*D),
                            stablecoins=dict(total_usd=1000000,as_of=40*D),
                            etf_flows=dict(unit='USD millions',last_date=39*D,last_total_musd=-2.5)))


class History(unittest.TestCase):
    def test_three_observations_two_explicitly_unavailable_and_no_early_use(self):
        doc=fixture();result=H.adapt(canonical(doc))
        by={x['feature']:x for x in result['observations']}
        self.assertEqual(set(by),set(H.SOURCES))
        self.assertEqual(by['etf_net_flow']['value'],'-2500000.0')
        self.assertEqual(set(result['unavailable']),{'btc_close','dvol'})
        self.assertFalse(result['dataset_accepted'])
        self.assertFalse(result['live_regime_gating_authorized'])
        inputs=R.Inputs(result['observations'])
        self.assertEqual(inputs.at('FEAR_GREED_AT_LEAST_50',doc['captured_at'])['state'],'UNKNOWN')
        self.assertEqual(inputs.at('FEAR_GREED_AT_LEAST_50',doc['captured_at']+1)['state'],'ON')

    def test_old_history_never_receives_invented_availability(self):
        doc=fixture();del doc['captured_at'];del doc['source_fetched_at']
        result=H.adapt(canonical(doc))
        self.assertEqual(result['observations'],[])
        self.assertEqual(set(result['unavailable']),set(R.FEATURES))

    def test_failed_future_and_missing_fetch_times_do_not_become_observations(self):
        for mutate in (lambda d:d['source_status'].update({'alt.fng':'ERROR'}),
                       lambda d:d['source_fetched_at'].update({'alt.fng':40*D+11}),
                       lambda d:d['source_fetched_at'].pop('alt.fng'),
                       lambda d:d['regime']['sentiment'].update(as_of=40*D+6),
                       lambda d:d['regime']['sentiment'].update(value=True)):
            doc=fixture();mutate(doc);r=H.adapt(canonical(doc))
            self.assertIn('fear_greed',r['unavailable'])
            self.assertEqual(len(r['observations']),2)

    def test_flow_day_units_and_supply_grid_are_checked(self):
        for mutate in (lambda d:d['regime']['etf_flows'].update(unit='USD'),
                       lambda d:d['regime']['etf_flows'].update(last_date=40*D),
                       lambda d:d['regime']['stablecoins'].update(as_of=40*D-1)):
            doc=fixture();mutate(doc)
            self.assertEqual(len(H.adapt(canonical(doc))['observations']),2)

    def test_writer_preserves_fetch_times_without_changing_input_or_regime(self):
        doc=dict(as_of=40*D,assets={},regime=fixture()['regime'],
                 sources={s:dict(status='OK',fetched_at=40*D+5) for s in H.SOURCES.values()})
        original=copy.deepcopy(doc)
        with patch.object(M.time,'time',return_value=40*D+10):record=M.history_record(doc)
        self.assertEqual(doc,original)
        self.assertEqual(record['regime'],doc['regime'])
        self.assertEqual(record['captured_at'],40*D+10)
        self.assertEqual(len(H.adapt(canonical(record))['observations']),3)
