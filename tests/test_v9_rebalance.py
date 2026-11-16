import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from tests import test_v9_risk_budget as B
from tests import test_v9_decision as F
from v9 import risk_budget as R
from v8 import decision as D

ROOT = Path(__file__).resolve().parents[1]


def book():
    p = B.Budget().book()
    p['positions'].append(F.P.book_position('second','LO',notional=50))
    return p


class Rebalance(unittest.TestCase):
    def test_diagonal_covariance_has_analytic_inverse_volatility_solution(self):
        shape,b,_=R._budget_weights([[.0001,0,0],[0,.0004,0],[0,0,.0009]],[1,.25,1])
        self.assertAlmostEqual(shape[0]/shape[1],4)
        self.assertAlmostEqual(shape[0]/shape[2],3)
        self.assertAlmostEqual(b[1],1/9)

    def test_diversified_book_risk_shares_recomputed_from_price_paths(self):
        p=F.P.portfolio([F.P.book_position('a','HI',notional=80),
                         F.P.book_position('b','LO',notional=70),F.P.book_position('c','ALPHA',notional=90)])
        a=R.rebalance(p,{'a':1,'b':.5,'c':1});self.assertEqual(a['status'],'MODEL_WITHIN_LIMITS')
        columns=[]
        for row in a['positions']:
            values=[v for _,v in p['returns'][row['asset']]]
            ret=[math.log(y/x) for x,y in zip(values,values[1:])]
            mean=sum(ret)/len(ret);columns.append([v-mean for v in ret])
        combined=[sum(r['target_notional_usd']*col[k] for r,col in zip(a['positions'],columns)) for k in range(len(columns[0]))]
        total=sum(v*v for v in combined)
        for row,col in zip(a['positions'],columns):
            share=row['target_notional_usd']*sum(x*y for x,y in zip(col,combined))/total
            self.assertAlmostEqual(share,row['target_risk_share'],places=7)
            self.assertAlmostEqual(share,row['modeled_risk_share'],places=7)

    def test_unpayable_turnover_is_unavailable(self):
        p=book()
        for row in p['positions']:row['notional']=1e9
        a=R.rebalance(p,{'old':1,'second':1})
        self.assertEqual(a['reason'],'TURNOVER_COST_EXCEEDS_EQUITY');self.assertNotIn('positions',a)

    def test_whole_book_parity_costs_caps_and_original_book(self):
        p=book(); original=copy.deepcopy(p)
        a=R.rebalance(p,{'old':1,'second':1})
        self.assertEqual(a['status'],'MODEL_WITHIN_LIMITS');self.assertTrue(a['whole_book_parity'])
        self.assertFalse(a['trade_authorization']);self.assertEqual(p,original)
        rows=a['positions']
        self.assertAlmostEqual(rows[0]['target_notional_usd']/rows[1]['target_notional_usd'],2,places=6)
        for row in rows:
            self.assertAlmostEqual(row['modeled_risk_share'],.5,places=7)
            self.assertLessEqual(row['target_notional_usd'],row['current_notional_usd'])
            self.assertLessEqual(row['target_notional_usd']*.05/a['modeled_equity_after_costs'],.005)
        self.assertAlmostEqual(a['estimated_fees_usd'],a['turnover_usd']*.00045)
        self.assertAlmostEqual(a['estimated_slippage_usd'],a['turnover_usd']*.0005)
        self.assertAlmostEqual(a['modeled_equity_after_costs'],500-a['estimated_fees_usd']-a['estimated_slippage_usd'])
        self.assertEqual(a['phase10_after']['state'],'WITHIN_LIMITS')
        self.assertGreater(a['uniform_scale_steps'],0)  # costs consume cap headroom

    def test_probation_and_sides_and_order(self):
        p=book();a=R.rebalance(p,{'old':1,'second':.5})
        self.assertEqual(a['status'],'MODEL_WITHIN_LIMITS')
        self.assertAlmostEqual(a['positions'][0]['modeled_risk_share'],.8,places=7)
        self.assertAlmostEqual(a['positions'][1]['modeled_risk_share'],.2,places=7)
        p['positions'].reverse();self.assertEqual(a,R.rebalance(p,{'old':1,'second':.5}))
        for row in p['positions']:
            row.update(direction=-1,stop=105.)
        shorts=R.rebalance(p,{'old':1,'second':.5})
        self.assertEqual(shorts['status'],'MODEL_WITHIN_LIMITS')
        self.assertTrue(all(r['direction']==-1 for r in shorts['positions']))

    def test_missing_stale_degenerate_and_unactionable_never_get_targets(self):
        for case in ('missing','stale','constant','blocked','bad_id','bad_sizing','duplicate','missing_tier'):
            p=book();tiers={'old':1,'second':1}
            if case=='missing':p['returns'].pop('LO')
            if case=='stale':p['returns']['LO']=p['returns']['LO'][:-2]
            if case=='constant':p['returns']['LO']=[[t,100.] for t,_ in p['returns']['LO']]
            if case=='blocked':p['positions'][0]['actionability']='IDENTITY_BLOCKED'
            if case=='bad_id':p['positions'][0]['id']=['invalid']
            if case=='bad_sizing':p['sizing']='bad'
            if case=='duplicate':p['positions'][1]['id']='old'
            if case=='missing_tier':tiers.pop('old')
            a=R.rebalance(p,tiers)
            self.assertEqual(a['status'],'UNAVAILABLE',case);self.assertNotIn('positions',a)

    def test_future_invariance_and_bounded_nonconvergence(self):
        p=book();a=R.rebalance(p,{'old':1,'second':1})
        p['returns']['LO'].append([p['as_of'],999999.])
        self.assertEqual(a,R.rebalance(p,{'old':1,'second':1}))
        with patch.dict(R.REBALANCE_NUMERICS,max_sweeps=0):
            b=R.rebalance(p,{'old':1,'second':1})
            self.assertEqual(b['reason'],'PARITY_DID_NOT_CONVERGE')
        with patch.dict(R.REBALANCE_NUMERICS,max_positions=1):
            self.assertEqual(R.rebalance(p,{'old':1,'second':1})['reason'],'POSITION_RESOURCE_LIMIT')
        with patch.dict(R.REBALANCE_NUMERICS,max_scale_steps=0):
            self.assertEqual(R.rebalance(p,{'old':1,'second':1})['reason'],'NO_WITHIN_LIMITS_TARGET')

    def test_perfect_hedge_does_not_create_unlimited_capacity(self):
        p=book();p['positions'][1].update(asset='HI',direction=-1,stop=105.)
        a=R.rebalance(p,{'old':1,'second':1})
        self.assertEqual(a['status'],'UNAVAILABLE');self.assertFalse(a['whole_book_parity'])

    def test_engine_model_never_changes_actual_positions_or_candidate_sizes(self):
        p=book();s=F.snap({'ALPHA':[F.P.sig('REQ')]},book=p['positions']);s['portfolio']=p
        original=copy.deepcopy(s);a=D.build(s)
        self.assertEqual(a['portfolio']['rebalance']['status'],'MODEL_WITHIN_LIMITS')
        with patch.object(R,'rebalance',return_value={'status':'UNAVAILABLE'}):b=D.build(s)
        self.assertEqual(a['candidates'],b['candidates'])
        self.assertEqual(a['portfolio']['governed_positions'],b['portfolio']['governed_positions'])
        self.assertEqual(a['portfolio']['phase10'],b['portfolio']['phase10'])
        self.assertEqual(s,original)

    def test_empty_and_single_position(self):
        p=book();p['positions']=[]
        self.assertEqual(R.rebalance(p,{})['status'],'EMPTY')
        p=B.Budget().book();a=R.rebalance(p,{'old':1})
        self.assertEqual(a['status'],'MODEL_WITHIN_LIMITS')
        self.assertAlmostEqual(a['positions'][0]['modeled_risk_share'],1)

    @unittest.skipUnless(shutil.which('node'),'node unavailable')
    def test_page_rendering_escapes_labels_and_fails_closed(self):
        p=book();s=F.snap({},book=p['positions']);s['portfolio']=p;doc=D.build(s)
        docs=[copy.deepcopy(doc) for _ in range(4)]
        docs[0]['portfolio']['rebalance']['positions'][0]['asset']='<img src=x onerror=alert(1)>'
        docs[1]['portfolio']['rebalance']['estimated_slippage_usd']=None
        docs[2]['portfolio']['rebalance']['trade_authorization']=True
        code="const D=require('./desk.js');const ds=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(ds.map((d,i)=>D.views.portfolio(d,i===3?d.valid_until+1:d.as_of,null,'loading').body)));"
        out=subprocess.check_output([shutil.which('node'),'-e',code],cwd=ROOT,input=json.dumps(docs).encode())
        bodies=json.loads(out)
        self.assertIn('Whole-book balance model',bodies[0]);self.assertIn('&lt;img',bodies[0]);self.assertNotIn('<img src=x',bodies[0])
        self.assertIn('Estimated slippage',bodies[0]);self.assertIn('No orders are placed',bodies[0])
        for body in bodies[1:3]:self.assertIn('No verified balance target',body);self.assertNotIn('Model target',body)
        self.assertNotIn('Whole-book balance model',bodies[3])


if __name__=='__main__':unittest.main()
