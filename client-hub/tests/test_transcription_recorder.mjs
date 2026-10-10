import test from 'node:test';
import assert from 'node:assert/strict';
import {VoiceRecorder} from '../static/kilas_transcription_recorder.mjs';

function fixture() {
  const state={calls:0,stopped:0,timers:0,blobs:[],states:[]};
  const stream={getTracks:()=>[{stop:()=>state.stopped++}]};
  class Recorder {
    static isTypeSupported(t){return t==='audio/webm;codecs=opus';}
    constructor(s,options){this.events={};this.mimeType=options.mimeType;this.state='inactive';}
    addEventListener(name,callback){this.events[name]=callback;}
    start(){this.state='recording';}
    stop(){this.state='inactive';this.events.dataavailable({data:new Blob(['synthetic'],{type:this.mimeType})});this.events.stop();}
  }
  const options={mediaDevices:{getUserMedia:async()=>{state.calls++;return stream;}},Recorder,
    onBlob:blob=>state.blobs.push(blob),onState:s=>state.states.push(s),
    setTimer:callback=>{state.tick=callback;state.timers++;return 1;},clearTimer:()=>state.timers--,now:()=>state.now||0};
  return {state,stream,options,recorder:new VoiceRecorder(options)};
}

test('default/consent/user gesture checks never request microphone',async()=>{
  const {state,recorder}=fixture();
  for(const options of [{},{enabled:true,userGesture:true},{enabled:true,consent:true}])await assert.rejects(recorder.start(options));
  assert.equal(state.calls,0);
});
test('explicit stop yields local preview and releases tracks/timer',async()=>{
  const {state,recorder}=fixture();await recorder.start({enabled:true,userGesture:true,consent:true});
  recorder.stop();assert.equal(state.blobs.length,1);assert.equal(state.stopped,1);assert.equal(state.timers,0);
});
test('cancellation suppresses late blob and frees tracks',async()=>{
  const {state,recorder}=fixture();await recorder.start({enabled:true,userGesture:true,consent:true});
  recorder.cancel();assert.equal(state.blobs.length,0);assert.equal(state.stopped,1);assert.equal(state.timers,0);
});
test('permission resolving after cancellation stops the incoming stream',async()=>{
  const {state,stream,options}=fixture();let resolve;options.mediaDevices.getUserMedia=()=>new Promise(r=>resolve=r);
  const recorder=new VoiceRecorder(options),pending=recorder.start({enabled:true,userGesture:true,consent:true});
  recorder.cancel();resolve(stream);await pending;assert.equal(state.stopped,1);assert.equal(state.timers,0);assert.equal(state.blobs.length,0);
});
test('recording bound stops at 179 seconds',async()=>{
  const {state,recorder}=fixture();await recorder.start({enabled:true,userGesture:true,consent:true});state.now=179000;state.tick();
  assert.equal(state.blobs.length,1);assert.equal(state.timers,0);
});
test('stop while microphone permission is pending cancels incoming stream',async()=>{
  const {state,stream,options}=fixture();let resolve;options.mediaDevices.getUserMedia=()=>new Promise(r=>resolve=r);
  const recorder=new VoiceRecorder(options),pending=recorder.start({enabled:true,userGesture:true,consent:true});
  recorder.stop();resolve(stream);await pending;assert.equal(state.stopped,1);assert.equal(state.blobs.length,0);assert.equal(state.states.at(-1),'cancelled');
});
test('recorder error releases tracks and suppresses preview',async()=>{
  const {state,recorder}=fixture();await recorder.start({enabled:true,userGesture:true,consent:true});recorder.recorder.events.error();
  assert.equal(state.stopped,1);assert.equal(state.blobs.length,0);assert.equal(state.timers,0);assert.equal(state.states.at(-1),'error');
});
