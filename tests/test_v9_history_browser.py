"""Browser checks against actual synthetic capture bytes, without network access."""
import base64
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from v9 import paper_history as H
from tests import test_v9_paper_history as fixtures
ROOT=Path(__file__).resolve().parents[1]

class Browser(unittest.TestCase):
    def test_bundle_keeps_exact_record_bytes_and_index_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.fixture(root);files,snapshot=H.package(root)
            ip=next(p for p in files if '/indexes/' in p);index=H.decode(H.unpack(files[ip]))
            view=H.decode(H.unpack(files[index['view_path']]))
            self.assertEqual(index['snapshot_path'],snapshot)
            self.assertEqual(view['snapshot'].encode(),H.unpack(files[snapshot]))
            self.assertTrue(ip.endswith(H.sha(H.unpack(files[ip]))+'.json.gz'))
            for path,raw in view['records'].items():self.assertEqual(raw.encode(),H.unpack(files[path]))
            self.assertEqual(index['records'],len(view['records']))
            with patch.object(H,'MAX_SOURCE_BYTES',1000):
                with self.assertRaisesRegex(ValueError,'limit'):H.package(root)
            fixtures.fixture(root,stamp=8640000000000)
            with self.assertRaisesRegex(ValueError,'audit time'):H.package(root)

    def test_browser_real_bundles_legacy_inventory_and_corruption(self):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.fixture(root);files,snapshot=H.package(root)
            ip=next(p for p in files if '/indexes/' in p)
            fixture=root/'fixture.json';fixture.write_text(json.dumps(dict(files={p:base64.b64encode(b).decode() for p,b in files.items()},snapshot=snapshot,index=ip)),encoding='utf-8')
            script=r'''const assert=require('node:assert/strict'),fs=require('node:fs'),z=require('node:zlib'),C=require('node:crypto');
const H=require('./paper-history.js'),P=require('./performance.js'),f=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const commit='a'.repeat(40), root='b'.repeat(40), dir='c'.repeat(40), snaps='d'.repeat(40), indexes='e'.repeat(40);
const files=Object.fromEntries(Object.entries(f.files).map(([p,b])=>[p,Buffer.from(b,'base64')]));
const blob=p=>({path:p.split('/').pop(),mode:'100644',type:'blob',sha:'f'.repeat(40)});
const tree=(sha,rows)=>({sha,truncated:false,tree:rows});
const directory=(path,sha)=>({path,sha,mode:'040000',type:'tree'});
let calls=[],truncate=false,missing=false,legacy=false;
const fetch=async(url,opts)=>{calls.push(url);assert.equal(opts.credentials,'omit');if(opts.signal&&opts.signal.aborted)throw Error('aborted');
 if(url.includes('raw.githubusercontent.com')){assert.ok(url.includes('/'+commit+'/'));const path=url.split('/'+commit+'/')[1];return new Response(files[path],{status:files[path]?200:404});}
 let data;if(url.endsWith('ref/heads/v9-market-history'))data={ref:'refs/heads/v9-market-history',object:{type:'commit',sha:commit}};
 else if(url.endsWith('commits/'+commit))data={sha:commit,tree:{sha:root}};
 else if(url.endsWith('trees/'+root))data=tree(root,missing?[]:[directory('paper-observations',dir)]);
 else if(url.endsWith('trees/'+dir))data=tree(dir,[directory('snapshots',snaps),...legacy?[]:[directory('indexes',indexes)]]);
 else if(url.endsWith('trees/'+snaps))data=tree(snaps,[blob(f.snapshot)]);
 else if(url.endsWith('trees/'+indexes))data=tree(indexes,[blob(f.index)]);
 else throw Error('unexpected URL '+url);
 if(truncate&&data.tree instanceof Array)data.truncated=true;return new Response(JSON.stringify(data));};
(async()=>{
 const inventory=await H.inventory({fetch});assert.equal(inventory.commit,commit);assert.equal(inventory.entries.length,1);
 let model=await H.load(commit,inventory.entries[0],P,{fetch});assert.equal(model.records[0].id,'old');assert.equal(model.records[0].entryTier,'unrecorded');assert.equal(model.records[0].reportedR,null);
 assert.equal(calls.filter(x=>x.includes('raw.')).length,2);const html=P.render(model);assert.ok(html.includes('Authority observed at capture'));assert.ok(!html.includes('<h2>Current authority'));assert.ok(html.includes('not reverified'));
 legacy=true;const old=await H.inventory({fetch});assert.equal(old.entries[0].legacy,true);assert.equal(old.entries[0].time,null);assert.deepEqual((await H.load(commit,old.entries[0],P,{fetch})).records,model.records);legacy=false;
 truncate=true;await assert.rejects(H.inventory({fetch}),/incomplete/);truncate=false;missing=true;assert.equal((await H.inventory({fetch})).entries.length,0);missing=false;
 for(const raw of ['{"a":1,"a":2}','{"a":1e400}','{"a":9007199254740993}','[]false','[1,]','{"__proto__":1,"__proto__":2}'])assert.throws(()=>H.parse(raw));
 assert.equal(H.parse('{"__proto__":1}').__proto__,1);
 const idx=H.parse(z.gunzipSync(files[f.index]).toString()),original=files[idx.view_path];files[idx.view_path]=z.gzipSync('{}');await assert.rejects(H.load(commit,inventory.entries[0],P,{fetch}),/hash/);files[idx.view_path]=original;
 await assert.rejects(H.load('main',inventory.entries[0],P,{fetch}),/commit/);
 await assert.rejects(H.load(commit,{legacy:true,path:'../secret'},P,{fetch}),/path/);
 const raw=z.gunzipSync(files[f.snapshot]).toString(),snapshot=JSON.parse(raw);
 const sha=s=>C.createHash('sha256').update(s).digest('hex');
 const verify=async s=>{const body=JSON.stringify(s);return H.verifySnapshot(body,'paper-observations/snapshots/'+sha(body)+'.json.gz',async path=>z.gunzipSync(files[path]).toString());};
 snapshot.records.push(snapshot.records[0]);await assert.rejects(verify(snapshot),/Duplicate/);snapshot.records.pop();snapshot.records[0].identity='wrong';await assert.rejects(verify(snapshot),/identity/);
 const abort=new AbortController();abort.abort();await assert.rejects(H.inventory({fetch,signal:abort.signal}),/aborted/);
 assert.ok(calls.every(x=>!x.includes('recursive=')));console.log('archive checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});'''
            result=subprocess.run(['node','-e',script,str(fixture)],cwd=ROOT,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_page_discards_late_archive_results_and_clears_failures(self):
        if not shutil.which('node'):self.skipTest('Node unavailable')
        script=r'''const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const page=fs.readFileSync('performance.html','utf8'),code=page.split('<script>').pop().split('</script>')[0];
const elements={};for(const id of ['status','ledger','strategy','state','history-list','history-select','history-load','history-status','reload'])elements[id]={value:'',innerHTML:'',textContent:'',disabled:false,children:[],handlers:{},addEventListener(n,cb){this.handlers[n]=cb;},replaceChildren(){this.children=[];this.value='';},append(o){this.children.push(o);if(this.children.length===1)this.value=o.value;}};
let resolveArchive,fail=false,mode='current';const current={records:[]};
const context={window:{DESK:{shell(){}},PERFORMANCE:{load:async()=>current,render:d=>d===current?'current rows':'archive rows'},PAPER_HISTORY:{inventory:async()=>({commit:'a'.repeat(40),entries:[{legacy:false,time:1000,snapshot:'x/hash',path:'index'}]}),load:async()=>{if(fail)throw Error('corrupt');return new Promise(r=>resolveArchive=r);}}},document:{getElementById:id=>elements[id],createElement:()=>({})},AbortController,setTimeout,clearTimeout,setInterval(){},Date};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{vm.runInNewContext(code,context);await tick();assert.equal(elements.ledger.innerHTML,'current rows');
 await elements['history-list'].handlers.click();assert.equal(elements.ledger.innerHTML,'');assert.equal(elements['history-load'].disabled,false);
 const pending=elements['history-load'].handlers.click();await tick();assert.equal(elements.ledger.innerHTML,'');
 await elements.reload.handlers.click();resolveArchive({records:[]});await pending;assert.equal(elements.ledger.innerHTML,'current rows');
 fail=true;await elements['history-load'].handlers.click();assert.equal(elements.ledger.innerHTML,'');assert.ok(elements.status.textContent.includes('No partial results'));
 console.log('page race checks passed');})().catch(e=>{console.error(e);process.exitCode=1;});'''
        result=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_browser_asset_is_published(self):
        import dashboard
        with tempfile.TemporaryDirectory() as tmp:
            dashboard.publish(tmp)
            self.assertEqual((Path(tmp)/'paper-history.js').read_bytes(),(ROOT/'paper-history.js').read_bytes())
