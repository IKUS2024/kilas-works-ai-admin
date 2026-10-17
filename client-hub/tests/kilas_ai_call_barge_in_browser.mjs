// Real Chromium getUserMedia -> CallCapture worklet -> CallSession -> CallPlayer.
// Only the microphone device and call transport are synthetic. No provider IO.
// This cannot establish physical microphone, speaker or acoustic echo quality.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url),{chromium}=require('playwright');
const root=fileURLToPath(new URL('../',import.meta.url));
const httpReady=[];
const server=createServer(async(req,res)=>{
 try{
  const path=new URL(req.url,'http://localhost').pathname;
  if(req.method==='POST'&&/^\/kilas-ai\/call\/[bc]{32}\/ready$/.test(path)){
   const body=[];for await(const part of req)body.push(part);
   httpReady.push({path,contentType:req.headers['content-type'],csrf:req.headers['x-csrf-token'],
    json:JSON.parse(Buffer.concat(body).toString('utf8'))});
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({ready:true,synthetic:true}));return;
  }
  if(path==='/'){
   res.setHeader('Content-Type','text/html');
   res.end('<!doctype html><html lang="id"><button id="start">Start</button></html>');return;
  }
  if(!/^\/static\/[a-z0-9_]+\.mjs$/.test(path)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type','text/javascript');res.end(await readFile(root+path));
 }catch{res.writeHead(500);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,
  args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
   '--use-file-for-fake-audio-capture='+root+'tests/fixtures/ai_call_synthetic/id-first.wav',
   '--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage(),pageErrors=[],origin='http://127.0.0.1:'+server.address().port;
 page.on('pageerror',error=>pageErrors.push(error.message));
 await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 await page.goto(origin);
 const result=await page.evaluate(async()=>{
  const [{CallCapture},{CallPlayer},{CallSession},{prepareCallPcm},{requestCallJSON}]=await Promise.all([
   import('/static/kilas_ai_call_capture.mjs'),import('/static/kilas_ai_call_player.mjs'),
   import('/static/kilas_ai_call_engine.mjs'),import('/static/kilas_ai_call_pcm.mjs'),
   import('/static/kilas_ai_call_api.mjs')]);
  const check=(value,message)=>{if(!value)throw Error(message);};
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const waitFor=async(test,label,ms=12000)=>{
   const until=performance.now()+ms;
   while(!test()){if(performance.now()>until)throw Error('Timed out: '+label);await delay(10);}
  };
  const bounded=async(promise,label,ms=12000)=>{
   let timer;
   try{return await Promise.race([promise,new Promise((_,reject)=>{
    timer=setTimeout(()=>reject(Error('Timed out: '+label)),ms);
   })]);}finally{clearTimeout(timer);}
  };
  const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
  const concat=arrays=>{
   const raw=new Uint8Array(arrays.reduce((n,value)=>n+value.length,0));let at=0;
   for(const value of arrays){raw.set(value,at);at+=value.length;}return raw;
  };
  const same=(a,b)=>a.length===b.length&&a.every((value,index)=>value===b[index]);
  const rms=raw=>{
   const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);let energy=0;
   for(let i=0;i<raw.length;i+=2)energy+=(view.getInt16(i,true)/32768)**2;
   return Math.sqrt(energy/(raw.length/2));
  };
  const modelPcm=()=>{
   const bytes=new Uint8Array(9600),view=new DataView(bytes.buffer);
   for(let i=0;i<4800;i++)view.setInt16(2*i,Math.round(1200*Math.sin(2*Math.PI*440*i/24000)),true);
   return btoa(String.fromCharCode(...bytes));
  };
  const encoded=modelPcm(),context=new AudioContext({sampleRate:48000}),sources=[];
  await context.resume();
  // Instrument actual AudioBufferSourceNodes; native stop/start still execute.
  const createSource=context.createBufferSource.bind(context);
  context.createBufferSource=()=>{
   const node=createSource(),record={node,starts:0,stops:0,disconnects:0};
   const start=node.start.bind(node),stop=node.stop.bind(node),disconnect=node.disconnect.bind(node);
   node.start=(...args)=>{record.starts++;record.at=args[0]??context.currentTime;return start(...args);};
   node.stop=(...args)=>{record.stops++;return stop(...args);};
   node.disconnect=(...args)=>{record.disconnects++;return disconnect(...args);};sources.push(record);return node;
  };
  const makeFixture=({holdAdmission=false,holdChunk=null,providerReady=false,id='b'.repeat(32)}={})=>{
   const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
   const observed=[],chunks=[],calls=[],readyCalls=[],states=[],errors=[],captions=[],citations=[],frames=[];
   const admission=deferred(),chunkGate=deferred();let session,pendingPoll=null;
   const f={capture,observed,chunks,calls,readyCalls,states,errors,captions,citations,frames,admission,chunkGate,cancellations:[],
    providerReady,holdPoll:false,providerReadyCaptureCount:null,modelState:'LISTENING',admissionRequested:false,
    get pendingPoll(){return pendingPoll;}};
   const captureStart=capture.start.bind(capture);
   capture.start=callbacks=>captureStart({...callbacks,pcm:raw=>{
    const speaking=session.speaking,unity=speaking||session.echoGuard;
    observed.push({raw:raw.slice(),expected:(unity?raw:prepareCallPcm(raw)).slice(),speaking,rms:rms(raw)});
    callbacks.pcm(raw);
   }});
   const player=new CallPlayer({getContext:()=>context,onError:error=>errors.push(error.code)});
   f.player=player;
   const cancel=player.cancel.bind(player);
   player.cancel=()=>{
    const event={pendingSamples:player.player.pendingSamples,at:context.currentTime,contextState:context.state,
     nodes:[...player.player.nodes].map(node=>{
     const record=sources.find(value=>value.node===node);return {record,stops:record.stops,disconnects:record.disconnects};
    })};
    cancel();f.cancellations.push(event);
   };
   const snapshot=after=>({state:f.modelState,provider_ready:f.providerReady,
    frames:frames.slice(after),next_index:frames.length,total_frames:frames.length});
   const request=async(path,args={})=>{
    calls.push({path,method:args.method||'GET',ended:session.state==='ended'});
    if(path==='/kilas-ai/call/readiness')return {available:true};
    if(path==='/kilas-ai/call/'+id&&args.method==='POST'){
     f.admissionRequested=true;if(holdAdmission)await admission.promise;return {call_id:id};
    }
    if(path.endsWith('/end'))return {ended:true};
    if(path.endsWith('/ready')){
     readyCalls.push({json:args.json,acknowledged:concat(chunks.filter(chunk=>chunk.acknowledged).map(chunk=>chunk.raw))});
     return requestCallJSON(path,{csrf:'synthetic-csrf',...args});
    }
    const match=path.match(/\/chunks\/(\d+)$/);
    if(match){
     check(args.method==='POST'&&args.body instanceof Uint8Array,'CallInput must submit PCM bytes');
     const index=Number(match[1]),chunk={index,raw:args.body.slice(),acknowledged:false};chunks.push(chunk);
     if(index===holdChunk)await chunkGate.promise;
     chunk.acknowledged=true;return {accepted_index:index};
    }
    const url=new URL(path,location.origin);
    check(url.pathname==='/kilas-ai/call/'+id&&url.searchParams.has('after'),'Unexpected synthetic request '+path);
    const after=Number(url.searchParams.get('after'));
    if(f.providerReady&&f.providerReadyCaptureCount===null)f.providerReadyCaptureCount=observed.length;
    if(f.holdPoll){pendingPoll=deferred();return pendingPoll.promise;}
    return snapshot(after);
   };
   session=new CallSession({request,capture,player,getLanguage:()=> 'id',key:()=>id,
    prepare:()=>context.resume(),onState:value=>states.push(value),onError:code=>errors.push(code),
    onText:value=>captions.push(value),onSources:value=>citations.push(value)});
   Object.assign(f,{session,started:session.start(),snapshot,
    inject(items){
     for(const item of items){frames.push({...item,index:frames.length});
      if(item.type==='audio')f.modelState='SPEAKING';else if(item.type==='reset')f.modelState='LISTENING';}
    }});
   return f;
  };
  const capturedBytes=f=>f.observed.reduce((n,frame)=>n+frame.raw.length,0);
  const assertCapturedPrefix=async(f,label)=>{
   const count=f.observed.length,expected=concat(f.observed.slice(0,count).map(frame=>frame.expected));
   f.session.input.flush();await bounded(f.session.input.chain,label+' input ACKs');
   const actual=concat(f.chunks.map(chunk=>chunk.raw));
   check(same(actual.subarray(0,expected.length),expected),label+': captured PCM lost, reordered or replaced');
   check(f.chunks.every((chunk,index)=>chunk.index===index&&chunk.raw.length<=16000),label+': invalid chunk sequence');
   return {frames:count,bytes:expected.length};
  };
  const main=makeFixture({holdAdmission:true,holdChunk:1});
  try{
   await waitFor(()=>main.admissionRequested&&main.observed.length>=3,'capture during held admission');
   check(main.chunks.length===0&&main.readyCalls.length===0,'Audio or readiness escaped before admission');
   const preAdmissionFrames=main.observed.length;main.admission.resolve();
   await waitFor(()=>main.chunks.length>=2&&main.observed.length>=6,'buffered microphone after admission');
   check(main.readyCalls.length===0,'Readiness sent before provider_ready');
   check(same(main.chunks[0].raw,main.observed[0].expected),'The first worklet frame was not the first submitted PCM');
   main.providerReady=true;
   await waitFor(()=>main.providerReadyCaptureCount!==null&&main.session.readyRequested,'provider readiness while PCM ACK is held');
   check(main.readyCalls.length===0,'Readiness overtook buffered input ACK');main.chunkGate.resolve();
   await waitFor(()=>main.session.readyAcknowledged,'readiness after buffered PCM');
   const ready=main.readyCalls[0],beforeReady=concat(main.observed.slice(0,main.providerReadyCaptureCount).map(frame=>frame.expected));
   check(same(ready.acknowledged.subarray(0,beforeReady.length),beforeReady),'Readiness preceded the first buffered utterance');
   check(ready.json.language==='id'&&ready.json.user_started_speaking===true,'Incorrect language or first-speech greeting suppression');
   // id-first.wav is 6.364 seconds: observe more than its full first utterance.
   await waitFor(()=>capturedBytes(main)>=7*32000,'complete first synthetic utterance');
   const first=await assertCapturedPrefix(main,'First utterance');
   check(main.observed.some(frame=>frame.rms>.001),'Synthetic microphone never delivered speech');
   const speakingStart=main.observed.length;
   main.inject([{type:'sources',citations:[{url:'https://example.org/synthetic',title:'Synthetic fixture'}]},
    ...Array.from({length:15},()=>({type:'audio',pcm:encoded})),{type:'text',text:'Synthetic model answer'},
    {type:'turn_complete'}]);
   await waitFor(()=>main.player.player.nodes.size>=4&&main.session.state==='speaking','scheduled model playback');
   await waitFor(()=>main.observed.slice(speakingStart).filter(frame=>frame.speaking).length>=5,'microphone during Speaking');
   const speaking=main.observed.slice(speakingStart).filter(frame=>frame.speaking);
   check(speaking.filter(frame=>frame.rms>.0005).length>=2,'Speaking microphone was silent or replaced');
   const acrossPlayback=await assertCapturedPrefix(main,'Microphone across model audio start');
   check(main.captions.at(-1)==='Synthetic model answer'&&main.citations.at(-1).length===1,
    'Scheduled reset fixture did not populate captions and sources');
   const generation=main.session.playVersion,cancellationsBefore=main.cancellations.length;
   check(main.player.player.nodes.size>0&&main.player.player.pendingSamples>0,'Reset did not exercise scheduled audio');
   main.inject([{type:'reset'}]);
   await waitFor(()=>main.session.playVersion>generation&&main.session.state==='listening','native reset');
   check(main.cancellations.length===cancellationsBefore+1,'Native reset did not cancel CallPlayer');
   const cancellation=main.cancellations.at(-1);
   check(cancellation.nodes.length>0&&cancellation.nodes.every(({record,stops,disconnects})=>record.stops>stops&&record.disconnects>disconnects),
    'Native reset left a scheduled AudioBufferSourceNode running');
   check(cancellation.contextState==='running'&&cancellation.nodes.some(({record})=>record.at>cancellation.at),
    'Native reset did not exercise future audio scheduled on a running context');
   check(context.state==='running'&&main.player.player.pendingSamples===0&&main.player.player.nodes.size===0&&main.player.player.queue.length===0,
    'Native reset retained scheduled or queued samples');
   check(main.captions.at(-1)===''&&main.citations.at(-1).length===0,'Native reset retained old captions or sources');
   check(main.errors.length===0,'Old playback checkpoint rejection ended the reset session');
   const scheduledReset={stoppedNodes:cancellation.nodes.length,pendingSamplesBefore:cancellation.pendingSamples,
    pendingSamplesAfter:main.player.player.pendingSamples};
   // A short response remains queued behind CallPlayer's real prefill timer.
   main.inject([{type:'audio',pcm:encoded},{type:'text',text:'Queued answer'}]);
   await waitFor(()=>main.player.waiting&&main.player.player.queue.length>0,'queued model prefill');
   const queuedBefore=main.player.player.pendingSamples,startsBefore=sources.length,queuedGeneration=main.session.playVersion;
   check(main.player.player.nodes.size===0,'Short response bypassed prefill fixture');
   main.inject([{type:'reset'}]);
   await waitFor(()=>main.session.playVersion>queuedGeneration&&main.session.state==='listening','reset queued model prefill');
   check(main.player.player.pendingSamples===0&&main.player.player.queue.length===0&&!main.player.waiting,
    'Native reset retained prefill audio');
   await delay(1350);check(sources.length===startsBefore,'Cancelled prefill scheduled audio after reset');
   const preserved=await assertCapturedPrefix(main,'Microphone through scheduled and queued resets');
   check(main.readyCalls.length===1,'Readiness was repeated across polls or resets');
   // End while actual audio is scheduled and an intentionally late poll is pending.
   main.inject([...Array.from({length:8},()=>({type:'audio',pcm:encoded})),{type:'text',text:'End fixture'}]);
   await waitFor(()=>main.player.player.nodes.size>=4,'audio scheduled before End');
   main.holdPoll=true;await waitFor(()=>main.pendingPoll,'poll held across End');
   const tracks=main.capture.stream.getTracks(),atEnd={frames:main.observed.length,chunks:main.chunks.length,
    ready:main.readyCalls.length,sources:sources.length},endNodes=[...main.player.player.nodes];
   main.session.end();
   main.pendingPoll.resolve({state:'SPEAKING',provider_ready:true,frames:[
    {index:main.session.cursor,type:'audio',pcm:encoded},{index:main.session.cursor+1,type:'text',text:'Late audio'}],
    next_index:main.session.cursor+2,total_frames:main.session.cursor+2});
   await bounded(main.started,'session ends after late poll');await delay(450);
   check(main.session.state==='ended'&&tracks.every(track=>track.readyState==='ended'),'End left microphone tracks alive');
   check(main.observed.length===atEnd.frames&&main.chunks.length===atEnd.chunks&&main.readyCalls.length===atEnd.ready,
    'Microphone PCM or readiness escaped after End');
   check(sources.length===atEnd.sources&&endNodes.every(node=>sources.find(record=>record.node===node).stops>0),
    'End left audio playing or accepted late poll audio');
   check(main.player.player.pendingSamples===0&&main.player.player.queue.length===0&&main.player.player.nodes.size===0,
    'End retained output samples');
   check(!main.captions.includes('Late audio')&&main.errors.length===0,'Late poll changed ended session');
   const mainResult={preAdmissionFrames,firstUtterance:first,preservedThroughReset:preserved,
    preservedThroughAudioStart:acrossPlayback,speakingMicFrames:speaking.length,
    voicedSpeakingMicFrames:speaking.filter(frame=>frame.rms>.0005).length,
    speakingMicMaxRms:Math.max(...speaking.map(frame=>frame.rms)),readyRequests:main.readyCalls.length,
    readyLanguage:ready.json.language,userStartedSpeaking:ready.json.user_started_speaking,
    scheduledReset,queuedReset:{pendingSamplesBefore:queuedBefore,pendingSamplesAfter:main.player.player.pendingSamples},
    postEndMicFrames:main.observed.length-atEnd.frames,postEndChunks:main.chunks.length-atEnd.chunks,
    postEndAudioSources:sources.length-atEnd.sources,tracksEnded:tracks.every(track=>track.readyState==='ended')};
   // End must also fence a ready task blocked on its first microphone ACK.
   const late=makeFixture({holdChunk:0,providerReady:true,id:'c'.repeat(32)});
   try{
    await waitFor(()=>late.session.readyRequested&&late.chunks.length===1&&late.observed.length>=3,'ready waiting for first PCM ACK');
    check(late.readyCalls.length===0,'Held first PCM ACK failed to hold readiness');
    late.holdPoll=true;await waitFor(()=>late.pendingPoll,'late provider-ready poll');
    const lateTracks=late.capture.stream.getTracks(),before={frames:late.observed.length,chunks:late.chunks.length,sources:sources.length};
    late.session.end();late.chunkGate.resolve();
    late.pendingPoll.resolve({state:'SPEAKING',provider_ready:true,frames:[{index:0,type:'audio',pcm:encoded}],next_index:1,total_frames:1});
    await bounded(late.started,'ready-pending session ends');
    await bounded(late.session.readyTask,'ready task settles after End');await delay(1350);
    check(late.readyCalls.length===0,'Buffered ready task issued /ready after End');
    check(late.observed.length===before.frames&&late.chunks.length===before.chunks&&sources.length===before.sources,
     'Late ACK or provider-ready poll caused post-End mic or audio');
    check(lateTracks.every(track=>track.readyState==='ended')&&late.errors.length===0,'Late readiness did not stay ended');
    return {synthetic_browser:true,physical_device_verified:false,acoustic_echo_verified:false,provider_io:false,
     deviceRate:context.sampleRate,...mainResult,endWhileReadyPending:{readyRequests:late.readyCalls.length,
      postEndMicFrames:late.observed.length-before.frames,postEndChunks:late.chunks.length-before.chunks,
      postEndAudioSources:sources.length-before.sources,tracksEnded:lateTracks.every(track=>track.readyState==='ended')}};
   }finally{late.session.end();}
  }finally{main.admission.resolve();main.chunkGate.resolve();main.session.end();await context.close();}
 });
 assert.deepEqual(pageErrors,[]);assert.equal(result.synthetic_browser,true);assert.equal(result.deviceRate,48000);
 assert.equal(httpReady.length,1);assert.equal(httpReady[0].contentType,'application/json');
 assert.equal(httpReady[0].csrf,'synthetic-csrf');assert.deepEqual(httpReady[0].json,{language:'id',user_started_speaking:true});
 result.httpReady={requests:httpReady.length,contentType:httpReady[0].contentType,csrfVerified:true,json:httpReady[0].json};
 console.log(JSON.stringify(result));
}finally{
 await browser?.close();await new Promise(resolve=>server.close(resolve));
}
