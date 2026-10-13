import test from 'node:test';
import assert from 'node:assert/strict';
import {LearningPlayer} from '../static/kilas_learning_player.mjs';
import {learningRequest} from '../static/kilas_learning_transport.mjs';

const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function fixture(){
  const sources=[],contexts=[];let decode;
  const create=()=>{
    const ctx={state:'running',destination:{},closed:false,
      resume:async()=>{},close:async()=>{ctx.closed=true;},
      decodeAudioData:async()=>decode?decode():({duration:.1}),
      createBufferSource:()=>{const s={start(){s.started=true;},stop(){s.stopped=true;},connect(){},disconnect(){s.disconnected=true;}};sources.push(s);return s;}};
    contexts.push(ctx);return ctx;
  };
  return {player:new LearningPlayer(create),sources,contexts,hold:fn=>{decode=fn;}};
}
test('playback resolves after complete audio and abort immediately stops and disconnects source',async()=>{
  const f=fixture(),control=new AbortController();let starts=0,done=false;
  const playing=f.player.play(new ArrayBuffer(1),control.signal,()=>starts++).then(()=>{done=true;});
  await tick();assert.equal(starts,1);assert.equal(done,false);f.sources[0].onended();await playing;
  assert.equal(done,true);assert.equal(f.sources[0].disconnected,true);
  const interrupted=f.player.play(new ArrayBuffer(1),control.signal);await tick();control.abort();await assert.rejects(interrupted,{name:'AbortError'});
  assert.equal(f.sources[1].stopped,true);assert.equal(f.sources[1].disconnected,true);
});
test('stop fences pending decode and cannot affect playback in a newer context',async()=>{
  const f=fixture(),first=new AbortController(),second=new AbortController();let release;
  f.hold(()=>new Promise(r=>{release=r;}));const old=f.player.play(new ArrayBuffer(1),first.signal);await tick();f.player.stop();
  f.hold(null);const current=f.player.play(new ArrayBuffer(1),second.signal);await tick();
  release({duration:.1});await assert.rejects(old,{name:'AbortError'});assert.equal(f.sources.length,1);assert.equal(f.contexts[0].closed,true);
  f.sources[0].onended();await current;
});
test('late source ended event after stop cannot clear newer playback cancellation',async()=>{
  const f=fixture(),control=new AbortController();const old=f.player.play(new ArrayBuffer(1),control.signal);await tick();const late=f.sources[0].onended;
  f.player.stop();await assert.rejects(old,{name:'AbortError'});
  const current=f.player.play(new ArrayBuffer(1),control.signal);await tick();late();f.player.stop();await assert.rejects(current,{name:'AbortError'});
  assert.equal(f.sources[1].stopped,true);
});
test('End during suspended context resume prevents all sources',async()=>{
  const f=fixture();f.player.connect().state='suspended';let release;
  f.contexts[0].resume=()=>new Promise(r=>{release=r;});const control=new AbortController();const pending=f.player.play(new ArrayBuffer(1),control.signal);
  await tick();control.abort();f.player.stop();release();await assert.rejects(pending,{name:'AbortError'});assert.equal(f.sources.length,0);
});
test('predecoded next segment uses the same live context and never decodes twice',async()=>{
  const f=fixture(),control=new AbortController();let decodes=0;f.player.connect().decodeAudioData=async()=>{decodes++;return {duration:.1};};
  const prepared=await f.player.prepare(new ArrayBuffer(1),control.signal),playing=f.player.play(prepared,control.signal);await tick();
  assert.equal(decodes,1);f.sources[0].onended();await playing;
});
test('cancelled preload never recreates a stopped audio context',async()=>{
  const f=fixture(),control=new AbortController();await f.player.unlock(control.signal);f.player.stop();control.abort();
  await assert.rejects(f.player.prepare(new ArrayBuffer(1),control.signal),{name:'AbortError'});
  await assert.rejects(f.player.unlock(control.signal),{name:'AbortError'});assert.equal(f.contexts.length,1);
});
test('HTTP request and response body timeout abort once without retrying a paid request',async()=>{
  for(const body of [false,true]){
    let calls=0,signal;const request=learningRequest({csrf:'synthetic',timeout:5,fetcher:async(_url,options)=>{
      calls++;signal=options.signal;return body?{ok:true,json:()=>new Promise(()=>{})}:new Promise(()=>{});
    }});
    await assert.rejects(request('/sessions',{data:new FormData()}),/Persiapan terlalu lama/);assert.equal(calls,1);assert.equal(signal.aborted,true);
  }
});
test('HTTP caller cancellation and server error code retain recovery semantics',async()=>{
  const control=new AbortController();let signal;
  const request=learningRequest({csrf:'synthetic',fetcher:(_url,options)=>{signal=options.signal;return new Promise(()=>{});}});
  const pending=request('/session',{signal:control.signal});control.abort();await assert.rejects(pending,{name:'AbortError'});assert.equal(signal.aborted,true);
  const missing=learningRequest({csrf:'synthetic',fetcher:async()=>({ok:false,json:async()=>({code:'not_found',error:'missing'})})});
  await assert.rejects(missing('/session'),error=>error.code==='not_found');
});
