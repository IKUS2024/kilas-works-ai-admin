// Offline production engine/capture with synthetic media and clocks. No browser/provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {RealtimeCapture} from '../static/kilas_live_translator_realtime_capture.mjs';
const id='a'.repeat(48),lateId='b'.repeat(48);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
function clock(){
 let sequence=0;const timers=new Map();
 return {timers,schedule(fn,ms){const key=++sequence;timers.set(key,{fn,ms});return key;},clear:key=>timers.delete(key),async fire(ms){const timer=[...timers].find(([,value])=>value.ms===ms);assert.ok(timer,'deadline '+ms+' exists');timers.delete(timer[0]);timer[1].fn();await tick();}};
}
function sessionFixture(){
 const time=clock(),calls={starts:0,captures:0,turns:0,ended:[],errors:[],states:[]};
 const api={async start(){calls.starts++;return {session_id:id};},async end(value){calls.ended.push(value);},async turn(){calls.turns++;}};
 const capture={async start(){calls.captures++;},cancel(){}};
 const playback={prepare(){},stop(){},cancel(){}};
 const session=new TranslatorSession({api,capture,playback,...time,onError:(message,error)=>calls.errors.push({message,error}),onState:state=>calls.states.push(state)});
 return {session,api,capture,playback,calls,time};
}
for(const stage of ['prepare','admission','capture'])test('unsettled '+stage+' is bounded and never auto-retries',async()=>{
 const f=sessionFixture(),held=deferred();
 if(stage==='prepare')f.playback.prepare=()=>held.promise;
 if(stage==='admission')f.api.start=()=>{f.calls.starts++;return held.promise;};
 if(stage==='capture')f.capture.start=()=>{f.calls.captures++;return held.promise;};
 const work=f.session.start({});await tick();await f.time.fire(stage==='prepare'?6000:stage==='admission'?32000:45000);await work;
 assert.equal(f.session.state,stage==='capture'?'paused':'ended');assert.match(f.calls.errors[0].error.code,/_timeout$/);assert.ok(f.calls.errors[0].error.startupStage);assert.equal(f.calls.turns,0);assert.equal(f.calls.starts,stage==='prepare'?0:1);assert.equal(f.calls.ended.length,0);assert.equal(f.time.timers.size,0);
 held.resolve(stage==='admission'?{session_id:lateId}:undefined);await tick();assert.deepEqual(f.calls.ended,stage==='admission'?[lateId]:[]);assert.equal(f.calls.captures,stage==='capture'?1:0);f.session.end();
});
for(const stage of ['prepare','admission','capture'])test('End during '+stage+' settles immediately even when adapter ignores abort',async()=>{
 const f=sessionFixture(),held=deferred();
 if(stage==='prepare')f.playback.prepare=()=>held.promise;
 if(stage==='admission')f.api.start=()=>held.promise;
 if(stage==='capture')f.capture.start=()=>held.promise;
 const work=f.session.start({});await tick();f.session.end();await work;
 assert.equal(f.session.state,'ended');assert.equal(f.time.timers.size,0);assert.equal(f.calls.turns,0);
 held.resolve(stage==='admission'?{session_id:lateId}:undefined);await tick();assert.deepEqual(f.calls.ended,stage==='admission'?[lateId]:stage==='capture'?[id]:[]);assert.equal(f.session.state,'ended');
});
for(const value of [undefined,null,{}, {session_id:''},{session_id:'  '},{session_id:'other-owner'}, {session_id:123},{session_id:'a'.repeat(47)}])test('invalid admission '+JSON.stringify(value)+' does not capture or send another request',async()=>{
 const f=sessionFixture();f.api.start=async()=>{f.calls.starts++;return value;};await f.session.start({});
 assert.equal(f.session.state,'ended');assert.equal(f.calls.errors[0].error.code,'session_response_invalid');assert.equal(f.calls.captures,0);assert.equal(f.calls.starts,1);assert.deepEqual(f.calls.ended,[]);assert.equal(f.time.timers.size,0);
});
test('native adapter rejection preserves its original cause and stage',async()=>{
 const f=sessionFixture(),failure=Object.assign(new TypeError('Illegal invocation'),{code:'native_receiver'});f.playback.prepare=()=>{throw failure;};await f.session.start({});
 assert.equal(f.calls.errors[0].error,failure);assert.equal(failure.startupStage,'audio_prepare');assert.equal(f.calls.starts,0);assert.equal(f.time.timers.size,0);
});
for(const stage of ['prepare','admission','capture'])test('empty rejection during '+stage+' leaves a clear failure instead of an infinite startup',async()=>{
 const f=sessionFixture();if(stage==='prepare')f.playback.prepare=()=>Promise.reject();if(stage==='admission')f.api.start=()=>Promise.reject();if(stage==='capture')f.capture.start=()=>Promise.reject();
 await f.session.start({});assert.equal(f.session.state,stage==='capture'?'paused':'ended');assert.match(f.calls.errors[0].error.code,/_failed$/);assert.ok(f.calls.errors[0].message);assert.equal(f.time.timers.size,0);f.session.end();
});
test('throwing error reporter cannot block local cleanup or End',async()=>{
 const f=sessionFixture();f.session.onError=()=>{throw Error('Detached error view');};f.playback.prepare=()=>Promise.reject();await f.session.start({});assert.equal(f.session.state,'ended');assert.equal(f.time.timers.size,0);
 f.playback.prepare=()=>{};f.capture.start=()=>Promise.reject();await f.session.start({});assert.equal(f.session.state,'paused');f.session.end();assert.deepEqual(f.calls.ended,[id]);
});
test('throwing state view cannot leave the startup engine active',async()=>{
 const f=sessionFixture();f.session.onState=()=>{throw Error('Detached state view');};await f.session.start({});assert.equal(f.session.state,'ended');assert.equal(f.calls.starts,0);assert.equal(f.time.timers.size,0);
});
test('Resume deadline preserves admitted session without a new admission',async()=>{
 const f=sessionFixture();await f.session.start({});f.session.pause(Error('Device interrupted'));const held=deferred();f.playback.prepare=()=>held.promise;
 const work=f.session.resume();await tick();await f.time.fire(6000);await work;assert.equal(f.session.state,'paused');assert.equal(f.session.id,id);assert.equal(f.calls.starts,1);assert.deepEqual(f.calls.ended,[]);f.session.end();
});
function captureFixture(){
 const time=clock(),calls={errors:[],ready:0,pcm:0},track={stops:0,stop(){this.stops++;},addEventListener(){}},stream={getTracks:()=>[track]};
 const node={port:{onmessage:null,postMessage(){}},connect(){},disconnect(){}};
 const context={state:'running',audioWorklet:{addModule(){return Promise.resolve();}},destination:{},createMediaStreamSource(){return {connect(){},disconnect(){}};},resume(){this.state='running';}};
 const mediaDevices={getUserMedia(){return Promise.resolve(stream);}};
 const capture=new RealtimeCapture({getContext:()=>context,mediaDevices,createNode:()=>node,...time});
 const begin=()=>capture.start({ready:()=>calls.ready++,level(){},pcm(){calls.pcm++;},blob(){},error:error=>calls.errors.push(error)});
 return {time,calls,track,stream,node,context,mediaDevices,capture,begin};
}
for(const stage of ['permission','module','first_pcm','context'])test('native '+stage+' never settles: typed failure releases owned resources',async()=>{
 const f=captureFixture(),held=deferred();
 if(stage==='permission')f.mediaDevices.getUserMedia=()=>held.promise;
 if(stage==='module')f.context.audioWorklet.addModule=()=>held.promise;
 if(stage==='context'){f.context.state='suspended';f.context.resume=()=>held.promise;}
 const work=f.begin(),code={permission:'microphone_permission_timeout',module:'realtime_module_timeout',first_pcm:'realtime_input_timeout',context:'audio_resume'}[stage];
 const failed=assert.rejects(work,error=>error.code===code);await tick();await f.time.fire(stage==='permission'?20000:stage==='module'?10000:5000);await failed;
 assert.equal(f.calls.ready,0);assert.equal(f.calls.pcm,0);assert.equal(f.calls.errors.length,0);assert.equal(f.node.port.onmessage,null);assert.equal(f.time.timers.size,0);
 held.resolve(stage==='permission'?f.stream:undefined);await tick();assert.equal(f.track.stops,stage==='context'?0:1);
});
test('first silent PCM confirms readiness without a supplier request',async()=>{
 const f=captureFixture(),work=f.begin();await tick();assert.equal(f.calls.ready,0);f.node.port.onmessage({data:{bytes:new ArrayBuffer(6400),rms:0}});await work;
 assert.equal(f.calls.ready,1);assert.equal(f.calls.pcm,0);assert.equal([...f.time.timers.values()].some(t=>t.ms===5000),false);f.capture.cancel();assert.equal(f.time.timers.size,0);assert.equal(f.track.stops,1);
});
test('first voiced PCM is retained when capture synchronously signals readiness to the engine',async()=>{
 const f=captureFixture(),pushed=[],api={async start(){return {session_id:id,input_mode:'realtime-v1'};},input:{reset(){},async push(_id,_key,bytes){pushed.push(bytes);}},async end(){}};
 const session=new TranslatorSession({api,capture:f.capture,playback:{prepare(){},stop(){},cancel(){}},...f.time,key:()=> 'c'.repeat(32)});
 const work=session.start({});await tick();assert.equal(session.state,'opening');const bytes=new ArrayBuffer(6400);new Uint8Array(bytes).fill(17);f.node.port.onmessage({data:{bytes,rms:.2}});await work;
 assert.equal(session.state,'listening');assert.equal(pushed.length,1);assert.deepEqual(pushed[0],new Uint8Array(bytes));assert.equal(session.gate.lastVoice!==null,true);session.end();assert.equal(f.time.timers.size,0);
});
test('late permission after End stops only its own stream while newer capture stays ready',async()=>{
 const f=captureFixture(),held=deferred();f.mediaDevices.getUserMedia=()=>held.promise;const old=f.begin(),failed=assert.rejects(old,{name:'AbortError'});await tick();f.capture.cancel();await failed;
 const newerTrack={stops:0,stop(){this.stops++;},addEventListener(){}};f.mediaDevices.getUserMedia=async()=>({getTracks:()=>[newerTrack]});const newer=f.begin();await tick();f.node.port.onmessage({data:{bytes:new ArrayBuffer(6400),rms:0}});await newer;
 held.resolve(f.stream);await tick();assert.equal(f.track.stops,1);assert.equal(newerTrack.stops,0);assert.equal(f.calls.ready,1);f.capture.cancel();assert.equal(newerTrack.stops,1);
});
test('permission denial is reported once with its typed cause',async()=>{
 const f=captureFixture();f.mediaDevices.getUserMedia=()=>Promise.reject(new DOMException('Denied','NotAllowedError'));await assert.rejects(f.begin(),error=>error.code==='microphone_permission_denied');assert.equal(f.calls.errors.length,0);assert.equal(f.time.timers.size,0);
});
