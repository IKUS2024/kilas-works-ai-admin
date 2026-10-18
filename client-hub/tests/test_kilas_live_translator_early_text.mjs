import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {TranslatorHistory} from '../static/kilas_live_translator_history.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const key='live-'+'b'.repeat(32),id='a'.repeat(48);
const ready={status:'PROCESSING',translation_ready:true,translation_key:key,translated_text:'Do not order 12 tickets for Rina.',source_text:'Jangan pesan 12 tiket untuk Rina.',source_language:'id',target_language:'en'};
const complete={...ready,status:'COMPLETED',audio_url:'/stored'};
function api(results){const calls=[];let index=0;return {calls,value:new TranslatorTurns({csrf:'synthetic',pollMs:0,json:async(url,options={})=>{calls.push([url,options.method||'GET']);return url.endsWith('/cancel')?{status:'CANCELLED'}:results[Math.min(index++,results.length-1)];}})};}

test('one complete text event precedes audio completion; duplicate polls do not emit twice or POST input',async()=>{
 const f=api([{status:'PROCESSING'},ready,ready,complete]),seen=[];
 const result=await f.value.turn(id,key,null,new AbortController().signal,null,null,value=>seen.push(value));
 assert.equal(seen.length,1);assert.equal(seen[0].status,'PROCESSING');assert.equal(seen[0].audio_url,undefined);assert.equal(result.status,'COMPLETED');assert.deepEqual(f.calls.map(v=>v[1]),['GET','GET','GET','GET']);
});

test('fresh TTS funding failure after complete text is still failure, without retry or audio',async()=>{
 const f=api([ready,{status:'FAILED',code:'provider_credit_exhausted',recoverable:false,error:'Capacity denied'}]),seen=[];
 await assert.rejects(f.value.turn(id,key,null,new AbortController().signal,null,null,v=>seen.push(v)),e=>e.code==='provider_credit_exhausted'&&e.turnSettled&&!e.recoverable);
 assert.equal(seen.length,1);assert.ok(f.calls.every(v=>v[1]==='GET'));
});

test('changed complete text, wrong turn or language shape is rejected before playback',async()=>{
 for(const changed of [{...complete,translated_text:'Wrong replacement'},{...ready,translation_key:'wrong'},{...ready,target_language:'id'}]){
  const f=api(changed.status==='COMPLETED'?[ready,changed]:[changed]),seen=[];
  await assert.rejects(f.value.turn(id,key,null,new AbortController().signal,null,null,v=>seen.push(v)),e=>e.code==='stream_invalid');
  assert.equal(f.calls.filter(v=>v[1]==='POST').length,1);assert.ok(f.calls.some(v=>v[0].endsWith('/cancel')));
 }
});

test('an End during a delayed status response cannot expose late complete text',async()=>{
 const response=deferred(),controller=new AbortController(),seen=[];
 const f=new TranslatorTurns({csrf:'synthetic',json:()=>response.promise});const p=f.turn(id,key,null,controller.signal,null,null,v=>seen.push(v));const rejected=assert.rejects(p,{name:'AbortError'});
 controller.abort();response.resolve(ready);await rejected;assert.equal(seen.length,0);
});

test('one pending text bubble becomes one stored replay; failed pending text survives without a fake replay',()=>{
 class Node{constructor(){this.children=[];}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}setAttribute(){}addEventListener(){}}
 const old=globalThis.document;globalThis.document={createElement:()=>new Node()};
 try{const element=new Node(),history=new TranslatorHistory({element,languageName:x=>x,replay(){},available:()=>true});history.busy(true);history.add(ready,'id');history.add(ready,'id');assert.equal(element.children.length,1);assert.equal(element.children[0].children.length,3);assert.equal(history.rows.size,0);
 history.add(complete,'id');history.add(complete,'id');assert.equal(element.children.length,1);assert.equal(element.children[0].children.length,4);assert.equal(history.rows.size,1);assert.equal(history.rows.get('/stored').button.disabled,true);history.busy(false);assert.equal(history.rows.get('/stored').button.disabled,false);
 history.add({...ready,translation_key:'another'},'id');assert.equal(element.children.length,2);history.busy(false);assert.equal(element.children[1].children.length,3);history.clear();assert.equal(element.children.length,0);assert.equal(history.pending.size,0);
 }finally{globalThis.document=old;}
});

test('pending complete text does not unlock capture, mark completion or play; release metrics are separate',async()=>{
 const output=deferred(),seen=[],timings=[];let handlers,captures=0,plays=0,time=0,calls=0;
 const capture={async start(h){handlers=h;captures++;h.ready();},cancel(){},finalize(){time=120;handlers.blob(new Blob(['tail']));}};
 const playback={async prepare(){},async play(url,signal,current,onStarted){plays++;onStarted();},cancel(){},stop(){}};
 const session=new TranslatorSession({pushToTalk:true,capture,playback,now:()=>time,onTiming:v=>timings.push(v),onResult:v=>seen.push(v),api:{async start(){return {session_id:id};},async end(){},async turn(...args){calls++;time=400;args[6](ready);return output.promise;}},schedule:()=>0,clear(){}});
 await session.start({});assert.equal(captures,0);await session.press();handlers.level(.2);time=100;session.release();await tick();assert.equal(session.state,'processing');assert.equal(plays,0);assert.equal(seen.length,1);await session.press();assert.equal(captures,1);assert.equal(calls,1);
 time=1000;output.resolve(complete);await tick();assert.equal(plays,1);assert.equal(session.state,'ready');assert.equal(calls,1);assert.ok(timings.some(x=>x.release_to_capture_flush_ms===20));assert.ok(timings.some(x=>x.release_to_first_text_ms===300));assert.ok(timings.some(x=>x.release_to_first_audio_ms===900));session.end();
});
