import test from 'node:test';
import assert from 'node:assert/strict';
import {LearningCall,SilenceGate} from '../static/kilas_learning_engine.mjs';
import {readFileSync} from 'node:fs';

function fixture(){
  const events=[],played=[],saved=[];let starts=0,submits=0,stops=0,listen=0,ends=0,clock=0;
  const completed={session_id:'session',turn:'greeting',status:'COMPLETED',clips:[{index:0},{index:1}],ended:false};
  const api={start:async()=>{starts++;return completed;},status:async()=>completed,current:async()=>completed,
    clip:async(_s,_t,index)=>index,submit:async()=>{submits++;return {...completed,turn:'answer'};},end:async()=>{ends++;}};
  const capture={permission:async()=>{},cancel:()=>{stops++;},start:async blob=>{listen++;capture.blob=blob;}};
  const player={unlock:async()=>{},play:async(index,signal,started)=>{assert.equal(signal.aborted,false);played.push(index);started?.();},stop:()=>{stops++;}};
  const call=new LearningCall({api,capture,player,onState:(s,m)=>events.push([s,m]),save:s=>saved.push(s),wait:async()=>{},id:()=>String(++clock).padStart(32,'0')});
  return {call,api,capture,player,events,played,saved,completed,counts:()=>({starts,submits,stops,listen,ends})};
}

test('silence ends an utterance only after speech and three seconds',()=>{
  let now=0;const gate=new SilenceGate(()=>now);
  assert.equal(gate.sample(0),false);assert.equal(gate.sample(.03),false);
  now=2999;assert.equal(gate.sample(0),false);now=3000;assert.equal(gate.sample(0),true);
});
test('Start speaks first once, all clips ordered, only then mic listens',async()=>{
  const f=fixture();f.player.play=async(index)=>{assert.equal(f.counts().listen,0);f.played.push(index);};
  await f.call.start({consent:'yes'});await f.call.start({consent:'yes'});
  assert.deepEqual(f.played,[0,1]);assert.equal(f.counts().starts,1);assert.equal(f.counts().listen,1);
});
test('temporarily empty queue does not resume mic before completion',async()=>{
  const f=fixture();let polls=0;
  f.api.start=async()=>({...f.completed,status:'PROCESSING',clips:[]});
  f.api.status=async()=>{assert.equal(f.counts().listen,0);return ++polls===1?{...f.completed,status:'PROCESSING',clips:[{index:0}]}:f.completed;};
  await f.call.start({});assert.equal(polls,2);assert.deepEqual(f.played,[0,1]);assert.equal(f.counts().listen,1);
});
test('mute cancels capture and rejects pending blobs, unmute listens manually',async()=>{
  const f=fixture();await f.call.start({});assert.equal(f.call.mute(),true);
  await f.call.submit(new Blob(['pending']));assert.equal(f.counts().submits,0);
  assert.equal(f.call.mute(),false);await Promise.resolve();assert.equal(f.counts().listen,2);
});
test('muting while tutor speaks never records over tutor audio',async()=>{
  const f=fixture();f.player.play=async index=>{if(index===0)f.call.mute();assert.equal(f.counts().listen,0);};
  await f.call.start({});assert.equal(f.counts().listen,0);assert.equal(f.events.at(-1)[0],'muted');
});
test('End immediately aborts request, player, mic, and invalidates pending results',async()=>{
  const f=fixture();let release;
  f.api.start=async(_settings,signal)=>{assert.equal(signal.aborted,false);return new Promise(resolve=>{release=resolve;});};
  const pending=f.call.start({});await Promise.resolve();await Promise.resolve();await Promise.resolve();
  await f.call.end();release(f.completed);await pending;
  assert.deepEqual(f.played,[]);assert.equal(f.counts().listen,0);assert.equal(f.call.control.signal.aborted,true);assert.equal(f.counts().ends,1);assert.equal(f.saved.at(-1),null);
});
test('End during playback never starts next clip or listens',async()=>{
  const f=fixture();f.player.play=async index=>{f.played.push(index);await f.call.end();};
  await f.call.start({});assert.deepEqual(f.played,[0]);assert.equal(f.counts().listen,0);
});
test('reconnect only polls same turn and skips already completed audio',async()=>{
  const f=fixture();await f.call.restore({session:'session',turn:'greeting',next:1});
  assert.equal(f.counts().starts,0);assert.equal(f.counts().listen,0);
  await f.call.resume();assert.deepEqual(f.played,[1]);assert.equal(f.counts().starts,0);assert.equal(f.counts().submits,0);
});
test('lost realtime response only polls the original turn, never uploads it again',async()=>{
  const f=fixture();await f.call.start({});f.call.beginInput('realtime-answer');
  f.call.pause('Connection lost');const turn=f.call.turn;
  assert.equal(f.events.at(-1)[0],'paused');f.api.status=async(_sid,key)=>({...f.completed,turn:key});
  await f.call.resume();assert.equal(f.call.turn,turn);assert.equal(f.counts().starts,1);
});

test('failed partial turn resumes with a new utterance without replaying old clips',async()=>{
  const f=fixture();f.api.start=async()=>({...f.completed,status:'FAILED',clips:[{index:0}]});
  await f.call.start({});f.api.status=async()=>({...f.completed,status:'FAILED',clips:[{index:0}]});
  await f.call.resume();assert.deepEqual(f.played,[0]);assert.equal(f.counts().listen,1);
});
test('late End failure cannot hide a newer call',async()=>{
  const f=fixture();await f.call.start({});let reject;
  f.api.end=()=>new Promise((_resolve,r)=>{reject=r;});
  const ending=f.call.end();await f.call.start({});reject(Error('late'));await ending;
  assert.equal(f.events.at(-1)[0],'listening');assert.equal(f.call.active,true);
});
test('End while resume permission pending never unlocks audio or calls API',async()=>{
  const f=fixture();await f.call.restore({session:'session',turn:'greeting',next:0});let release,unlocks=0;
  f.capture.permission=()=>new Promise(resolve=>{release=resolve;});f.player.unlock=async()=>{unlocks++;};
  const pending=f.call.resume();await f.call.end();release();await pending;
  assert.equal(unlocks,0);assert.deepEqual(f.played,[]);
});
test('unknown non-admitted upload resumes listening without replaying greeting',async()=>{
  const f=fixture();await f.call.restore({session:'session',turn:'unknown',next:0});
  f.api.status=async(_sid,key)=>{if(key){const error=Error('missing');error.code='not_found';throw error;}return f.completed;};
  await f.call.resume();assert.deepEqual(f.played,[]);assert.equal(f.counts().listen,1);
});
test('partial failed response is honest and never retries automatically',async()=>{
  const f=fixture();f.api.start=async()=>({...f.completed,status:'FAILED',clips:[{index:0}]});
  await f.call.start({});assert.deepEqual(f.played,[0]);assert.equal(f.events.at(-1)[0],'paused');assert.equal(f.counts().listen,0);assert.equal(f.counts().starts,0);
});
test('hidden-page pause stops capture/playback and preserves resumable cursor',async()=>{
  const f=fixture();await f.call.start({});const before=f.counts().stops;
  f.call.pause();assert.equal(f.call.active,true);assert.ok(f.counts().stops>before);assert.equal(f.events.at(-1)[0],'paused');
});
test('Learning code remains isolated, responsive constraints and no transcript DOM',()=>{
  const page=readFileSync(new URL('../templates/kilas_learning/home.html',import.meta.url),'utf8');
  const css=readFileSync(new URL('../static/kilas_learning.css',import.meta.url),'utf8');
  const js=readFileSync(new URL('../static/kilas_learning.mjs',import.meta.url),'utf8');
  assert.ok(!page.includes('data-transcript'));assert.ok(!js.includes('kilas_live_translator'));
  assert.ok(css.includes('minmax(0,1fr)'));assert.ok(css.includes('max-width:480px'));assert.ok(css.includes('max-width:760px'));assert.ok(css.includes('prefers-reduced-motion'));
  const nav=readFileSync(new URL('../templates/kilas_ai/_home_task_selector.html',import.meta.url),'utf8');
  assert.ok(nav.indexOf("('translate'")<nav.indexOf("('learning'"));assert.ok(nav.indexOf("('learning'")<nav.indexOf("('voiceover'"));
});
