import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(mode='realtime-v1'){
  let h,time=0,mics=0,turns=0,starts=0,plays=0,finish,fail;
  const api={start:async()=>({session_id:'a'.repeat(48),input_mode:mode}),input:{reset(){},push:async()=>{},finish:async()=>{}},
    turn:async()=>{turns++;return {audio_url:'audio-'+turns};},resume:async()=>{},end:async()=>{}};
  const capture={start:async value=>{assert.equal(mics,0);mics++;starts++;h=value;h.ready();},cancel(){mics=0;},finalize(){mics=0;h.blob(new Blob(['fixture']));}};
  const playback={play:()=>{assert.equal(mics,0);plays++;return new Promise((resolve,reject)=>{finish=resolve;fail=reject;});},stop(){mics=0;finish?.();},cancel(){finish?.();}};
  const session=new TranslatorSession({api,capture,playback,pushToTalk:true,recordOnStart:true,continuous:true,now:()=>time,key:()=>String(turns).padStart(32,'a')});
  return {session,api,capture,get h(){return h;},get starts(){return starts;},get turns(){return turns;},get mics(){return mics;},get plays(){return plays;},level(rms,ms){time+=ms;if(rms>.015&&mode==='realtime-v1')h.pcm(new Uint8Array(6400));h.level(rms);},finish(){finish();},fail(){fail(Error('output unavailable'));}};
}
test('Start streams PCM, silence commits once, playback excludes mic, then next direction listens without Start',async()=>{
 const f=fixture();await f.session.start({});
 for(let i=0;i<3;i++){
  const old=f.h;f.level(.2,100);assert.ok(f.session.pendingKey);assert.equal(f.turns,i);
  f.level(0,1199);assert.equal(f.turns,i);f.level(0,1);await tick();
  assert.equal(f.turns,i+1);assert.equal(f.mics,0);assert.equal(f.session.running,true);
  old.blob(new Blob(['duplicate']));old.level(.2);assert.equal(f.turns,i+1);
  f.finish();await tick();assert.equal(f.mics,1);assert.equal(f.session.state,'listening');
 }
 f.session.release();assert.equal(f.session.running,false);assert.equal(f.mics,0);f.session.end();
});
for(const phase of ['processing','playing'])test('Stop during '+phase+' drains only admitted output and cannot restart capture',async()=>{
 const f=fixture();let resolve;if(phase==='processing')f.api.turn=()=>new Promise(r=>resolve=r);
 await f.session.start({});f.level(.2,100);f.level(0,1200);await tick();assert.equal(f.session.state,phase);
 f.session.release();assert.equal(f.session.running,false);
 if(resolve){resolve({audio_url:'one'});await tick();}
 f.finish();await tick();assert.equal(f.session.state,'ready');assert.equal(f.starts,1);assert.equal(f.mics,0);f.session.end();
});
test('manual Stop flushes remaining speech once and a later Start begins a new run',async()=>{
 const f=fixture();await f.session.start({});f.level(.2,100);f.session.release();f.session.release();await tick();assert.equal(f.turns,1);
 f.finish();await tick();assert.equal(f.session.state,'ready');await f.session.press();assert.equal(f.session.running,true);assert.equal(f.starts,2);f.session.end();
});
test('batch fallback never auto-submits or claims continuous streaming',async()=>{
 const f=fixture('batch');await f.session.start({});assert.equal(f.session.running,false);f.level(.2,100);f.level(0,4000);assert.equal(f.turns,0);
 f.session.release();await tick();f.finish();await tick();assert.equal(f.session.state,'ready');assert.equal(f.starts,1);f.session.end();
});
test('twenty admitted turns require a fresh intentional Start',async()=>{
 const f=fixture();await f.session.start({});
 for(let i=0;i<20;i++){f.level(.2,100);f.level(0,1200);await tick();f.finish();await tick();}
 assert.equal(f.turns,20);assert.equal(f.starts,20);assert.equal(f.session.running,false);assert.equal(f.session.state,'ready');f.session.end();
});
test('ten minute idle run stops locally without a provider call',async()=>{
 const f=fixture();await f.session.start({});f.level(0,600000);assert.equal(f.turns,0);assert.equal(f.mics,0);assert.equal(f.session.state,'ready');f.session.end();
});
test('failure and visibility recovery cannot auto-run or regenerate paid speech',async()=>{
 for(const failure of ['provider','visibility']){
  const f=fixture();await f.session.start({});f.level(.2,100);f.level(0,1200);await tick();
  if(failure==='provider')f.fail();else f.session.suspend();await tick();assert.equal(f.session.running,false);assert.equal(f.mics,0);assert.equal(f.turns,1);f.session.end();
 }
});
