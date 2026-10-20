// The actual worklet encoder and capture adapters, with nonprivate speech.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PcmEncoder} from '../static/kilas_live_translator_pcm.mjs';
import {RealtimeCapture} from '../static/kilas_live_translator_realtime_capture.mjs';
import {CallCapture} from '../static/kilas_ai_call_capture.mjs';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(Capture=CallCapture,options={}){
 const output=[],timers=new Map(),errors=[];let ident=0,stops=0,constraints;
 const track={stop(){stops++;},addEventListener(){}},stream={getTracks:()=>[track]};
 const node={port:{},connect(){},disconnect(){}};
 const context={state:'running',audioWorklet:{addModule:async()=>{}},destination:{},createMediaStreamSource:()=>({connect(){},disconnect(){}})};
 const capture=new Capture({getContext:()=>context,continuous:true,
  mediaDevices:{getUserMedia:async value=>{constraints=value;return stream;}},createNode:()=>node,
  schedule:(fn,ms)=>{timers.set(++ident,{fn,ms});return ident;},clear:id=>timers.delete(id),...options});
 const frame=data=>node.port.onmessage({data});
 const start=async()=>{const work=capture.start({pcm:raw=>output.push(raw),level(){},ready(){},blob(){},error:e=>errors.push(e)});await tick();frame({bytes:new ArrayBuffer(6400),rms:0});await work;};
 return {capture,node,context,output,errors,timers,start,frame,get stops(){return stops;},get constraints(){return constraints;}};
}

function quietFrames(){
 const wav=readFileSync(new URL('./fixtures/ai_call_synthetic/id-first.wav',import.meta.url));
 // Python wave writer creates the canonical 44-byte mono PCM header.
 assert.equal(wav.toString('ascii',36,40),'data');
 const samples=Float32Array.from({length:(wav.length-44)/2},(_,i)=>wav.readInt16LE(44+i*2)/32768);
 const frames=[],encoder=new PcmEncoder(16000,value=>frames.push(value));
 for(let i=0;i<samples.length;i+=128)encoder.feed([samples.subarray(i,i+128)]);
 encoder.finish();return {wav,frames};
}

test('Reproduced: old capture loses the entire quiet Indonesian question; Call retains every sample',async t=>{
 const old=fixture(RealtimeCapture),fixed=fixture();await old.start();await fixed.start();
 const {wav,frames}=quietFrames();assert.ok(frames.some(frame=>frame.rms>.001));assert.ok(frames.every(frame=>frame.rms<.015));
 for(const frame of frames){old.frame(frame);fixed.frame(frame);}
 assert.equal(old.output.length,0);
 const delivered=Buffer.concat(fixed.output.slice(1).map(bytes=>Buffer.from(bytes)));
 assert.deepEqual(delivered,wav.subarray(44));
 t.diagnostic(JSON.stringify({synthetic:true,input_ms:delivered.length/32,old_sent_ms:0,fixed_sent_ms:delivered.length/32,max_frame_rms:Math.max(...frames.map(f=>f.rms))}));
 old.capture.cancel();fixed.capture.cancel();
});

test('Call supplies initial silence and quiet speech without a loudness threshold or local duration timer',async()=>{
 const f=fixture();await f.start();f.frame({bytes:new ArrayBuffer(6400),rms:.001});
 assert.equal(f.output.length,2);assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,5000);
 assert.deepEqual(f.constraints,{audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
 const late=f.node.port.onmessage;f.capture.cancel();late({data:{bytes:new ArrayBuffer(6400),rms:.1}});
 assert.equal(f.output.length,2);assert.equal(f.stops,1);assert.equal(f.node.port.onmessage,null);
 assert.equal(f.timers.size,0);
});

test('PCM48k and PCM44.1k stereo capture have exact mono16k duration and preserve quiet sample amplitudes',()=>{
 for(const rate of [16000,44100,48000]){
  const frames=[],encoder=new PcmEncoder(rate,value=>frames.push(value));
  for(let i=0;i<rate;i+=128){const width=Math.min(128,rate-i);encoder.feed([new Float32Array(width).fill(.008),new Float32Array(width).fill(.004)]);}
  encoder.finish();const raw=Buffer.concat(frames.map(frame=>Buffer.from(frame.bytes)));
  assert.equal(raw.length,32000);assert.ok(Math.abs(raw.readInt16LE(0)/32768-.006)<1/32768);
  assert.ok(frames.every(frame=>frame.bytes.byteLength<=6400));
 }
});

test('Malformed capture frame stops microphone before dispatching any invalid PCM',async()=>{
 const f=fixture();await f.start();f.frame({bytes:new ArrayBuffer(3),rms:.1});
 assert.equal(f.errors[0].code,'realtime_capture_failed');assert.equal(f.stops,1);assert.equal(f.output.length,1);
});

test('End during microphone permission request stops a late stream without attaching audio',async()=>{
 let resolve,stopped=0;
 const f=fixture(CallCapture,{mediaDevices:{getUserMedia:()=>new Promise(r=>resolve=r)}});
 const pending=f.capture.start({pcm(){throw Error('late PCM');},level(){},blob(){},error(){}});
 await tick();f.capture.cancel();resolve({getTracks:()=>[{stop(){stopped++;}}]});
 await assert.rejects(pending,{name:'AbortError'});await tick();assert.equal(stopped,1);assert.equal(f.node.port.onmessage,undefined);
});

test('Loss of worklet frames after startup fails closed and releases microphone',async()=>{
 const f=fixture();await f.start();
 const idle=[...f.timers.values()].find(value=>value.ms===5000);
 try{
  assert.ok(idle,'continuous capture needs a watchdog after the first valid frame');
  idle.fn();assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'realtime_input_timeout');
  assert.equal(f.stops,1);assert.equal(f.capture.node,null);assert.equal(f.timers.size,0);
 }finally{f.capture.cancel();}
});

test('Continuous silence refreshes the runtime watchdog without a call duration cap',async()=>{
 const f=fixture();await f.start();
 for(let i=0;i<600;i++){
  f.frame({bytes:new ArrayBuffer(6400),rms:0});
  assert.equal(f.timers.size,1);assert.equal([...f.timers.values()][0].ms,5000);
 }
 assert.equal(f.output.length,601);assert.deepEqual(f.errors,[]);
 const late=[...f.timers.values()][0];f.capture.cancel();late.fn();
 assert.equal(f.timers.size,0);assert.deepEqual(f.errors,[]);assert.equal(f.stops,1);
});

for(const code of ['NotAllowedError','SecurityError'])test(`Microphone ${code} is classified and releases startup timers`,async()=>{
 const f=fixture(CallCapture,{mediaDevices:{getUserMedia:async()=>{throw Object.assign(Error('synthetic denial'),{name:code});}}});
 await assert.rejects(f.capture.start({pcm(){},level(){},blob(){},error(){}}),e=>e.code==='microphone_permission_denied');
 assert.equal(f.timers.size,0);assert.equal(f.stops,0);
});

test('Missing AudioWorklet rejects before microphone permission or admission',async()=>{
 let requests=0;const f=fixture(CallCapture,{getContext:()=>({state:'running'}),mediaDevices:{getUserMedia(){requests++;}}});
 await assert.rejects(f.capture.start({pcm(){},level(){},blob(){},error(){}}),e=>e.code==='realtime_capture_unavailable');
 assert.equal(requests,0);assert.equal(f.timers.size,0);
});

test('End while worklet module is pending stops tracks and fences its late resolution',async()=>{
 let resolve,stops=0,created=0;
 const module=new Promise(r=>{resolve=r;});
 const f=fixture(CallCapture,{getContext:()=>({state:'running',audioWorklet:{addModule:()=>module}}),
  mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stops++;},addEventListener(){}}]})},createNode(){created++;}});
 const start=f.capture.start({pcm(){},level(){},blob(){},error(){}});await tick();f.capture.cancel();resolve();
 await assert.rejects(start,{name:'AbortError'});assert.equal(stops,1);assert.equal(created,0);assert.equal(f.timers.size,0);
});
