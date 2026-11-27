"""Evidence-based ordering cannot grant authority or invent candidate forecasts."""
import copy
import unittest
from tests import test_v9_decision as F
from v8 import decision as D


class ExpectedR(unittest.TestCase):
    def fixture(self):
        low, high = F.prob_strategy(), F.prob_strategy()
        low['probation']['sides']['long']['expectation'].update(
            out_of_sample_mean_R=-0.1, out_of_sample_lower_95=-0.3, out_of_sample_upper_95=0.2)
        high['probation']['sides']['long']['expectation'].update(
            out_of_sample_mean_R=0.2, out_of_sample_lower_95=-0.2, out_of_sample_upper_95=0.5)
        strategies=F.strats(); strategies.update(LOW=low, HIGH=high)
        return F.snap({'HI':[F.P.sig('LOW',age=600)], 'LO':[F.P.sig('HIGH',age=1200)],
                       'BTC':[F.P.sig('REQ',age=300)]}, strategies=strategies)

    def test_expected_return_precedes_age_and_unknown_is_not_zero(self):
        doc=D.build(self.fixture())
        self.assertEqual([r['asset'] for r in doc['best_trades_now']['items']], ['LO','HI','BTC'])
        high=F.cand(doc,'LO','HIGH'); missing=F.cand(doc,'BTC','REQ')
        self.assertEqual(high['ranking_expectation']['lower_95'],-0.2)
        self.assertFalse(high['ranking_expectation']['candidate_specific'])
        self.assertIsNone(missing['ranking_inputs']['expected_net_R'])
        trace=doc['best_trades_now']['selection_trace']['order']
        self.assertEqual(trace[0]['rule'],['expected_net_R','desc'])

    def test_ranking_changes_no_gate_proposal_or_portfolio(self):
        snap=self.fixture(); original=copy.deepcopy(snap)
        policy=D.load_policy(); old=copy.deepcopy(policy)
        old['ranking']['best_trades_now']['value']=old['ranking']['best_trades_now']['value'][1:]
        before,after=D.build(snap,old),D.build(snap,policy)
        for a,b in zip(before['candidates'],after['candidates']):
            for key in ('state','proposal','portfolio','authority_tier','blockers','caps','missing_authorities'):
                self.assertEqual(a.get(key),b.get(key),key)
        self.assertEqual(snap,original)

    def test_high_expectation_does_not_rescue_failed_forward_gate(self):
        s=self.fixture();s['forward_tests']=F.forward(n=10000,mean=-100)
        doc=D.build(s)
        c=F.cand(doc,'LO','HIGH')
        self.assertNotEqual(c['state'],D.TRADE)
        self.assertNotIn(c['id'],[r['id'] for r in doc['best_trades_now']['items']])

    def test_invalid_interval_and_binding_are_unknown(self):
        terms=copy.deepcopy(F.REAL_TERMS['sides']['long']);ev=F.REAL_TERMS['evidence']
        for bad in (True, float('nan'), float('inf'), 10**1000, '0.2', None):
            t=copy.deepcopy(terms);t['expectation']['out_of_sample_mean_R']=bad
            self.assertEqual(D._ranking_expectation(t,ev)['status'],'UNAVAILABLE')
        t=copy.deepcopy(terms);t['expectation']['out_of_sample_lower_95']=99
        self.assertEqual(D._ranking_expectation(t,ev)['status'],'UNAVAILABLE')
        for bad in (None,{},dict(ev,sha256='x'*64)):
            self.assertEqual(D._ranking_expectation(terms,bad)['status'],'UNAVAILABLE')

    def test_equal_estimates_use_existing_tiebreak_and_ignore_design_window(self):
        s=self.fixture()
        s['strategies']['HIGH']['probation']['sides']['long']['expectation']=copy.deepcopy(
            s['strategies']['LOW']['probation']['sides']['long']['expectation'])
        s['strategies']['HIGH']['probation']['sides']['long']['expectation']['all_windows_mean_R']=999
        doc=D.build(s)
        self.assertEqual([r['asset'] for r in doc['best_trades_now']['items']],['HI','LO','BTC'])
        e=F.cand(doc,'LO','HIGH')['ranking_expectation']
        self.assertEqual(e['mean_net_R'],-0.1)
        self.assertEqual(e['evidence'],F.REAL_TERMS['evidence'])


if __name__ == '__main__':
    unittest.main()
