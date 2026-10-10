import test from 'node:test';
import assert from 'node:assert/strict';
import {TabAudioSession,ChunkQueue} from '../static/kilas_live_core.mjs';
import {PCMChunks} from '../static/kilas_live_pcm.mjs';
import {syntheticStream} from '../static/kilas_listening_core.mjs';

function fixture({select,enabled=true}={}) {
  const original=syntheticStream(),events=[],chunks=[],levels=[],timers=new Map();
  const stats={picker:0,closed:0,disconnected:0,createdStreams:[],node:null};
  class Context {
    constructor(){this.audioWorklet={addModule:async()=>{}};this.destination={};}
    createMediaStreamSource(stream){stats.createdStreams.push(stream);return {connect(){},disconnect(){stats.disconnected++;}};}
    createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
    async resume(){}
    async close(){stats.closed++;}
  }
  class Stream {constructor(tracks){this.tracks=tracks;}}
  class Worklet {constructor(){this.port={postMessage(){}};stats.node=this;}connect(){}disconnect(){}}
  const session=new TabAudioSession({enabled,mediaDevices:{getDisplayMedia:options=>{stats.picker++;stats.options=options;return select?select():Promise.resolve(original);}},Context,Stream,Worklet,
    onState:event=>events.push(event),onChunk:chunk=>chunks.push(chunk),onLevel:level=>levels.push(level),schedule:fn=>{timers.set(1,fn);return 1;},clear:key=>timers.delete(key)});
  return {session,original,events,chunks,levels,timers,stats};
}
const consent={consent:true,userGesture:true};

test('capture remains gated and explicit with no mic API',async()=>{
  const f=fixture({enabled:false});await f.session.start(consent);assert.equal(f.stats.picker,0);assert.equal(f.events.at(-1).reason,'real_disabled');
  const g=fixture();await g.session.start();assert.equal(g.stats.picker,0);await g.session.start({consent:true});assert.equal(g.stats.picker,0);
});
test('real adapter requests only chosen tab and audio stream feeds worklet',async()=>{
  const f=fixture();const promise=f.session.start(consent);assert.equal(f.stats.picker,1);await promise;
  assert.equal(f.stats.options.systemAudio,'exclude');assert.equal(f.stats.options.monitorTypeSurfaces,'exclude');
  assert.equal(f.session.state,'active');assert.ok(f.stats.createdStreams[0].tracks.every(t=>t.kind==='audio'));
  f.stats.node.port.onmessage({data:{kind:'level',level:.3}});assert.equal(f.levels.at(-1),.3);
  f.session.stop();assert.ok(f.original.getTracks().every(t=>t.readyState==='ended'));assert.equal(f.stats.closed,1);assert.equal(f.timers.size,0);
});
test('wrong surface and missing shared-tab audio stop every track',async()=>{
  for(const reason of ['audio_missing','tab_required']){
    const stream=syntheticStream();if(reason==='audio_missing')stream.getAudioTracks=()=>[];else stream.getVideoTracks()[0].getSettings=()=>({displaySurface:'window'});
    const f=fixture({select:()=>Promise.resolve(stream)});await f.session.start(consent);
    assert.equal(f.events.at(-1).reason,reason);assert.ok(stream.getTracks().every(t=>t.readyState==='ended'));
  }
});
test('late chooser resolution after stop cannot start worklet',async()=>{
  let resolve;const f=fixture({select:()=>new Promise(r=>resolve=r)}),pending=f.session.start(consent);
  f.session.stop();resolve(f.original);await pending;assert.equal(f.stats.node,null);assert.ok(f.original.getTracks().every(t=>t.readyState==='ended'));
});
test('track ended, processor error and timeout all release tracks and nodes',async()=>{
  for(const reason of ['ended','processor','timeout']){
    const f=fixture();await f.session.start(consent);
    if(reason==='ended')f.original.getAudioTracks()[0].dispatchEvent(new Event('ended'));
    else if(reason==='processor')f.stats.node.onprocessorerror();else f.timers.get(1)();
    assert.equal(f.session.state,'idle');assert.equal(f.stats.closed,1);assert.equal(f.timers.size,0);assert.equal(f.session.node,null);
  }
});
test('maximum twelve chunks stops capture without retaining a tail',async()=>{
  const f=fixture();await f.session.start(consent);
  for(let i=0;i<12;i++)f.stats.node.port.onmessage({data:{kind:'chunk',buffer:new ArrayBuffer(44)}});
  assert.equal(f.chunks.length,12);assert.equal(f.session.state,'idle');assert.equal(f.events.at(-1).reason,'limit');
});
test('PCM downsampling yields independent mono16k 10-second WAV files',()=>{
  const outputs=[],levels=[];const encoder=new PCMChunks({emit:value=>outputs.push(value),meter:level=>levels.push(level)});
  encoder.push([new Float32Array(480000).fill(.2),new Float32Array(480000).fill(.4)],48000);
  encoder.push([new Float32Array(441000).fill(.1)],44100);
  assert.equal(outputs.length,2);
  for(const buffer of outputs){assert.equal(buffer.byteLength,320044);const view=new DataView(buffer);assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint32(40,true),320000);assert.equal(new TextDecoder().decode(buffer.slice(0,4)),'RIFF');}
  assert.ok(levels.some(level=>level>0));encoder.clear();assert.equal(encoder.at,0);assert.ok(encoder.samples.every(value=>value===0));
});
test('bounded queue stops on backpressure without accumulating audio',async()=>{
  const results=[],errors=[];let resolve;
  const queue=new ChunkQueue({send:()=>new Promise(r=>resolve=r),onResult:value=>results.push(value),onError:error=>errors.push(error)});
  assert.equal(queue.push(1),true);assert.equal(queue.push(2),true);assert.equal(queue.push(3),false);
  assert.deepEqual(errors,['backpressure']);assert.equal(queue.pending.length,0);resolve('late');await new Promise(r=>setImmediate(r));assert.deepEqual(results,[]);
});
test('in-order results and cancellation fence provider replies',async()=>{
  const results=[];let resolve;
  const queue=new ChunkQueue({send:value=>value===1?Promise.resolve('first'):new Promise(r=>resolve=r),onResult:value=>results.push(value),onError:()=>{}});
  queue.push(1);queue.push(2);await new Promise(r=>setImmediate(r));assert.deepEqual(results,['first']);
  queue.clear();resolve('late');await new Promise(r=>setImmediate(r));assert.deepEqual(results,['first']);
});
