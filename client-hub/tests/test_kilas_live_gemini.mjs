// Synthetic clocks, PCM, transport and capture. No browser/provider/microphone.
import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiPlayer} from '../static/kilas_live_gemini_player.mjs';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';
const tick=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const pcm=()=>new Uint8Array(9600);
function clock(){let time=0,id=0;const timers=new Map();return {now:()=>time,schedule:(fn,ms)=>{const key=++id;timers.set(key,{fn,at:time+ms});return key;},clear:key=>timers.delete(key),advance(ms){time+=ms;const due=[...timers].filter(([,v])=>v.at<=time);for(const [key,v] of due){timers.delete(key);v.fn();}},timers};}
function audio(){
 const starts=[],nodes=[];const context={currentTime:0,state:'running',destination:{},
  createBuffer(channels,length,rate){assert.equal(channels,1);assert.equal(rate,24000);return {length,duration:length/rate,getChannelData:()=>new Float32Array(length)};},
  createBufferSource(){const node={connect(){},disconnect(){},stop(){node.stopped=true;},start(at){starts.push(at);}};nodes.push(node);return node;}};
 return {context,starts,nodes};
}

test('PCM prebuffer schedules consecutive buffers on one audio clock and drains the final short buffer',async()=>{
 const c=clock(),a=audio();const player=new GeminiPlayer({...c,getContext:()=>a.context});
 player.push(pcm());assert.equal(a.starts.length,0);
 player.push(pcm());assert.deepEqual(a.starts,[.02,.22]);
 const last=new Uint8Array(480);player.push(last);
 assert.ok(Math.abs(a.starts[2]-.42)<1e-8);
 let done=false;const drained=player.drain().then(()=>{done=true;});await tick();assert.equal(done,false);
 a.context.currentTime=.1;a.nodes[0].onended(); // First clip is still playing: must fail, not drop its end.
 await assert.rejects(drained,error=>error.code==='audio_stalled');
});

test('complete audio drains only after every sample; missing onended uses audio-clock completion',async()=>{
 const c=clock(),a=audio();const player=new GeminiPlayer({...c,getContext:()=>a.context});player.push(pcm());
 let done=false;const drained=player.drain().then(()=>{done=true;});assert.equal(a.starts.length,1);await tick();assert.equal(done,false);
 a.context.currentTime=.1;c.advance(250);await tick();assert.equal(done,false);
 a.context.currentTime=.6;c.advance(250);await drained;assert.equal(done,true);
});

test('continuous PCM cannot hide a stalled clock and End cancels every scheduled node',async()=>{
 const c=clock(),a=audio(),errors=[];const player=new GeminiPlayer({...c,getContext:()=>a.context,onError:e=>errors.push(e.code)});
 player.push(pcm());player.push(pcm());
 for(let i=0;i<5;i++){c.advance(1000);if(!player.failed)player.push(pcm());}
 assert.deepEqual(errors,['audio_stalled']);assert.ok(a.nodes.every(n=>n.stopped));
 const next=new GeminiPlayer({...c,getContext:()=>a.context});next.push(pcm());const drain=next.drain();next.cancel();
 await assert.rejects(drain,{name:'AbortError'});assert.ok(a.nodes.every(n=>n.stopped));
});

test('queue is bounded and malformed PCM never enters playback',()=>{
 const c=clock(),a=audio(),player=new GeminiPlayer({...c,getContext:()=>a.context});
 assert.throws(()=>player.push(new Uint8Array(3)),/gemini_pcm_invalid/);
 for(let i=0;i<40;i++)player.push(pcm());
 assert.throws(()=>player.push(pcm()),/gemini_playback_backlog/);player.cancel();
});

function fixture(){
 const requests=[],played=[],states=[],errors=[],tails=deferred(),drained=deferred(),c=clock();let handlers,reads=0,mic=false;
 const id='a'.repeat(48),key='live-'+'b'.repeat(32),path='/kilas-translator/live/gemini/sessions/'+id+'/turns/'+key;
 const frame=(index)=>({index,type:'audio',generation:0,pcm:btoa(String.fromCharCode(...new Uint8Array(480)))});
 const player={reset(){},push(raw){played.push({raw,mic});},cancel(){},drain:()=>drained.promise};
 const capture={async start(value){handlers=value;mic=true;value.ready();},finalize(){mic=false;handlers.blob(null);},cancel(){mic=false;}};
 const json=async(url,options={})=>{
  requests.push({url,...options});
  if(url==='/kilas-translator/live/gemini/sessions')return {session_id:id,input_mode:'gemini-live-v1'};
  if(url.endsWith('/end'))return {status:'ENDED'};
  if(url.endsWith('/chunks/0'))return {accepted_index:0};
  if(url.endsWith('/chunks/1'))return {accepted_index:1};
  if(url.endsWith('/finish'))return {status:'DRAINING'};
  if(options.method==='POST')return {input_mode:'gemini-live-v1'};
  if(reads++===0)return {status:'PROCESSING',frames:[frame(0)],next_index:1,translated_text:'Repeat. ',output_closed:false};
  return tails.promise;
 };
 const session=new GeminiSession({...c,json,capture,player,csrf:'synthetic',prepare:async()=>{},key:()=> 'b'.repeat(32),onState:s=>states.push(s),onError:e=>errors.push(e)});
 return {session,requests,played,states,errors,tails,drained,c,id,path,frame,get handlers(){return handlers;},get mic(){return mic;}};
}

test('native output is consumed while microphone remains active; Finish flushes partial input and drains tail before End',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();
 assert.equal(f.played.length,1);assert.equal(f.played[0].mic,true);assert.equal(f.mic,true);
 f.handlers.pcm(new Uint8Array(122));f.session.finish();await tick();
 const uploads=f.requests.filter(r=>r.url.includes('/chunks/'));
 assert.equal(uploads.length,2);assert.deepEqual(await uploads[0].body.get('pcm').arrayBuffer(),new Uint8Array(6400).buffer);
 assert.equal(uploads[1].body.get('pcm').size,122);
 assert.equal(f.requests.find(r=>r.url.endsWith('/finish')).body.get('count'),'2');
 f.c.advance(200);await tick();
 f.tails.resolve({status:'COMPLETED',frames:[f.frame(1)],next_index:2,translated_text:'Repeat. Complete tail.',output_closed:true,total_frames:2});await tick();
 assert.equal(f.played.length,2);assert.equal(f.session.active,true);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,0);
 f.drained.resolve();await tick();assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);assert.deepEqual(f.errors,[]);
});

test('late output after End is ignored and does not reopen capture or another provider request',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 await f.session.end();f.tails.resolve({status:'COMPLETED',frames:[f.frame(1)],next_index:2,translated_text:'Late',output_closed:true,total_frames:2});await tick();
 assert.equal(f.played.length,1);assert.equal(f.mic,false);assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url===f.path&&r.method==='POST').length,1);
});

test('duplicate or out-of-order output fails closed without paid replay',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'PROCESSING',frames:[f.frame(0)],next_index:2,translated_text:'Repeat.',output_closed:false});await tick();
 assert.equal(f.errors.length,1);assert.match(f.errors[0].message,/gemini_output_invalid/);assert.equal(f.session.active,false);assert.equal(f.played.length,1);
});

test('a late admitted session is closed after End; original admission never auto-retries',async()=>{
 const admission=deferred(),requests=[];const f=fixture();f.session.json=async(url,options={})=>{
  requests.push({url,...options});if(url.endsWith('/end'))return {status:'ENDED'};return admission.promise;
 };
 const start=f.session.start(new FormData());await tick();await f.session.end();
 admission.resolve({session_id:f.id,input_mode:'gemini-live-v1'});await start;await tick();
 assert.equal(f.mic,false);assert.equal(requests.length,2);assert.ok(requests[1].url.endsWith('/'+f.id+'/end'));
});

test('provider interruption clears pending output generation while input capture continues',async()=>{
 const f=fixture();let resets=0;f.session.player.cancel=()=>{resets++;};
 await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'PROCESSING',frames:[{index:1,type:'reset',generation:1},{...f.frame(2),generation:1}],next_index:3,translated_text:'New generation',output_closed:false});
 await tick();assert.equal(resets,1);assert.equal(f.mic,true);assert.equal(f.played.length,2);assert.equal(f.session.cursor,3);
 await f.session.end();assert.equal(f.mic,false);
});

test('End still cleans media and reaches the server when a UI callback throws',async()=>{
 const f=fixture();await f.session.start(new FormData());f.session.onState=()=>{throw Error('synthetic UI');};
 await f.session.end();assert.equal(f.mic,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});
