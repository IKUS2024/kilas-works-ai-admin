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
 const f=fixture(),pending=deferred();f.api.start=()=>pending.promise;const started=f.session.start({});f.session.end();pending.resolve({session_id:'late'});await started;assert.equal(f.mics,0);assert.equal(f.ends,1);
});
test('network and permission failure stop resources without retry',async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.reject(Error('Synthetic network unavailable'));await tick();assert.deepEqual(f.errors,['Synthetic network unavailable']);assert.equal(f.mics,0);assert.equal(f.calls,1);assert.equal(f.session.state,'ended');
 const denied=fixture();denied.capture.start=async()=>{throw Error('Permission denied');};await denied.session.start({});assert.equal(denied.session.state,'ended');assert.equal(denied.ends,1);
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

for(const name of ['Error','AbortError'])test(`unexpected playback ${name} ends the owned session without regeneration or capture`,async()=>{
 const f=fixture();await f.session.start({});f.level(.1,0);f.level(0,2000);f.turn.resolve({audio_url:'/synthetic'});await tick();
 const error=Error('Audio unavailable');error.name=name;f.play.reject(error);await tick();
 assert.equal(f.session.state,'ended');assert.equal(f.mics,0);assert.equal(f.captureCalls,1);assert.equal(f.calls,1);assert.equal(f.ends,1);assert.deepEqual(f.errors,['Audio unavailable']);
});

for(const adapter of ['capture','playback'])test(`End stays responsive when ${adapter} cleanup throws`,async()=>{
 const f=fixture();await f.session.start({});const original=f[adapter][adapter==='capture'?'cancel':'stop'];
 f[adapter][adapter==='capture'?'cancel':'stop']=()=>{original();throw Error('Synthetic detached device');};
 f.session.end();assert.equal(f.session.state,'ended');assert.equal(f.session.controller.signal.aborted,true);assert.equal(f.mics,0);assert.equal(f.playing,false);assert.equal(f.ends,1);
});
