import test from 'node:test';
import assert from 'node:assert/strict';
import {RealtimeMic,microphone} from '../static/kilas_learning_realtime.mjs';
import {PCMEncoder} from '../static/kilas_learning_pcm.mjs';

const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function fixture(){
  let callback,clock=0,stopped=0,idle;
  const sent=[],results=[],errors=[],opened=[],cancels=[];
  const api={begin:async()=>{opened.push(true);},chunk:async(_s,_t,i,pcm)=>{sent.push([i,...pcm.filter((_,index)=>index%2===0)]);},
    commit:async()=>({status:'PROCESSING',turn:'learn-synthetic-1234567890'}),cancel:async(_s,t)=>{cancels.push(t);}};
  const mic=new RealtimeMic({api,session:()=> 'session',id:()=> 'synthetic-1234567890',onOpened:()=>{},
    now:()=>clock,setTimer:fn=>{idle=fn;return 1;},clearTimer:()=>{},
    openMicrophone:async fn=>{callback=fn;return ()=>{stopped++;};}});
  return {mic,api,sent,results,errors,opened,cancels,stopped:()=>stopped,idle:()=>idle(),
    start:()=>mic.start(r=>results.push(r),e=>errors.push(e)),
    chunk:(rms,value=1,advance=250)=>{clock+=advance;callback({pcm:new Uint8Array([value,0]),rms});}};
}

test('PCM encoder preserves sample count and phase across browser sample rates',()=>{
  for(const rate of [16000,44100,48000]){
    const encoder=new PCMEncoder(rate);let chunks=[];
    for(let i=0;i<rate;i+=128)chunks.push(...encoder.push(new Float32Array(Math.min(128,rate-i)).fill(.2)));
    assert.equal(chunks.length,4);assert.equal(chunks.reduce((n,c)=>n+c.pcm.length,0),32000);
    assert.ok(chunks.every(c=>Math.abs(c.rms-.2)<.001));
  }
});
test('PCM uploads during speech, stable commit only after three seconds of silence',async()=>{
  const f=fixture();await f.start();
  f.chunk(0,1);f.chunk(.03,2);await tick();
  assert.deepEqual(f.sent,[[0,1,2]]);assert.equal(f.results.length,0);
  f.chunk(.03,3);await tick();
  for(let i=0;i<11;i++){f.chunk(0,4);await tick();}
  assert.equal(f.results.length,0);f.chunk(0,5);await tick();
  assert.equal(f.results.length,1);assert.equal(f.opened.length,1);
  assert.deepEqual(f.sent.map(x=>x[0]),Array.from({length:f.sent.length},(_,i)=>i));
  assert.deepEqual(f.sent.flatMap(x=>x.slice(1)),[1,2,3,...Array(11).fill(4),5]);
  assert.equal(f.stopped(),1);assert.equal(f.cancels.length,0);
});
test('idle silence never opens a paid stream and stops microphone',async()=>{
  const f=fixture();await f.start();f.chunk(0);f.idle();await tick();
  assert.equal(f.opened.length,0);assert.equal(f.stopped(),1);assert.equal(f.errors.length,1);
});
test('End during pending admission aborts and fences late responses',async()=>{
  const f=fixture();let release,signal;
  f.api.begin=(_s,_t,s)=>{signal=s;return new Promise(r=>{release=r;});};
  await f.start();f.chunk(.03);f.mic.cancel();assert.equal(signal.aborted,true);
  release();await tick();assert.equal(f.sent.length,0);assert.equal(f.results.length,0);assert.equal(f.cancels.length,1);
});
test('transport failure never retries PCM or commits and closes microphone',async()=>{
  const f=fixture();let attempts=0;f.api.chunk=async()=>{attempts++;throw Error('lost');};
  await f.start();f.chunk(.03);await tick();
  assert.equal(attempts,1);assert.equal(f.results.length,0);assert.equal(f.errors.length,1);assert.equal(f.stopped(),1);
});
test('End during microphone permission stops the late acquired microphone',async()=>{
  const f=fixture();let release,stopped=0;f.mic.openMicrophone=()=>new Promise(r=>{release=r;});
  const pending=f.start();f.mic.cancel();release(()=>{stopped++;});await pending;
  assert.equal(stopped,1);assert.equal(f.opened.length,0);
});
test('old cancelled pump cannot unlock a newer generation chunk pump',async()=>{
  const f=fixture();let oldRelease,newRelease,calls=0;
  f.api.chunk=()=>{calls++;return new Promise(resolve=>{if(calls===1)oldRelease=resolve;else newRelease=resolve;});};
  await f.start();f.chunk(.03);await tick();f.mic.cancel();
  await f.start();f.chunk(.03);await tick();assert.equal(calls,2);
  oldRelease();await tick();f.chunk(.03);await tick();assert.equal(calls,2);
  newRelease();await tick();assert.equal(calls,3);f.mic.cancel();newRelease();await tick();
});
test('acquired microphone is stopped immediately if End interrupts worklet initialization',async()=>{
  const oldNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator'),oldWindow=globalThis.window;
  let release,stops=0,closes=0,resumes=0;
  class Context{
    constructor(){this.audioWorklet={addModule:()=>new Promise(r=>{release=r;})};}
    async close(){closes++;}
    async resume(){resumes++;}
  }
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop:()=>{stops++;}}]})}}});
  globalThis.window={AudioWorkletNode:class{},AudioContext:Context};
  try{
    const control=new AbortController(),pending=microphone(()=>{},control.signal);
    await tick();assert.ok(release);control.abort();assert.equal(stops,1);assert.equal(closes,1);
    release();await assert.rejects(pending,{name:'AbortError'});assert.equal(resumes,0);assert.equal(stops,1);
  }finally{
    if(oldNavigator)Object.defineProperty(globalThis,'navigator',oldNavigator);else delete globalThis.navigator;
    if(oldWindow===undefined)delete globalThis.window;else globalThis.window=oldWindow;
  }
});

test('real microphone adapter stops a late permission grant after End before creating audio context',async()=>{
  const oldNavigator=Object.getOwnPropertyDescriptor(globalThis,'navigator'),oldWindow=globalThis.window;
  let release,stops=0,contexts=0;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:()=>new Promise(r=>{release=r;})}}});
  globalThis.window={AudioWorkletNode:class{},AudioContext:class{constructor(){contexts++;}}};
  try{
    const control=new AbortController(),pending=microphone(()=>{},control.signal);control.abort();
    release({getTracks:()=>[{stop:()=>{stops++;}}]});await assert.rejects(pending,{name:'AbortError'});
    assert.equal(stops,1);assert.equal(contexts,0);
  }finally{
    if(oldNavigator)Object.defineProperty(globalThis,'navigator',oldNavigator);else delete globalThis.navigator;
    if(oldWindow===undefined)delete globalThis.window;else globalThis.window=oldWindow;
  }
});

test('default microphone timers preserve the browser global receiver during start, speech and cancel',async()=>{
  // HTML timers operate on Window/WorkerGlobalScope, not a RealtimeMic instance.
  // Node timers and the old arrow-function stubs accepted the wrong receiver.
  const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout;
  let chunk,timers=0,clears=0,stops=0;
  globalThis.setTimeout=function(fn,ms){assert.equal(this,globalThis,'native timer receiver');timers++;return 23;};
  globalThis.clearTimeout=function(id){assert.equal(this,globalThis,'native timer receiver');clears++;};
  try{
    const mic=new RealtimeMic({api:{begin:async()=>{},chunk:async()=>{},cancel:async()=>{}},session:()=> 'session',id:()=> 'synthetic-native-timer',onOpened:()=>{},
      openMicrophone:async callback=>{chunk=callback;return ()=>{stops++;};}});
    mic.cancel();await mic.start(()=>{},()=>{});assert.equal(timers,1);
    chunk({pcm:new Uint8Array([1,0]),rms:.03});mic.cancel();await tick();
    assert.ok(clears>=3);assert.equal(stops,1);
  }finally{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;}
});

test('quarter-second live PCM keeps up with 750ms ACKs using bounded coalescing, preserves samples and commits once',async()=>{
  let clock=0,onChunk,stops=0,commits=0;const pending=[],uploads=[],results=[],errors=[],captured=[];
  const api={begin:async()=>{},chunk:async(_s,_t,index,pcm)=>{uploads.push({index,pcm:[...pcm]});await new Promise(resolve=>pending.push({at:clock+750,resolve}));},
    commit:async()=>{commits++;return {status:'PROCESSING'};},cancel:async()=>{}};
  const mic=new RealtimeMic({api,session:()=> 'session',id:()=> 'latency-synthetic-123',now:()=>clock,setTimer:()=>1,clearTimer:()=>{},onOpened:()=>{},
    openMicrophone:async callback=>{onChunk=callback;return ()=>{stops++;};}});
  await mic.start(state=>results.push(state),error=>errors.push(error));
  async function advance(){clock+=250;for(const item of pending.filter(x=>x.at<=clock)){pending.splice(pending.indexOf(item),1);item.resolve();}await tick();}
  for(let frame=0;frame<84;frame++){
    await advance();const pcm=new Uint8Array(8000).fill(frame);captured.push(...pcm);onChunk({pcm,rms:frame<72?.03:0});await tick();
  }
  for(let n=0;n<30&&!results.length;n++)await advance();
  assert.deepEqual(errors,[]);assert.equal(commits,1);assert.equal(stops,1);assert.equal(results.length,1);
  assert.ok(uploads.every(x=>x.pcm.length<=32000));assert.ok(uploads.some(x=>x.pcm.length>8000));
  assert.deepEqual(uploads.map(x=>x.index),Array.from({length:uploads.length},(_,i)=>i));
  assert.deepEqual(uploads.flatMap(x=>x.pcm),captured);
});
