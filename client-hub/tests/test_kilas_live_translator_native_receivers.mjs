// Enforce Window/native receiver rules in Node; no browser, microphone or provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {requestJSON,TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function nativeGlobals(run){
 const originals={setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout,fetch:globalThis.fetch};
 const performanceDescriptor=Object.getOwnPropertyDescriptor(globalThis,'performance');
 const timers=new Map(),calls=[];let seq=0;
 function requireWindow(receiver){if(receiver!==undefined&&receiver!==globalThis)throw new TypeError('Illegal invocation');}
 globalThis.setTimeout=function(fn,ms){requireWindow(this);const id=++seq;timers.set(id,{fn,ms});calls.push(['set',ms]);return id;};
 globalThis.clearTimeout=function(id){requireWindow(this);timers.delete(id);calls.push(['clear',id]);};
 globalThis.fetch=async function(url,options){requireWindow(this);calls.push(['fetch',url]);return {ok:true,json:async()=>({status:'ACTIVE'}),arrayBuffer:async()=>new ArrayBuffer(8)};};
 const performance={now(){if(this!==performance)throw new TypeError('Illegal invocation');return 0;}};
 Object.defineProperty(globalThis,'performance',{configurable:true,value:performance});
 try{await run({timers,calls});}finally{Object.assign(globalThis,originals);if(performanceDescriptor)Object.defineProperty(globalThis,'performance',performanceDescriptor);else delete globalThis.performance;}
}

test('default Translator transport polls with Window timer receiver and submits once',()=>nativeGlobals(async({timers})=>{
 const requests=[];let gets=0;
 const api=new TranslatorTurns({csrf:'synthetic',json:async(url,options={})=>{requests.push({url,method:options.method||'GET'});if(url.endsWith('/cancel'))return {status:'CANCELLED'};if(options.method==='POST')return {status:'PROCESSING'};return {status:++gets===1?'PROCESSING':'COMPLETED',translated_text:'Synthetic'};}});
 const result=api.turn('synthetic-session','synthetic-key',new Blob(['synthetic']),new AbortController().signal).then(value=>({value}),error=>({error}));
 await flush();if(!timers.size){const failed=await result;assert.equal(failed.error,undefined,'default polling must not throw '+failed.error?.message);}assert.equal(timers.size,1);const timer=[...timers.entries()][0];assert.equal(timer[1].ms,250);timers.delete(timer[0]);timer[1].fn();
 const outcome=await result;assert.equal(outcome.error,undefined);assert.equal(outcome.value.translated_text,'Synthetic');assert.equal(requests.filter(r=>r.method==='POST').length,1);assert.equal(timers.size,0);
}));

test('default Translator polling cancellation clears timer with Window receiver',()=>nativeGlobals(async({timers})=>{
 const api=new TranslatorTurns({csrf:'synthetic',json:async()=>({})}),controller=new AbortController();
 const outcome=api.pause(controller.signal).then(()=>({}),error=>({error}));await flush();if(!timers.size){const failed=await outcome;assert.equal(failed.error,undefined,'default pause must not throw '+failed.error?.message);}assert.equal(timers.size,1);controller.abort();
 assert.equal((await outcome).error.name,'AbortError');assert.equal(timers.size,0,'cancel should clear the native timer');
}));

test('default JSON fetch and deadline cleanup preserve native receiver',()=>nativeGlobals(async({timers,calls})=>{
 const result=await requestJSON('/synthetic',{csrf:'synthetic'});assert.equal(result.status,'ACTIVE');assert.equal(timers.size,0);assert.equal(calls.filter(c=>c[0]==='fetch').length,1);assert.equal(calls.filter(c=>c[0]==='clear').length,1);
}));

test('existing playback wrappers retain context/decode and native timer/fetch receivers',()=>nativeGlobals(async({timers,calls})=>{
 const context={state:'running',currentTime:0,resume(){assert.equal(this,context);return Promise.resolve();},decodeAudioData(){assert.equal(this,context);return Promise.resolve({duration:1});},createBufferSource(){assert.equal(this,context);return source;},destination:{}};
 const source={connect(){assert.equal(this,source);},disconnect(){assert.equal(this,source);},start(){assert.equal(this,source);queueMicrotask(()=>source.onended());},stop(){assert.equal(this,source);}};
 const player=new TranslatorPlayback({getContext:()=>context});await player.prepare(new AbortController().signal,()=>true);await player.play('/kilas-translator/live/sessions/'+ 'a'.repeat(48)+'/turns/live-'+ 'b'.repeat(32)+'/audio',new AbortController().signal,()=>true);
 assert.equal(timers.size,0);assert.equal(calls.filter(c=>c[0]==='fetch').length,1);
}));

test('default JSON timeout aborts transport and clears native deadline without duplicate request',()=>nativeGlobals(async({timers,calls})=>{
 let resolvePending,transportSignal;const pending=new Promise(resolve=>{resolvePending=resolve;});
 globalThis.fetch=async function(url,options){if(this!==undefined&&this!==globalThis)throw new TypeError('Illegal invocation');calls.push(['fetch',url]);transportSignal=options.signal;return pending;};
 const outcome=requestJSON('/synthetic',{csrf:'synthetic',timeoutMs:10}).then(()=>({}),error=>({error}));await flush();const timer=[...timers.entries()][0];assert.equal(timer[1].ms,10);timers.delete(timer[0]);timer[1].fn();
 assert.equal((await outcome).error.code,'request_timeout');assert.equal(transportSignal.aborted,true);assert.equal(timers.size,0);assert.equal(calls.filter(c=>c[0]==='fetch').length,1);
 resolvePending({ok:true,json:async()=>({})});await flush();assert.equal(timers.size,0);
}));
