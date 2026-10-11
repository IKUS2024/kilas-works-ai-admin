import assert from 'node:assert/strict';
import test from 'node:test';
import {SilenceGate,TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(){
 let time=0,handlers,mics=0,captureCalls=0,turnCalls=0,playing=false,ends=0,states=[],errors=[];
 const turn=deferred(),play=deferred();
 const capture={start:async h=>{handlers=h;mics++;captureCalls++;},finalize:()=>{mics--;handlers.blob(new Blob(['synthetic']));},cancel:()=>{mics=0;}};
 const api={start:async()=>({session_id:'synthetic-session'}),turn:async()=>{turnCalls++;assert.equal(mics,0);return turn.promise;},end:async()=>{ends++;}};
 const playback={play:async()=>{assert.equal(mics,0);playing=true;await play.promise;playing=false;},stop:()=>{playing=false;play.resolve();}};
 const session=new TranslatorSession({api,capture,playback,onState:s=>states.push(s),onError:e=>errors.push(e),now:()=>time,key:()=> 'a'.repeat(32)});
 return {session,api,capture,playback,turn,play,states,errors,level:(r,t)=>{time=t;handlers.level(r);},get mics(){return mics;},get calls(){return turnCalls;},get captureCalls(){return captureCalls;},get playing(){return playing;},get ends(){return ends;}};
}

test('exact three seconds after last voice; leading silence never finalizes; duplicate samples finalize once',()=>{
 const gate=new SilenceGate();assert.equal(gate.sample(0,500000),false);gate.sample(.1,501000);assert.equal(gate.sample(0,503999),false);assert.equal(gate.sample(0,504000),true);assert.equal(gate.sample(0,504001),false);
 gate.reset();gate.sample(.1,0);gate.sample(.1,2000);assert.equal(gate.sample(0,4999),false);assert.equal(gate.sample(0,5000),true);
});
test('processing and playback have no mic; resume only after playback; no per-turn Start',async()=>{
 const f=fixture();await f.session.start({});assert.equal(f.mics,1);f.level(0,10000);assert.equal(f.calls,0);
 f.level(.1,11000);f.level(0,13999);assert.equal(f.calls,0);f.level(0,14000);assert.equal(f.calls,1);assert.equal(f.mics,0);
 f.level(.1,15000);f.level(0,18000);assert.equal(f.calls,1);
 f.turn.resolve({audio_url:'/synthetic'});await tick();assert.equal(f.playing,true);assert.equal(f.mics,0);f.level(.2,19000);f.level(0,22000);assert.equal(f.calls,1);
 f.play.resolve();await tick();assert.equal(f.mics,1);assert.equal(f.captureCalls,2);f.session.end();assert.equal(f.mics,0);assert.equal(f.ends,1);
});
test('End aborts processing; late successful response never plays or resumes',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,3000);f.session.end();assert.equal(f.session.controller.signal.aborted,true);
 f.turn.resolve({audio_url:'/synthetic'});await tick();assert.equal(f.playing,false);assert.equal(f.mics,0);assert.equal(f.captureCalls,1);assert.equal(f.session.state,'ended');
});
test('End during playback stops audio and never resumes capture',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,3000);f.turn.resolve({audio_url:'/synthetic'});await tick();f.session.end();await tick();assert.equal(f.playing,false);assert.equal(f.mics,0);assert.equal(f.captureCalls,1);
});
test('End during session admission cancels the late admitted server session',async()=>{
 const f=fixture(),pending=deferred();f.api.start=()=>pending.promise;const started=f.session.start({});f.session.end();pending.resolve({session_id:'late'});await started;assert.equal(f.mics,0);assert.equal(f.ends,1);
});
test('network and permission failure stop resources without retry',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,3000);f.turn.reject(Error('Synthetic network unavailable'));await tick();assert.deepEqual(f.errors,['Synthetic network unavailable']);assert.equal(f.mics,0);assert.equal(f.calls,1);assert.equal(f.session.state,'ended');
 const denied=fixture();denied.capture.start=async()=>{throw Error('Permission denied');};await denied.session.start({});assert.equal(denied.session.state,'ended');assert.equal(denied.ends,1);
});
test('no-speech is recoverable with a new utterance; failed request is never resent',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,3000);const e=Error('No speech');e.code='no_speech';f.turn.reject(e);await tick();assert.equal(f.session.state,'listening');assert.equal(f.mics,1);assert.equal(f.calls,1);f.session.end();
});
test('double Start and duplicate audio callback cannot dispatch duplicate turns',async()=>{
 const f=fixture();await Promise.all([f.session.start({}),f.session.start({})]);assert.equal(f.captureCalls,1);f.level(.1,0);f.level(0,3000);await f.session.utterance(new Blob(['late']),f.session.version);assert.equal(f.calls,1);f.session.end();f.turn.resolve({audio_url:'/synthetic'});
});
