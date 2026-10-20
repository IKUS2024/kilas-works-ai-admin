import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';
import {progressivePlay} from '../static/kilas_live_translator_progressive.mjs';
const url='/kilas-translator/live/sessions/'+'a'.repeat(48)+'/turns/live-'+'b'.repeat(32)+'/audio/progress';
async function fixture(mode='buffer'){
 const names=['Audio','AudioContext','MediaSource','URL','crypto'],old=new Map(names.map(n=>[n,Object.getOwnPropertyDescriptor(globalThis,n)]));
 let media,appends=0,reads=0,plays=0,starts=0,revokes=0,resolvePlay,rejectPlay;
 const controller=new AbortController(),bytes=new Uint8Array([1,2]),digest=Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');
 class Element extends EventTarget{
  currentTime=0;duration=1;
  set src(v){queueMicrotask(()=>media.dispatchEvent(new Event('sourceopen')));}
  play(){plays++;return new Promise((resolve,reject)=>{resolvePlay=resolve;rejectPlay=reject;if(mode==='denied')reject(new DOMException('','NotAllowedError'));if(mode==='error')reject(new Error('decoder failure'));});}
  pause(){}removeAttribute(){}load(){}
 }
 const audio=new Element();
 class Source extends EventTarget{
  static isTypeSupported(){return true;}
  constructor(){super();media=this;}
  addSourceBuffer(){const b=new EventTarget();b.buffered={length:1,end:()=>.2};b.appendBuffer=()=>{appends++;queueMicrotask(()=>{b.dispatchEvent(new Event('updateend'));if(appends===2&&mode==='buffer')resolvePlay();});};return b;}
  endOfStream(){audio.currentTime=1;audio.dispatchEvent(new Event('ended'));}
 }
 try{
  for(const [n,value] of Object.entries({Audio:Element,AudioContext:class{createMediaElementSource(){}},MediaSource:Source,crypto:webcrypto,URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL:()=>revokes++}}))Object.defineProperty(globalThis,n,{configurable:true,value});
  const context={state:'running'},player=new TranslatorPlayback({getContext:()=>context,schedule:(fn,ms)=>setTimeout(fn,Math.min(ms,80)),fetchAudio:async()=>{
   reads++;if(reads===2&&['cancel','cancelResolve'].includes(mode)){await new Promise(r=>setImmediate(r));controller.abort();queueMicrotask(()=>mode==='cancelResolve'?resolvePlay():rejectPlay(new DOMException('late rejection','AbortError')));}
   const i=reads-1;return new Response(bytes.slice(i,i+1),{headers:{'Content-Type':'audio/mpeg','Content-Length':'1','X-Audio-Offset':String(i),'X-Audio-Size':String(reads),'X-Audio-Complete':reads===2?'1':'0',...(reads===2?{'X-Audio-SHA256':digest}:{})}});
  }});
  player.progressiveMedia={audio,context,ready:true};
  const result=await progressivePlay(player,url,controller.signal,()=>true,()=>starts++).then(value=>({value}),error=>({error}));
  await new Promise(r=>setImmediate(r));
  return {...result,appends,reads,plays,starts,revokes,cached:player.has(url.slice(0,-9)),ready:player.progressiveMedia.ready};
 }finally{for(const [n,d] of old){if(d)Object.defineProperty(globalThis,n,d);else delete globalThis[n];}}
}
test('pending play requiring a second buffer does not block sequential download',async()=>{
 const f=await fixture();assert.equal(f.error,undefined);assert.equal(f.reads,2);assert.equal(f.appends,2);assert.equal(f.plays,1);assert.equal(f.starts,1);assert.equal(f.cached,true);assert.equal(f.revokes,1);
});
test('denied permission drains and caches the same stream for explicit Resume',async()=>{
 const f=await fixture('denied');assert.equal(f.error,undefined);assert.equal(f.value.playbackError.code,'audio_permission');assert.equal(f.reads,2);assert.equal(f.plays,1);assert.equal(f.starts,0);assert.equal(f.cached,true);assert.equal(f.ready,false);
});
test('cancel during pending play fences late rejection and onset',async()=>{
 const f=await fixture('cancel');assert.equal(f.error.name,'AbortError');assert.equal(f.starts,0);assert.equal(f.cached,false);assert.equal(f.revokes,1);assert.equal(f.plays,1);
});
test('decoder start rejection is consumed and fails without another play',async()=>{
 const f=await fixture('error');assert.match(f.error.message,/decoder failure/);assert.equal(f.starts,0);assert.equal(f.plays,1);assert.equal(f.cached,false);assert.equal(f.revokes,1);
});

test('unresolved start stays bounded and never caches or announces playback',async()=>{
 const f=await fixture('timeout');assert.ok(f.error.code==='audio_stalled'||f.error.name==='AbortError');assert.equal(f.reads,2);assert.equal(f.plays,1);assert.equal(f.starts,0);assert.equal(f.cached,false);assert.equal(f.revokes,1);
});

test('cancel during pending play fences a late successful resolution',async()=>{
 const f=await fixture('cancelResolve');assert.equal(f.error.name,'AbortError');assert.equal(f.starts,0);assert.equal(f.cached,false);assert.equal(f.revokes,1);assert.equal(f.plays,1);
});
