// Pure production adapters with synthetic PCM/HTTP/media/clock; no browser/mic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {PcmEncoder} from '../static/kilas_live_translator_pcm.mjs';
import {RealtimeInput} from '../static/kilas_live_translator_realtime_input.mjs';
import {RealtimeCapture} from '../static/kilas_live_translator_realtime_capture.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const id='a'.repeat(48),key='live-'+'b'.repeat(32),url='/kilas-translator/live/sessions/'+id+'/turns/'+key;
function encode(rate,values,width){const result=[],pcm=new PcmEncoder(rate,p=>result.push(p));for(let i=0;i<values.length;i+=width)pcm.feed([values.subarray(i,i+width)]);pcm.finish();return {parts:result,bytes:Buffer.concat(result.map(p=>Buffer.from(p.bytes)))};}

test('PCM48k/44.1k becomes exactly16k mono little endian, bounded200ms frames',()=>{
 for(const rate of [48000,44100,16000]){const f=encode(rate,new Float32Array(rate).fill(.5),128);assert.equal(f.bytes.length,32000);assert.equal(f.bytes.readInt16LE(0),16384);assert.equal(f.parts.length,5);assert.ok(f.parts.every(p=>p.bytes.byteLength===6400&&p.rms>.49));}
});
test('PCM phase and final partial frame survive arbitrary source block boundaries',()=>{
 const data=Float32Array.from({length:54321},(_,i)=>Math.sin(i*.013)*.2),a=encode(44100,data,128),b=encode(44100,data,997);assert.deepEqual(a.bytes,b.bytes);assert.equal(a.bytes.length,Math.ceil(data.length*16000/44100)*2);assert.ok(a.parts.at(-1).bytes.byteLength<6400);
});
test('PCM stereo is averaged/clamped and invalid rate/frame/sample rejects',()=>{
 const parts=[],p=new PcmEncoder(16000,v=>parts.push(v));p.feed([new Float32Array([1,-1,.5]),new Float32Array([1,-1,-.5])]);p.finish();const bytes=Buffer.from(parts[0].bytes);assert.deepEqual([0,2,4].map(i=>bytes.readInt16LE(i)),[32767,-32768,0]);
 for(const rate of [8000,NaN,100000])assert.throws(()=>new PcmEncoder(rate,()=>{}));assert.throws(()=>new PcmEncoder(16000,()=>{}).feed([new Float32Array([NaN])]));
});
function inputFixture({delay=null,failCommit=false}={}){
 const requests=[],accepted=[],controller=new AbortController();
 const input=new RealtimeInput({csrf:'synthetic',json:async(path,options)=>{
  requests.push({path,options});if(path.endsWith('/cancel'))return {status:'CANCELLED'};
  if(path.endsWith('/input/start')){if(delay)await delay();return {input_mode:'realtime-v1'};}
  if(path.includes('/input/chunks/')){const bytes=new Uint8Array(await options.body.get('pcm').arrayBuffer());accepted.push({index:Number(path.split('/').at(-1)),bytes});if(delay)await delay();return {accepted_index:Number(path.split('/').at(-1))};}
  if(path.endsWith('/input/commit')){if(failCommit)throw Object.assign(Error('Lost ack'),{code:'request_timeout'});return {status:'PROCESSING'};}
  throw Error('Unexpected whole STT POST');
 }});return {input,requests,accepted,controller,push:bytes=>input.push(id,key,bytes,controller.signal),finish:()=>input.finish(id,key,controller.signal)};
}
test('input primes first200ms then aggregates1s and drains exact final tail before one commit',async()=>{
 const f=inputFixture(),original=[];for(let i=0;i<12;i++){const bytes=new Uint8Array(6400).fill(i);original.push(bytes);await f.push(bytes);}
 assert.equal(f.requests[0].path,url+'/input/start');assert.equal(f.accepted.length,3);assert.equal(f.accepted[0].bytes.length,6400);await f.finish();assert.deepEqual(f.accepted.map(p=>p.index),[0,1,2,3]);assert.equal(f.accepted.at(-1).bytes.length,6400);
 assert.deepEqual(Buffer.concat(f.accepted.map(p=>Buffer.from(p.bytes))),Buffer.concat(original.map(p=>Buffer.from(p))));const commit=f.requests.at(-1);assert.equal(commit.path,url+'/input/commit');assert.equal(commit.options.body.get('count'),'4');assert.equal(commit.options.body.get('csrf_token'),'synthetic');
});
test('first capture frame reaches the same lease before more speech or finalization',async()=>{
 const f=inputFixture(),first=new Uint8Array(6400).fill(31);await f.push(first);
 assert.deepEqual(f.accepted.map(p=>p.bytes),[first]);
 assert.equal(f.requests.filter(r=>r.path.endsWith('/input/start')).length,1);
 assert.equal(f.requests.some(r=>r.path.endsWith('/input/commit')),false);
 await f.push(new Uint8Array(138).fill(19));assert.equal(f.accepted.length,1);
 await f.finish();assert.equal(f.accepted.length,2);assert.equal(f.accepted[1].bytes.length,138);
 assert.equal(f.requests.filter(r=>r.path.endsWith('/input/start')).length,1);
});
test('healthy350ms serialHTTP sustains200ms PCM production over a long utterance with exact final tail',async()=>{
 let now=0,timers=[];const delay=()=>new Promise(resolve=>timers.push({at:now+350,resolve}));
 async function advance(ms){const end=now+ms;await tick();while(timers.some(t=>t.at<=end)){timers.sort((a,b)=>a.at-b.at);const timer=timers.shift();now=timer.at;timer.resolve();await tick();}now=end;await tick();}
 const f=inputFixture({delay}),original=[],pending=[];
 for(let i=0;i<250;i++){const bytes=new Uint8Array(6400).fill(i%255);original.push(bytes);pending.push(f.push(bytes));await advance(200);}
 const tail=new Uint8Array(138).fill(87);original.push(tail);pending.push(f.push(tail));const finish=f.finish();await advance(5000);await Promise.all(pending);await finish;
 assert.equal(f.accepted.length,51);assert.deepEqual(Buffer.concat(f.accepted.map(p=>Buffer.from(p.bytes))),Buffer.concat(original.map(p=>Buffer.from(p))));assert.equal(f.requests.filter(r=>r.path.endsWith('/input/commit')).length,1);
});
test('bounded upload overflow cancels rather than translating accepted prefix',async()=>{
 const held=deferred(),f=inputFixture({delay:()=>held.promise}),pending=[];
 for(let i=0;i<8;i++)pending.push(f.push(new Uint8Array(32000)).catch(e=>e));
 await assert.rejects(f.push(new Uint8Array(2)),e=>e.code==='realtime_queue_full');const done=assert.rejects(f.finish(),e=>e.code==='realtime_queue_full');held.resolve();await Promise.all(pending);await done;assert.equal(f.requests.some(r=>r.path.endsWith('/input/commit')),false);assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,1);
});
test('six seconds of startup backlog drains every byte in order before one final commit',async()=>{
 const held=deferred(),f=inputFixture({delay:()=>held.promise}),pending=[],original=[];
 for(let i=0;i<6;i++){const bytes=new Uint8Array(32000).fill(i+1);original.push(bytes);pending.push(f.push(bytes));}
 const tail=new Uint8Array(138).fill(71);original.push(tail);pending.push(f.push(tail));
 const finished=f.finish();await tick();assert.equal(f.accepted.length,0);
 held.resolve();await Promise.all(pending);await finished;
 assert.deepEqual(Buffer.concat(f.accepted.map(p=>Buffer.from(p.bytes))),Buffer.concat(original.map(p=>Buffer.from(p))));
 assert.deepEqual(f.accepted.map(p=>p.index),[0,1,2,3,4,5,6]);
 assert.equal(f.requests.filter(r=>r.path.endsWith('/input/start')).length,1);
 assert.equal(f.requests.filter(r=>r.path.endsWith('/input/commit')).length,1);
 assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,0);
});
test('End abort cancels scoped input and late start acknowledgement cannot send buffered PCM',async()=>{
 const held=deferred(),f=inputFixture({delay:()=>held.promise}),work=f.push(new Uint8Array(32000)),failed=assert.rejects(work,{name:'AbortError'});f.controller.abort();held.resolve();await failed;assert.equal(f.accepted.length,0);assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,1);f.input.reset();
});
test('lost final commit acknowledgement cancels without any batch fallback/regeneration',async()=>{
 const f=inputFixture({failCommit:true});await f.push(new Uint8Array(32000));await assert.rejects(f.finish(),e=>e.code==='request_timeout'&&e.turnSettled&&e.recoverable);assert.equal(f.requests.filter(r=>r.path.endsWith('/input/start')).length,1);assert.equal(f.requests.filter(r=>r.path.endsWith('/input/commit')).length,1);assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,1);
});
test('settled realtime output polls existing turn with no admission/paidSTTPOST',async()=>{
 const requests=[],api=new TranslatorTurns({csrf:'synthetic',json:async(path,options={})=>{requests.push({path,options});return {status:'COMPLETED',audio_url:url+'/audio',translated_text:'Complete saved translation'};}});
 const result=await api.turn(id,key,null,new AbortController().signal,async()=>{});assert.equal(result.translated_text,'Complete saved translation');assert.equal(requests.length,1);assert.equal(requests[0].options.method,undefined);
});
function captureFixture(options={}){
 let now=0,next=0;const timers=new Map(),events=new Map(),track={stops:0,stop(){this.stops++;},addEventListener(name,fn){events.set(name,fn);}};
 const node={port:{onmessage:null,postMessage(message){node.message=message;}},connect(){},disconnect(){node.detached=true;}},stream={getTracks:()=>[track]};
 const context={state:'running',audioWorklet:{addModule:async()=>{}},destination:{},createMediaStreamSource:()=>({connect(){},disconnect(){}})};
 const output=[],levels=[],errors=[],blobs=[];
 const capture=new RealtimeCapture({getContext:()=>context,mediaDevices:{getUserMedia:async()=>stream},createNode:()=>node,schedule:(fn,ms)=>{const id=++next;timers.set(id,{at:now+ms,fn});return id;},clear:id=>timers.delete(id),...options});
 const begin=()=>capture.start({level:value=>levels.push(value),pcm:value=>output.push(value),blob:value=>blobs.push(value),error:value=>errors.push(value)});
 const start=async()=>{const work=begin();await tick();frame(0);await work;levels.length=0;};
 const frame=(rms=.1,length=6400)=>node.port.onmessage({data:{bytes:new ArrayBuffer(length),rms}});
 async function advance(ms){now+=ms;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn();}await tick();}
 return {capture,context,node,track,events,timers,output,levels,errors,blobs,start,frame,advance};
}
test('capture retains voice pre-roll and drains final partial FIFO before releasing blob',async()=>{
 const f=captureFixture();await f.start();f.frame(0);f.frame(0);f.frame(.1);assert.equal(f.output.length,3);f.capture.finalize();assert.equal(f.track.stops,1);assert.deepEqual(f.node.message,{finish:true});f.frame(.05,138);f.node.port.onmessage({data:{finished:true}});assert.equal(f.output.at(-1).byteLength,138);assert.deepEqual(f.blobs,[null]);assert.equal(f.errors.length,0);assert.equal(f.timers.size,0);
});
test('missing finished flush reports owned error and stops every capture resource',async()=>{
 const f=captureFixture();await f.start();f.frame();f.capture.finalize();await f.advance(3000);assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'realtime_capture_failed');assert.equal(f.blobs.length,0);assert.equal(f.timers.size,0);assert.equal(f.node.port.onmessage,null);
});
test('idle capture rotates locally after60s without sending silence or ending logical session',async()=>{
 const f=captureFixture();await f.start();f.frame(0);await f.advance(60000);assert.equal(f.output.length,0);assert.equal(f.errors[0].code,'capture_idle');assert.equal(f.errors[0].silent,true);assert.equal(f.errors[0].recoverable,true);assert.equal(f.timers.size,0);
});
test('voice179s limit begins at first voice rather than idle capture time',async()=>{
 const f=captureFixture();await f.start();await f.advance(50000);f.frame();await f.advance(60000);assert.equal(f.errors.length,0);assert.ok([...f.timers.values()].some(t=>t.at===229000));await f.advance(119000);assert.equal(f.errors[0].code,'utterance_limit');assert.equal(f.blobs.length,0);
});
test('native continuous capture keeps unpaid initial VAD and runs until End without utterance or idle expiry',async()=>{
 const f=captureFixture({continuous:true});await f.start();f.frame(0);await f.advance(180000);
 assert.equal(f.output.length,0);assert.equal(f.errors.length,0);assert.equal(f.track.stops,0);
 f.frame(.1);assert.equal(f.output.length,3);f.frame(0);await f.advance(240000);
 assert.equal(f.output.length,4);assert.equal(f.errors.length,0);assert.equal(f.track.stops,0);assert.equal(f.timers.size,0);
 f.capture.cancel();assert.equal(f.track.stops,1);assert.equal(f.node.port.onmessage,null);
});
test('End cleans up and late worklet frames cannot reach a newer capture',async()=>{
 const f=captureFixture();await f.start();const old=f.node.port.onmessage;f.capture.cancel();old({data:{bytes:new ArrayBuffer(6400),rms:.1}});assert.equal(f.output.length,0);assert.equal(f.blobs.length,0);assert.equal(f.timers.size,0);assert.equal(f.track.stops,1);
});
test('ended track during module load is not ignored by previous finalizing state',async()=>{
 const f=captureFixture(),held=deferred();f.capture.finalizing=true;f.context.audioWorklet.addModule=()=>held.promise;const work=f.capture.start({level(){},pcm(){},blob(){},error(){}}),failed=assert.rejects(work,e=>e.code==='microphone_unavailable');await tick();f.events.get('ended')();held.resolve();await failed;assert.equal(f.errors.length,0);assert.equal(f.node.port.onmessage,null);
});
test('realtime session waits tail/commit plus backend and complete playback before mic resume',async()=>{
 const committed=deferred(),lastPlay=deferred(),producer=deferred();let handlers,mics=0,now=0;const calls=[],plays=[],timings=[];
 const capture={start:async h=>{handlers=h;mics++;},finalize(){mics=0;handlers.pcm(new Uint8Array(138));handlers.blob(null);},cancel(){mics=0;}};
 const api={start:async()=>({session_id:id,input_mode:'realtime-v1'}),input:{reset(){},push:async(...args)=>calls.push(['pcm',args[2].byteLength]),finish:async()=>{calls.push(['commit']);await committed.promise;}},turn:async(_id,_key,blob,signal,onSegment)=>{assert.equal(blob,null);calls.push(['poll']);await onSegment({audio_url:url+'/audio/segments/0',translated_text:'Complete first sentence.'});await producer.promise;await onSegment({audio_url:url+'/audio/segments/1',translated_text:'Complete first sentence. Last sentence.'});return {streamed:true,translated_text:'Complete first sentence. Last sentence.'};},end:async()=>{}};
 const session=new TranslatorSession({api,capture,playback:{prepare:async()=>{},play:async(audio,signal,current,onStarted)=>{assert.equal(mics,0);plays.push(audio);onStarted();if(plays.length===2)await lastPlay.promise;},cancel(){},stop(){}},now:()=>now,key:()=> 'b'.repeat(32),onTiming:value=>timings.push(value)});
 await session.start({});handlers.pcm(new Uint8Array(6400));handlers.level(.1);now=2000;handlers.level(0);await tick();assert.deepEqual(calls,[['pcm',6400],['pcm',138],['commit']]);assert.equal(mics,0);committed.resolve();await tick();assert.equal(plays.length,1);assert.equal(mics,0);producer.resolve();await tick();assert.equal(plays.length,2);assert.equal(mics,0);lastPlay.resolve();await tick();assert.equal(mics,1);assert.equal(session.state,'listening');assert.equal(timings[0].speech_end_to_submit_ms,2000);session.end();
});

test('failed PCM settles once before listening for fresh speech; it never replays prior bytes',async()=>{
 const requests=[],gate=deferred();let failed=true,handlers,mics=0,captures=0,sequence=0;
 const input=new RealtimeInput({csrf:'test',json:async(path,options={})=>{
  requests.push(path);if(path.endsWith('/cancel')){await gate.promise;return {status:'CANCELLED',input_settled:true};}
  if(path.endsWith('/input/start'))return {input_mode:'realtime-v1'};
  if(path.includes('/input/chunks/')){if(failed){failed=false;throw Object.assign(Error('transport lost'),{code:'realtime_transport'});}return {accepted_index:Number(path.split('/').at(-1))};}
  if(path.endsWith('/input/commit'))return {status:'PROCESSING'};throw Error('unexpected request');
 }});
 const capture={start:async h=>{handlers=h;mics++;captures++;},cancel(){mics=0;},finalize(){mics=0;handlers.blob(null);}};
 const session=new TranslatorSession({capture,api:{input,start:async()=>({session_id:id,input_mode:'realtime-v1'}),resume:async()=>{},turn:async()=>({audio_url:'/synthetic'}),end:async()=>{}},playback:{play:async()=>assert.equal(mics,0),stop(){}},key:()=>String(++sequence).padStart(32,'0')});
 await session.start({});const stale=handlers;handlers.pcm(new Uint8Array(6400));await tick();assert.equal(captures,1);gate.resolve();await tick();assert.equal(session.state,'listening');assert.equal(captures,2);
 stale.pcm(new Uint8Array(6400));handlers.pcm(new Uint8Array(6400));await tick();session.stateTo('finalizing');handlers.blob(null);await tick();assert.equal(captures,3);
 assert.equal(requests.filter(x=>x.endsWith('/cancel')).length,1);assert.equal(requests.filter(x=>x.endsWith('/input/start')).length,2);assert.equal(requests.filter(x=>x.endsWith('/input/commit')).length,1);session.end();
});
test('credit failure or unconfirmed cancellation never authorizes fresh input',async()=>{
 for(const mode of ['credit','unknown']){
  let starts=0;const input=new RealtimeInput({csrf:'test',json:async path=>{
   if(path.endsWith('/cancel'))return mode==='credit'?{status:'FAILED',code:'provider_credit_exhausted',recoverable:false}:null;
   if(path.endsWith('/input/start')){starts++;throw Object.assign(Error('input failed'),{code:'realtime_transport'});}throw Error('No replay allowed');
  }});
  await assert.rejects(input.push(id,key,new Uint8Array(6400),new AbortController().signal),e=>e.recoverable===false);assert.equal(starts,1);
 }
});
test('already-failed input reads its real terminal cause before allowing fresh speech',async()=>{
 for(const code of ['realtime_transport','provider_credit_exhausted']){
  const paths=[],input=new RealtimeInput({csrf:'test',json:async path=>{paths.push(path);if(path.endsWith('/input/start'))throw Object.assign(Error('input failed'),{code:'realtime_failed'});if(path.endsWith('/cancel'))return {status:'FAILED'};return {status:'FAILED',code,recoverable:code==='realtime_transport'};}});
  await assert.rejects(input.push(id,key,new Uint8Array(6400),new AbortController().signal),e=>e.code===code&&e.recoverable===(code==='realtime_transport'));assert.deepEqual(paths,[url+'/input/start',url+'/cancel',url]);
 }
});
