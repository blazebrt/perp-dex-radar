"""Truthful market context and source-bound retained paper performance."""
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_v9_audit_loading import node

ROOT = Path(__file__).resolve().parents[1]


class Context(unittest.TestCase):
    def test_missing_coin_does_not_invent_listing_status(self):
        report = node("const D=require('./desk.js');console.log(JSON.stringify([D.views.marketAsset(null,'BTC',100),D.views.marketAsset({schema:'v9.market/1',as_of:1,fresh_until:50,regime:{},assets:{},sources:{}},'<BTC>',100)]));")
        self.assertIn('unavailable', report[0])
        self.assertIn('does not establish whether it is listed', report[1])
        self.assertIn('&lt;BTC&gt;', report[1])
        self.assertNotIn('not a listed Hyperliquid perp', report[1])

    def test_complete_context_provenance_missing_zero_and_no_mutation(self):
        report = node(r'''
const D=require('./desk.js');
const m={schema:'v9.market/1',as_of:100,fresh_until:200,assets:{BTC:{mark:100,oracle:99,max_leverage:10,funding_8h:0,at_oi_cap:null,gate:{as_of:50,liq_long_24h_usd:0}}},
 regime:{stablecoins:{total_usd:123,chg_7d:0},sentiment:{as_of:25}},sources:{'alt.fng':{status:'OK',fetched_at:100},'<bad>':{status:'<error>',fetched_at:100}}};
const before=JSON.stringify(m),html=D.views.marketAsset(m,'BTC',201);
console.log(JSON.stringify({html,unchanged:before===JSON.stringify(m)}));
''')
        self.assertTrue(report['unchanged'])
        for text in ('oracle', 'not independent venue observations', 'cap status: unknown', 'Gate observation time',
                     'Sources and observation times', 'Observed UTC', 'Stablecoin supply', '(stale)', '&lt;bad&gt;', '&lt;error&gt;'):
            self.assertIn(text, report['html'])
        self.assertNotIn('<bad>', report['html'])


class Ledger(unittest.TestCase):
    def test_current_tier_never_relabels_historical_entries(self):
        report = node(r'''
const P=require('./performance.js');
const d={schema:'v8.decision/1',as_of:100,valid_until:200,strategy_tiers:{FULL:[],PROBATION:[{strategy:'X',sides:{long:{expectation:{out_of_sample_mean_R:0.2,out_of_sample_lower_95:0.1,out_of_sample_upper_95:0.3},forward_test:{closed:1,mean_R:-0.1,effective_from:90,experiment_id:'test'},forward_test_state:'ACTIVE'}}}]}};
const j={open:[{id:'o',s:'X',c:'BTC',d:1,t_in:95,r:10}],closed:[{id:'a',s:'X',c:'BTC',d:1,t_in:50,t_out:80,r:0},{id:'b',s:'Y',c:'ETH',d:-1,t_in:92,t_out:99,r:null}]};
const before=JSON.stringify([d,j]),m=P.model(d,j);
console.log(JSON.stringify({m,html:P.render(m,{},201),filtered:P.render(m,{strategy:'Y',state:'closed'},201),unchanged:before===JSON.stringify([d,j])}));
''')
        self.assertTrue(report['unchanged'])
        self.assertEqual({r['entryTier'] for r in report['m']['records']}, {'unrecorded'})
        self.assertIsNone(next(r for r in report['m']['records'] if r['state']=='open')['reportedR'])
        self.assertEqual(next(r for r in report['m']['records'] if r['id']=='a')['reportedR'], 0)
        for text in ('stale', 'not a complete lifetime ledger', '0.200 R', '-0.100 R', 'unqualified paper outcomes', 'unrecorded'):
            self.assertIn(text, report['html'])
        self.assertIn('showing 1', report['filtered'])

    def test_malformed_and_duplicate_journal_cannot_be_summarized(self):
        report = node(r'''
const P=require('./performance.js'),d={schema:'v8.decision/1',as_of:1};
const inputs=[null,{open:[],closed:null},{open:[null],closed:[]},{open:[{id:'x'}],closed:[{id:'x'}]}];
console.log(JSON.stringify(inputs.map(j=>{try{P.model(d,j);return false;}catch(e){return true;}})));
''')
        self.assertEqual(report, [True]*4)

    def test_untrusted_labels_are_escaped_and_unknown_results_stay_unknown(self):
        report = node(r'''
const P=require('./performance.js'),m=P.model({schema:'v8.decision/1',as_of:1,strategy_tiers:{}},{open:[],closed:[{id:'<script>',c:'<img>',s:'<svg>',r:true,execution:{state:'<bad>'}}]});
console.log(JSON.stringify(P.render(m)));
''')
        for raw in ('<script>', '<img>', '<svg>', '<bad>'):
            self.assertNotIn(raw, report)
        self.assertIn('&lt;script&gt;', report)
        self.assertIn('unavailable', report)
        self.assertNotIn('0.000 R', report)

    def test_real_hash_binding_rejects_mixed_scans_and_ambiguous_refs(self):
        report = node(r'''
const P=require('./performance.js'),C=require('node:crypto');
const d=Buffer.from(JSON.stringify({schema:'v8.decision/1',as_of:100,valid_until:200,strategy_tiers:{}})),j=Buffer.from(JSON.stringify({open:[],closed:[]}));
const ref=(b,path)=>({path,bytes:b.length,sha256:C.createHash('sha256').update(b).digest('hex')});
const audit={manifest:{decision:{file:ref(d,'data/v8/decision.json')}},legacy_output_refs:[ref(j,'data/quant_journal.json')]};
(async()=>{const out=[];
 for(const mode of ['valid','journalChanged','decisionChanged','duplicateRef','missingRef','invalidDecision']){
  const a=JSON.parse(JSON.stringify(audit));if(mode==='duplicateRef')a.legacy_output_refs.push(a.legacy_output_refs[0]);if(mode==='missingRef')a.legacy_output_refs=[];
  global.fetch=async path=>new Response(path.includes('quant_journal')?(mode==='journalChanged'?Buffer.from('{}'):j):(mode==='decisionChanged'?Buffer.from('{}'):d));
  try{await P.load({loadAudit:async()=>({status:'OK',data:a}),authority:()=>({status:mode==='invalidDecision'?'MALFORMED':'AVAILABLE'})});out.push(true);}catch(e){out.push(false);}
 }
 console.log(JSON.stringify(out));
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
        self.assertEqual(report, [True, False, False, False, False, False])

    def test_page_and_module_are_published_and_discoverable(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp:
            dashboard.publish(tmp)
            for name in ('performance.html','performance.js'):
                self.assertEqual((Path(tmp)/name).read_bytes(), (ROOT/name).read_bytes())
        self.assertIn('href="performance.html"', (ROOT/'portfolio.html').read_text(encoding='utf-8'))
        page=(ROOT/'performance.html').read_text(encoding='utf-8')
        self.assertIn('aria-live="polite"',page)
        self.assertIn('token!==request',page)
        self.assertIn("body.innerHTML=''",page)


if __name__ == '__main__':
    unittest.main()
