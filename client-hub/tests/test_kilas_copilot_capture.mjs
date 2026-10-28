import assert from 'node:assert/strict';
import {PcmBuffer,CopilotCapture} from '../static/kilas_copilot_capture.mjs';
const buffer=new PcmBuffer(10);buffer.append(new Uint8Array([1,2,3,4,5,6,7,8]).buffer);buffer.append(new Uint8Array([9,10,11,12]).buffer);
assert.equal(buffer.size,10);assert.deepEqual([...new Uint8Array(buffer.chunks[1])],[9,10]);
assert.throws(()=>buffer.append(new ArrayBuffer(1)),/Invalid PCM/);
let stops=0,closes=0,received=[];
const stream={getTracks:()=>[{stop(){stops++;}}]};
const context={sampleRate:48000,resume:async()=>{},close:async()=>{closes++;},destination:{},audioWorklet:{addModule:async()=>{}},createMediaStreamSource:()=>({connect(){},disconnect(){}}),createGain:()=>({gain:{},connect(){},disconnect(){}})};
let node;
globalThis.AudioWorkletNode=class{constructor(){node=this;this.port={postMessage(){queueMicrotask(()=>{node.port.onmessage({data:{bytes:new ArrayBuffer(14),rms:.1}});node.port.onmessage({data:{finished:true}});});}};}connect(){}disconnect(){}};
const capture=new CopilotCapture(stream,context,value=>received.push(value.bytes.byteLength));await capture.start();await capture.finish();capture.close();capture.close();
assert.deepEqual(received,[14]);assert.equal(stops,1);assert.equal(closes,1);
// Cancellation during final worklet flush rejects; no incomplete clip is used.
const interrupted=new CopilotCapture(stream,context,()=>{});await interrupted.start();node.port.postMessage=()=>{};
const pending=interrupted.finish();interrupted.close();await assert.rejects(pending,/cancelled/);
console.log('PCM cap partial frame + FIFO worklet flush + idempotent cleanup/cancel: PASS');
// No final acknowledgement: stop recording and reject rather than upload partial.
const timeoutCapture=new CopilotCapture(stream,context,()=>{});await timeoutCapture.start();node.port.postMessage=()=>{};
await assert.rejects(timeoutCapture.finish(),/microphone/);timeoutCapture.close();
// Actual resampler admission at common device rates, including the final tail.
const {PcmEncoder}=await import('../static/kilas_live_translator_pcm.mjs');
for(const rate of [16000,32000,44100,48000,96000]){
  const pcm=new PcmBuffer(),encoder=new PcmEncoder(rate,frame=>pcm.append(frame.bytes),1600);
  for(let at=0;at<rate+137;at+=128)encoder.feed([new Float32Array(Math.min(128,rate+137-at)).fill(.004)]);
  encoder.finish();assert.equal(pcm.size,Math.ceil((rate+137)*16000/rate)*2);
}
console.log('Missing flush acknowledgement fails closed + actual 16/32/44.1/48/96 kHz encoder tails: PASS');
