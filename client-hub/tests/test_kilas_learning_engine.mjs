import test from 'node:test';
import assert from 'node:assert/strict';
import {LearningCall,SilenceGate,within} from '../static/kilas_learning_engine.mjs';
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
  const pending=f.call.start({});for(let i=0;i<20&&!release;i++)await Promise.resolve();assert.ok(release,'Start reached request admission');
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
test('End during resumed permission stops pre-unlocked audio and never plays or admits API work',async()=>{
  const f=fixture();await f.call.restore({session:'session',turn:'greeting',next:0});let release,unlocks=0;
  f.capture.permission=()=>new Promise(resolve=>{release=resolve;});f.player.unlock=async()=>{unlocks++;};
  const pending=f.call.resume();await f.call.end();release();await pending;
  assert.equal(unlocks,1);assert.deepEqual(f.played,[]);
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

const tick=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
test('permission rejection returns to setup without provider admission and Start works again',async()=>{
  const f=fixture();f.capture.permission=async()=>{throw new DOMException('denied','NotAllowedError');};
  await f.call.start({});assert.equal(f.call.active,false);assert.equal(f.events.at(-1)[0],'ended');assert.match(f.events.at(-1)[1],/Izin mikrofon/);
  assert.equal(f.counts().starts,0);f.capture.permission=async()=>{};await f.call.start({});assert.equal(f.counts().starts,1);
});
test('repeated Start during pending permission admits exactly once and preserves settings',async()=>{
  const f=fixture();let release,settings;
  f.capture.permission=()=>new Promise(r=>{release=r;});f.api.start=async values=>{settings=values;return f.completed;};
  const pending=f.call.start({target:'zh',native:'es',level:'advanced',voice:'kilas-female',consent:'yes'});
  await f.call.start({target:'en'});release();await pending;
  assert.deepEqual({...settings,start_key:undefined},{target:'zh',native:'es',level:'advanced',voice:'kilas-female',consent:'yes',start_key:undefined});
});
test('startup timeout closes local resources and admits no server session',async()=>{
  const f=fixture();f.call.startupMs=5;f.capture.permission=()=>new Promise(()=>{});
  await f.call.start({});assert.equal(f.call.active,false);assert.equal(f.call.control.signal.aborted,true);assert.equal(f.counts().starts,0);assert.equal(f.events.at(-1)[0],'ended');
});
test('End during permission settles startup immediately even before permission resolves',async()=>{
  const f=fixture();f.capture.permission=()=>new Promise(()=>{});
  const pending=f.call.start({});await f.call.end();await pending;
  assert.equal(f.counts().starts,0);assert.equal(f.call.active,false);
});
test('ambiguous Start saves cancellation identity and resume only discovers existing session',async()=>{
  const f=fixture();f.api.start=async()=>{throw Error('lost response');};
  await f.call.start({});assert.equal(f.events.at(-1)[0],'paused');assert.ok(f.saved.at(-1).startKey);assert.equal(f.saved.at(-1).session,null);
  let discoveries=0;f.api.current=async()=>{discoveries++;return f.completed;};await f.call.resume();assert.equal(discoveries,1);assert.deepEqual(f.played,[0,1]);
});
test('repeated resume during pending permission cannot cancel the first resume',async()=>{
  const f=fixture();let release,permissions=0;
  await f.call.restore({session:'session',turn:'greeting',next:1});
  f.capture.permission=()=>{permissions++;return new Promise(r=>{release=r;});};
  const pending=f.call.resume();await f.call.resume();assert.equal(permissions,1);release();await pending;assert.deepEqual(f.played,[1]);
});
test('unmute after cancelled realtime input checks status then starts a new listen',async()=>{
  const f=fixture();await f.call.start({});f.call.beginInput('learner-input');
  let polls=0;f.api.status=async(_sid,turn)=>{polls++;assert.equal(turn,'learner-input');return {...f.completed,turn,status:'CANCELLED',clips:[]};};
  f.call.mute();assert.equal(f.call.mute(),false);await tick();assert.equal(polls,1);assert.equal(f.events.at(-1)[0],'listening');
});
test('next known complete clip is fetched during playback and never played out of order',async()=>{
  const f=fixture(),fetched=[];let release;
  f.api.clip=async(_s,_t,index)=>{fetched.push(index);return index;};
  f.player.play=async index=>{f.played.push(index);if(index===0)await new Promise(r=>{release=r;});};
  const pending=f.call.start({});await tick();assert.deepEqual(fetched,[0,1]);assert.deepEqual(f.played,[0]);
  release();await pending;assert.deepEqual(f.played,[0,1]);assert.equal(f.counts().listen,1);
});
test('completed response with a missing audio segment pauses without reopening the mic',async()=>{
  const f=fixture();f.api.start=async()=>({...f.completed,clips:[{index:0},{index:2}]});
  await f.call.start({});assert.deepEqual(f.played,[0]);assert.equal(f.events.at(-1)[0],'paused');assert.equal(f.counts().listen,0);
});
test('startup wrapper calls gesture task synchronously and cleans timeout after completion',async()=>{
  let called=false,timer,cleared=false;const control=new AbortController();
  const pending=within(()=>{called=true;return 'ok';},control.signal,30,{setTimer:fn=>{timer=fn;return 1;},clearTimer:()=>{cleared=true;}});
  assert.equal(called,true);assert.equal(await pending,'ok');assert.equal(cleared,true);timer();
});

test('restored call settings come from server state and persist the actual language and voice',async()=>{
  const f=fixture(),choices=[];f.call.onSettings=value=>choices.push(value);
  await f.call.restore({session:'session',turn:'greeting',next:2});assert.equal(choices.at(-1),null);
  f.api.status=async()=>({...f.completed,target:'es',native:'zh',level:'intermediate',voice:'kilas-female'});
  await f.call.resume();assert.deepEqual(choices.at(-1),{target:'es',native:'zh',level:'intermediate',voice:'kilas-female'});
  assert.deepEqual(f.saved.at(-1).settings,choices.at(-1));
});
test('late cancelled listen cannot close microphone permission in a newer Start',async()=>{
  const f=fixture();let openings=0,cancelledNewPermission=0,newPermission=false;
  f.capture.start=async()=>{openings++;if(openings===1)return new Promise(()=>{});};
  const old=f.call.start({});await tick();assert.equal(openings,1);
  const ending=f.call.end();f.capture.permission=async()=>{newPermission=true;};
  f.capture.cancel=()=>{if(newPermission&&f.call.phase==='preparing'&&!f.call.session)cancelledNewPermission++;};
  const current=f.call.start({});await Promise.all([old,ending,current]);
  assert.equal(cancelledNewPermission,0);assert.equal(f.call.phase,'listening');assert.equal(openings,2);
});
test('gesture audio unlock begins before awaiting microphone consent and all admission waits for both',async()=>{
  const f=fixture(),events=[];let release;
  f.player.unlock=async()=>{events.push('unlock');};f.capture.permission=()=>{events.push('permission');return new Promise(r=>{release=r;});};
  const pending=f.call.start({});assert.deepEqual(events,['unlock','permission']);assert.equal(f.counts().starts,0);release();await pending;assert.equal(f.counts().starts,1);
});
test('early startup ID errors are caught, shown and leave another deliberate Start available',async()=>{
  const f=fixture();f.call.id=()=>{throw Error('Secure randomness unavailable');};await f.call.start({});
  assert.equal(f.call.active,false);assert.equal(f.events.at(-1)[0],'ended');assert.match(f.events.at(-1)[1],/Secure randomness/);assert.equal(f.counts().starts,0);
});

test('new lesson cleanup failure admits no provider work and leaves editable setup available',async()=>{
  const f=fixture();f.api.end=async()=>{throw Error('Old session closure unconfirmed');};
  await f.call.start({target:'es'},{session:'old',startKey:'old-key'});
  assert.equal(f.call.active,false);assert.equal(f.counts().starts,0);assert.equal(f.events.at(-1)[0],'ended');assert.match(f.events.at(-1)[1],/unconfirmed/);
});
test('resume distinguishes local permission from reading server state and rejects unknown state instead of polling forever',async()=>{
  const f=fixture();await f.call.restore({session:'session'});f.api.status=async()=>({...f.completed,status:'unexpected'});
  await f.call.resume();assert.equal(f.events.at(-1)[0],'paused');assert.match(f.events.at(-1)[1],/Status sesi/);
  assert.ok(f.events.some(([_,message])=>message.includes('izin mikrofon')));assert.ok(f.events.some(([_,message])=>message.includes('Memeriksa sesi')));
  assert.equal(f.counts().starts,0);assert.equal(f.counts().listen,0);
});

test('End during old-session closure targets that session and fences late closure from new admission',async()=>{
  const f=fixture();let release,attempts=[];
  f.api.end=(sid,key)=>{attempts.push([sid,key]);return attempts.length===1?new Promise(resolve=>{release=resolve;}):Promise.resolve();};
  const pending=f.call.start({},{session:'old-session',startKey:'old-key'});await tick();assert.ok(release);
  await f.call.end();release();await pending;
  assert.deepEqual(attempts,[['old-session','old-key'],['old-session','old-key']]);assert.equal(f.counts().starts,0);assert.equal(f.call.active,false);
});
test('new-start permission rejection retains old saved cursor and never closes its session',async()=>{
  const f=fixture(),previous={session:'old-session',turn:'old-turn',next:2};f.capture.permission=async()=>{throw new DOMException('denied','NotAllowedError');};
  await f.call.start({},previous);assert.deepEqual(f.saved.at(-1),previous);assert.equal(f.counts().ends,0);assert.equal(f.counts().starts,0);
});
