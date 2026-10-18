import test from 'node:test';
import assert from 'node:assert/strict';
import {requestJSON,TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function clock(){let now=0,id=0;const timers=new Map();return {timers,now:()=>now,schedule:(fn,ms)=>{const key=++id;timers.set(key,{fn,at:now+ms});return key;},clear:key=>timers.delete(key),async advance(ms){const target=now+ms;while(true){const next=[...timers].filter(([,t])=>t.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;now=next[1].at;timers.delete(next[0]);next[1].fn();await tick();}now=target;await tick();}};}
const failure=(code,recoverable=false)=>({status:'FAILED',code,recoverable,error:'Synthetic failure'});
const id='a'.repeat(48),key='live-'+'b'.repeat(32),blob=new Blob(['synthetic']);

for(const stage of ['headers','body'])test(`JSON ${stage} deadline and End settle even when transport ignores abort`,async()=>{
 const c=clock(),pending=deferred(),signal=new AbortController();let requestSignal;
 const fetcher=async(url,options)=>{requestSignal=options.signal;return stage==='headers'?pending.promise:{ok:true,json:()=>pending.promise};};
 const p=requestJSON('/synthetic',{csrf:'test',fetcher,signal:signal.signal,timeoutMs:10,schedule:c.schedule,clear:c.clear}),failed=assert.rejects(p,e=>e.code==='request_timeout');
 await tick();await c.advance(10);await failed;assert.equal(requestSignal.aborted,true);assert.equal(c.timers.size,0);
 pending.resolve(stage==='headers'?{ok:true,json:async()=>({})}:{});await tick();
 const d=clock(),blocked=deferred(),ended=new AbortController();
 const q=requestJSON('/synthetic',{csrf:'test',fetcher:()=>blocked.promise,signal:ended.signal,schedule:d.schedule,clear:d.clear}),aborted=assert.rejects(q,{name:'AbortError'});
 ended.abort();await aborted;assert.equal(d.timers.size,0);blocked.resolve({ok:true,json:async()=>({})});await tick();
});

test('authentication redirects and refusals retain typed errors, with no retry',async()=>{
 for(const response of [{ok:true,redirected:true},{ok:false,status:403,json:async()=>({})},{ok:false,status:429,json:async()=>({code:'budget_limit',error:'Capacity denied'})}]){
  let calls=0;await assert.rejects(requestJSON('/synthetic',{csrf:'test',fetcher:async()=>{calls++;return response;}}),e=>['auth_required','budget_limit'].includes(e.code));assert.equal(calls,1);
 }
});

test('a slow turn is cancelled by its existing key and can recover without resubmitting POST',async()=>{
 const c=clock(),calls=[];const api=new TranslatorTurns({csrf:'test',now:c.now,schedule:c.schedule,clear:c.clear,turnMs:1000,
 json:async(url,options={})=>{calls.push({url,method:options.method||'GET'});return url.endsWith('/cancel')?{status:'CANCELLED'}:{status:'PROCESSING'};}});
 const p=api.turn(id,key,blob,new AbortController().signal),failed=assert.rejects(p,e=>e.code==='turn_timeout'&&e.turnSettled&&e.recoverable);
 await tick();await c.advance(1000);await failed;
 assert.equal(calls.filter(x=>x.method==='POST'&&!x.url.endsWith('/cancel')).length,1);assert.equal(calls.filter(x=>x.url.endsWith('/cancel')).length,1);assert.equal(c.timers.size,0);
});

test('ambiguous submission gets a cancellation tombstone; an unconfirmed cancellation remains paused',async()=>{
 for(const confirmed of [true,false]){
  const calls=[],api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,method:options.method});if(url.endsWith('/cancel')){if(!confirmed)throw Error('Offline');return {status:'CANCELLED'};}throw Object.assign(Error('Ambiguous POST'),{code:'request_timeout'});}});
  await assert.rejects(api.turn(id,key,blob,new AbortController().signal),e=>e.recoverable===confirmed&&Boolean(e.turnSettled)===confirmed);
  assert.equal(calls.length,2);assert.equal(calls.filter(x=>x.method==='POST'&&!x.url.endsWith('/cancel')).length,1);
 }
});

test('completed work discovered during cancellation is recovered through GET without paid regeneration',async()=>{
 const calls=[],api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,method:options.method||'GET'});if(url.endsWith('/cancel'))return {status:'COMPLETED'};if(options.method==='POST')throw Object.assign(Error('Lost acknowledgement'),{code:'request_timeout'});return {status:'COMPLETED',translated_text:'Synthetic result',audio_url:'/synthetic'};}});
 const result=await api.turn(id,key,blob,new AbortController().signal);assert.equal(result.translated_text,'Synthetic result');assert.equal(calls.length,3);assert.equal(calls.filter(x=>x.method==='POST'&&!x.url.endsWith('/cancel')).length,1);
});

test('a lost response followed by confirmed credit failure stays blocked rather than auto-listening',async()=>{
 const calls=[],api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,method:options.method||'GET'});if(url.endsWith('/cancel'))return {status:'FAILED'};if(options.method==='POST')throw Object.assign(Error('Lost response'),{code:'request_timeout'});return failure('provider_credit_exhausted');}});
 await assert.rejects(api.turn(id,key,blob,new AbortController().signal),e=>e.code==='provider_credit_exhausted'&&e.turnSettled&&e.recoverable===false);
 assert.equal(calls.length,3);assert.equal(calls.filter(x=>x.method==='POST'&&!x.url.endsWith('/cancel')).length,1);
});

for(const code of ['provider_credit_exhausted','provider_credit_check_failed','provider_billing_unverified','attempt_limit','live_audio_limit','zero_balance','insufficient_balance'])test(`${code} never becomes an automatic retry`,async()=>{
 const calls=[],api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,method:options.method||'GET'});return options.method==='POST'?{status:'PROCESSING'}:failure(code);}});
 await assert.rejects(api.turn(id,key,blob,new AbortController().signal),e=>e.code===code&&e.recoverable===false&&e.turnSettled===true);
 assert.equal(calls.length,2);assert.equal(calls.some(x=>x.url.endsWith('/cancel')),false);
});

test('known recoverable provider failure permits a new utterance without repeating the failed one',async()=>{
 let posts=0;const api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{if(options.method==='POST'){posts++;return {status:'PROCESSING'};}return failure('translation_failed',true);}});
 await assert.rejects(api.turn(id,key,blob,new AbortController().signal),e=>e.recoverable&&e.turnSettled);assert.equal(posts,1);
});

test('resume verifies the same owner session and never submits provider work',async()=>{
 for(const state of [{status:'ACTIVE',processing:false},{status:'ENDED',processing:false},{status:'ACTIVE',processing:true}]){
  const calls=[],api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,method:options.method||'GET'});return url.endsWith('/cancel')?{status:'CANCELLED'}:state;}});
  const p=api.resume(id,key,new AbortController().signal);if(state.status==='ACTIVE'&&!state.processing)await p;else await assert.rejects(p);
  assert.deepEqual(calls.map(x=>x.method),['POST','GET']);assert.ok(calls[0].url.endsWith('/cancel'));assert.ok(!calls[1].url.includes('/turns/'));
 }
});

test('controlled mock polling detects ready results up to 250ms earlier; this is not provider/audio latency',async()=>{
 const measurements=[];
 for(const pollMs of [500,250]){
  const c=clock(),reads=[];const api=new TranslatorTurns({csrf:'test',now:c.now,schedule:c.schedule,clear:c.clear,pollMs,
   json:async(url,options={})=>{if(options.method==='POST')return {status:'PROCESSING'};reads.push(c.now());return {status:c.now()>=600?'COMPLETED':'PROCESSING'};}});
  const p=api.turn(id,key,blob,new AbortController().signal);await tick();await c.advance(1000);await p;measurements.push(reads.at(-1));
 }
 assert.deepEqual(measurements,[1000,750]);
});

test('only owned expired ACTIVE metadata can renew with original pair voice consent; no speech POST',async()=>{
 const params=new FormData();for(const [k,v] of Object.entries({language_a:'id',language_b:'en',voice:'kilas-female',consent:'yes'}))params.append(k,v);
 for(const renewable of [true,false]){
  const calls=[],admitted=[];const api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,options});return url.endsWith('/renew')?{session_id:id,input_mode:'realtime-v1'}:{status:'ENDED',renewable};}});
  const work=api.resume(id,null,new AbortController().signal,params,'realtime-v1',value=>admitted.push(value));
  if(renewable){await work;const post=calls.at(-1);assert.equal(post.options.body.get('voice'),'kilas-female');assert.equal(post.options.body.get('language_a'),'id');assert.equal(post.options.body.get('consent'),'yes');assert.equal(admitted.length,1);}
  else await assert.rejects(work,e=>e.code==='session_ended');
  assert.equal(calls.some(c=>c.url.includes('/turns/')),false);assert.equal(calls.filter(c=>c.options.method==='POST').length,renewable?1:0);
 }
});
test('cancelled input must reconcile durable lease before resume can finish',async()=>{
 const c=clock(),calls=[];let reads=0;const api=new TranslatorTurns({csrf:'test',schedule:c.schedule,clear:c.clear,json:async(url)=>{calls.push(url);if(url.endsWith('/cancel'))return {status:'CANCELLED',input_settled:false};if(url.includes('/turns/'))return {status:'CANCELLED',input_settled:++reads>1};return {status:'ACTIVE',processing:false};}});
 let done=false;const work=api.resume(id,key,new AbortController().signal).then(()=>done=true);await tick();assert.equal(done,false);await c.advance(250);assert.equal(done,false);await c.advance(250);await work;assert.equal(done,true);assert.equal(calls.filter(x=>x.endsWith('/cancel')).length,1);assert.equal(reads,2);
});
test('lost renewal acknowledgement recovers owned ACTIVE metadata once without another renewal or speech request',async()=>{
 const calls=[],params=new FormData();for(const [k,v] of Object.entries({language_a:'id',language_b:'en',voice:'kilas-male',consent:'yes'}))params.append(k,v);
 let reads=0,admitted=0;const api=new TranslatorTurns({csrf:'test',json:async(url,options={})=>{calls.push({url,options});if(url.endsWith('/renew'))throw Object.assign(Error('Lost ACK'),{code:'request_timeout'});return ++reads===1?{status:'ENDED',renewable:true}:{status:'ACTIVE',processing:false};}});
 await api.resume(id,null,new AbortController().signal,params,'realtime-v1',result=>{assert.equal(result.session_id,id);admitted++;});assert.equal(admitted,1);assert.equal(calls.filter(c=>c.options.method==='POST').length,1);assert.equal(calls.some(c=>c.url.includes('/turns/')),false);
 // A repeated recovery verifies the same ACTIVE row with no extra POST.
 await api.resume(id,null,new AbortController().signal,params,'realtime-v1');assert.equal(calls.filter(c=>c.options.method==='POST').length,1);
});
