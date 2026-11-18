import copy
import random
import unittest
from tools.v9 import control_execution as E, verify_control_prices as V


class Prices(unittest.TestCase):
    def audit(self,rows,direction=1,geometry=None,eligible=True,disputes=(),end=10*14400):
        geometry=geometry or dict(stop=.02,target=2.,trail=.01,be=1.,hold=3)
        outcome=E.simulate(rows,0,direction,geometry,eligible,disputes,end)
        V.verify(rows,0,direction,geometry,eligible,disputes,end,outcome)
        return outcome

    def test_stop_target_time_and_gap_both_sides(self):
        for side in (-1,1):
            for h,l in ((110,90),(101,99),(106,99),(101,94)):
                rows={0:dict(o=100,h=h,l=l,c=100,qv=1),14400:dict(o=90,h=91,l=89,c=90,qv=1)}
                self.audit(rows,side)
                self.audit(rows,side,dict(stop=.2,target=0.,trail=0.,be=0.,hold=1))

    def test_missing_zero_disputed_malformed_and_terminal(self):
        good=dict(o=100,h=101,l=99,c=100,qv=1)
        for rows,disputes,end in [({},(),14400),({0:dict(good,qv=0)},(),14400),({0:good},(0,),14400),
                                 ({0:dict(good,c=None)},(),14400),({0:good},(),0),({0:good},(),14400)]:
            self.audit(rows,disputes=disputes,end=end)
        self.audit({},eligible=False)

    def test_next_bar_trailing_and_breakeven(self):
        for side in (-1,1):
            rows={0:dict(o=100,h=103,l=97,c=102 if side==1 else 98,qv=1),
                  14400:dict(o=102 if side==1 else 98,h=103,l=97,c=100,qv=1)}
            for trail,be in ((.01,0.),(0.,.5)):
                self.audit(rows,side,dict(stop=.05,target=0.,trail=trail,be=be,hold=2))

    def test_tampered_exit_cost_status_and_authority(self):
        rows={0:dict(o=100,h=101,l=99,c=100,qv=1)};g=dict(stop=.02,target=0.,trail=0.,be=0.,hold=1)
        good=self.audit(rows,geometry=g)
        for key,value in [('cost_R',0.),('exit_price',101.),('reason','TARGET'),('net_R',1.),('promotion_authority',True)]:
            bad=copy.deepcopy(good);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):V.verify(rows,0,1,g,True,(),144000,bad)

    def test_seeded_varied_paths_and_future_invariance(self):
        rng=random.Random(842)
        for _ in range(200):
            rows={i*14400:dict(o=(p:=rng.uniform(90,110)),h=p+rng.random()*8,l=p-rng.random()*8,
                              c=p,qv=1) for i in range(5)}
            g=dict(stop=rng.choice([.01,.03,.1]),target=rng.choice([0.,1.,3.]),
                   trail=rng.choice([0.,.01]),be=rng.choice([0.,1.]),hold=5)
            for side in (-1,1):
                outcome=self.audit(rows,side,g)
                rows[10*14400]=dict(o=999,h=999,l=999,c=999,qv=1)
                V.verify(rows,0,side,g,True,(),144000,outcome)
