// Offline PCM/clocks only. No language recognition, browser, media or provider IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';
import {GeminiPlayer} from '../static/kilas_live_gemini_player.mjs';
import {PlaybackEcho} from '../static/kilas_live_gemini_echo.mjs';
import {PcmEncoder} from '../static/kilas_live_translator_pcm.mjs';
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
function clock(){let time=0,id=0;const timers=new Map();return {now:()=>time,schedule(fn,ms){timers.set(++id,{fn,at:time+ms});return id;},clear:id=>timers.delete(id),advance(ms){time+=ms;for(const [id,timer] of [...timers])if(timer.at<=time){timers.delete(id);timer.fn();}}};}
function sound(samples=1600,seed=1){const raw=new Uint8Array(samples*2),view=new DataView(raw.buffer);for(let i=0;i<samples;i++)view.setInt16(i*2,Math.round(Math.sin((i+seed)*.13)*8000),true);return raw;}
const frame=(index,generation=0)=>({type:'audio',index,generation,pcm:Buffer.from(sound(2400,index+1)).toString('base64')});
const snapshot=(frames,next,extra={})=>({status:'PROCESSING',frames,next_index:next,translated_text:'Synthetic output.',output_closed:false,...extra});
function audio(c){
 const nodes=[],starts=[];
 const context={state:'running',destination:{},get currentTime(){return c.now()/1000;},
  createBuffer(_channels,length,rate){const values=new Float32Array(length);return {length,sampleRate:rate,duration:length/rate,getChannelData:()=>values};},
  createBufferSource(){const node={connect(){},disconnect(){},stop(){this.stopped=true;},start(at){starts.push({at,node:this});}};nodes.push(node);return node;}};
 return {context,nodes,starts};
}
function fixture({isEcho=()=>false}={}){
 const c=clock(),a=audio(c),requests=[],polls=[],errors=[];let handlers,key=0,mic=false;
 const player=new GeminiPlayer({...c,getContext:()=>a.context,maxBufferedSeconds:90});
 const capture={async start(value){handlers=value;mic=true;value.ready();},cancel(){mic=false;}};
 const json=async(url,options={})=>{
  requests.push({url,...options});
  if(url==='/kilas-translator/live/gemini/sessions')return {session_id:'a'.repeat(48),input_mode:'gemini-live-v1'};
  if(url.endsWith('/end'))return {status:'ENDED'};
  const chunk=url.match(/\/chunks\/(\d+)$/);if(chunk)return {accepted_index:Number(chunk[1])};
  if(url.endsWith('/finish'))return {status:'DRAINING'};
  if(options.method==='POST')return {input_mode:'gemini-live-v1'};
  const result=deferred();polls.push({...result,url});return result.promise;
 };
 const session=new GeminiSession({...c,json,capture,player,prepare:async()=>{},csrf:'synthetic',utterancePlayback:true,isEcho,
  key:()=> (++key).toString(16).padStart(32,'0'),onError:error=>errors.push(error)});
 const turns=()=>requests.filter(r=>r.method==='POST'&&/\/turns\/live-[a-f0-9]{32}$/.test(r.url));
 const uploaded=async path=>Buffer.concat(await Promise.all(requests.filter(r=>r.url.startsWith(path+'/chunks/')).map(async r=>Buffer.from(await r.body.get('pcm').arrayBuffer()))));
 return {c,a,player,session,requests,polls,errors,turns,uploaded,get mic(){return mic;},
  async input(raw){c.advance(raw.length/32);handlers.pcm(raw);await tick();},get handlers(){return handlers;}};
}
async function silence(f,count){for(let i=0;i<count;i++)await f.input(new Uint8Array(3200));}
async function voice(f,count){for(let i=0;i<count;i++)await f.input(sound(1600,i+1));}

test('stream processing overlaps speech but audible output waits for2s final silence, not an intra-sentence pause',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());
 await voice(f,5);f.polls[0].resolve(snapshot([frame(0)],1));await tick();
 assert.equal(f.player.pendingSamples,2400);assert.equal(f.a.starts.length,0);assert.equal(f.turns().length,1);
 await silence(f,19);assert.equal(f.a.starts.length,0);assert.equal(f.session.speech.active,true);
 await voice(f,10);assert.equal(f.a.starts.length,0);
 await silence(f,19);assert.equal(f.a.starts.length,0);
 await silence(f,1);assert.equal(f.session.speech.active,false);assert.equal(f.player.holding,false);assert.equal(f.a.starts.length,1);
 assert.equal(f.requests.some(r=>r.url.endsWith('/finish')),false);assert.equal(f.mic,true);
 await silence(f,30);assert.equal(f.turns().length,1);assert.deepEqual(f.errors,[]);
});

test('a new utterance pauses accepted playback and resumes its exact remaining samples in order',async()=>{
 const c=clock(),a=audio(c),player=new GeminiPlayer({...c,getContext:()=>a.context,maxBufferedSeconds:90});
 const first=sound(4800,1),second=sound(4800,2),third=sound(2400,3);
 player.hold();player.push(first,'one');player.push(second,'one');assert.equal(a.starts.length,0);
 player.release();assert.equal(a.starts.length,2);c.advance(70);player.hold();
 const consumed=1200;assert.equal(player.queue.length,2);assert.equal(player.queue[0].buffer.length,4800-consumed);
 const expected=new Float32Array((first.length+second.length+third.length)/2-consumed);
 let at=0;for(const [raw,skip] of [[first,consumed],[second,0],[third,0]]){const view=new DataView(raw.buffer);for(let i=skip;i<raw.length/2;i++)expected[at++]=view.getInt16(i*2,true)/32768;}
 player.push(third,'two');const actual=Float32Array.from(player.queue.flatMap(entry=>Array.from(entry.buffer.getChannelData(0))));
 assert.deepEqual(actual,expected);assert.ok(a.nodes.slice(0,2).every(node=>node.stopped));
 c.advance(1500);assert.equal(a.starts.length,2);player.release();assert.equal(a.starts.length,5);
 assert.ok(a.starts[3].at>=a.starts[2].at);player.cancel();
});

test('provider reset does not erase accepted sentence PCM in utterance-gated playback',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());await voice(f,3);
 let interrupted=0;f.player.interrupt=()=>interrupted++;
 f.polls[0].resolve(snapshot([frame(0),{index:1,type:'reset',generation:1},frame(2,1)],3));await tick();
 assert.equal(f.player.pendingSamples,4800);assert.equal(interrupted,0);assert.equal(f.a.starts.length,0);
 await silence(f,20);assert.equal(f.a.starts.length,2);assert.deepEqual(f.errors,[]);
});

test('quiet renewal preserves source bytes and standby silence never reserves a successor',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());
 const sent=[];for(let i=0;i<440;i++){const raw=sound(1600,i);sent.push(Buffer.from(raw));await f.input(raw);}
 assert.equal(f.requests.some(r=>r.url.endsWith('/finish')),false);
 for(let i=0;i<20;i++){const raw=new Uint8Array(3200);sent.push(Buffer.from(raw));await f.input(raw);}
 const path=f.turns()[0].url;assert.equal(f.requests.filter(r=>r.url===path+'/finish').length,1);
 assert.deepEqual(await f.uploaded(path),Buffer.concat(sent));
 await silence(f,20);assert.equal(f.session.carryBytes,0);
 const pending=f.polls.at(-1);pending.resolve(snapshot([],0,{status:'COMPLETED',output_closed:true,total_frames:0,completion_kind:'bounded_drain',tail_confirmed:false}));await tick();
 assert.equal(f.session.turn,null);await silence(f,20);assert.equal(f.turns().length,1);
 await voice(f,1);assert.equal(f.turns().length,2);assert.equal(f.session.active,true);assert.deepEqual(f.errors,[]);
});

test('a hard renewal during continuous speech preserves all source bytes and keeps both turns inaudible until silence',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());const sent=[];
 for(let i=0;i<600;i++){const raw=sound(1600,i);sent.push(Buffer.from(raw));await f.input(raw);}
 const first=f.turns()[0].url;assert.equal(f.requests.filter(r=>r.url===first+'/finish').length,1);assert.equal(f.a.starts.length,0);
 f.polls[0].resolve(snapshot([frame(0)],1,{status:'COMPLETED',output_closed:true,total_frames:1,completion_kind:'bounded_drain',tail_confirmed:false}));await tick();
 assert.equal(f.turns().length,2);const second=f.turns()[1].url;
 // Flush the successor's partial input as ordinary silence enters its stream.
 await silence(f,20);f.session.flush(f.session.version,f.session.turn);await tick();
 const expected=Buffer.concat([...sent,Buffer.alloc(20*3200)]);
 assert.deepEqual(Buffer.concat([await f.uploaded(first),await f.uploaded(second)]),expected);
 assert.equal(f.player.holding,false);assert.equal(f.a.starts.length,1);assert.deepEqual(f.errors,[]);
});

test('silence carried across a hard boundary does not reserve an otherwise idle successor',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());await voice(f,590);await silence(f,20);
 assert.equal(f.session.carryBytes,20*3200);
 f.polls[0].resolve(snapshot([],0,{status:'COMPLETED',output_closed:true,total_frames:0,completion_kind:'bounded_drain',tail_confirmed:false}));await tick();
 assert.equal(f.session.turn,null);assert.equal(f.turns().length,1);assert.equal(f.session.speech.preRoll.length,4);
 await voice(f,1);assert.equal(f.turns().length,2);assert.deepEqual(f.errors,[]);
});

test('recognizable playback echo neither starts another utterance nor opens an idle provider connection',async t=>{
 const echo=sound(),f=fixture({isEcho:bytes=>bytes===echo});t.after(()=>f.session.end());await f.session.start(new FormData());
 for(let i=0;i<30;i++)await f.input(echo);
 assert.equal(f.session.speech.active,false);assert.equal(f.turns().length,0);assert.equal(f.a.starts.length,0);
 await voice(f,1);assert.equal(f.turns().length,1);assert.equal(f.session.speech.active,true);
});

test('the local echo check rejects delayed scaled playback and retains mixed new speech',()=>{
 const context={currentTime:.8},echo=new PlaybackEcho({getContext:()=>context}),base=Float32Array.from({length:800},(_,i)=>Math.sin(i*.19)*.3+Math.sin(i*.371)*.15);
 const reference=Float32Array.from({length:4800},(_,i)=>base[Math.floor(i/6)]);
 echo.remember({sampleRate:24000,getChannelData:()=>reference},.2);
 const input=mixed=>{const raw=new Uint8Array(6400),view=new DataView(raw.buffer);for(let i=0;i<3200;i++)view.setInt16(i*2,Math.round((base[Math.floor(i/4)]*.35+(mixed?Math.sin(i*.031)*.15:0))*32768),true);return raw;};
 assert.equal(echo.matches(input(false)),true);assert.equal(echo.matches(input(true)),false);
 echo.hold(.2);assert.equal(echo.matches(input(false)),false);
});

test('network failure cannot release queued translation over ongoing speech; local silence permits a bounded drain',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());await voice(f,2);f.player.push(sound(2400));
 f.session.fail(Object.assign(Error('synthetic'),{code:'network'}),f.session.version);await tick();assert.equal(f.a.starts.length,0);assert.equal(f.mic,true);
 const before=f.requests.length;await voice(f,2);await silence(f,19);assert.equal(f.requests.length,before);assert.equal(f.a.starts.length,0);
 await silence(f,1);assert.equal(f.mic,false);assert.equal(f.a.starts.length,1);
 f.c.advance(1000);await tick();assert.equal(f.session.active,false);assert.equal(f.turns().length,1);assert.equal(f.errors.length,1);
});

test('terminal server failure preserves local endpoint observation before draining its accepted tail',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());await voice(f,2);
 f.polls[0].resolve(snapshot([frame(0)],1,{status:'FAILED',code:'gemini_transport',output_closed:true,total_frames:1}));await tick();
 assert.equal(f.mic,true);assert.equal(f.a.starts.length,0);assert.equal(f.session.stopping,true);
 const before=f.requests.length;await silence(f,19);assert.equal(f.mic,true);assert.equal(f.a.starts.length,0);assert.equal(f.requests.length,before);
 await silence(f,1);assert.equal(f.mic,false);assert.equal(f.a.starts.length,1);
 f.c.advance(1000);await tick();assert.equal(f.session.active,false);assert.equal(f.turns().length,1);assert.equal(f.errors.length,1);
});

test('new speech while a failed tail is paginating holds its final accepted PCM without upload',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());await voice(f,1);await silence(f,20);
 f.polls[0].resolve(snapshot([],0,{status:'FAILED',output_closed:false,code:'gemini_transport'}));await tick();
 const before=f.requests.filter(r=>r.method==='POST').length;
 await voice(f,3);assert.equal(f.session.speech.active,true);assert.equal(f.player.holding,true);
 assert.equal(f.requests.filter(r=>r.method==='POST').length,before);
 f.polls.at(-1).resolve(snapshot([frame(0)],1,{status:'FAILED',output_closed:true,total_frames:1,code:'gemini_transport'}));await tick();
 assert.equal(f.a.starts.length,0);assert.equal(f.mic,true);await silence(f,19);assert.equal(f.a.starts.length,0);
 await silence(f,1);assert.equal(f.a.starts.length,1);assert.equal(f.mic,false);
});

test('failure silence wait is bounded and explicit End cannot be undone by a late local endpoint',async t=>{
 for(const explicit of [false,true]){
  const f=fixture();await f.session.start(new FormData());await voice(f,2);f.player.push(sound(2400));
  f.session.fail(Error('synthetic'),f.session.version);await tick();
  if(explicit)await f.session.end();else f.c.advance(10000);
  await tick();assert.equal(f.session.active,false);assert.equal(f.mic,false);assert.equal(f.a.starts.length,0);
  await silence(f,20);assert.equal(f.a.starts.length,0);assert.equal(f.turns().length,1);
 }
});

test('native100ms PCM frames preserve the final partial samples and legacy framing stays200ms',()=>{
 for(const size of [1600,3200]){
  const emitted=[],encoder=new PcmEncoder(48000,value=>emitted.push(value),size);
  for(let i=0;i<13;i++)encoder.feed([new Float32Array(1000).fill(.2)]);
  encoder.finish();assert.equal(emitted.reduce((total,item)=>total+item.bytes.byteLength/2,0),Math.ceil(13000/3));
  assert.equal(emitted[0].bytes.byteLength,size*2);assert.ok(emitted.at(-1).bytes.byteLength>0);
 }
});

test('a new failed preparation does not inherit the previous session speech endpoint',async()=>{
 const f=fixture();await f.session.start(new FormData());await voice(f,1);await f.session.end();
 f.session.prepare=async()=>{throw Error('synthetic preparation failure');};await f.session.start(new FormData());await tick();
 assert.equal(f.session.speech.active,false);assert.equal(f.mic,false);assert.equal(f.session.failureEndpoint,null);assert.equal(f.session.active,false);
});
