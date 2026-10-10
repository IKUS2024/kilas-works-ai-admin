import test from 'node:test';
import assert from 'node:assert/strict';
import {ListeningSession,displayCapture,syntheticStream} from '../static/kilas_listening_core.mjs';

function harness(selectStream=async()=>syntheticStream()) {
  let next=0;const jobs=new Map(),states=[],segments=[];
  const session=new ListeningSession({selectStream,onState:s=>states.push(s),onSegment:s=>segments.push(s),
    schedule:fn=>{jobs.set(++next,fn);return next;},cancel:id=>jobs.delete(id)});
  const tick=()=>{const [id,fn]=jobs.entries().next().value;jobs.delete(id);fn();};
  return {session,jobs,states,segments,tick};
}

test('real capture is locked by default and cannot request media',async()=>{
  let called=0;const select=displayCapture({mediaDevices:{getDisplayMedia:()=>{called++;}}});
  await assert.rejects(select({userGesture:true}),/real_disabled/);assert.equal(called,0);
});
test('future adapter requires explicit gesture and invokes chooser immediately',async()=>{
  let options;const fake=syntheticStream();
  const select=displayCapture({enabled:true,mediaDevices:{getDisplayMedia:value=>{options=value;return Promise.resolve(fake);}}});
  await assert.rejects(select({userGesture:false}),/gesture_required/);assert.equal(options,undefined);
  const pending=select({userGesture:true});assert.equal(options.audio,true);
  assert.equal(options.video.displaySurface,'browser');assert.equal(options.systemAudio,'exclude');
  assert.equal(await pending,fake); // Entirely injected; no browser capture.
});
test('consent required before selecting a source',async()=>{
  let calls=0;const h=harness(async()=>{calls++;return syntheticStream();});
  await h.session.start();assert.equal(calls,0);assert.equal(h.states.at(-1).reason,'consent_required');
});
test('stream sequences, duplicate start and explicit stop cleanup',async()=>{
  const stream=syntheticStream();let calls=0;const h=harness(async()=>{calls++;return stream;});
  await h.session.start({consent:true,segments:[{original:'Synthetic',translated:'Sintetis'}]});
  await h.session.start({consent:true});assert.equal(calls,1);
  h.tick();assert.equal(h.segments[0].sequence,1);
  h.session.stop();assert.equal(h.jobs.size,0);assert.equal(h.session.listeners.length,0);
  assert.equal(h.session.stream,null);assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
test('source ended stops all tracks and pending stream timer',async()=>{
  const stream=syntheticStream(),h=harness(async()=>stream);
  await h.session.start({consent:true});stream.getTracks()[0].dispatchEvent(new Event('ended'));
  assert.equal(h.states.at(-1).reason,'disconnected');assert.equal(h.jobs.size,0);
  assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
test('late picker resolution after stop is fenced and tracks closed',async()=>{
  let resolve;const stream=syntheticStream(),h=harness(()=>new Promise(r=>{resolve=r;}));
  const pending=h.session.start({consent:true});h.session.stop();resolve(stream);await pending;
  assert.equal(h.session.state,'idle');assert.equal(h.jobs.size,0);
  assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
test('missing audio stops the entire selected stream',async()=>{
  const stream=syntheticStream();stream.getAudioTracks=()=>[];const h=harness(async()=>stream);
  await h.session.start({consent:true});assert.equal(h.states.at(-1).reason,'audio_missing');
  assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
test('non-tab selection is rejected and tracks stopped',async()=>{
  const stream=syntheticStream();stream.getVideoTracks()[0].getSettings=()=>({displaySurface:'monitor'});
  const h=harness(async()=>stream);await h.session.start({consent:true});
  assert.equal(h.states.at(-1).reason,'tab_required');assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
test('permission denial, unsupported browser and adapter failure report no live success',async()=>{
  const error=new Error('permission');error.name='NotAllowedError';const h=harness(async()=>{throw error;});
  await h.session.start({consent:true});assert.equal(h.states.at(-1).reason,'permission_denied');
  assert.equal(h.session.stream,null);assert.equal(h.jobs.size,0);
  await assert.rejects(displayCapture({enabled:true,mediaDevices:{}})({userGesture:true}),/unsupported/);
});
test('completion and rendering error clean resources',async()=>{
  const h=harness();await h.session.start({consent:true,segments:[]});h.tick();
  assert.equal(h.states.at(-1).reason,'complete');assert.equal(h.jobs.size,0);
  const stream=syntheticStream(),bad=harness(async()=>stream);bad.session.onSegment=()=>{throw Error('mock failure');};
  await bad.session.start({consent:true,segments:[{}]});bad.tick();
  assert.equal(bad.states.at(-1).reason,'stream_failed');assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
});
