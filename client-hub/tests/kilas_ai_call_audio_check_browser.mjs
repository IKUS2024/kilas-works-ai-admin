// Synthetic device + actual Chromium/AudioWorklet/CallPlayer, no provider IO.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const {chromium}=createRequire(import.meta.url)('playwright'),root=fileURLToPath(new URL('../',import.meta.url));
const requests=[];
const server=createServer(async(req,res)=>{
 try{
  const path=new URL(req.url,'http://localhost').pathname;requests.push({path,method:req.method});
  if(req.method!=='GET'){res.writeHead(405);res.end();return;}
  if(path==='/kilas-ai/call/audio-check'){
   const template=await readFile(root+'/templates/kilas_ai/call_audio_check.html','utf8');
   res.setHeader('Content-Type','text/html');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'");
   res.end(template.replace(/{{ url_for\('static',filename='([^']+)',v='([^']+)'\) }}/g,(_,name,v)=>'/static/'+name+'?v='+v));return;
  }
  if(!/^\/static\/[a-z0-9_]+\.mjs$/.test(path)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type','text/javascript');res.end(await readFile(root+path));
 }catch{res.writeHead(500);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
try{
 browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+root+'tests/fixtures/ai_call_synthetic/id-first.wav','--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage(),origin='http://127.0.0.1:'+server.address().port,errors=[],violations=[],sockets=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('websocket',socket=>sockets.push(socket.url()));
 page.on('console',message=>{if(message.type()==='error')violations.push(message.text());});
 await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 await page.addInitScript(()=>{
  window.audioProbe={tracks:[],contexts:[],getUserMediaCalls:0,sourceCount:0,holdMic:false};const probe=window.audioProbe;
  const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia=async options=>{probe.getUserMediaCalls++;const stream=await get(options);probe.tracks.push(...stream.getTracks());if(probe.holdMic)await new Promise(resolve=>{probe.releaseMic=resolve;});return stream;};
  const Native=window.AudioContext;window.AudioContext=class extends Native{constructor(...args){super(...args);probe.contexts.push(this);}createBufferSource(){probe.sourceCount++;return super.createBufferSource();}};
 });
 await page.goto(origin+'/kilas-ai/call/audio-check');await page.waitForTimeout(150);
 assert.deepEqual(await page.evaluate(()=>({calls:audioProbe.getUserMediaCalls,contexts:audioProbe.contexts.length})),{calls:0,contexts:0});
 await page.click('#check-start');await page.waitForFunction(()=>document.querySelector('#check-summary').textContent.trim().startsWith('{'),{timeout:18000});
 const summary=JSON.parse(await page.textContent('#check-summary'));
 assert.equal(summary.providerCalls,0);assert.equal(summary.audioUploaded,false);assert.equal(summary.audioRecorded,false);
 assert.equal(summary.settings.echoCancellation,true);assert.equal(summary.settings.noiseSuppression,true);assert.equal(summary.settings.autoGainControl,true);
 assert.ok(summary.capture.frames>35&&summary.capture.samples>140000);assert.ok(!/deviceId|groupId|label/.test(JSON.stringify(summary)));
 assert.ok(await page.evaluate(()=>audioProbe.tracks.every(track=>track.readyState==='ended')&&audioProbe.contexts.every(context=>context.state==='closed')));
 await page.evaluate(()=>{audioProbe.holdMic=true;});await page.click('#check-start');
 await page.waitForFunction(()=>!!audioProbe.releaseMic);await page.click('#check-stop');
 const before=await page.evaluate(()=>audioProbe.sourceCount);await page.evaluate(()=>audioProbe.releaseMic());await page.waitForTimeout(1400);
 const cleanup=await page.evaluate(()=>({tracksEnded:audioProbe.tracks.every(track=>track.readyState==='ended'),contextsClosed:audioProbe.contexts.every(context=>context.state==='closed'),sourceCount:audioProbe.sourceCount,status:document.querySelector('#check-status').textContent}));
 assert.equal(cleanup.tracksEnded,true);assert.equal(cleanup.contextsClosed,true);assert.equal(cleanup.sourceCount,before);assert.match(cleanup.status,/dihentikan/);
 assert.deepEqual(errors,[]);assert.deepEqual(violations,[]);assert.deepEqual(sockets,[]);assert.ok(requests.every(request=>request.method==='GET'&&(request.path==='/kilas-ai/call/audio-check'||request.path.startsWith('/static/'))));
 console.log(JSON.stringify({synthetic_browser:true,physical_device_verified:false,acoustic_echo_verified:false,provider_io:false,summary,pendingPermissionCancellation:cleanup,network:{requests:requests.length,posts:0,websockets:0},errors},null,2));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
