import assert from 'node:assert/strict';
import test from 'node:test';
import {SilenceGate,TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(){
 let time=0,handlers,mics=0,captureCalls=0,turnCalls=0,playing=false,ends=0,states=[],errors=[];
 const turn=deferred(),play=deferred();
 const capture={start:async h=>{handlers=h;mics++;captureCalls++;},finalize:()=>{mics--;handlers.blob(new Blob(['synthetic']));},cancel:()=>{mics=0;}};
 const api={start:async()=>({session_id:'a'.repeat(48)}),turn:async()=>{turnCalls++;assert.equal(mics,0);return turn.promise;},end:async()=>{ends++;}};
 const playback={play:async()=>{assert.equal(mics,0);playing=true;await play.promise;playing=false;},cancel:()=>{playing=false;},stop:()=>{playing=false;play.resolve();}};
 const session=new TranslatorSession({api,capture,playback,onState:s=>states.push(s),onError:e=>errors.push(e),now:()=>time,key:()=> 'a'.repeat(32)});
 return {session,api,capture,playback,turn,play,states,errors,level:(r,t)=>{time=t;handlers.level(r);},get handlers(){return handlers;},get mics(){return mics;},get calls(){return turnCalls;},get captureCalls(){return captureCalls;},get playing(){return playing;},get ends(){return ends;}};
}

test('exact two seconds after last voice; leading silence never finalizes; duplicate samples finalize once',()=>{
 const gate=new SilenceGate();assert.equal(gate.silenceMs,2000);assert.equal(gate.sample(0,500000),false);gate.sample(.1,501000);assert.equal(gate.sample(0,502999),false);assert.equal(gate.sample(0,503000),true);assert.equal(gate.sample(0,503001),false);
 gate.reset();gate.sample(.1,0);gate.sample(.1,2000);assert.equal(gate.sample(0,3999),false);assert.equal(gate.sample(0,4000),true);
});
test('processing and playback have no mic; resume only after playback; no per-turn Start',async()=>{
 const f=fixture();await f.session.start({});assert.equal(f.mics,1);f.level(0,10000);assert.equal(f.calls,0);
 f.level(.1,11000);f.level(0,12999);assert.equal(f.calls,0);f.level(0,13000);assert.equal(f.calls,1);assert.equal(f.mics,0);
 f.level(.1,15000);f.level(0,18000);assert.equal(f.calls,1);
 f.turn.resolve({audio_url:'/synthetic'});await tick();assert.equal(f.playing,true);assert.equal(f.mics,0);f.level(.2,19000);f.level(0,22000);assert.equal(f.calls,1);
 f.play.resolve();await tick();assert.equal(f.mics,1);assert.equal(f.captureCalls,2);f.session.end();assert.equal(f.mics,0);assert.equal(f.ends,1);
});
test('End aborts processing; late successful response never plays or resumes',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.session.end();assert.equal(f.session.controller.signal.aborted,true);
 f.turn.resolve({audio_url:'/synthetic'});await tick();assert.equal(f.playing,false);assert.equal(f.mics,0);assert.equal(f.captureCalls,1);assert.equal(f.session.state,'ended');
});
test('End during playback stops audio and never resumes capture',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.resolve({audio_url:'/synthetic'});await tick();f.session.end();await tick();assert.equal(f.playing,false);assert.equal(f.mics,0);assert.equal(f.captureCalls,1);
});
test('End during session admission cancels the late admitted server session',async()=>{
 const f=fixture(),pending=deferred();f.api.start=()=>pending.promise;const started=f.session.start({});f.session.end();pending.resolve({session_id:'b'.repeat(48)});await started;assert.equal(f.mics,0);assert.equal(f.ends,1);
});
test('unconfirmed network and permission failure pause resources without retry or End',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.reject(Error('Synthetic network unavailable'));await tick();assert.deepEqual(f.errors,['Synthetic network unavailable']);assert.equal(f.mics,0);assert.equal(f.calls,1);assert.equal(f.session.state,'paused');assert.equal(f.ends,0);f.session.end();
 const denied=fixture();denied.capture.start=async()=>{throw Error('Permission denied');};await denied.session.start({});assert.equal(denied.session.state,'paused');assert.equal(denied.ends,0);denied.session.end();
});
test('no-speech is recoverable with a new utterance; failed request is never resent',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);const e=Error('No speech');e.code='no_speech';f.turn.reject(e);await tick();assert.equal(f.session.state,'listening');assert.equal(f.mics,1);assert.equal(f.calls,1);f.session.end();
});
test('double Start and duplicate audio callback cannot dispatch duplicate turns',async()=>{
 const f=fixture();await Promise.all([f.session.start({}),f.session.start({})]);assert.equal(f.captureCalls,1);f.level(.1,0);f.level(0,2000);await f.session.utterance(new Blob(['late']),f.session.version);assert.equal(f.calls,1);f.session.end();f.turn.resolve({audio_url:'/synthetic'});
});

test('empty capture resumes listening locally without any provider turn',async()=>{
 const f=fixture();f.capture.finalize=()=>{f.capture.cancel();f.handlers.blob(new Blob([]));};
 await f.session.start({});f.level(.1,0);f.level(0,2000);await tick();
 assert.equal(f.calls,0);assert.equal(f.captureCalls,2);assert.equal(f.session.state,'listening');assert.equal(f.mics,1);f.session.end();
});

test('late permission completion from ended session cannot cancel the next session',async()=>{
 const f=fixture(),permission=deferred();let calls=0,cancels=0;
 f.capture.start=async()=>{if(++calls===1)await permission.promise;};f.capture.cancel=()=>cancels++;
 const old=f.session.start({});await tick();f.session.end();await f.session.start({});
 const before=cancels;permission.resolve();await old;
 assert.equal(cancels,before);assert.equal(f.session.state,'listening');f.session.end();
});

test('late previous utterance callbacks cannot supply a newer turn in the same session',async()=>{
 const f=fixture();await f.session.start({});const old=f.handlers;
 f.level(.1,0);f.level(0,2000);f.turn.resolve({audio_url:'/synthetic'});await tick();f.play.resolve();await tick();
 f.capture.finalize=()=>f.capture.cancel();f.level(.1,4000);f.level(0,6000);
 assert.equal(f.session.state,'finalizing');old.blob(new Blob(['stale']));old.error(Error('stale error'));old.level(.1);
 assert.equal(f.calls,1);assert.equal(f.session.state,'finalizing');assert.deepEqual(f.errors,[]);f.session.end();
});

for(const state of ['processing','playing'])test(`a finalized capture error cannot pause the accepted utterance during ${state}`,async()=>{
 const f=fixture();await f.session.start({});const retired=f.handlers;
 f.level(.1,0);f.level(0,2000);
 if(state==='playing'){f.turn.resolve({audio_url:'/synthetic'});await tick();}
 assert.equal(f.session.state,state);const version=f.session.version;
 retired.error(Object.assign(Error('Late processor error after capture finished'),{code:'realtime_capture_failed'}));
 retired.blob(new Blob(['duplicate finished']));
 assert.equal(f.session.state,state);assert.equal(f.session.version,version);assert.deepEqual(f.errors,[]);assert.equal(f.calls,1);
 if(state==='processing')f.turn.resolve({audio_url:'/synthetic'});
 await tick();assert.equal(f.playing,true);f.play.resolve();await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.captureCalls,2);assert.equal(f.mics,1);f.session.end();
});

test('no-speech recovery ignores retired capture errors while verifying the owned session',async()=>{
 const f=fixture(),verify=deferred();let checks=0;f.api.resume=async()=>{checks++;await verify.promise;};
 await f.session.start({});const retired=f.handlers;
 retired.error(Object.assign(Error('No speech'),{code:'no_speech'}));assert.equal(f.session.state,'recovering');const version=f.session.version;
 retired.error(Object.assign(Error('Late processor error during recovery'),{code:'realtime_capture_failed'}));
 assert.equal(f.session.state,'recovering');assert.equal(f.session.version,version);assert.equal(checks,1);assert.deepEqual(f.errors,['No speech']);
 verify.resolve();await tick();assert.equal(f.session.state,'listening');assert.equal(f.captureCalls,2);assert.equal(f.mics,1);assert.equal(f.calls,0);f.session.end();
});

test('old no-speech recovery permission rejection cannot end a restarted session',async()=>{
 const f=fixture(),permission=deferred(),original=f.capture.start;let calls=0;
 f.capture.start=async h=>{if(++calls===2)await permission.promise;else await original(h);};
 await f.session.start({});f.level(.1,0);f.level(0,2000);
 const error=Error('No speech');error.code='no_speech';f.turn.reject(error);await tick();
 f.session.end();await f.session.start({});permission.reject(Error('Old permission denied'));await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.mics,1);assert.deepEqual(f.errors,['No speech']);f.session.end();
});

test('audio preparation failure never admits a server session or captures a microphone',async()=>{
 const f=fixture();let starts=0;f.api.start=async()=>{starts++;return {session_id:'unexpected'};};
 f.playback.prepare=async()=>{throw Error('Audio permission failed');};await f.session.start({});
 assert.equal(starts,0);assert.equal(f.captureCalls,0);assert.equal(f.session.state,'ended');assert.deepEqual(f.errors,['Audio permission failed']);
});

test('End while audio preparation is pending never admits or captures when it completes late',async()=>{
 const f=fixture(),ready=deferred();let starts=0;f.playback.prepare=()=>ready.promise;f.api.start=async()=>{starts++;};
 const pending=f.session.start({});f.session.end();ready.resolve();await pending;
 assert.equal(starts,0);assert.equal(f.captureCalls,0);assert.equal(f.session.state,'ended');
});

for(const name of ['Error','AbortError'])test(`playback ${name} recovers listening in the same session without regeneration`,async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.resolve({audio_url:'/synthetic'});await tick();
 const error=Error('Audio unavailable');error.name=name;f.play.reject(error);await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.mics,1);assert.equal(f.playing,false);assert.equal(f.captureCalls,2);assert.equal(f.calls,1);assert.equal(f.ends,0);assert.equal(f.session.id,'a'.repeat(48));assert.deepEqual(f.errors,['Audio unavailable']);f.session.end();
});

for(const adapter of ['capture','playback'])test(`End stays responsive when ${adapter} cleanup throws`,async()=>{
 const f=fixture();await f.session.start({});const original=f[adapter][adapter==='capture'?'cancel':'stop'];
 f[adapter][adapter==='capture'?'cancel':'stop']=()=>{original();throw Error('Synthetic detached device');};
 f.session.end();assert.equal(f.session.state,'ended');assert.equal(f.session.controller.signal.aborted,true);assert.equal(f.mics,0);assert.equal(f.playing,false);assert.equal(f.ends,1);
});

test('idle buffer renewal keeps the session listening without error, End or provider work',async()=>{
 const f=fixture();await f.session.start({});const old=f.handlers;
 old.error(Object.assign(Error(''),{code:'capture_idle',silent:true,recoverable:true}));await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.session.id,'a'.repeat(48));assert.equal(f.captureCalls,2);assert.equal(f.calls,0);assert.equal(f.ends,0);assert.deepEqual(f.errors,[]);old.blob(new Blob(['stale']));assert.equal(f.calls,0);f.session.end();
});

test('confirmed turn timeout recovers listening in the owned session without resubmission',async()=>{
 const f=fixture();let checks=0;f.api.resume=async(id,key)=>{checks++;assert.equal(id,'a'.repeat(48));assert.equal(key,null);};
 await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.reject(Object.assign(Error('Turn timeout'),{code:'turn_timeout',recoverable:true,turnSettled:true}));await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.mics,1);assert.equal(f.calls,1);assert.equal(f.ends,0);assert.equal(checks,1);f.session.end();
});

test('credit exhaustion pauses without ending or starting another capture until an explicit resume',async()=>{
 const f=fixture();let checks=0;f.api.resume=async()=>{checks++;};await f.session.start({});f.level(.1,0);f.level(0,2000);
 f.turn.reject(Object.assign(Error('Capacity exhausted'),{code:'provider_credit_exhausted',recoverable:false,turnSettled:true}));await tick();
 assert.equal(f.session.state,'paused');assert.equal(f.mics,0);assert.equal(f.calls,1);assert.equal(f.ends,0);assert.equal(checks,0);
 await f.session.resume();assert.equal(f.session.state,'listening');assert.equal(f.calls,1);assert.equal(checks,1);f.session.end();
});

test('End during uncertain-turn resume invalidates late verification and never captures again',async()=>{
 const f=fixture(),verify=deferred();let pending;f.api.resume=async(id,key)=>{pending=key;await verify.promise;};
 await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.reject(Error('Offline'));await tick();assert.equal(f.session.state,'paused');assert.ok(f.session.pendingKey);
 const resume=f.session.resume();await tick();assert.ok(pending);f.session.end();verify.resolve();await resume;
 assert.equal(f.session.state,'ended');assert.equal(f.captureCalls,1);assert.equal(f.ends,1);assert.equal(f.calls,1);
});

test('hidden page pauses local media while retaining the session; old provider response cannot play',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.session.suspend();
 assert.equal(f.session.state,'paused');assert.equal(f.session.id,'a'.repeat(48));assert.equal(f.mics,0);assert.equal(f.ends,0);
 f.turn.resolve({audio_url:'/synthetic'});await tick();assert.equal(f.playing,false);assert.equal(f.captureCalls,1);f.session.end();
});

test('a too-long recording pauses truthfully without sending truncated speech or closing the session',async()=>{
 const f=fixture();await f.session.start({});f.handlers.error(Object.assign(Error('Recording limit'),{code:'utterance_limit'}));await tick();
 assert.equal(f.session.state,'paused');assert.equal(f.calls,0);assert.equal(f.mics,0);assert.equal(f.ends,0);f.session.end();
});
