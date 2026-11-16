/* Public, read-only archive browser. Every read is pinned to one commit. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.PAPER_HISTORY=api;})(typeof window!=='undefined'?window:globalThis,function(){
 'use strict';
 const repo='blazebrt/perp-dex-radar', prefix='paper-observations/', limit=64*1024*1024;
 const hex=/^[a-f0-9]{40}$/, object=/^paper-observations\/(records|snapshots|views)\/([a-f0-9]{64})\.json\.gz$/;
 const index=/^paper-observations\/indexes\/(\d{20})-([a-f0-9]{64})-([a-f0-9]{64})\.json\.gz$/;
 const need=(v,m)=>{if(!v)throw Error(m);};
 const dict=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
 const time=v=>Number.isSafeInteger(v)&&v>0&&v<8640000000000;
 // Strict JSON: duplicate keys, nonfinite/unsafe numbers and excessive depth fail closed.
 function parse(text){
  let i=0;const ws=()=>{while(/[ \r\n\t]/.test(text[i]||'!'))i++;};
  function string(){const start=i++;while(i<text.length){const c=text[i++];if(c==='"')return JSON.parse(text.slice(start,i));if(c==='\\')i++;}throw Error('Unterminated JSON string');}
  function value(depth){
   need(depth<100,'JSON nesting limit');ws();const c=text[i];
   if(c==='"')return string();
   if(c==='{'||c==='['){const arr=c==='[',out=arr?[]:Object.create(null),keys=new Set();i++;ws();if(text[i]===(arr?']':'}')){i++;return out;}
    for(;;){ws();let key;if(!arr){need(text[i]==='"','Invalid object key');key=string();need(!keys.has(key),'Duplicate JSON key');keys.add(key);ws();need(text[i++]===':','Missing colon');}
     const v=value(depth+1);if(arr)out.push(v);else out[key]=v;ws();const end=text[i++];if(end===(arr?']':'}'))return out;need(end===',','Invalid JSON separator');}
   }
   for(const [word,v] of [['true',true],['false',false],['null',null]])if(text.startsWith(word,i)){i+=word.length;return v;}
   const m=text.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);need(m,'Invalid JSON value');i+=m[0].length;
   const n=Number(m[0]);need(Number.isFinite(n)&&(!Number.isInteger(n)||Number.isSafeInteger(n)),'Unsafe JSON number');return n;
  }
  const result=value(0);ws();need(i===text.length,'Trailing JSON data');return result;
 }
 async function bytes(stream){
  need(stream&&stream.getReader,'Streaming response unavailable');const reader=stream.getReader(),chunks=[];let count=0;
  try{for(;;){const {value,done}=await reader.read();if(done)break;count+=value.byteLength;if(count>limit){await reader.cancel();throw Error('Archive object exceeds size limit');}chunks.push(value);}}finally{reader.releaseLock();}
  const out=new Uint8Array(count);let offset=0;for(const c of chunks){out.set(c,offset);offset+=c.byteLength;}return out;
 }
 const decode=b=>new TextDecoder('utf-8',{fatal:true}).decode(b);
 async function hash(raw){need(globalThis.crypto&&crypto.subtle,'SHA-256 unavailable');return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw))),x=>x.toString(16).padStart(2,'0')).join('');}
 async function request(url,options){const r=await (options.fetch||fetch)(url,{signal:options.signal,credentials:'omit'});need(r.ok,'Archive request failed ('+r.status+')');return bytes(r.body);}
 async function json(url,options){return parse(decode(await request(url,options)));}
 async function read(commit,path,options){
  need(hex.test(commit),'Invalid archive commit');const m=path.match(object),n=path.match(index);need(m||n,'Invalid archive path');
  need(typeof DecompressionStream==='function','Gzip decompression unavailable');
  const compressed=await request('https://raw.githubusercontent.com/'+repo+'/'+commit+'/'+path,options);
  const raw=decode(await bytes(new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip'))));
  need(await hash(raw)===(m?m[2]:n[3]),'Archive content hash mismatch');return raw;
 }
 async function inventory(options={}){
  const api='https://api.github.com/repos/'+repo+'/git/';
  const ref=await json(api+'ref/heads/v9-market-history',options);
  need(ref.ref==='refs/heads/v9-market-history'&&dict(ref.object)&&ref.object.type==='commit'&&hex.test(ref.object.sha),'Invalid history reference');
  const commit=ref.object.sha,c=await json(api+'commits/'+commit,options);need(c.sha===commit&&dict(c.tree)&&hex.test(c.tree.sha),'Invalid commit tree');
  async function tree(sha){need(hex.test(sha),'Invalid tree hash');const t=await json(api+'trees/'+sha,options);need(t.sha===sha&&t.truncated===false&&Array.isArray(t.tree)&&t.tree.length<=20000,'Archive listing is incomplete or exceeds the browsing limit');return t.tree;}
  function directory(rows,name){const matches=rows.filter(r=>r.path===name);need(matches.length<=1,'Ambiguous archive directory');if(!matches.length)return null;const r=matches[0];need(r.type==='tree'&&r.mode==='040000'&&hex.test(r.sha),'Invalid archive directory');return r.sha;}
  const root=await tree(c.tree.sha),dir=directory(root,'paper-observations');if(!dir)return {commit,entries:[]};
  const dirs=await tree(dir),snapDir=directory(dirs,'snapshots'),idxDir=directory(dirs,'indexes');
  const snaps=new Set(),entries=[],indexed=new Set();
  for(const r of snapDir?await tree(snapDir):[]){need(r.type==='blob'&&r.mode==='100644'&&/^[a-f0-9]{64}\.json\.gz$/.test(r.path),'Invalid snapshot listing');snaps.add(prefix+'snapshots/'+r.path);}
  for(const r of idxDir?await tree(idxDir):[]){const path=prefix+'indexes/'+r.path,m=path.match(index);need(r.type==='blob'&&r.mode==='100644'&&m&&time(Number(m[1])),'Invalid capture index');const snapshot=prefix+'snapshots/'+m[2]+'.json.gz';need(snaps.has(snapshot),'Index references a missing snapshot');indexed.add(snapshot);entries.push({path,snapshot,time:Number(m[1]),legacy:false});}
  for(const snapshot of snaps)if(!indexed.has(snapshot))entries.push({path:snapshot,snapshot,time:null,legacy:true});
  entries.sort((a,b)=>(b.time||0)-(a.time||0)||a.path.localeCompare(b.path));return {commit,entries};
 }
 async function verifySnapshot(raw,snapshotPath,readRecord){
  const m=snapshotPath.match(object);need(m&&m[1]==='snapshots'&&await hash(raw)===m[2],'Snapshot hash mismatch');
  const s=parse(raw);need(dict(s)&&s.schema==='v9.paper-observation-snapshot/1'&&time(s.snapshot_time)&&time(s.decision_time)&&dict(s.observed_authority)&&
   s.trade_authorization===false&&s.historical_entry_authority==='UNRECORDED_NOT_INFERRED'&&Array.isArray(s.records)&&s.records.length<=20000,'Invalid archive snapshot');
  const journal={open:[],closed:[]},ids=new Set();
  // Bounded batches also support old captures that predate bundled views.
  for(let i=0;i<s.records.length;i+=4){const batch=await Promise.all(s.records.slice(i,i+4).map(async ref=>{
   need(dict(ref)&&typeof ref.path==='string','Invalid record reference');const m=ref.path.match(object);need(m&&m[1]==='records'&&m[2]===ref.sha256,'Invalid record binding');
   const body=await readRecord(ref.path);need(typeof body==='string'&&await hash(body)===m[2],'Record hash mismatch');const row=parse(body);
   need(dict(row)&&row.schema==='v9.paper-observation-record/1'&&['open','closed'].includes(row.journal_state)&&row.journal_state===ref.state&&dict(row.record),'Invalid archived record');
   const id=row.record.id;need((typeof id==='string'&&id!==''||Number.isSafeInteger(id))&&id===ref.identity,'Archive identity mismatch');return row;
  }));for(const row of batch){const id=JSON.stringify(row.record.id);need(!ids.has(id),'Duplicate archived identity');ids.add(id);journal[row.journal_state].push(row.record);}}
  return {snapshot:s,journal};
 }
 async function load(commit,entry,P,options={}){
  need(entry&&typeof entry.path==='string','Missing capture selection');let verified;
  if(entry.legacy){verified=await verifySnapshot(await read(commit,entry.path,options),entry.path,path=>read(commit,path,options));}
  else{
   const m=entry.path.match(index);need(m,'Invalid index path');const idx=parse(await read(commit,entry.path,options));
   need(idx.schema==='v9.paper-observation-index/1'&&idx.snapshot_time===Number(m[1])&&idx.snapshot_path===prefix+'snapshots/'+m[2]+'.json.gz'&&Number.isSafeInteger(idx.records)&&idx.records>=0&&idx.records<=20000,'Invalid capture index binding');
   const vp=typeof idx.view_path==='string'&&idx.view_path.match(object);need(vp&&vp[1]==='views','Invalid capture view path');
   const view=parse(await read(commit,idx.view_path,options));need(view.schema==='v9.paper-observation-view/1'&&view.snapshot_path===idx.snapshot_path&&typeof view.snapshot==='string'&&dict(view.records)&&Object.keys(view.records).length===idx.records,'Invalid browse bundle');
   verified=await verifySnapshot(view.snapshot,idx.snapshot_path,async path=>view.records[path]);
   need(verified.snapshot.snapshot_time===idx.snapshot_time&&verified.snapshot.records.length===idx.records,'Capture index differs from snapshot');
  }
  const s=verified.snapshot,data=P.model({schema:'v8.decision/1',as_of:s.decision_time,valid_until:s.decision_valid_until,strategy_tiers:s.observed_authority},verified.journal);
  data.archive={commit,snapshotTime:s.snapshot_time,originalSourcesReverified:false};return data;
 }
 return {parse,inventory,load,verifySnapshot};
});
