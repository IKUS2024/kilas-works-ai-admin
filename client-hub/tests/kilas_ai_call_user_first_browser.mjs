// Restored user-first lifecycle in actual Chromium, with synthetic mic/transport.
// Never connects a provider; cannot establish real speech understanding.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('playwright'),root=fileURLToPath(new URL('../',import.meta.url));
const server=createServer(async(req,res)=>{try{const path=new URL(req.url,'http://localhost').pathname;if(path==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><html lang="id"><title>Local user-first fixture</title>');return;}if(!/^\/static\/[a-z0-9_]+\.mjs$/.test(path)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type','text/javascript');res.end(await readFile(root+path));}catch{res.writeHead(500);res.end();}});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
try{
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+root+'tests/fixtures/ai_call_synthetic/id-first.wav','--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage(),origin='http://127.0.0.1:'+server.address().port,errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());await page.goto(origin);
 const result=await page.evaluate(async()=>{
  const [{CallSession},{CallPlayer},{CallCapture}]=await Promise.all([import('/static/kilas_ai_call_engine.mjs'),import('/static/kilas_ai_call_player.mjs'),import('/static/kilas_ai_call_capture.mjs')]);
  const check=(value,message)=>{if(!value)throw Error(message);},delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const wait=async(fn,label)=>{const end=performance.now()+10000;while(!fn()){if(performance.now()>end)throw Error(label);await delay(10);}};
  const context=new AudioContext({latencyHint:'playback'});await context.resume();
  const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices}),player=new CallPlayer({getContext:()=>context});
  const frames=[],chunks=[],requests=[],captions=[],states=[];let session;
  const id='e'.repeat(32),request=async(path,args={})=>{
   requests.push({path,method:args.method||'GET'});
   if(path.endsWith('/ready'))throw Error('Unexpected automatic-opening handshake');
   if(path==='/kilas-ai/call/readiness')return {available:true};
   if(path.endsWith('/end'))return {ended:true};
   if(path==='/kilas-ai/call/'+id&&args.method==='POST')return {call_id:id};
   const chunk=path.match(/\/chunks\/(\d+)$/);if(chunk){chunks.push({nonzero:args.body.some(value=>value!==0),speaking:session.speaking,bytes:args.body.length});return {accepted_index:Number(chunk[1])};}
   const after=Number(new URL(path,location.origin).searchParams.get('after'));return {state:'LISTENING',frames:frames.slice(after),next_index:frames.length,total_frames:frames.length};
  };
  session=new CallSession({request,capture,player,key:()=>id,prepare:()=>context.resume(),onState:value=>states.push(value),onText:value=>captions.push(value)});
  const started=session.start();await wait(()=>session.state==='listening'&&chunks.some(chunk=>chunk.nonzero),'first synthetic user input');await delay(700);
  check(player.player.pendingSamples===0&&captions.at(-1)==='','Automatic output appeared before a provider reply');
  const idleUploads=chunks.length,raw=new Uint8Array(9600),view=new DataView(raw.buffer);for(let i=0;i<4800;i++)view.setInt16(i*2,Math.round(1200*Math.sin(2*Math.PI*440*i/24000)),true);
  const pcm=btoa(String.fromCharCode(...raw));for(let i=0;i<5;i++)frames.push({index:frames.length,type:'audio',pcm});
  frames.push({index:frames.length,type:'text',text:'Synthetic reply after user input'},{index:frames.length+1,type:'turn_complete'});
  await wait(()=>session.state==='speaking'&&player.player.nodes.size>0,'provider reply playback');
  await wait(()=>chunks.some(chunk=>chunk.speaking&&!chunk.nonzero),'restored previous playback input policy');
  await wait(()=>session.state==='listening'&&player.player.pendingSamples===0,'playback drain');const nextAt=chunks.length;
  await wait(()=>chunks.slice(nextAt).some(chunk=>chunk.nonzero&&!chunk.speaking),'next synthetic question');
  check(captions.at(-1)==='Synthetic reply after user input','Reply caption lost on normal drain');
  const tracks=capture.stream.getTracks(),beforeEnd=chunks.length;session.end();await started;await context.close();await delay(350);
  check(tracks.every(track=>track.readyState==='ended')&&chunks.length===beforeEnd,'End failed to stop capture/uploads');
  return {synthetic_browser:true,physical_device_verified:false,provider_io:false,semantic_understanding_verified:false,automaticOpeningRequests:requests.filter(value=>value.path.endsWith('/ready')).length,outputBeforeReply:false,idleMicrophoneUploads:idleUploads,replyPlayed:true,returnedToListeningAfterDrain:true,nextQuestionMicResumed:true,endStoppedTracks:true,postEndUploads:chunks.length-beforeEnd,states};
 });
 assert.equal(result.automaticOpeningRequests,0);assert.deepEqual(errors,[]);console.log(JSON.stringify({...result,errors},null,2));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
