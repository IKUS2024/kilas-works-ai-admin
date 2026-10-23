import test from 'node:test';
import assert from 'node:assert/strict';
import {StreamingTranslatorSession} from '../static/kilas_live_translator_streaming.mjs';
const tick=()=>new Promise(r=>setTimeout(r,4));
async function until(fn){for(let n=0;n<100&&!fn();n++)await tick();assert.ok(fn());}
function fixture(){
 let h,clock=0,mics=0,starts=0,serial=0,pushes=0,plays=0,cancels=0,finishPlay;
 const states=new Map(),keys=[],acks=[];
 const api={start:async()=>({session_id:'a'.repeat(48),input_mode:'realtime-v1'}),end:async()=>{},
  input:{reset(){},push:async(id,key)=>{pushes++;if(!states.has(key)){keys.push(key);states.set(key,{status:'PROCESSING',clauses:[]});}},finish:async(id,key)=>{states.get(key).status='COMPLETED';}},
  clauses:{read:async(id,key)=>({...states.get(key),clauses:[...states.get(key).clauses]}),ack:async(id,key,index)=>{acks.push(index);states.get(key).clauses.shift();},cancel:async()=>{cancels++;}},
  turn:async(id,key)=>({status:'COMPLETED',audio_url:key,translated_text:'stable '+key})};
 const capture={start:async value=>{h=value;starts++;mics=1;h.ready();},cancel(){mics=0;},finalize(){mics=0;h.blob(null);}};
 const playback={play:async()=>{assert.equal(mics,1);plays++;await new Promise(r=>finishPlay=r);},cancel(){finishPlay?.();},stop(){finishPlay?.();}};
 const session=new StreamingTranslatorSession({api,capture,playback,continuous:true,pushToTalk:true,recordOnStart:true,now:()=>clock,key:()=>String(++serial).padStart(32,'0'),schedule:(fn,ms)=>setTimeout(fn,ms===250?1:ms)});
 return {session,api,capture,states,keys,acks,get h(){return h;},get mics(){return mics;},get starts(){return starts;},get pushes(){return pushes;},get plays(){return plays;},get cancels(){return cancels;},finish(){finishPlay();},frame(rms=.2,ms=200){clock+=ms;h.pcm(new Uint8Array(6400),{rms});},clause(index=0){states.get(keys.at(-1)).clauses.push({index,key:'live-'+(index+1).toString(16).padStart(32,'a')});}};
}
test('committed clause playback overlaps ongoing PCM and duplicate snapshots never replay it',async()=>{
 const f=fixture();await f.session.start({});f.frame();await tick();f.clause();await until(()=>f.plays===1);
 const before=f.pushes;for(let n=0;n<20;n++)f.frame();assert.ok(f.pushes>before);assert.equal(f.mics,1);assert.equal(f.starts,1);
 await tick();assert.equal(f.plays,1);f.finish();await until(()=>f.acks.length===1);await tick();assert.equal(f.plays,1);
 f.session.release();await until(()=>f.session.state==='ready');const stopped=f.pushes;f.h.pcm(new Uint8Array(6400),{rms:.2});await tick();assert.equal(f.pushes,stopped);f.session.end();
});
test('continuous speech rotates finite supplier leases without reopening mic or losing frames',async()=>{
 const f=fixture();await f.session.start({});
 for(let n=0;n<1300;n++){f.frame();if(n%20===0)await tick();}
 await tick();assert.ok(f.keys.length>=3);assert.equal(f.pushes,1300);assert.equal(f.starts,1);assert.equal(f.mics,1);assert.equal(f.session.running,true);f.session.end();
});
test('idle capture creates no paid input; Stop and End retire pending callbacks',async()=>{
 const f=fixture();await f.session.start({});for(let n=0;n<50;n++)f.frame(0,30000);assert.equal(f.pushes,0);
 f.session.release();assert.equal(f.mics,0);f.frame();assert.equal(f.pushes,0);await f.session.press();f.frame();await tick();
 const old=f.h;f.session.end();const count=f.pushes;old.pcm(new Uint8Array(6400),{rms:.2});old.blob(null);await tick();assert.equal(f.pushes,count);assert.equal(f.mics,0);
});
test('bounded backlog pauses and cancels rather than opening another supplier or dropping hidden audio',async()=>{
 const f=fixture();f.api.input.finish=async()=>{};await f.session.start({});f.frame();for(let n=0;n<50;n++)f.frame(0);
 for(let n=0;n<45;n++)f.frame();assert.equal(f.session.state,'paused');assert.equal(f.mics,0);assert.equal(f.keys.length,1);assert.ok(f.cancels);f.session.end();
});
test('unverified echo cancellation selects the existing fallback before supplier dispatch',async()=>{
 const f=fixture(),start=f.capture.start;f.capture.start=async options=>{if(options.duplex)throw Object.assign(Error('no echo protection'),{code:'duplex_unavailable'});return start(options);};
 await f.session.start({});assert.equal(f.session.streaming,false);assert.equal(f.pushes,0);assert.equal(f.session.state,'listening');f.session.end();
});

test('short conversational pauses keep the input lease open while audio is playing',async()=>{
 const f=fixture();await f.session.start({});f.frame();await tick();f.clause();await until(()=>f.plays===1);
 for(let n=0;n<10;n++)f.frame(0);
 assert.equal(f.session.lease.finishing,false);assert.equal(f.session.bufferBytes,0);
 const before=f.pushes;f.frame();assert.equal(f.pushes,before+1);assert.equal(f.keys.length,1);
 f.finish();await until(()=>f.acks.length===1);f.session.release();await until(()=>f.session.state==='ready');f.session.end();
});
