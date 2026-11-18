import copy
import math
import unittest
from tests import test_v9_decision as F
from v9 import risk_budget as R
from v8 import decision as D


class Budget(unittest.TestCase):
    def book(self):
        p=F.P.portfolio([F.P.book_position('old','HI',notional=50)])
        def prices(scale):
            price=100.; out=[]
            for i in range(F.P.N_BARS):
                price*=math.exp(scale*(1 if i%2 else -1))
                out.append([F.P.T0+i*F.P.DAY,price])
            return out
        p['returns'].update(HI=prices(.01),LO=prices(.02))
        return p

    def test_hand_computed_perfect_correlation_budget(self):
        p=self.book(); original=copy.deepcopy(p)
        a=R.allocate(p,'LO',1,.05,.005,1,{'old':1})
        self.assertEqual(a['status'],'TARGETED')
        self.assertAlmostEqual(a['risk_fraction'],.0025)
        self.assertAlmostEqual(a['actual_share'],.5)
        self.assertAlmostEqual(a['existing_contributions'][0]['actual_share'],.5)
        self.assertEqual(p,original)
        b=R.allocate(p,'LO',1,.05,.0025,.5,{'old':1})
        self.assertAlmostEqual(b['target_share'],.2)
        self.assertAlmostEqual(b['risk_fraction'],.000625)

    def test_cap_never_increases_and_parity_is_not_claimed(self):
        a=R.allocate(self.book(),'LO',1,.05,.0001,1,{'old':1})
        self.assertEqual(a['status'],'CAPPED');self.assertEqual(a['risk_fraction'],.0001)
        self.assertLess(a['actual_share'],a['target_share'])
        self.assertFalse(a['whole_book_parity']);self.assertFalse(a['existing_positions_changed'])

    def test_missing_stale_duplicate_constant_and_future_history(self):
        p=self.book(); baseline=R.allocate(p,'LO',1,.05,.005,1,{'old':1})
        future=copy.deepcopy(p);future['returns']['LO'].append([p['as_of'],999999.])
        self.assertEqual(baseline,R.allocate(future,'LO',1,.05,.005,1,{'old':1}))
        for mutation in ('missing','stale','duplicate','constant'):
            q=copy.deepcopy(p)
            if mutation=='missing':q['returns'].pop('LO')
            if mutation=='stale':q['returns']['LO']=q['returns']['LO'][:-2]
            if mutation=='duplicate':q['returns']['LO'].append(q['returns']['LO'][-1])
            if mutation=='constant':q['returns']['LO']=[[t,100.] for t,_ in q['returns']['LO']]
            self.assertEqual(R.allocate(q,'LO',1,.05,.005,1,{'old':1})['status'],'UNAVAILABLE',mutation)

    def test_unknown_tier_and_invalid_inputs_fail_closed(self):
        self.assertEqual(R.allocate(self.book(),'LO',1,.05,.005,1,{})['reason'],'EXISTING_TIER_UNKNOWN')
        for bad in (True,None,float('nan'),float('inf'),10**1000,-.1,0):
            self.assertEqual(R.allocate(self.book(),'LO',1,.05,bad,1,{'old':1})['status'],'UNAVAILABLE')

    def test_single_position_retains_tier_cap_with_valid_volatility(self):
        p=self.book();p['positions']=[]
        a=R.allocate(p,'LO',1,.05,.0025,.5,{})
        self.assertEqual(a['status'],'SINGLE_POSITION');self.assertEqual(a['risk_fraction'],.0025)

    def test_engine_uses_reduced_proposal_and_phase10_limits(self):
        p=self.book()
        s=F.snap({'LO':[F.P.sig('REQ')]},book=p['positions'])
        s['portfolio']=p
        doc=D.build(s);c=F.cand(doc,'LO','REQ')
        self.assertAlmostEqual(c['proposal']['risk_fraction'],.0025)
        self.assertEqual(c['risk_budget']['status'],'TARGETED')
        self.assertAlmostEqual(c['proposal']['size_multiplier'],.5)
        self.assertEqual(c['proposal']['tier_size_multiplier'],1)
        self.assertEqual(s['portfolio'],p)
        self.assertAlmostEqual(c['proposal']['risk_fraction'],c['proposal']['stop_risk'])

    def test_missing_volatility_never_falls_back_to_original_size(self):
        s=F.snap({'LO':[F.P.sig('REQ')]});s['portfolio']['returns'].pop('LO')
        c=F.cand(D.build(s),'LO','REQ')
        self.assertIsNone(c['proposal']['risk_fraction']);self.assertNotEqual(c['state'],D.TRADE)

    def test_malformed_existing_identity_cannot_crash_sizing(self):
        p=self.book();p['positions'][0]['id']=['invalid']
        s=F.snap({'LO':[F.P.sig('REQ')]},book=p['positions']);s['portfolio']=p
        c=F.cand(D.build(s),'LO','REQ')
        self.assertIsNone(c['proposal']['risk_fraction']);self.assertNotEqual(c['state'],D.TRADE)


if __name__=='__main__':unittest.main()
