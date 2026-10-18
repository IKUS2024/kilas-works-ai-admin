import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
import {progressiveSupported} from '../static/kilas_live_translator_progressive.mjs';
const id='a'.repeat(48),key='live-'+'b'.repeat(32),url='/kilas-translator/live/sessions/'+id+'/turns/'+key,sha='c'.repeat(64);
const ready={status:'PROCESSING',translation_ready:true,translation_key:key,source_text:'Saya mau tiket.',translated_text:'I want a ticket.',source_language:'id',target_language:'en',audio_progress_url:url+'/audio/progress'};
const done={...ready,status:'COMPLETED',audio_url:url+'/audio',audio_sha256:sha};
const tick=()=>new Promise(r=>setImmediate(r));
test('unsupported browsers keep the existing complete-file path without progressive fetch',async()=>{
 assert.equal(progressiveSupported(),false);let count=0;
 const api=new TranslatorTurns({csrf:'x',pollMs:0,json:async()=>++count===1?ready:done});
 const result=await api.turn(id,key,null,new AbortController().signal);assert.equal(result.streamed,undefined);assert.equal(result.audio_url,done.audio_url);
});
test('one progressive player across duplicate status reads, wait producer AND playback, validate final digest',async()=>{
 let resolve,plays=0,reads=0;const playback=new Promise(r=>resolve=r),calls=[];const controller=new AbortController();
 const api=new TranslatorTurns({csrf:'x',pollMs:0,json:async(path,o={})=>{calls.push([path,o.method||'GET']);return ++reads<3?ready:done;}});
 const p=api.turn(id,key,null,controller.signal,null,null,()=>{},async(path,signal)=>{plays++;assert.equal(path,ready.audio_progress_url);assert.equal(signal.aborted,false);await playback;return {sha256:sha};});
 await tick();await new Promise(r=>setTimeout(r,10));assert.equal(plays,1);let settled=false;p.then(()=>settled=true);await tick();assert.equal(settled,false);resolve();const result=await p;assert.equal(result.streamed,true);assert.equal(plays,1);assert.ok(calls.every(v=>v[1]==='GET'));
});
test('bad digest or malformed turn URL fails without automatic complete-audio replay or provider submission',async()=>{
 for(const invalid of [false,true]){
 let reads=0,plays=0;const posts=[];const api=new TranslatorTurns({csrf:'x',pollMs:0,json:async(path,o={})=>{if(o.method==='POST'){posts.push(path);return {status:'COMPLETED'};}return ++reads===1?{...ready,...(invalid?{audio_progress_url:'/foreign/audio/progress'}:{})}:done;}});
 await assert.rejects(api.turn(id,key,null,new AbortController().signal,null,null,()=>{},async()=>{plays++;return {sha256:'wrong'};}),e=>e.code==='stream_invalid');assert.equal(plays,invalid?0:1);assert.deepEqual(posts,[url+'/cancel']);
 }
});
test('End aborts progressive playback and cannot return a late completed response',async()=>{
 const controller=new AbortController();let seenSignal;const api=new TranslatorTurns({csrf:'x',pollMs:0,json:async()=>ready});
 const p=api.turn(id,key,null,controller.signal,null,null,()=>{},async(path,signal)=>{seenSignal=signal;return new Promise((r,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('','AbortError'))));});
 const rejected=assert.rejects(p,{name:'AbortError'});await tick();controller.abort();await rejected;assert.equal(seenSignal.aborted,true);
});

test('progressive decoder rejects oversized response bodies before append and cleans every media object',async()=>{
 const {progressivePlay}=await import('../static/kilas_live_translator_progressive.mjs');const {webcrypto}=await import('node:crypto');
 const names=['Audio','AudioContext','MediaSource','URL','crypto'],old=new Map(names.map(n=>[n,Object.getOwnPropertyDescriptor(globalThis,n)]));let media,reads=0,cancels=0,appends=0,revokes=0,paused=0;
 class Source extends EventTarget{static isTypeSupported(){return true;}constructor(){super();media=this;}addSourceBuffer(){const b=new EventTarget();b.buffered={length:0};b.appendBuffer=()=>{appends++;};return b;}}
 class Element extends EventTarget{set src(v){queueMicrotask(()=>media.dispatchEvent(new Event('sourceopen')));}pause(){paused++;}removeAttribute(){}load(){}}
 try{
  Object.defineProperty(globalThis,'Audio',{configurable:true,value:Element});Object.defineProperty(globalThis,'AudioContext',{configurable:true,value:class{createMediaElementSource(){}}});Object.defineProperty(globalThis,'MediaSource',{configurable:true,value:Source});Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});Object.defineProperty(globalThis,'URL',{configurable:true,value:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:()=>revokes++}});
  const player={now:()=>0,check(op){if(op.controller.signal.aborted)throw new DOMException('','AbortError');},bounded:async(op,fn)=>fn(),fetchAudio:async()=>({status:200,headers:new Map([['Content-Type','audio/mpeg'],['Content-Length','2'],['X-Audio-Offset','0'],['X-Audio-Size','65537'],['X-Audio-Complete','0']]),body:{getReader:()=>({read:async()=>{reads++;return {done:false,value:new Uint8Array(65537)};},cancel:async()=>{cancels++;}})}}),run:async(signal,current,work)=>{const op={controller:new AbortController(),context:{createMediaElementSource:()=>({connect(){},disconnect(){}}),destination:{}},isCurrent:current};try{return await work(op);}finally{op.controller.abort();}}};
  await assert.rejects(progressivePlay(player,url+'/audio/progress',new AbortController().signal,()=>true),e=>e.code==='audio_stalled'&&e.segmentPlayback);assert.equal(reads,1);assert.equal(cancels,1);assert.equal(appends,0);assert.equal(revokes,1);assert.equal(paused,1);
 }finally{for(const [n,d] of old){if(d)Object.defineProperty(globalThis,n,d);else delete globalThis[n];}}
});
