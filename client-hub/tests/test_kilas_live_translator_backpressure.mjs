import test from 'node:test';
import assert from 'node:assert/strict';
import {RealtimeInput} from '../static/kilas_live_translator_realtime_input.mjs';
import {captureMode,compatibleRecorder,TranslatorAudioRoute} from '../static/kilas_live_translator_capabilities.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const id='a'.repeat(48),key='live-'+'b'.repeat(32);
function fixture({rtt=1500,negotiated=true,badAck=false}={}){
 let now=0,timers=[],accepted=[],requests=[],metrics=[];
 const wait=()=>new Promise(resolve=>timers.push({at:now+rtt,resolve}));
 const input=new RealtimeInput({csrf:'synthetic',now:()=>now,onTiming:v=>metrics.push(v),json:async(path,o)=>{
  requests.push({path,o});if(path.endsWith('/cancel'))return {status:'CANCELLED',input_settled:true};
  if(path.endsWith('/input/start')){await wait();return {input_mode:'realtime-v1',...(negotiated?{max_chunk_bytes:128000}:{})};}
  if(path.includes('/chunks/')){accepted.push(new Uint8Array(await o.body.get('pcm').arrayBuffer()));await wait();return {accepted_index:badAck?-1:Number(path.split('/').at(-1))};}
  if(path.endsWith('/commit'))return {status:'PROCESSING'};throw Error('Unexpected paid retry');
 }});
 async function advance(ms){const end=now+ms;await tick();while(timers.some(t=>t.at<=end)){timers.sort((a,b)=>a.at-b.at);const timer=timers.shift();now=timer.at;timer.resolve();await tick();}now=end;await tick();}
 const controller=new AbortController();return {input,controller,accepted,requests,metrics,advance,get now(){return now;},push:bytes=>input.push(id,key,bytes,controller.signal),finish:()=>input.finish(id,key,controller.signal)};
}
for(const rtt of [350,1500,2500])test('coalescing sustains '+rtt+'ms serialHTTP: exact50s PCM plus final tail, one lease/commit',async()=>{
 const f=fixture({rtt}),original=[],pending=[];
 for(let i=0;i<250;i++){const bytes=new Uint8Array(6400).fill(i%251);original.push(bytes);pending.push(f.push(bytes));await f.advance(200);assert.ok(f.input.current.queued<=8*32000);}
 const tail=new Uint8Array(138).fill(91);original.push(tail);pending.push(f.push(tail));const done=f.finish();await f.advance(15000);await Promise.all(pending);await done;
 assert.deepEqual(Buffer.concat(f.accepted.map(b=>Buffer.from(b))),Buffer.concat(original.map(b=>Buffer.from(b))));assert.ok(f.accepted.every(b=>b.length<=128000));
 assert.equal(f.requests.filter(v=>v.path.endsWith('/input/start')).length,1);assert.equal(f.requests.filter(v=>v.path.endsWith('/commit')).length,1);assert.equal(f.requests.filter(v=>v.path.endsWith('/cancel')).length,0);
 const metric=f.metrics.find(v=>'pcm_max_backlog_ms'in v);assert.ok(metric.pcm_max_backlog_ms<=8000);assert.equal(f.input.current,null);
 if(rtt>1000)assert.ok(f.accepted.some(b=>b.length>32000));
});
test('old1s transport reproduces guard at1500ms RTT; coalescing leaves8s guard intact',async()=>{
 const f=fixture({negotiated:false}),work=[];let error;
 for(let n=0;n<250&&!error;n++){work.push(f.push(new Uint8Array(6400)).catch(e=>{error=e;}));await f.advance(200);}
 assert.equal(error.code,'realtime_queue_full');assert.ok(f.now<25000);assert.equal(f.requests.filter(v=>v.path.endsWith('/cancel')).length,1);assert.equal(f.requests.some(v=>v.path.endsWith('/commit')),false);
 await f.advance(15000);await Promise.all(work);
});
test('genuine8s overflow still cancels once and never commits accepted prefix',async()=>{
 const f=fixture({rtt:9000}),work=[];for(let n=0;n<8;n++)work.push(f.push(new Uint8Array(32000)).catch(e=>e));
 await assert.rejects(f.push(new Uint8Array(2)),e=>e.code==='realtime_queue_full'&&e.turnSettled);await f.advance(20000);await Promise.all(work);
 assert.equal(f.requests.filter(v=>v.path.endsWith('/cancel')).length,1);assert.equal(f.requests.some(v=>v.path.endsWith('/commit')),false);
});
test('bad ACK blocks all following PCM and one final commit even with coalesced backlog',async()=>{
 const f=fixture({badAck:true}),work=[];for(let n=0;n<5;n++)work.push(f.push(new Uint8Array(32000)).catch(e=>e));
 const done=f.finish().catch(e=>e);await f.advance(15000);const error=await done;await Promise.all(work);
 assert.equal(error.code,'realtime_chunk_invalid');assert.equal(f.accepted.length,1);assert.equal(f.requests.filter(v=>v.path.endsWith('/cancel')).length,1);assert.equal(f.requests.some(v=>v.path.endsWith('/commit')),false);
});
test('End during admission cannot drain buffered frames into a later turn',async()=>{
 const f=fixture(),work=f.push(new Uint8Array(6400)).catch(e=>e);f.controller.abort();await f.advance(3000);assert.equal((await work).name,'AbortError');assert.equal(f.accepted.length,0);f.input.reset();assert.equal(f.input.current,null);
});
for(const [name,mime] of [['Safari/iOS/iPadOS','audio/mp4'],['Chrome/Android/desktop','audio/webm;codecs=opus'],['Edge','audio/webm;codecs=opus'],['Firefox','audio/ogg;codecs=opus']])test(name+' capability profile prefersPCM and selects supported batch before capture when unavailable',()=>{
 class Recorder{static isTypeSupported(type){return type===mime;}}
 const scope={MediaRecorder:Recorder,AudioWorkletNode:class{}},media={getUserMedia(){}};
 assert.equal(captureMode({audioWorklet:{addModule(){}}},scope,media),'realtime-v1');assert.equal(captureMode({},scope,media),'batch');assert.equal(captureMode({},scope,{}),null);
});
test('missingMediaRecorder feature probe uses native default; unsupported transport fails before paid input',()=>{
 class Recorder{};const compatible=compatibleRecorder(Recorder);assert.equal(compatible.isTypeSupported('audio/mp4'),false);assert.ok(new compatible() instanceof Recorder);
 assert.equal(captureMode({},{MediaRecorder:Recorder},{getUserMedia(){}}),'batch');assert.equal(captureMode({},{MediaRecorder:class{static isTypeSupported(){return false;}}},{getUserMedia(){}}),null);assert.equal(captureMode({},{} ,{getUserMedia(){}}),null);
});
test('optionalAudioSession returns from capture to playback and restores original route onEnd',()=>{
 const changes=[],session={get type(){return this.value||'auto';},set type(v){changes.push(v);this.value=v;}},route=new TranslatorAudioRoute({audioSession:session});
 for(let n=0;n<3;n++){route.playback();route.capture();route.playback();}route.restore();assert.equal(changes.at(-1),'auto');assert.equal(changes.filter(v=>v==='play-and-record').length,3);assert.equal(changes.filter(v=>v==='playback').length,6);
 const absent=new TranslatorAudioRoute({});absent.capture();absent.playback();absent.restore();const denied=new TranslatorAudioRoute({get audioSession(){throw Error('unsupported');}});denied.capture();denied.playback();denied.restore();
});
