"""A02/A07/A08: exact proposal, shared time authority and truthful diagnostic labels."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests import test_v8_phase11 as P
from v8 import decision as DE

ROOT = Path(__file__).resolve().parents[1]
JS_ROOT = Path(os.environ.get('ACCURACY_DESK_ROOT', ROOT))
NODE = shutil.which('node')
RUNNER = r'''
const D=require(process.argv[2]), TA=require(process.argv[3]);
const F=JSON.parse(require('fs').readFileSync(process.argv[4],'utf8'));
const out=F.map(x=>{
  const a=TA.decide(Object.assign({coin:'HI',price:151,now:x.now,src:{decision:x.doc}}, x.input||{}));
  const sec=D.section(x.doc,'best_trades_now',x.now);
  const html=require('fs').readFileSync(require('path').join(require('path').dirname(process.argv[3]),'analyze.html'),'utf8');
  const ai=html.slice(html.indexOf('function aiPayload()'),html.indexOf('const AI_SYSTEM'));
  const payload=a.plan ? require('vm').runInNewContext(ai+'\naiPayload()', {TA, S:{call:a,coin:'HI',tf:'1h',data:{exchange:'context'},all:{}},
    A:()=>({price:151,chgDay:0,bias:0,parts:[],zones:{support:[],resistance:[]}}), sigName:s=>s.name, TFS:[], PK:null}) : null;
  return {status:D.authority(x.doc,x.now).status, verdict:a.verdict, plan:a.plan, headline:a.headline, payload,
    panel:D.views.assetPanel(x.doc,'HI',x.now,a), today:D.views.today(x.doc,x.now), best:sec.items.length};
});
process.stdout.write(JSON.stringify(out));
'''

def doc():
    return DE.build(P.snapshot([P.rec('HI')], {'HI':[P.sig()]}))

def run(cases):
    with tempfile.TemporaryDirectory() as t:
        f=Path(t)/'f.json'; j=Path(t)/'r.js'
        f.write_text(json.dumps(cases),encoding='utf8'); j.write_text(RUNNER,encoding='utf8')
        r=subprocess.run([NODE,str(j),str(JS_ROOT/'desk.js'),str(JS_ROOT/'analyze.js'),str(f)],
                         capture_output=True,encoding='utf8',timeout=60)
        if r.returncode: raise AssertionError(r.stderr)
        return json.loads(r.stdout)

@unittest.skipUnless(NODE,'node unavailable')
class Consumers(unittest.TestCase):
    def test_exact_governed_proposal_and_all_custom_fields(self):
        d=doc(); c=next(c for c in d['candidates'] if c['state']=='TRADE'); p=c['proposal']
        self.assertEqual(p['risk_fraction'],.005)
        variants=[{}, {'risk':.1}, {'account':p['equity']*2}, {'entry':p['mark']+1},
                  {'stop':p['stop']-1}, {'size':p['notional']*2}, {'leverage':p['leverage']*2},
                  {'proposal':{'risk_fraction':.1}}, {'proposal':copy.deepcopy(p)}]
        rows=run([{'doc':d,'now':P.AS_OF+60,'input':x} for x in variants])
        for i in (0,8):
            self.assertEqual(rows[i]['verdict'],'LONG'); q=rows[i]['plan']
            for key,other in [('entry','mark'),('stop','stop'),('size','notional'),('lev','leverage'),
                              ('equity','equity'),('riskUsd','stop_risk_usd')]:
                self.assertEqual(q[key],p[other])
            self.assertEqual(q['costs'],{'fees':p['expected_fees'],'slippage':p['expected_slippage']})
            self.assertEqual(rows[i]['payload']['plan']['proposal'],p)
        for r in rows[1:8]:
            self.assertEqual(r['verdict'],'WAIT'); self.assertIsNone(r['plan'])
            self.assertIn('Custom proposal not evaluated by the governed risk engine.',r['headline'])
            self.assertNotIn('Every governed gate passes',r['headline'])
            self.assertNotIn('every required desk gate passes',r['panel'])
            self.assertNotIn('All required desk gates currently pass',r['panel']['html'])
            self.assertNotIn('is-trade',r['panel']['html'])
        s=P.snapshot([P.rec('HI')],{'HI':[P.sig()]})
        s['sizing']['risk_per_trade']=.1; s['portfolio']['sizing']['risk_per_trade']=.1
        larger=DE.build(s); c=next(c for c in larger['candidates'] if c['type']==DE.DIRECTIONAL)
        self.assertEqual(c['state'],'AVOID'); self.assertIn('PORTFOLIO_LIMIT_BREACHED',c['blockers'])

    def test_document_time_boundaries_shared_by_today_and_analyzer(self):
        d=doc()
        empty=DE.build(P.snapshot([P.rec('HI')],{}))
        self.assertEqual(run([{'doc':empty,'now':empty['as_of']-1}])[0]['status'],'MALFORMED')
        for now,status,actionable in [(d['as_of']-1,'MALFORMED',False),(d['as_of'],'AVAILABLE',True),
                (d['as_of']+60,'AVAILABLE',True),(d['valid_until']+1,'STALE',False)]:
            with self.subTest(now=now):
                r=run([{'doc':d,'now':now}])[0]; self.assertEqual(r['status'],status)
                self.assertEqual(r['verdict']=='LONG',actionable)
                if not actionable: self.assertNotIn('data-state="TRADE"',json.dumps(r['today']))
        bad=copy.deepcopy(d); bad['valid_until']=bad['as_of']-1
        self.assertEqual(run([{'doc':bad,'now':P.AS_OF}])[0]['status'],'MALFORMED')

    def test_candidate_window_invalid_future_expired_and_equal(self):
        d=doc(); c=next(c for c in d['candidates'] if c['type']==DE.DIRECTIONAL); now=P.AS_OF+60
        variants=[{'valid_from':P.AS_OF,'as_of':now+1},{'valid_from':now+1},{'as_of':now+1},{'valid_until':'later'},
                  {'valid_until':d['valid_until']+1},{'valid_until':d['as_of']-1},
                  {'valid_until':now-1},{'valid_until':now}]
        for v in variants:
            dd=copy.deepcopy(d); next(x for x in dd['candidates'] if x['id']==c['id']).update(v)
            r=run([{'doc':dd,'now':now}])[0]
            if v==variants[-1]: self.assertEqual(r['verdict'],'LONG')
            else:
                self.assertEqual(r['verdict'],'WAIT'); self.assertEqual(r['best'],0)
                self.assertNotIn('data-state="TRADE"',json.dumps(r['today']))

    def test_watch_avoid_holdover_and_missing_never_promoted(self):
        for sid in ('TSMOM','DIS'):
            d=DE.build(P.snapshot([P.rec('HI')],{'HI':[P.sig(sid)]}))
            r=run([{'doc':d,'now':P.AS_OF+60,'input':{'risk':.1,'account':50000}}])[0]
            self.assertIn(r['verdict'],('WATCH','AVOID')); self.assertIsNone(r['plan'])
        d=doc(); c=next(x for x in d['candidates'] if x['state']=='TRADE'); del c['proposal']
        r=run([{'doc':d,'now':P.AS_OF+60}])[0]; self.assertEqual(r['verdict'],'WAIT')

    def test_browser_uses_immutable_plan_and_diagnostic_copy(self):
        a=(ROOT/'analyze.html').read_text(encoding='utf8')
        self.assertIn('Exact governed proposal',a)
        self.assertNotIn('account: acct(), risk: riskPct(), src: SRC',a)
        picks=(ROOT/'picks.html').read_text(encoding='utf8')
        self.assertNotIn('Trade only "Ready"',picks); self.assertNotIn('✓ Proven',picks)
        self.assertNotIn('" trades" + (SIDE',picks); self.assertIn('watchlist scores',picks)
        for name in ('picks.html','quant.html','smart.html','index.html'):
            self.assertIn('diagnostic',(ROOT/name).read_text(encoding='utf8').lower())
        import dashboard
        t={'n':10,'R':.1,'ret':.01,'win':.5,'years':{'2025':{'R':.1}}}
        result=dashboard.picks_accuracy({}, {'swing':{'long':{'ready':t},'short':{'ready':t}}})[0]
        self.assertEqual(result['verdict'],'Unqualified historical result')
