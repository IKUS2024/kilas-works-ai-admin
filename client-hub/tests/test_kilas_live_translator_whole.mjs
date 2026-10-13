// Offline synthetic response/media/clock fixtures; no browser, microphone or provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';
const id='a'.repeat(48),key='live-'+'b'.repeat(32),url='/kilas-translator/live/sessions/'+id+'/turns/'+key;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const full='Repeated words. Repeated words. 最后一句 كاملة.';
const prefix={status:'PROCESSING',stream_output:'sentences-v1',translated_text:full,source_language:'en',target_language:'id',total_segments:2,segments:[{index:0,duration_ms:900,audio_url:url+'/audio/segments/0',translated_text:'Repeated words.'}]};
const completed={...prefix,status:'COMPLETED',audio_url:url+'/audio',segments:[...prefix.segments,{index:1,duration_ms:2500,audio_url:url+'/audio/segments/1',translated_text:full}]};
function transport(sequence){
 const requests=[],pending=[];let reads=0;
 const turns=new TranslatorTurns({csrf:'synthetic',wholeUtterance:true,schedule:fn=>{queueMicrotask(fn);return 1;},clear(){},json:async(path,options={})=>{
  requests.push({path,method:options.method||'GET',body:options.body});
  if(path.endsWith('/cancel'))return {status:'CANCELLED'};
  if(options.method==='POST')return {status:'PROCESSING'};
  const value=sequence[reads++];if(value instanceof Error)throw value;return typeof value==='function'?value():value;
 }});
 return {turns,requests,pending,get reads(){return reads;}};
}
test('a delayed legacy second chunk never starts early prefix playback or another submission',async()=>{
 const delayed=deferred(),f=transport([prefix,()=>delayed.promise]),clips=[],prefetched=[];
 const work=f.turns.turn(id,key,new Blob(['whole source']),new AbortController().signal,p=>clips.push(p),p=>prefetched.push(p));await tick();
 assert.equal(f.reads,2);assert.deepEqual(clips,[]);assert.deepEqual(prefetched,[]);assert.equal(f.requests[0].body.get('stream_output'),null);
 delayed.resolve(completed);const result=await work;assert.equal(result.translated_text,full);assert.equal(result.audio_url,url+'/audio');assert.equal(result.streamed,undefined);assert.deepEqual(clips,[]);assert.equal(f.requests.filter(r=>r.method==='POST').length,1);
});
test('realtime whole output uses existing poll-only turn and never issues another STT POST',async()=>{
 const f=transport([prefix,completed]);const result=await f.turns.turn(id,key,null,new AbortController().signal,()=>{throw Error('No prefix');});assert.equal(result.audio_url,url+'/audio');assert.ok(f.requests.every(r=>r.method==='GET'));
});
function mediaFixture(duration){
 const held=deferred(),sources=[],requests=[],timers=new Map();let seq=0,decoded=null;
 const raw=Uint8Array.from({length:120},(_,i)=>i).buffer;
 const context={state:'running',currentTime:0,destination:{},decodeAudioData:async bytes=>{decoded=bytes;return {duration};},createBufferSource(){const source={connect(){},disconnect(){},stop(){source.stopped=true;},start(){source.started=true;}};sources.push(source);return source;}};
 const player=new TranslatorPlayback({getContext:()=>context,fetchAudio:async(path,options)=>{requests.push({path,options});return {ok:true,arrayBuffer:async()=>{await held.promise;return raw;}};},schedule:(fn,ms)=>{const n=++seq;timers.set(n,{fn,ms});return n;},clear:n=>timers.delete(n)});
 return {held,sources,requests,timers,raw,context,player,get decoded(){return decoded;}};
}
for(const duration of [.15,3.4,75,599])test('variable '+duration+'s utterance waits for every byte then starts one ordered complete buffer',async()=>{
 const f=mediaFixture(duration),controller=new AbortController();let ended=false;
 const work=f.player.play(url+'/audio',controller.signal,()=>true).then(()=>{ended=true;});await tick();assert.equal(f.sources.length,0);assert.equal(f.decoded,null);
 f.held.resolve();await tick();assert.equal(f.sources.length,1);assert.equal(f.sources[0].buffer.duration,duration);assert.deepEqual(new Uint8Array(f.decoded),new Uint8Array(f.raw));assert.equal(ended,false);assert.equal(f.requests.length,1);
 f.context.currentTime=duration;f.sources[0].onended();await work;assert.equal(ended,true);assert.equal(f.timers.size,0);assert.equal(f.sources.length,1);
});
test('End while the full audio body is incomplete releases its request and cannot play the late tail',async()=>{
 const f=mediaFixture(4),controller=new AbortController(),work=f.player.play(url+'/audio',controller.signal,()=>true),failed=assert.rejects(work,{name:'AbortError'});await tick();controller.abort();f.player.cancel();await failed;
 assert.equal(f.requests[0].options.signal.aborted,true);assert.equal(f.timers.size,0);f.held.resolve();await tick();assert.equal(f.sources.length,0);assert.equal(f.decoded,null);
});
test('failed full body cannot decode a prefix, replay or fetch a replacement',async()=>{
 const f=mediaFixture(4),work=f.player.play(url+'/audio',new AbortController().signal,()=>true),failed=assert.rejects(work,e=>e.code==='audio_fetch');await tick();f.held.reject(Error('Synthetic tail lost'));await failed;assert.equal(f.sources.length,0);assert.equal(f.decoded,null);assert.equal(f.requests.length,1);assert.equal(f.timers.size,0);
});
test('complete utterance keeps capture off until one full playback ends, including delayed output',async()=>{
 const delayed=deferred(),f=transport([prefix,()=>delayed.promise]),playing=deferred();let handlers,mics=0,now=0;const heard=[],results=[],timings=[];
 const api={start:async()=>({session_id:id}),turn:(...args)=>f.turns.turn(...args),end:async()=>{}};
 const capture={async start(h){handlers=h;mics++;},finalize(){mics=0;handlers.blob(new Blob(['source']));},cancel(){mics=0;}};
 const session=new TranslatorSession({api,capture,playback:{async play(audio,signal,current,onStarted){assert.equal(mics,0);heard.push(audio);onStarted();await playing.promise;},stop(){playing.resolve();},cancel(){playing.resolve();}},now:()=>now,key:()=> 'b'.repeat(32),onResult:r=>results.push(r.translated_text),onTiming:r=>timings.push(r)});
 await session.start({});handlers.level(.1);now=2000;handlers.level(0);await tick();assert.equal(session.state,'processing');assert.equal(mics,0);assert.deepEqual(heard,[]);assert.deepEqual(results,[]);
 delayed.resolve(completed);await tick();assert.deepEqual(heard,[url+'/audio']);assert.deepEqual(results,[full]);assert.equal(session.state,'playing');assert.equal(mics,0);playing.resolve();await tick();assert.equal(mics,1);assert.equal(session.state,'listening');assert.equal(f.requests.filter(r=>r.method==='POST').length,1);assert.equal(timings.some(t=>'interclip_gap_ms' in t),false);session.end();
});
test('confirmed whole-output failure recovers locally without playing a prefix or resubmitting speech',async()=>{
 const f=transport([{status:'FAILED',code:'processing_failed',recoverable:true,error:'Synthetic output failed'}]);let handlers,mics=0,now=0,checks=0,plays=0;
 const api={start:async()=>({session_id:id}),turn:(...args)=>f.turns.turn(...args),resume:async()=>{checks++;},end:async()=>{}};
 const capture={async start(h){handlers=h;mics++;},finalize(){mics=0;handlers.blob(new Blob(['source']));},cancel(){mics=0;}};
 const session=new TranslatorSession({api,capture,playback:{async play(){plays++;},stop(){},cancel(){}},now:()=>now,key:()=> 'b'.repeat(32)});await session.start({});handlers.level(.1);now=2000;handlers.level(0);await tick();assert.equal(session.state,'listening');assert.equal(mics,1);assert.equal(plays,0);assert.equal(checks,1);assert.equal(f.requests.filter(r=>r.method==='POST').length,1);session.end();
});
