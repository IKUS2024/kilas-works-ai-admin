// Synthetic PCM, transport and capture only; no browser/provider/microphone.
import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';

const INPUT_BYTES=59*32000,QUEUE_BYTES=8*32000;
const tick=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
function clock(){
 let time=0,next=0;const timers=new Map();
 return {now:()=>time,schedule(fn,ms){const id=++next;timers.set(id,{fn,at:time+ms});return id;},clear:id=>timers.delete(id),
  advance(ms){time+=ms;for(const [id,timer] of [...timers])if(timer.at<=time){timers.delete(id);timer.fn();}},timers};
}
function pattern(length,seed=0){return Uint8Array.from({length},(_,index)=>(seed+index*17)%256);}
const audioFrame=(index,seed=0)=>({index,type:'audio',generation:0,pcm:Buffer.from(pattern(480,seed)).toString('base64')});
const completed=(frames=[],total=frames.length)=>({status:'COMPLETED',frames,next_index:frames.at(-1)?.index+1||0,
 translated_text:'Synthetic bounded output.',output_closed:true,total_frames:total,
 completion_kind:'bounded_drain',tail_confirmed:false,tail_code:'gemini_tail_unconfirmed'});

function fixture({turnPost=()=>null,chunkPost=()=>null}={}){
 const c=clock(),requests=[],polls=[],played=[],errors=[],warnings=[],states=[],captures=[];
 const counts={admissions:0,turns:0,captureStarts:0,captureCancels:0,resets:0,cancels:0,drains:0};
 let handlers,mic=false,key=0;
 const capture={async start(value){handlers=value;captures.push(value);counts.captureStarts++;mic=true;value.ready();},
  finalize(){throw Error('Continuous renewal must keep capture alive');},cancel(){counts.captureCancels++;mic=false;}};
 const player={reset(){counts.resets++;},cancel(){counts.cancels++;},
  push(raw,scope){played.push({raw:raw.slice(),scope,mic});},drain(){counts.drains++;return new Promise(()=>{});}};
 const json=async(url,options={})=>{
  const request={url,...options};requests.push(request);
  if(url==='/kilas-translator/live/gemini/sessions'){
   const session_id=(++counts.admissions).toString(16).padStart(48,'0');return {session_id,input_mode:'gemini-live-v1'};
  }
  if(url.endsWith('/end'))return {status:'ENDED'};
  const chunk=url.match(/\/chunks\/(\d+)$/);
  if(chunk){const pending=chunkPost(request,Number(chunk[1]));return pending||{accepted_index:Number(chunk[1])};}
  if(url.endsWith('/finish'))return {status:'DRAINING'};
  if(options.method==='POST'){
   counts.turns++;const pending=turnPost(request,counts.turns);return pending||{input_mode:'gemini-live-v1'};
  }
  const result=deferred();polls.push({...request,...result});return result.promise;
 };
 const session=new GeminiSession({...c,json,capture,player,prepare:async()=>{},csrf:'synthetic',
  key:()=> (++key).toString(16).padStart(32,'0'),onState:value=>states.push(value),
  onError:error=>errors.push(error),onWarning:warning=>warnings.push(warning)});
 const turnRequests=()=>requests.filter(request=>request.method==='POST'&&/\/turns\/live-[a-f0-9]{32}$/.test(request.url));
 const uploads=path=>requests.filter(request=>request.url.startsWith(path+'/chunks/'));
 const uploaded=async path=>Buffer.concat(await Promise.all(uploads(path).map(async request=>Buffer.from(await request.body.get('pcm').arrayBuffer()))));
 return {session,c,requests,polls,played,errors,warnings,states,captures,counts,turnRequests,uploads,uploaded,
  get handlers(){return handlers;},get mic(){return mic;}};
}

async function send(f,length,{seed=0,mutate=false}={}){
 const expected=[];
 for(let offset=0;offset<length;offset+=6400){
  const bytes=pattern(Math.min(6400,length-offset),seed+offset/2);expected.push(Buffer.from(bytes));
  f.handlers.pcm(bytes);if(mutate)bytes.fill(255);
  // Give accepted uploads a chance to leave the bounded input queue.
  if((offset/6400)%16===15)await tick();
 }
 await tick();return Buffer.concat(expected);
}

test('59 seconds of samples split one PCM frame exactly and renew the same logical session without replay',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());
 const prefix=await send(f,INPUT_BYTES-3200,{seed:11,mutate:true});
 const first=f.turnRequests()[0].url;
 assert.equal(f.c.now(),0);assert.equal(f.requests.some(request=>request.url.endsWith('/finish')),false);
 const crossing=pattern(6400,73),owned=Buffer.from(crossing);f.handlers.pcm(crossing);crossing.fill(255);await tick();
 assert.equal(f.requests.filter(request=>request.url===first+'/finish').length,1);
 assert.deepEqual(await f.uploaded(first),Buffer.concat([prefix,owned.subarray(0,3200)]));
 assert.equal(f.session.queuedBytes,3200);assert.equal(f.turnRequests().length,1);

 f.polls[0].resolve(completed([audioFrame(0)]));await tick();
 const turns=f.turnRequests();assert.equal(turns.length,2);assert.notEqual(turns[1].url,first);
 assert.equal(turns[1].url.split('/turns/')[0],first.split('/turns/')[0]);
 assert.deepEqual(await f.uploaded(turns[1].url),owned.subarray(3200));
 assert.equal(f.counts.admissions,1);assert.equal(f.counts.captureStarts,1);assert.equal(f.mic,true);
 assert.equal(f.counts.resets,1);assert.equal(f.counts.cancels,0);assert.equal(f.counts.drains,0);
 assert.equal(f.requests.some(request=>request.url.endsWith('/end')),false);
 assert.equal(f.warnings.length,1);assert.equal(f.warnings[0].tail_confirmed,false);assert.deepEqual(f.errors,[]);
});

test('terminal total_frames gates the successor until every retained output page is consumed',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());
 await send(f,6400);f.session.finish();await tick();const first=f.turnRequests()[0].url;
 const carry=await send(f,6400,{seed:43,mutate:true});
 f.polls[0].resolve(completed([audioFrame(0,1)],3));await tick();
 assert.equal(f.session.cursor,1);assert.equal(f.turnRequests().length,1);assert.equal(f.mic,true);
 f.c.advance(200);await tick();assert.equal(f.polls[1].url,first+'?after=1');
 f.polls[1].resolve(completed([audioFrame(1,2)],3));await tick();
 assert.equal(f.session.cursor,2);assert.equal(f.turnRequests().length,1);
 f.c.advance(200);await tick();assert.equal(f.polls[2].url,first+'?after=2');
 f.polls[2].resolve(completed([audioFrame(2,3)],3));await tick();

 assert.equal(f.turnRequests().length,2);assert.equal(f.played.length,3);
 assert.deepEqual(f.played.map(value=>Buffer.from(value.raw)),[1,2,3].map(seed=>Buffer.from(pattern(480,seed))));
 assert.deepEqual(await f.uploaded(f.turnRequests()[1].url),carry);
 assert.equal(f.counts.drains,0);assert.equal(f.counts.resets,1);assert.equal(f.counts.captureStarts,1);
 assert.equal(f.requests.some(request=>request.url.endsWith('/end')),false);assert.deepEqual(f.errors,[]);
});

test('old unacknowledged input and owned carry share one eight-second bound and transfer once',async t=>{
 const upload=deferred();let held=false;
 const f=fixture({chunkPost:(_request,index)=>{if(!held&&index===0){held=true;return upload.promise;}return null;}});
 t.after(()=>f.session.end());await f.session.start(new FormData());
 const oldFirst=pattern(6400,5),oldLast=pattern(122,9),oldExpected=Buffer.concat([Buffer.from(oldFirst),Buffer.from(oldLast)]);
 f.handlers.pcm(oldFirst);oldFirst.fill(255);await tick();f.handlers.pcm(oldLast);oldLast.fill(255);f.session.finish();await tick();
 const first=f.turnRequests()[0].url,carry=await send(f,QUEUE_BYTES-oldExpected.length,{seed:61,mutate:true});
 assert.equal(f.session.queuedBytes,QUEUE_BYTES);assert.equal(f.turnRequests().length,1);
 assert.throws(()=>f.session.push(new Uint8Array(2),f.session.version),error=>error.code==='gemini_backlog');
 assert.equal(f.session.queuedBytes,QUEUE_BYTES);assert.equal(f.requests.some(request=>request.url===first+'/finish'),false);
 upload.resolve({accepted_index:0});await tick();
 assert.deepEqual(await f.uploaded(first),oldExpected);assert.equal(f.session.queuedBytes,carry.length);
 assert.equal(f.requests.filter(request=>request.url===first+'/finish').length,1);
 f.polls[0].resolve(completed());await tick();f.session.finish();await tick();
 const second=f.turnRequests()[1].url;assert.notEqual(second,first);
 assert.deepEqual(await f.uploaded(second),carry);assert.equal(f.session.queuedBytes,0);
 assert.equal(f.uploads(first).length,2);assert.deepEqual(f.errors,[]);
});

test('End during successor admission fences its late response and callbacks from an explicitly restarted session',async t=>{
 const successor=deferred(),f=fixture({turnPost:(_request,index)=>index===2?successor.promise:null});
 t.after(()=>f.session.end());await f.session.start(new FormData());const oldHandlers=f.handlers,oldId=f.session.id;
 await send(f,6400);f.session.finish();await tick();await send(f,6400,{seed:17});
 f.polls[0].resolve(completed());await tick();assert.equal(f.turnRequests().length,2);
 const oldSuccessor=f.turnRequests()[1].url;assert.equal(f.uploads(oldSuccessor).length,0);
 await f.session.end();assert.equal(f.mic,false);
 assert.equal(f.requests.filter(request=>request.url.endsWith('/'+oldId+'/end')).length,1);
 await f.session.start(new FormData());await send(f,6400,{seed:29});const newId=f.session.id,newTurn=f.turnRequests()[2].url;
 assert.notEqual(newId,oldId);assert.equal(f.session.active,true);

 successor.resolve({input_mode:'gemini-live-v1'});oldHandlers.pcm(pattern(6400,97));oldHandlers.blob(null);oldHandlers.error(Error('late capture error'));await tick();
 assert.equal(f.session.id,newId);assert.equal(f.session.active,true);assert.equal(f.mic,true);
 assert.equal(f.counts.admissions,2);assert.equal(f.turnRequests().length,3);
 assert.equal(f.uploads(oldSuccessor).length,0);assert.equal(f.polls.some(poll=>poll.url.startsWith(oldSuccessor)),false);
 assert.equal(f.uploads(newTurn).length,1);
 assert.equal(f.requests.filter(request=>request.url.endsWith('/'+oldId+'/end')).length,1);
 assert.equal(f.requests.some(request=>request.url.endsWith('/'+newId+'/end')),false);assert.deepEqual(f.errors,[]);
});

test('four clock-based renewals keep one logical session and lazily admit each confirmed successor',async t=>{
 const f=fixture();t.after(()=>f.session.end());await f.session.start(new FormData());
 const ownedId=f.session.id,ticket=f.session.version;
 for(let index=0;index<4;index++){
  await send(f,6400,{seed:index+31});const path=f.turnRequests()[index].url;
  assert.equal(f.turnRequests().length,index+1);
  f.c.advance(58999);await tick();
  assert.equal(f.requests.some(request=>request.url===path+'/finish'),false);
  f.c.advance(1);await tick();
  const finishes=f.requests.filter(request=>request.url===path+'/finish');
  assert.equal(finishes.length,1);assert.equal(finishes[0].body.get('count'),'1');
  assert.equal(f.mic,true);assert.equal(f.counts.captureStarts,1);
  f.polls[index].resolve({...completed([audioFrame(0,index+41)]),completion_kind:'turn_complete',tail_confirmed:true});await tick();
  assert.equal(f.session.turn,null);assert.equal(f.session.active,true);
  assert.equal(f.session.id,ownedId);assert.equal(f.session.version,ticket);
  assert.equal(f.turnRequests().length,index+1); // Silence does not reserve a successor.
  assert.equal(f.warnings.length,0);
 }
 await send(f,6400,{seed:99});
 const turns=f.turnRequests();assert.equal(turns.length,5);
 assert.equal(new Set(turns.map(request=>request.url)).size,5);
 assert.ok(turns.every(request=>request.url.includes('/sessions/'+ownedId+'/turns/')));
 assert.equal(f.c.now(),4*59000);assert.equal(f.counts.admissions,1);assert.equal(f.counts.captureStarts,1);
 assert.equal(f.counts.resets,1);assert.equal(f.counts.cancels,0);assert.equal(f.counts.drains,0);
 assert.equal(f.played.length,4);assert.equal(new Set(f.played.map(value=>value.scope)).size,4);
 assert.equal(f.requests.some(request=>request.url.endsWith('/end')),false);assert.equal(f.mic,true);
 assert.deepEqual(f.warnings,[]);assert.deepEqual(f.errors,[]);
});

test('a successor budget rejection stops capture without replay and drains accepted audio before error and End',async t=>{
 const drained=deferred(),budget=Object.assign(Error('budget_limit'),{code:'budget_limit'});
 const f=fixture({turnPost:(_request,index)=>index===2?Promise.reject(budget):null});
 t.after(()=>f.session.end());
 f.session.player.drain=()=>{f.counts.drains++;return drained.promise;};
 await f.session.start(new FormData());const id=f.session.id;
 await send(f,6400,{seed:7});f.session.finish();await tick();await send(f,6400,{seed:71});
 f.polls[0].resolve({...completed([audioFrame(0,83)]),completion_kind:'turn_complete',tail_confirmed:true});await tick();

 assert.equal(f.turnRequests().length,2);const successor=f.turnRequests()[1].url;
 assert.equal(f.mic,false);assert.ok(f.counts.captureCancels>0);assert.equal(f.session.stopping,true);
 assert.equal(f.session.controller.signal.aborted,true);assert.equal(f.states.at(-1),'draining');
 assert.equal(f.counts.drains,1);assert.equal(f.counts.cancels,0);assert.equal(f.counts.resets,1);
 assert.deepEqual(f.played.map(value=>Buffer.from(value.raw)),[Buffer.from(pattern(480,83))]);
 assert.equal(f.session.active,true);assert.equal(f.session.id,id);assert.deepEqual(f.errors,[]);
 assert.equal(f.requests.some(request=>request.url.endsWith('/end')),false);
 const stoppedRequests=f.requests.length;
 f.handlers.pcm(pattern(6400,91));f.handlers.error(Error('late capture callback'));f.session.finish();f.c.advance(59000);await tick();
 assert.equal(f.requests.length,stoppedRequests);assert.equal(f.turnRequests().length,2);
 assert.equal(f.uploads(successor).length,0);assert.equal(f.polls.length,1);assert.equal(f.counts.admissions,1);
 assert.deepEqual(f.errors,[]);assert.equal(f.counts.cancels,0);

 drained.resolve();await tick();
 assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'budget_limit');
 assert.equal(f.session.active,false);assert.equal(f.session.id,null);assert.equal(f.counts.cancels,1);
 assert.equal(f.requests.filter(request=>request.url.endsWith('/'+id+'/end')).length,1);
 assert.equal(f.turnRequests().length,2);assert.equal(f.uploads(successor).length,0);assert.equal(f.played.length,1);
 assert.deepEqual(f.warnings,[]);
});
