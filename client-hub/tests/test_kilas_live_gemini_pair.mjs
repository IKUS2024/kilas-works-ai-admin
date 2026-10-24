// Negotiated pair protocol with synthetic clocks/PCM only; no browser/media/provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';
import {GeminiPlayer} from '../static/kilas_live_gemini_player.mjs';
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
const MODE='gemini-live-two-way-v2',ids=['id','en'];
const pcm=(samples=1600,value=8000)=>{const raw=new Uint8Array(samples*2),view=new DataView(raw.buffer);for(let i=0;i<samples;i++)view.setInt16(i*2,value,true);return raw;};
const frame=(index,stream_id,generation=0,value=1000)=>({type:'audio',index,stream_id,target_language:stream_id,generation,pcm:Buffer.from(pcm(2400,value)).toString('base64')});
function clock(){let time=0,id=0;const timers=new Map();return {now:()=>time,schedule(fn,ms){timers.set(++id,{fn,at:time+ms});return id;},clear:id=>timers.delete(id),advance(ms){time+=ms;for(const [id,timer] of [...timers])if(timer.at<=time){timers.delete(id);timer.fn();}}};}
function snapshot(frames=[],extra={}){
 const closed=extra.output_closed??false;
 const streams=Object.fromEntries(ids.map(id=>[id,{target_language:id,generation:0,output_closed:closed,tail_confirmed:false,completion_kind:closed?'bounded_drain':null}]));
 return {input_mode:MODE,translation_mode:'two_way',output_order:'progressive_stream_runs',streams,status:closed?'COMPLETED':'PROCESSING',frames,next_index:frames.at(-1)?.index+1||0,translated_text:'',output_closed:closed,total_frames:closed?frames.length:null,tail_confirmed:false,completion_kind:closed?'bounded_drain':null,...extra};
}
function fixture({admission={},turnAdmission={},maxBufferedSeconds=8,legacy=false,fast=false,waitForOutputBeforeFinish=false}={}){
 const c=clock(),nodes=[],requests=[],polls=[],errors=[],warnings=[];let handlers,mic=false,key=0;
 const context={state:'running',destination:{},get currentTime(){return c.now()/1000;},createBuffer(_channels,length,rate){const values=new Float32Array(length);return {length,sampleRate:rate,duration:length/rate,getChannelData:()=>values};},createBufferSource(){const node={connect(){},disconnect(){},stop(){this.stopped=true;},start(at){this.at=at;}};nodes.push(node);return node;}};
 const player=new GeminiPlayer({...c,getContext:()=>context,maxBufferedSeconds});
 const capture={async start(value){handlers=value;mic=true;value.ready();},cancel(){mic=false;}};
 const json=async(url,options={})=>{
  requests.push({url,...options});
  if(url==='/kilas-translator/live/gemini/sessions')return {session_id:'a'.repeat(48),input_mode:legacy?'gemini-live-two-way-v1':MODE,translation_mode:'two_way',streams:ids,...(legacy?{}:{output_order:'progressive_stream_runs'}),...admission};
  if(url.endsWith('/end'))return {status:'ENDED'};
  const chunk=url.match(/\/chunks\/(\d+)$/);if(chunk)return {accepted_index:Number(chunk[1])};
  if(url.endsWith('/finish'))return {status:'DRAINING'};
  if(options.method==='POST')return {input_mode:legacy?'gemini-live-two-way-v1':MODE,translation_mode:'two_way',streams:ids,...(legacy?{}:{output_order:'progressive_stream_runs'}),...turnAdmission};
  const result=deferred();polls.push({...result,url});return result.promise;
 };
 const session=new GeminiSession({waitForOutputBeforeFinish,...c,json,capture,player,prepare:async()=>{},csrf:'synthetic',utterancePlayback:true,...(fast?{endpointMs:600,packetBytes:3200,readRetries:2}:{}),key:()=> (++key).toString(16).padStart(32,'0'),onError:error=>errors.push(error),onWarning:value=>warnings.push(value)});
 const form=new FormData();form.set('translation_mode','two_way');form.set('language_a','id');form.set('language_b','en');form.set('consent',legacy?'gemini-live-two-way-v1':'gemini-live-two-way-v2');if(!legacy)form.set('output_order','progressive_stream_runs');
 const input=async(raw)=>{c.advance(raw.length/32);handlers.pcm(raw);await tick();};
 const voice=async(count=1)=>{for(let i=0;i<count;i++)await input(pcm());},silence=async(count)=>{for(let i=0;i<count;i++)await input(pcm(1600,0));};
 const turns=()=>requests.filter(r=>r.method==='POST'&&/\/turns\/live-[a-f0-9]{32}$/.test(r.url));
 return {session,form,c,nodes,requests,polls,errors,warnings,player,voice,silence,turns,get mic(){return mic;}};
}
async function publish(f,frames,extra={}){
 for(let offset=0;offset<frames.length;offset+=12){
  f.polls.at(-1).resolve(snapshot(frames.slice(offset,offset+12),{output_closed:true,total_frames:frames.length,...extra}));await tick();
  if(offset+12<frames.length){f.c.advance(200);await tick();}
 }
}
const longFrames=(count)=>Array.from({length:count},(_,index)=>({...frame(index,index<count/2?'en':'id'),pcm:Buffer.from(pcm(4800,index+1)).toString('base64')}));

test('open primary PCM starts at the2s local endpoint while both provider streams remain open',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();
 f.polls[0].resolve(snapshot([frame(0,'en'),frame(1,'en'),frame(2,'en')]));await tick();
 assert.equal(f.player.pendingSamples,7200);assert.equal(f.nodes.length,0);await f.silence(19);assert.equal(f.nodes.length,0);assert.equal(f.session.speech.active,true);
 await f.silence(1);assert.equal(f.nodes.length,3);assert.equal(f.session.turn.closed,false);assert.equal(f.session.active,true);assert.equal(f.mic,true);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,1);assert.deepEqual(f.warnings,[]);assert.deepEqual(f.errors,[]);
});

test('late primary PCM precedes progressive secondary PCM without replay or returning to the primary stream',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();
 f.polls[0].resolve(snapshot([frame(0,'en',0,1000),frame(1,'en',0,2000),frame(2,'en',0,3000)]));await tick();await f.silence(20);
 f.polls.at(-1).resolve(snapshot([frame(3,'en',0,4000)]));await tick();f.c.advance(200);await tick();
 const streams=snapshot().streams;streams.en={...streams.en,output_closed:true,completion_kind:'bounded_drain'};
 f.polls.at(-1).resolve(snapshot([frame(4,'id',0,5000)],{streams}));await tick();assert.equal(f.session.turn.closed,false);f.c.advance(200);await tick();
 f.polls.at(-1).resolve(snapshot([frame(5,'id',0,6000)],{output_closed:true,total_frames:6}));await tick();
 assert.deepEqual(f.nodes.map(node=>Math.round(node.buffer.getChannelData(0)[0]*32768)),[1000,2000,3000,4000,5000,6000]);assert.equal(f.turns().length,1);assert.equal(f.mic,true);assert.deepEqual(f.errors,[]);
});

test('new speech during a failed progressive page holds early PCM and the final tail without another upload',async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();
 f.polls[0].resolve(snapshot([frame(0,'en'),frame(1,'en'),frame(2,'en')]));await tick();await f.silence(20);
 f.polls.at(-1).resolve(snapshot([],{status:'FAILED',code:'gemini_transport',next_index:3}));await tick();const uploads=f.requests.filter(r=>r.url.includes('/chunks/')).length;
 await f.voice();assert.equal(f.player.holding,true);assert.equal(f.mic,true);const before=f.nodes.length;f.c.advance(200);await tick();
 f.polls.at(-1).resolve(snapshot([frame(3,'en',0,4000),frame(4,'id',0,5000)],{status:'FAILED',code:'gemini_transport',output_closed:true,total_frames:5}));await tick();
 assert.equal(f.nodes.length,before);await f.silence(19);assert.equal(f.nodes.length,before);await f.silence(1);assert.ok(f.nodes.length>before);assert.equal(f.mic,false);
 f.c.advance(2000);await tick();assert.equal(f.session.active,false);assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'gemini_transport');assert.equal(f.requests.filter(r=>r.url.includes('/chunks/')).length,uploads);assert.equal(f.turns().length,1);
});

test('End discards an open progressive page and fences a late accepted tail',async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();f.polls[0].resolve(snapshot([frame(0,'en')]));await tick();assert.equal(f.player.pendingSamples,2400);assert.equal(f.nodes.length,0);
 f.c.advance(200);await tick();const pending=f.polls.at(-1);await f.session.end();pending.resolve(snapshot([frame(1,'en'),frame(2,'id')],{output_closed:true,total_frames:3}));await tick();
 assert.equal(f.player.pendingSamples,0);assert.equal(f.nodes.length,0);assert.equal(f.mic,false);assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);assert.deepEqual(f.errors,[]);
});

test('a cachedv1 form retains whole-turn publication without being silently upgraded to progressivev2',async t=>{
 const f=fixture({legacy:true});t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();await f.silence(20);
 const legacy={input_mode:'gemini-live-two-way-v1',output_order:'stream_runs_after_close',output_closed:true,total_frames:3};
 f.polls[0].resolve(snapshot([frame(0,'en')],legacy));await tick();assert.equal(f.player.pendingSamples,0);assert.equal(f.nodes.length,0);f.c.advance(300);await tick();
 f.polls.at(-1).resolve(snapshot([frame(1,'en'),frame(2,'id')],legacy));await tick();assert.equal(f.nodes.length,3);assert.deepEqual(f.errors,[]);assert.equal(f.session.inputMode,'gemini-live-two-way-v1');
});

test('paired input reaches EOS only after2s silence and consumes coherent labeled pages progressively',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice(3);await f.silence(19);
 assert.equal(f.requests.some(r=>r.url.endsWith('/finish')),false);await f.voice(1);await f.silence(20);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,1);assert.equal(f.mic,true);assert.equal(f.nodes.length,0);
 f.polls[0].resolve(snapshot([frame(0,'en'),{index:1,type:'reset',stream_id:'en',target_language:'en',generation:1}],{output_closed:true,total_frames:4,streams:{en:{target_language:'en',generation:1,output_closed:true,tail_confirmed:false,completion_kind:'bounded_drain'},id:{target_language:'id',generation:0,output_closed:true,tail_confirmed:false,completion_kind:'bounded_drain'}}}));await tick();
 assert.equal(f.nodes.length,0);assert.equal(f.session.cursor,2);f.c.advance(200);await tick();
 f.polls[1].resolve(snapshot([frame(2,'en',1,2000),frame(3,'id',0,3000)],{output_closed:true,total_frames:4,streams:{en:{target_language:'en',generation:1,output_closed:true,tail_confirmed:false,completion_kind:'bounded_drain'},id:{target_language:'id',generation:0,output_closed:true,tail_confirmed:false,completion_kind:'bounded_drain'}}}));await tick();
 assert.equal(f.nodes.length,3);assert.deepEqual(f.nodes.map(node=>node.buffer.getChannelData(0)[0]),[1000,2000,3000].map(value=>value/32768));assert.equal(f.warnings.length,1);assert.equal(f.turns().length,1);assert.equal(f.mic,true);assert.deepEqual(f.errors,[]);
});

test('new speech keeps both accepted target runs held and an already-ended carry gets its own immediate EOS',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();await f.silence(20);await f.voice(2);
 f.polls[0].resolve(snapshot([frame(0,'id'),frame(1,'en')],{output_closed:true,total_frames:2}));await tick();
 assert.equal(f.nodes.length,0);assert.equal(f.player.pendingSamples,4800);assert.equal(f.turns().length,2);await f.silence(19);assert.equal(f.nodes.length,0);await f.silence(1);assert.equal(f.nodes.length,2);assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,2);
 f.c.advance(200);await tick();await f.voice();await f.silence(20);
 f.polls.at(-1).resolve(snapshot([],{output_closed:true,total_frames:0}));await tick();
 assert.equal(f.turns().length,3);assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,3);assert.equal(f.mic,true);assert.deepEqual(f.errors,[]);
});

for(const invalid of ['missing_label','wrong_target','wrong_generation','interleaved','unclosed_primary','missing_protocol','wrong_order'])test(`paired output rejects ${invalid} without retrying or mixing streams`,async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();await f.silence(20);
 let frames=[frame(0,'en')],result=snapshot(frames,{output_closed:true,total_frames:1});
 if(invalid==='missing_label')delete frames[0].stream_id;
 if(invalid==='wrong_target')frames[0].target_language='id';
 if(invalid==='wrong_generation')frames[0].generation=1;
 if(invalid==='interleaved'){frames=[frame(0,'en'),frame(1,'id'),frame(2,'en')];result=snapshot(frames,{output_closed:true,total_frames:3});}
 if(invalid==='unclosed_primary')result=snapshot([frame(0,'en'),frame(1,'id')]);
 if(invalid==='missing_protocol')delete result.input_mode;
 if(invalid==='wrong_order')result.output_order='arrival_order';
 f.polls[0].resolve(result);await tick();f.c.advance(2000);await tick();
 assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'gemini_output_invalid');assert.equal(f.session.active,false);assert.equal(f.turns().length,1);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('pair admission refuses a one-way downgrade before opening media or a provider turn',async()=>{
 const f=fixture({admission:{input_mode:'gemini-live-v1'}});await f.session.start(f.form);await tick();
 assert.equal(f.errors[0].code,'gemini_protocol');assert.equal(f.mic,false);assert.equal(f.turns().length,0);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('progressive admission refuses a legacy paired downgrade or a mismatched output contract before media starts',async()=>{
 for(const admission of [{input_mode:'gemini-live-two-way-v1'},{output_order:'stream_runs_after_close'},{output_order:undefined}]){
  const f=fixture({admission});await f.session.start(f.form);await tick();assert.equal(f.errors[0].code,'gemini_protocol');assert.equal(f.mic,false);assert.equal(f.turns().length,0);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
 }
});

test('stream labels follow a negotiated generic selected pair rather than a hard-coded EN/ID pair',async t=>{
 const selected=['es','zh'],f=fixture({admission:{streams:selected},turnAdmission:{streams:selected}});t.after(()=>f.session.end());
 f.form.set('language_a','es');f.form.set('language_b','zh');await f.session.start(f.form);await f.voice();await f.silence(20);
 const streams=Object.fromEntries(selected.map(id=>[id,{target_language:id,generation:0,output_closed:true,tail_confirmed:true,completion_kind:'turn_complete'}]));
 f.polls[0].resolve(snapshot([frame(0,'zh'),frame(1,'es')],{output_closed:true,total_frames:2,streams,tail_confirmed:true,completion_kind:'turn_complete'}));await tick();f.c.advance(300);await tick();
 assert.equal(f.nodes.length,2);assert.deepEqual(f.warnings,[]);assert.deepEqual(f.errors,[]);assert.equal(f.mic,true);
});

test('one confirmed stream cannot certify the paired tail and reports the bounded completion warning',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();await f.silence(20);
 const result=snapshot([frame(0,'en'),frame(1,'id')],{output_closed:true,total_frames:2});result.streams.en.tail_confirmed=true;result.streams.en.completion_kind='turn_complete';
 f.polls[0].resolve(result);await tick();f.c.advance(300);await tick();assert.equal(f.nodes.length,2);assert.equal(f.warnings.length,1);assert.equal(f.warnings[0].tail_confirmed,false);assert.equal(f.warnings[0].completion_kind,'bounded_drain');assert.deepEqual(f.errors,[]);
});

test('End fences a late paired terminal page and never plays or opens a successor',async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();await f.silence(20);const pending=f.polls[0];await f.session.end();
 pending.resolve(snapshot([frame(0,'en'),frame(1,'id')],{output_closed:true,total_frames:2}));await tick();
 assert.equal(f.nodes.length,0);assert.equal(f.mic,false);assert.equal(f.session.active,false);assert.equal(f.turns().length,1);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('default8s player capacity feeds a complete8.2s pair without ending the logical session',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(f.form);await f.voice();await f.silence(20);await publish(f,longFrames(41));
 assert.equal(f.player.pendingSamples,8*24000);assert.equal(f.session.outputQueue.length,1);assert.equal(f.mic,true);assert.equal(f.session.active,true);assert.deepEqual(f.errors,[]);
 f.c.advance(8500);await tick();assert.equal(f.nodes.length,41);assert.equal(f.session.outputQueue.length,0);
 assert.deepEqual(f.nodes.map(node=>Math.round(node.buffer.getChannelData(0)[0]*32768)),Array.from({length:41},(_,index)=>index+1));
 assert.equal(f.mic,true);assert.equal(f.turns().length,1);assert.deepEqual(f.errors,[]);
});

test('held failure releases at local quiet before feeding beyond player capacity and draining all accepted PCM',async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();await f.silence(20);await f.voice();
 await publish(f,longFrames(41),{status:'FAILED',code:'gemini_transport'});assert.equal(f.nodes.length,0);assert.equal(f.mic,true);assert.equal(f.session.outputQueue.length,1);
 await f.silence(19);assert.equal(f.nodes.length,0);await f.silence(1);assert.equal(f.nodes.length,40);assert.equal(f.mic,false);assert.equal(f.session.active,true);
 f.c.advance(8500);await tick();assert.equal(f.nodes.length,41);f.c.advance(1000);await tick();
 assert.equal(f.session.active,false);assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'gemini_transport');assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('End wakes a capacity checkpoint and no accepted raw tail leaks into a restarted session',async()=>{
 const f=fixture();await f.session.start(f.form);await f.voice();await f.silence(20);await publish(f,longFrames(41));assert.equal(f.session.outputQueue.length,1);
 await f.session.end();assert.equal(f.session.outputQueue.length,0);assert.ok(f.nodes.every(node=>node.stopped));const before=f.nodes.length;
 await f.session.start(f.form);f.c.advance(10000);await tick();assert.equal(f.nodes.length,before);assert.equal(f.session.active,true);assert.equal(f.mic,true);assert.deepEqual(f.errors,[]);await f.session.end();
});

test('a cumulative90s player backlog stages the next pair intact and denies a further paid admission',async()=>{
 const f=fixture({maxBufferedSeconds:90});await f.session.start(f.form);await f.voice();await f.silence(20);
 // Represent89.8s accepted by a prior settled turn, held by the latest voice.
 f.player.hold();for(let i=0;i<449;i++)f.player.push(pcm(4800,123));await publish(f,longFrames(2));
 assert.equal(f.session.queuedOutputBytes,90.2*48000);assert.equal(f.session.outputQueue.length,1);const before=f.turns().length;
 await f.voice();assert.equal(f.turns().length,before);assert.equal(f.errors[0].code,'gemini_playback_backlog');assert.equal(f.mic,true);
 await f.silence(20);assert.equal(f.mic,false);assert.equal(f.session.active,true);f.c.advance(90500);await tick();f.c.advance(1000);await tick();
 assert.equal(f.session.active,false);assert.equal(f.turns().length,before);assert.equal(f.session.outputQueue.length,0);
});

for(const target of ['en','id'])test(`fast ${target} PCM plays before End after600ms while microphone continues`,async t=>{
 const f=fixture({fast:true});t.after(()=>f.session.end());await f.session.start(f.form);await f.voice(3);
 assert.equal(f.requests.filter(r=>r.url.includes('/chunks/')).length,3);
 f.polls[0].resolve(snapshot([frame(0,target)]));await tick();
 await f.silence(5);assert.equal(f.nodes.length,0);await f.silence(1);
 assert.equal(f.nodes.length,1);assert.equal(f.mic,true);assert.equal(f.session.active,true);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,0);assert.equal(f.session.turn.closed,false);
 console.log(JSON.stringify({synthetic:true,target,uploadedPackets:3,packetMs:100,pauseMs:600,outputNodesBeforeEnd:f.nodes.length,microphoneActive:f.mic}));
});


test('native UI keeps the provider input open through a short pause until first translated PCM',async t=>{
 const f=fixture({fast:true,waitForOutputBeforeFinish:true});t.after(()=>f.session.end());
 await f.session.start(f.form);await f.voice();await f.silence(6);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,0);
 assert.equal(f.session.active,true);assert.equal(f.mic,true);
 f.polls[0].resolve(snapshot(Array.from({length:6},(_,i)=>frame(i,'en'))));await tick();
 assert.equal(f.requests.filter(r=>r.url.endsWith('/finish')).length,1);
 assert.ok(f.nodes.length>0);assert.equal(f.mic,true);
 assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,0);
});
