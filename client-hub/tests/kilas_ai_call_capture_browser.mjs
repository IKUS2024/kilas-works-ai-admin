// Chromium's actual getUserMedia -> AudioWorklet -> PCM path, synthetic device.
// This cannot verify a physical Android microphone or acoustic echo cancellation.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const root=fileURLToPath(new URL('../',import.meta.url));
const server=createServer(async(req,res)=>{
 try{
  const path=new URL(req.url,'http://localhost').pathname;
  if(path==='/'){res.setHeader('Content-Type','text/html');res.end('<button id="start">Start</button>');return;}
  if(!/^\/static\/[a-z0-9_]+\.mjs$/.test(path)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type','text/javascript');res.end(await readFile(root+path));
 }catch{res.writeHead(500);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,
  args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
   '--use-file-for-fake-audio-capture='+root+'tests/fixtures/ai_call_synthetic/id-first.wav','--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage();
 await page.goto('http://127.0.0.1:'+server.address().port);
 const result=await page.evaluate(async()=>{
  const {CallCapture}=await import('/static/kilas_ai_call_capture.mjs');
  const context=new AudioContext({sampleRate:48000}),frames=[];await context.resume();
  const capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
  let error=null;
  await capture.start({ready(){},level(){},blob(){},error:e=>{error=e.code;},pcm:raw=>{
   const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);let energy=0,peak=0;
   for(let i=0;i<raw.length;i+=2){const value=view.getInt16(i,true)/32768;energy+=value*value;peak=Math.max(peak,Math.abs(value));}
   frames.push({bytes:raw.length,rms:Math.sqrt(energy/(raw.length/2)),peak});
  }});
  const settings=capture.stream.getAudioTracks()[0].getSettings();
  await new Promise(resolve=>setTimeout(resolve,7200));
  const tracks=capture.stream.getTracks();capture.cancel();const before=frames.length;
  await new Promise(resolve=>setTimeout(resolve,300));await context.close();
  return {error,deviceRate:context.sampleRate,channelCount:settings.channelCount,
   frames:frames.length,bytes:frames.reduce((n,f)=>n+f.bytes,0),
   voicedFrames:frames.filter(f=>f.rms>.0005).length,maxFrameRms:Math.max(...frames.map(f=>f.rms)),
   postEndFrames:frames.length-before,tracksEnded:tracks.every(t=>t.readyState==='ended')};
 });
 assert.equal(result.error,null);assert.equal(result.deviceRate,48000);assert.equal(result.channelCount,1);
 assert.ok(result.frames>=35);assert.ok(result.voicedFrames>10);assert.ok(result.bytes>=7*32000);
 assert.equal(result.postEndFrames,0);assert.equal(result.tracksEnded,true);
 console.log(JSON.stringify({synthetic_browser:true,physical_device_verified:false,...result}));
}finally{
 await browser?.close();await new Promise(resolve=>server.close(resolve));
}
