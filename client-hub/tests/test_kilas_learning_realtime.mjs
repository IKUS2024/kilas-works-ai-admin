import test from 'node:test';
import assert from 'node:assert/strict';
import {RealtimeMic,microphone} from '../static/kilas_learning_realtime.mjs';
import {PCMEncoder} from '../static/kilas_learning_pcm.mjs';

const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function fixture(){
  let callback,clock=0,stopped=0,idle;
  const sent=[],results=[],errors=[],opened=[],cancels=[];
  const api={begin:async()=>{opened.push(true);},chunk:async(_s,_t,i,pcm)=>{sent.push([i,pcm[0]]);},
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
  assert.deepEqual(f.sent,[[0,1],[1,2]]);assert.equal(f.results.length,0);
  f.chunk(.03,3);await tick();
  for(let i=0;i<11;i++){f.chunk(0,4);await tick();}
  assert.equal(f.results.length,0);f.chunk(0,5);await tick();
  assert.equal(f.results.length,1);assert.equal(f.opened.length,1);
  assert.deepEqual(f.sent.map(x=>x[0]),Array.from({length:15},(_,i)=>i));
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
