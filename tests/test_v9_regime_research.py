"""All five D5 definitions on invented values; no market data or outcomes."""
import copy
from decimal import Decimal, localcontext
import unittest
from tools.v9 import regime_research as R

D=R.DAY


def row(feature, end, value, available=None, digest='a'*64):
    return dict(feature=feature,period_end=end,available_at=end if available is None else available,
                value=str(value),source_sha256=digest)


class Regimes(unittest.TestCase):
    def test_btc_complete_window_exact_boundary_and_missing_day(self):
        rows=[row('btc_close',i*D,'100') for i in range(1,201)]
        self.assertEqual(R.Inputs(rows).at('BTC_ABOVE_SMA200',200*D+1)['state'],'OFF')
        rows[-1]['value']='100.000000000000000000000000000000000001'
        with localcontext() as c:
            c.prec=4
            self.assertEqual(R.Inputs(rows).at('BTC_ABOVE_SMA200',200*D+1)['state'],'ON')
        self.assertEqual(R.Inputs(rows[1:]).at('BTC_ABOVE_SMA200',200*D+1)['state'],'UNKNOWN')

    def test_late_revisions_future_observations_and_exact_cutoff_do_not_leak(self):
        base=[row('fear_greed',D,'40',D+1)]
        revised=base+[row('fear_greed',D,'90',D+10,digest='b'*64),row('fear_greed',2*D,'99')]
        for cutoff in (D+1,D+2,D+10):
            self.assertEqual(R.Inputs(base).at('FEAR_GREED_AT_LEAST_50',cutoff),
                             R.Inputs(revised).at('FEAR_GREED_AT_LEAST_50',cutoff))
        result=R.Inputs(revised).at('FEAR_GREED_AT_LEAST_50',D+11)
        self.assertEqual(result['state'],'ON')
        self.assertEqual(result['observation_refs'][0]['source_sha256'],'b'*64)

    def test_all_thresholds_and_staleness(self):
        cases=[('dvol','DVOL_AT_LEAST_60','60','59'),
               ('etf_net_flow','ETF_POSITIVE_FLOW','0.1','0'),
               ('fear_greed','FEAR_GREED_AT_LEAST_50','50','49')]
        for feature, regime, on, off in cases:
            for value,state in ((on,'ON'),(off,'OFF')):
                self.assertEqual(R.Inputs([row(feature,D,value)]).at(regime,D+1)['state'],state)
            self.assertEqual(R.Inputs([row(feature,D,on)]).at(regime,D+R.DEFINITIONS[regime][1]+1)['state'],'UNKNOWN')
        rows=[row('stablecoin_supply',D,'100'),row('stablecoin_supply',31*D,'101')]
        self.assertEqual(R.Inputs(rows).at('STABLECOIN_30D_GROWTH',31*D+1)['state'],'ON')
        self.assertEqual(R.Inputs(rows[1:]).at('STABLECOIN_30D_GROWTH',31*D+1)['state'],'UNKNOWN')

    def test_invalid_observations_and_ambiguous_revisions_rejected(self):
        good=row('dvol',D,'60')
        for change in ({'available_at':D-1},{'period_end':True},{'value':'NaN'},
                       {'value':'-1'},{'source_sha256':'bad'},{'feature':'other'}):
            with self.assertRaises(ValueError): R.Inputs([dict(good,**change)])
        with self.assertRaisesRegex(ValueError,'ambiguous'): R.Inputs([good,dict(good,value='61')])
        with self.assertRaises(ValueError): R.Inputs([row('fear_greed',D,'101')])

    def test_report_conserves_all_trades_and_missing_outcomes_without_authority(self):
        observations=[row('fear_greed',D,'60')]
        trades=[dict(id='first',signal_time=D,net_R=None),dict(id='second',signal_time=D+1,net_R='0'),
                dict(id='third',signal_time=D+2,net_R='-2')]
        before=copy.deepcopy((observations,trades))
        report=R.report(observations,trades,protocol_sha256='c'*64)
        self.assertEqual((observations,trades),before)
        for groups in report['groups'].values():
            self.assertEqual(sum(x['trades'] for x in groups.values()),3)
            self.assertEqual(sum(x['missing_returns'] for x in groups.values()),1)
            self.assertEqual(sum(Decimal(x['observed_net_R_sum'] or '0') for x in groups.values()),Decimal(-2))
        self.assertEqual(report['groups']['FEAR_GREED_AT_LEAST_50']['UNKNOWN']['observed_net_R_sum'],None)
        self.assertFalse(report['live_regime_gating_authorized'])
        self.assertFalse(report['statistical_confirmation'])
        with self.assertRaises(ValueError): R.report([],trades+trades[:1],protocol_sha256='c'*64)

    def test_empty_and_work_budget_remain_explicit(self):
        self.assertEqual(R.report([],[],protocol_sha256='a'*64)['baseline_trades'],0)
        with self.assertRaisesRegex(ValueError,'join-work'):
            R.report([{}]*10000,[{}]*501,protocol_sha256='a'*64)
