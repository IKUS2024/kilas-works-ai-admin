// Synthetic transport/clock/player contracts only. No browser, mic or provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorTurns} from '../static/kilas_live_translator_api.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const id='a'.repeat(48),key='live-'+'b'.repeat(32),url='/kilas-translator/live/sessions/'+id+'/turns/'+key;
const part=(index,changes={})=>({index,duration_ms:600,audio_url:url+'/audio/segments/'+index,translated_text:index?'Hello. Goodbye.':'Hello.',...changes});
const progress=(status='PROCESSING',segments=[part(0)],changes={})=>({status,stream_output:'sentences-v1',total_segments:2,segments,translated_text:'Hello. Goodbye.',source_language:'id',target_language:'en',...changes});
function transport(sequence,{cancelStatus='CANCELLED'}={}){
 const requests=[],played=[];let now=0,reads=0;
 const api=new TranslatorTurns({csrf:'synthetic',now:()=>now,schedule:fn=>{queueMicrotask(fn);return 1;},clear:()=>{},json:async(path,options={})=>{
  requests.push({path,method:options.method||'GET',body:options.body});
  if(path.endsWith('/cancel'))return {status:cancelStatus};
  if(options.method==='POST')return {status:'PROCESSING'};
  const result=sequence[reads++];if(result instanceof Error)throw result;return typeof result==='function'?result():result;
 }});
 return {api,requests,played,setNow:n=>{now=n;},get reads(){return reads;},turn:(onSegment=async p=>played.push(p.index),signal=new AbortController().signal)=>api.turn(id,key,new Blob(['synthetic']),signal,onSegment)};
}

test('first validated sentence plays while second producer remains blocked; one POST and serial queue',async()=>{
 const later=deferred(),f=transport([progress(),()=>later.promise]);let finished=false;
 const p=f.turn(async clip=>{assert.equal(finished,clip.index===1);f.played.push(clip.index);});await tick();
 assert.deepEqual(f.played,[0]);assert.equal(finished,false);assert.equal(f.requests[0].body.get('stream_output'),'sentences-v1');
 finished=true;later.resolve(progress('COMPLETED',[part(0),part(1)]));assert.equal((await p).streamed,true);assert.deepEqual(f.played,[0,1]);assert.equal(f.requests.filter(r=>r.method==='POST').length,1);
});

test('repeated progress never replays a published clip and completion waits for final clip',async()=>{
 const f=transport([progress(),progress(),progress('COMPLETED',[part(0),part(1)])]);await f.turn();assert.deepEqual(f.played,[0,1]);assert.equal(f.reads,3);
});

test('foreign turn URL, duplicate index, oversized total duration and missing final clip reject before playback',async()=>{
 const bad=[progress('COMPLETED',[part(0,{audio_url:url.replace(id,'c'.repeat(48))+'/audio/segments/0'}),part(1)]),progress('COMPLETED',[part(0),part(1,{audio_url:url+'/audio/segments/0'})]),progress('COMPLETED',[part(1),part(0)]),progress('COMPLETED',[part(0,{duration_ms:400000}),part(1,{duration_ms:400000})])];
 for(const data of bad){const f=transport([data]);await assert.rejects(f.turn(),e=>e.code==='stream_invalid');assert.deepEqual(f.played,[]);assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,1);}
 const missing=transport([progress('COMPLETED',[part(0)])]);await assert.rejects(missing.turn(),e=>e.code==='stream_invalid');assert.deepEqual(missing.played,[]);
});

test('changed total or earlier clip identity is rejected without replaying heard output',async()=>{
 for(const next of [progress('COMPLETED',[part(0),part(1)],{total_segments:3}),progress('COMPLETED',[part(0,{duration_ms:700}),part(1)])]){
  const f=transport([progress(),next]);await assert.rejects(f.turn(),e=>e.code==='stream_invalid');assert.deepEqual(f.played,[0]);
 }
});

test('End during early playback aborts transport; late output cannot start the next clip',async()=>{
 const playing=deferred(),controller=new AbortController(),f=transport([progress(),progress('COMPLETED',[part(0),part(1)])]);
 const p=f.turn(async clip=>{f.played.push(clip.index);await playing.promise;},controller.signal),failed=assert.rejects(p,{name:'AbortError'});await tick();controller.abort();playing.resolve();await failed;
 assert.deepEqual(f.played,[0]);assert.equal(f.reads,1);assert.equal(f.requests.filter(r=>r.path.endsWith('/cancel')).length,0);
});

test('a failed early playback cannot return completed whole audio for replay or regeneration',async()=>{
 const f=transport([progress('COMPLETED',[part(0),part(1)],{audio_url:url+'/audio'})],{cancelStatus:'COMPLETED'});
 await assert.rejects(f.turn(async()=>{throw Object.assign(Error('Synthetic audio failure'),{code:'audio_stalled'});}),e=>e.segmentPlayback===true&&e.turnSettled===true);
 assert.equal(f.reads,1);assert.equal(f.requests.filter(r=>r.method==='POST'&&!r.path.endsWith('/cancel')).length,1);
});

test('long valid playback is excluded from backend timeout and fresh completion is read once',async()=>{
 const f=transport([progress(),progress('COMPLETED',[part(0),part(1)])]);await f.turn(async clip=>{f.played.push(clip.index);if(!clip.index)f.setNow(240000);});
 assert.deepEqual(f.played,[0,1]);assert.equal(f.reads,2);assert.equal(f.requests.some(r=>r.path.endsWith('/cancel')),false);
});

test('lost first response retrieves only saved completed whole output, never regenerates paid work',async()=>{
 const failure=Object.assign(Error('Lost first response'),{code:'request_timeout'}),f=transport([failure,progress('COMPLETED',[part(0),part(1)],{audio_url:url+'/audio'})],{cancelStatus:'COMPLETED'});
 const result=await f.turn();assert.equal(result.audio_url,url+'/audio');assert.equal(result.streamed,undefined);assert.deepEqual(f.played,[]);assert.equal(f.requests.filter(r=>r.method==='POST'&&!r.path.endsWith('/cancel')).length,1);
});

test('non-streaming completed fallback remains one playback without incremental callback',async()=>{
 const f=transport([{status:'COMPLETED',audio_url:url+'/audio',translated_text:'Single sentence.'}]);const result=await f.turn();assert.equal(result.streamed,undefined);assert.deepEqual(f.played,[]);
 const old=transport([{status:'COMPLETED',audio_url:url+'/audio'}]);await old.api.turn(id,key,new Blob(['synthetic']),new AbortController().signal);assert.equal(old.requests[0].body.get('stream_output'),null);
});

function sessionFixture({throwsTiming=false}={}){
 const later=deferred(),firstPlay=deferred(),f=transport([progress(),()=>later.promise]);let mics=0,handlers,now=0,producerDone=false,activePlayer=0;
 const timing=[],played=[],states=[];
 const api={start:async()=>({session_id:id}),turn:(...args)=>f.api.turn(...args),end:async()=>({})};
 const capture={start:async h=>{handlers=h;mics++;},finalize(){mics=0;handlers.blob(new Blob(['synthetic']));},cancel(){mics=0;}};
 const playback={async play(audio,signal,isCurrent,onStarted){assert.equal(mics,0);assert.equal(activePlayer,0);activePlayer++;assert.equal(isCurrent(),true);onStarted();played.push(audio);if(played.length===1)await firstPlay.promise;activePlayer--;},cancel(){firstPlay.resolve();},stop(){firstPlay.resolve();}};
 const session=new TranslatorSession({api,capture,playback,now:()=>now,key:()=> 'b'.repeat(32),onTiming:value=>{if(throwsTiming)throw Error('Diagnostics unavailable');timing.push(value);},onState:value=>states.push(value)});
 return {session,f,later,firstPlay,played,timing,states,get mics(){return mics;},get producerDone(){return producerDone;},level(r,time){now=time;handlers.level(r);},finishProducer(){producerDone=true;later.resolve(progress('COMPLETED',[part(0),part(1)]));}};
}

test('session starts first playback before producer completion, keeps mic off, then resumes after last clip',async()=>{
 const f=sessionFixture();await f.session.start({});f.level(.1,0);f.level(0,2000);await tick();assert.equal(f.played.length,1);assert.equal(f.producerDone,false);assert.equal(f.mics,0);assert.equal(f.session.state,'playing');
 f.firstPlay.resolve();await tick();assert.equal(f.mics,0);f.finishProducer();await tick();assert.equal(f.played.length,2);assert.equal(f.mics,1);assert.equal(f.session.state,'listening');
 assert.equal(f.timing[0].speech_end_to_submit_ms,2000);assert.equal(f.timing[1].speech_end_to_first_playback_ms,2000);assert.equal(f.timing.length,2);f.session.end();
});

test('End during first streamed clip stops media immediately and ignores late producer completion',async()=>{
 const f=sessionFixture();await f.session.start({});f.level(.1,0);f.level(0,2000);await tick();f.session.end();assert.equal(f.mics,0);assert.equal(f.session.state,'ended');f.finishProducer();await tick();assert.equal(f.played.length,1);assert.equal(f.mics,0);
});

test('diagnostic callback failure cannot block turn admission, playback or continuity',async()=>{
 const f=sessionFixture({throwsTiming:true});await f.session.start({});f.level(.1,0);f.level(0,2000);await tick();assert.equal(f.played.length,1);f.firstPlay.resolve();f.finishProducer();await tick();assert.equal(f.played.length,2);assert.equal(f.session.state,'listening');f.session.end();
});

test('definite unsupported stream chooses standard mode only for new speech in the same session',async()=>{
 const f=transport([{status:'FAILED',code:'stream_unavailable',recoverable:false,error:'Use standard for new speech'},{status:'COMPLETED',audio_url:url+'/audio'}]);
 await assert.rejects(f.turn(),e=>e.code==='stream_unavailable'&&e.turnSettled&&!e.recoverable);assert.equal(f.requests.filter(r=>r.method==='POST').length,1);assert.equal(f.requests[0].body.get('stream_output'),'sentences-v1');
 await f.api.turn(id,'live-'+'c'.repeat(32),new Blob(['new synthetic utterance']),new AbortController().signal,async p=>f.played.push(p.index));
 const posts=f.requests.filter(r=>r.method==='POST');assert.equal(posts.length,2);assert.equal(posts[1].body.get('stream_output'),null);assert.notEqual(posts[0].path,posts[1].path);assert.deepEqual(f.played,[]);
});

test('quota/auth/transport failures never select unsupported-stream fallback for new speech',async()=>{
 for(const code of ['provider_credit_exhausted','provider_billing_unverified','provider_transport']){
  const f=transport([{status:'FAILED',code,recoverable:false,error:'Synthetic failure'},{status:'COMPLETED',audio_url:url+'/audio'}]);await assert.rejects(f.turn());
  await f.api.turn(id,'live-'+'c'.repeat(32),new Blob(['new speech']),new AbortController().signal,async()=>{});
  assert.equal(f.requests.filter(r=>r.method==='POST')[1].body.get('stream_output'),'sentences-v1');
 }
});

test('lost acknowledgement followed by confirmed unsupported failure also disables only future streaming',async()=>{
 const f=transport([Object.assign(Error('Lost acknowledgement'),{code:'request_timeout'}),{status:'FAILED',code:'stream_unavailable',recoverable:false,error:'Unavailable'},{status:'COMPLETED',audio_url:url+'/audio'}],{cancelStatus:'FAILED'});
 await assert.rejects(f.turn(),e=>e.code==='stream_unavailable'&&e.turnSettled);await f.api.turn(id,'live-'+'c'.repeat(32),new Blob(['fresh speech']),new AbortController().signal,async()=>{});
 const posts=f.requests.filter(r=>r.method==='POST'&&!r.path.endsWith('/cancel'));assert.equal(posts.length,2);assert.equal(posts[1].body.get('stream_output'),null);assert.notEqual(posts[0].path,posts[1].path);
});


test('stream protocol cannot switch to whole completion after a heard prefix',async()=>{
 const f=transport([progress(),{status:'COMPLETED',audio_url:url+'/audio',translated_text:'Hello. Goodbye.'}],{cancelStatus:'COMPLETED'});
 await assert.rejects(f.turn(),e=>e.code==='stream_invalid');assert.deepEqual(f.played,[0]);assert.equal(f.reads,2);
});

test('stream full text, cumulative prefixes and distinct language pair are stable and complete',async()=>{
 for(const next of [progress('COMPLETED',[part(0),part(1)],{translated_text:'Hello. Goodbye. More.'}),progress('COMPLETED',[part(0),part(1,{translated_text:'Goodbye.'})]),progress('COMPLETED',[part(0),part(1)],{target_language:'id'}),progress('COMPLETED',[part(0),part(1)],{source_language:'fr'})]){
  const f=transport([progress(),next]);await assert.rejects(f.turn(),e=>e.code==='stream_invalid');assert.deepEqual(f.played,[0]);
 }
});

test('long multilingual text plays every segment once; empty temporary queue and delayed final playback are unfinished',async()=>{
 const texts=['你好。','مرحبا؟ ','Unpunctuated tail '+ 'words '.repeat(300)],full=texts.join(''),last=deferred(),produced=deferred(),seen=[];let done=false;
 const clips=texts.map((_,index)=>part(index,{translated_text:texts.slice(0,index+1).join('')}));
 const meta=(status,segments)=>progress(status,segments,{total_segments:3,translated_text:full,source_language:'zh',target_language:'ar'});
 const f=transport([meta('PROCESSING',[]),meta('PROCESSING',clips.slice(0,2)),()=>produced.promise]);
 const turn=f.turn(async p=>{seen.push(p.translated_text);if(p.index===2)await last.promise;}).then(r=>{done=true;return r;});await tick();assert.equal(done,false);assert.equal(seen.length,2);
 produced.resolve(meta('COMPLETED',clips));await tick();assert.equal(done,false);assert.equal(seen.length,3);last.resolve();assert.equal((await turn).streamed,true);assert.equal(seen.at(-1),full);
});

test('provider failure after a played prefix never reports completed or returns whole audio',async()=>{
 const f=transport([progress(),{status:'FAILED',code:'speech_failed',recoverable:true,error:'Synthetic partial failure'}]);
 await assert.rejects(f.turn(),e=>e.code==='speech_failed'&&e.turnSettled);assert.deepEqual(f.played,[0]);assert.equal(f.requests.filter(r=>r.method==='POST').length,1);
});


test('mixed protocol after first heard clip pauses session without whole replay or mic resumption',async()=>{
 const f=sessionFixture();await f.session.start({});f.level(.1,0);f.level(0,2000);await tick();f.firstPlay.resolve();await tick();
 f.later.resolve({status:'COMPLETED',audio_url:url+'/audio',translated_text:'Hello. Goodbye.'});await tick();
 assert.equal(f.played.length,1);assert.equal(f.mics,0);assert.equal(f.session.state,'paused');f.session.end();
});
