"""G2: the audit is compressed and absent from the Today critical path."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def node(script):
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class AuditLoading(unittest.TestCase):
    def test_compressed_audit_and_safe_fallbacks(self):
        report = node(r'''
const D = require('./desk.js'), z = require('node:zlib');
(async () => {
 const original = global.DecompressionStream, out = [];
 for (const mode of ['gzip', 'corrupt', 'missing', 'unsupported']) {
  const calls = []; global.DecompressionStream = mode === 'unsupported' ? undefined : original;
  global.fetch = async path => {
   calls.push(path);
   if (path.endsWith('.gz')) return mode === 'missing' ? new Response('', {status:404}) :
    new Response(mode === 'corrupt' ? Buffer.from('bad gzip') : z.gzipSync(JSON.stringify({bound:42})));
   return new Response(JSON.stringify({bound:42}));
  };
  out.push({mode, calls, result:await D.loadAudit()});
 }
 console.log(JSON.stringify(out));
})().catch(e => {console.error(e); process.exitCode=1;});
''')
        for row in report:
            self.assertEqual(row['result'], {'status': 'OK', 'data': {'bound': 42}})
            expected = ['data/v8/audit_latest.json.gz']
            if row['mode'] in ('corrupt', 'missing'): expected.append('data/v8/audit_latest.json')
            if row['mode'] == 'unsupported': expected = ['data/v8/audit_latest.json']
            self.assertEqual(row['calls'], expected)

    def test_today_never_requests_audit_and_portfolio_renders_before_detail(self):
        report = node(r'''
const fs = require('fs'), vm = require('vm');
(async () => {
 const out = [];
 for (const page of ['today.html', 'portfolio.html']) {
  const calls = [], events = [], element = {classList:{toggle(){}}, addEventListener(){}};
  let release;
  const D = {shell(){}, nowS:()=>1, timeKey:()=> 'key', authority:()=>({}),
   loadDecision:async()=>{calls.push('decision');return {doc:{}};},
   loadMarket:async()=>{calls.push('market');return {};},
   loadAudit:()=>{calls.push('audit');return new Promise(r=>{release=r;});},
   views:{today:()=>{events.push('summary');return {};},portfolio:()=>{events.push('summary');return {};},market:()=>''},
   html:{freshness:()=>''}, bindTraces(){}};
  const context={window:{DESK:D},document:{querySelector:()=>element,getElementById:()=>element,addEventListener(){}},
    setInterval(){},Date,console};
  const scripts=[...fs.readFileSync(page,'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)];
  vm.runInNewContext(scripts.at(-1)[1], context);
  await new Promise(r=>setImmediate(r));
  out.push({page,calls:[...calls],renderedBeforeDetail:events.includes('summary')});
  if(release){release({status:'OK',data:{}});await new Promise(r=>setImmediate(r));}
 }
 console.log(JSON.stringify(out));
})().catch(e=>{console.error(e);process.exitCode=1;});
''')
        self.assertEqual(report[0]['calls'], ['decision', 'market'])
        self.assertTrue(report[0]['renderedBeforeDetail'])
        self.assertEqual(report[1]['calls'], ['decision', 'audit'])
        self.assertTrue(report[1]['renderedBeforeDetail'])


if __name__ == '__main__':
    unittest.main()
