import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';
const URL='/kilas-translator/live/sessions/'+'a'.repeat(48)+'/turns/live-'+'b'.repeat(32)+'/audio';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

function fixture(){
  let now=0,seq=0,current=true,clock=true;const timers=new Map(),nodes=[],requests=[];
  const stats={decoded:0,resumed:0,started:0,stopped:0,disconnected:0};
  const context={state:'running',currentTime:0,destination:{},
    async resume(){stats.resumed++;this.state='running';},
    async decodeAudioData(){stats.decoded++;return {duration:2};},
    createBufferSource(){const node={connect(){},start(){stats.started++;},stop(){stats.stopped++;},disconnect(){stats.disconnected++;}};nodes.push(node);return node;},
  };
  let response={ok:true,redirected:false,headers:{get:()=>null},arrayBuffer:async()=>new ArrayBuffer(32)};
  const player=new TranslatorPlayback({getContext:()=>context,now:()=>now,
    fetchAudio:async(url,options)=>{requests.push({url,options});return response;},
    schedule:(fn,ms)=>{const id=++seq;timers.set(id,{at:now+ms,fn});return id;},clear:id=>timers.delete(id),
  });
  const controller=new AbortController();
  const play=()=>player.play(URL,controller.signal,()=>current);
  const advance=async ms=>{
    const target=now+ms;
    while(true){const entry=[...timers].filter(([,t])=>t.at<=target).sort((a,b)=>a[1].at-b[1].at)[0];if(!entry)break;
      const [id,t]=entry;if(clock&&context.state==='running')context.currentTime+=(t.at-now)/1000;now=t.at;timers.delete(id);t.fn();await tick();
    }
    if(clock&&context.state==='running')context.currentTime+=(target-now)/1000;now=target;await tick();
  };
  return {player,context,controller,stats,nodes,requests,timers,play,advance,set response(value){response=value;},set current(value){current=value;},set clock(value){clock=value;}};
}

test('prepare resumes synchronously in Start gesture; normal onended releases all resources',async()=>{
  const f=fixture();f.context.state='suspended';const ready=f.player.prepare(f.controller.signal,()=>true);
  assert.equal(f.stats.resumed,1);await ready;assert.equal(f.timers.size,0);
  const p=f.play();await tick();assert.equal(f.stats.started,1);
  assert.equal(f.requests[0].options.credentials,'same-origin');assert.equal(f.requests[0].options.redirect,'error');
  f.nodes[0].onended();await p;assert.equal(f.stats.disconnected,1);assert.equal(f.timers.size,0);
});

for(const stage of ['fetch','body','decode','resume'])test(`${stage} never settles: deadline rejects and End can clean up without replay`,async()=>{
  const f=fixture(),pending=deferred();let limit=15000,code='audio_fetch';
  if(stage==='fetch')f.player.fetchAudio=()=>pending.promise;
  if(stage==='body')f.response={ok:true,arrayBuffer:()=>pending.promise};
  if(stage==='decode'){f.context.decodeAudioData=()=>pending.promise;limit=10000;code='audio_decode';}
  if(stage==='resume'){f.context.state='suspended';f.context.resume=()=>pending.promise;limit=5000;code='audio_resume';}
  const p=stage==='resume'?f.player.prepare(f.controller.signal,()=>true):f.play();const rejected=assert.rejects(p,e=>e.code===code);
  await tick();await f.advance(limit);await rejected;assert.equal(f.timers.size,0);assert.equal(f.stats.started,0);
  pending.resolve(stage==='decode'?{duration:2}:undefined);await tick();assert.equal(f.stats.started,0);
});

for(const stage of ['fetch','body','decode','resume'])test(`End during ${stage} settles immediately; late completion cannot start audio`,async()=>{
  const f=fixture(),pending=deferred();
  if(stage==='fetch')f.player.fetchAudio=()=>pending.promise;
  if(stage==='body')f.response={ok:true,arrayBuffer:()=>pending.promise};
  if(stage==='decode')f.context.decodeAudioData=()=>pending.promise;
  if(stage==='resume'){f.context.state='suspended';f.context.resume=()=>pending.promise;}
  const p=stage==='resume'?f.player.prepare(f.controller.signal,()=>true):f.play();const rejected=assert.rejects(p,{name:'AbortError'});
  await tick();f.controller.abort();f.player.cancel();await rejected;assert.equal(f.timers.size,0);
  pending.resolve(stage==='fetch'?{ok:true,arrayBuffer:async()=>new ArrayBuffer(32)}:stage==='decode'?{duration:2}:new ArrayBuffer(32));
  await tick();assert.equal(f.stats.started,0);
});

test('reject, malformed or stale URL, redirect, empty and oversized audio fail once before playback',async()=>{
  for(const response of [{ok:false},{ok:true,redirected:true},{ok:true,arrayBuffer:async()=>new ArrayBuffer(0)},
    {ok:true,headers:{get:()=>String(21*1024*1024)},arrayBuffer:async()=>{throw Error('Must not read');}}]){
    const f=fixture();f.response=response;await assert.rejects(f.play());assert.equal(f.requests.length,1);assert.equal(f.stats.decoded,0);assert.equal(f.timers.size,0);
  }
  const f=fixture();for(const url of [null,'https://elsewhere.invalid/audio','/kilas-translator/live/sessions/old/audio',URL+'?redirect=1'])await assert.rejects(f.player.play(url,f.controller.signal,()=>true),e=>e.code==='audio_url');
  assert.equal(f.requests.length,0);
});

test('decode rejection, invalid duration, failed resume and source start rejection are actionable failures',async()=>{
  for(const kind of ['decode','duration','resume','running','start']){
    const f=fixture();
    if(kind==='decode')f.context.decodeAudioData=async()=>{throw Error('Synthetic decode');};
    if(kind==='duration')f.context.decodeAudioData=async()=>({duration:NaN});
    if(kind==='resume'){f.context.state='suspended';f.context.resume=async()=>{throw Error('Synthetic autoplay denial');};}
    if(kind==='running'){f.context.state='suspended';f.context.resume=async()=>{};}
    if(kind==='start')f.context.createBufferSource=()=>({connect(){},start(){throw Error('Synthetic start');},stop(){},disconnect(){f.stats.disconnected++;}});
    await assert.rejects(f.play(),e=>/^audio_/.test(e.code)&&/tidak dibuat ulang/.test(e.message));assert.equal(f.timers.size,0);
    if(kind==='start')assert.equal(f.stats.disconnected,1);
  }
});

test('suspended context after download and one interruption during playback recover on the same buffer',async()=>{
  const f=fixture();f.context.decodeAudioData=async()=>{f.context.state='suspended';return {duration:2};};
  const p=f.play();await tick();assert.equal(f.stats.resumed,1);f.context.state='suspended';await f.advance(250);assert.equal(f.stats.resumed,2);
  f.nodes[0].onended();await p;assert.equal(f.requests.length,1);assert.equal(f.stats.started,1);assert.equal(f.timers.size,0);
});

test('repeated suspension stops without replay; a frozen audio clock cannot leave playing indefinitely',async()=>{
  const f=fixture(),p=f.play(),rejected=assert.rejects(p,e=>e.code==='audio_stalled');await tick();
  f.context.state='suspended';await f.advance(250);f.context.state='suspended';await f.advance(250);await rejected;
  assert.equal(f.stats.resumed,1);assert.equal(f.requests.length,1);assert.equal(f.timers.size,0);
  const g=fixture();g.clock=false;const playing=g.play(),stalled=assert.rejects(playing,e=>e.code==='audio_stalled');await tick();await g.advance(5000);await stalled;
  assert.equal(g.stats.stopped,1);assert.equal(g.stats.disconnected,1);assert.equal(g.timers.size,0);
});

test('missing onended recovers completion only once the running audio clock passes buffer duration',async()=>{
  const f=fixture();let ended=false;const p=f.play().then(()=>ended=true);await tick();
  await f.advance(2000);assert.equal(ended,false);await f.advance(250);await p;assert.equal(ended,true);assert.equal(f.timers.size,0);
});

test('wall deadline bounds a source with a slowly advancing audio clock',async()=>{
  const f=fixture();f.clock=false;const p=f.play(),rejected=assert.rejects(p,e=>e.code==='audio_timeout');await tick();
  for(let i=0;i<48;i++){f.context.currentTime+=.001;await f.advance(250);}await rejected;assert.equal(f.timers.size,0);assert.equal(f.stats.stopped,1);
});

test('End during playback rejects, removes callbacks and timers; stale operation cannot stop a newer source',async()=>{
  const f=fixture();const p=f.play(),rejected=assert.rejects(p,{name:'AbortError'});await tick();const old=f.nodes[0].onended;
  f.controller.abort();f.player.cancel();await rejected;assert.equal(f.nodes[0].onended,null);assert.equal(f.timers.size,0);
  const newController=new AbortController(),next=f.player.play(URL,newController.signal,()=>true);await tick();old();
  assert.equal(f.stats.started,2);assert.equal(f.stats.stopped,1);f.nodes[1].onended();await next;assert.equal(f.stats.stopped,2);assert.equal(f.timers.size,0);
});

test('a stale session after decode never starts a source or resumes audio',async()=>{
  const f=fixture(),decode=deferred();f.context.decodeAudioData=()=>decode.promise;
  const p=f.play(),rejected=assert.rejects(p,{name:'AbortError'});await tick();f.current=false;decode.resolve({duration:2});await rejected;
  assert.equal(f.stats.started,0);assert.equal(f.stats.resumed,0);assert.equal(f.timers.size,0);
});

test('unexpected AbortError from the device is a playback failure when the session was not cancelled',async()=>{
  const f=fixture();f.context.decodeAudioData=async()=>{throw new DOMException('Synthetic device error','AbortError');};
  await assert.rejects(f.play(),e=>e.code==='audio_decode');assert.equal(f.timers.size,0);
});

test('End during interruption recovery stops the old source even when resume never settles',async()=>{
  const f=fixture(),ready=deferred();const p=f.play(),rejected=assert.rejects(p,{name:'AbortError'});await tick();
  f.context.state='suspended';f.context.resume=()=>ready.promise;await f.advance(250);f.controller.abort();await rejected;
  assert.equal(f.stats.stopped,1);assert.equal(f.timers.size,0);ready.resolve();await tick();assert.equal(f.stats.started,1);assert.equal(f.timers.size,0);
});
