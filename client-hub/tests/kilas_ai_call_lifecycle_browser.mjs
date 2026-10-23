// Actual Call UI + native Chromium audio, synthetic microphone and local HTTP.
// No provider, account session, production URL, API key or paid network access.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const {chromium}=createRequire(process.env.KILAS_CALL_TOOLS||'/tmp/kilas-call-tools/package.json')('playwright');
const root=fileURLToPath(new URL('../',import.meta.url));
const pages=JSON.parse(await readFile(process.env.KILAS_AI_CALL_UI_FIXTURE_PATH,'utf8'));
const surface=pages.id.match(/<dialog id="ai-call-dialog"[\s\S]*?<\/dialog>/)[0];
const button=pages.id.match(/<button class="ai-call-launch"[\s\S]*?<\/button>/)[0];
const html='<!doctype html><html lang="id"><meta name="csrf-token" content="audio-csrf"><title>Offline Call QA</title>'+
 '<link rel="stylesheet" href="/static/kilas_ai_call.css"><form><button type="submit">Send</button>'+button+'</form>'+surface+
 '<script type="module" src="/static/kilas_ai_call.mjs"></script></html>';
const server=createServer(async(req,res)=>{
 try{
  const path=new URL(req.url,'http://localhost').pathname;
  if(path==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}
  if(!/^\/static\/[a-z0-9_]+\.(mjs|css)$/.test(path)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',path.endsWith('.mjs')?'text/javascript':'text/css');res.end(await readFile(root+path));
 }catch{res.writeHead(500);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
let browser;
try{
 browser=await chromium.launch({executablePath:process.env.KILAS_CHROMIUM||'/usr/bin/chromium',headless:true,args:[
  '--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
  '--use-file-for-fake-audio-capture='+root+'tests/fixtures/ai_call_synthetic/id-first.wav']});
 const results=[];
 for(const mode of ['normal-and-stalled','denied','no-worklet','no-dialog']){
  const page=await browser.newPage({viewport:{width:393,height:852},isMobile:true,hasTouch:true});
  const errors=[],requests=[],calls=new Map();let active;
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(mode=>{
   window.qa={streams:[],nodes:[],microphones:0};
   const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
   navigator.mediaDevices.getUserMedia=async options=>{
    qa.microphones++;
    if(mode==='denied')throw new DOMException('Synthetic denied permission','NotAllowedError');
    const stream=await get(options);qa.streams.push(stream);return stream;
   };
   const Native=AudioWorkletNode;
   window.AudioWorkletNode=class extends Native{constructor(...args){super(...args);qa.nodes.push(this);}};
   if(mode==='no-worklet')Object.defineProperty(AudioContext.prototype,'audioWorklet',{get:()=>undefined});
   if(mode==='no-dialog')HTMLDialogElement.prototype.showModal=undefined;
  },mode);
  await page.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.origin!==origin){await route.abort();return;}
   if(!url.pathname.startsWith('/kilas-ai/call/')){await route.continue();return;}
   requests.push({method:req.method(),path:url.pathname});
   const reply=body=>route.fulfill({json:body});
   if(url.pathname.endsWith('/readiness'))return reply({available:true});
   const match=url.pathname.match(/^\/kilas-ai\/call\/([a-f0-9]{32})(.*)$/);assert.ok(match);
   const [,id,suffix]=match;
   if(req.method()==='POST'&&!suffix){
    assert.ok(await page.evaluate('qa.streams.some(s=>s.getAudioTracks().some(t=>t.readyState==="live"))'));
    active={id,frames:[],ended:false};calls.set(id,active);return reply({call_id:id});
   }
   const call=calls.get(id);assert.ok(call);
   if(suffix==='/end'){call.ended=true;return reply({state:'CLOSED'});}
   if(suffix.startsWith('/chunks/'))return reply({accepted_index:Number(suffix.split('/').at(-1))});
   const after=Number(url.searchParams.get('after')||0);
   return reply({state:call.ended?'CLOSED':'LISTENING',code:call.ended?'call_ended':null,
    frames:call.frames.slice(after),next_index:call.frames.length,total_frames:call.frames.length});
  });
  await page.goto(origin);await page.waitForFunction('document.querySelector("#ai-call-dialog").parentNode===document.body');
  await page.locator('[data-ai-call-launch]').click();
  if(mode!=='no-dialog')await page.locator('#ai-call-start').click();
  if(mode==='no-dialog'){
   await page.waitForTimeout(150);assert.equal(requests.length,0);assert.equal(await page.evaluate('qa.microphones'),0);
  }else if(mode!=='normal-and-stalled'){
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="ended"');
   assert.ok(await page.locator('#ai-call-error').isVisible());
   assert.equal(requests.filter(r=>r.method==='POST').length,0);
   assert.equal(await page.evaluate('qa.microphones'),mode==='denied'?1:0);
  }else{
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="listening"');
   active.frames.push({index:0,type:'text',text:'Synthetic early reply'});
   await page.waitForFunction('document.querySelector("#ai-call-caption").textContent==="Synthetic early reply"');
   const pcm=Buffer.alloc(9600);for(let i=0;i<4800;i++)pcm.writeInt16LE(Math.round(1000*Math.sin(2*Math.PI*440*i/24000)),i*2);
   active.frames.push({index:1,type:'audio',pcm:pcm.toString('base64')},{index:2,type:'turn_complete'});
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="speaking"');
   assert.equal(await page.locator('#ai-call-caption').textContent(),'Synthetic early reply');
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="listening"');
   const previous=active;
   await page.locator('#ai-call-end').click();await page.waitForFunction('document.querySelector("#ai-call-dialog").hidden');
   await page.waitForFunction('qa.streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))');
   assert.ok(previous.ended);await page.waitForTimeout(100);
   await page.locator('[data-ai-call-launch]').click();
  if(mode!=='no-dialog')await page.locator('#ai-call-start').click();
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="listening"');
   assert.notEqual(active.id,previous.id);
   // Model a capture pipeline that silently stops delivering, while its
   // AudioContext and media track still report running/live.
   await page.evaluate('qa.nodes.at(-1).port.onmessage=()=>{}');
   await page.waitForFunction('document.querySelector("#ai-call-dialog").dataset.state==="ended"',null,{timeout:8000});
   await page.waitForFunction('qa.streams.every(s=>s.getTracks().every(t=>t.readyState==="ended"))');
   assert.ok(await page.locator('#ai-call-error').isVisible());assert.ok(active.ended);
   const postCount=requests.filter(r=>r.method==='POST').length;
   await page.waitForTimeout(500);assert.equal(requests.filter(r=>r.method==='POST').length,postCount);
   assert.equal(calls.size,2);
  }
  assert.deepEqual(errors,[]);
  results.push({mode,passed:true,admissions:calls.size,microphones:await page.evaluate('qa.microphones'),pageErrors:errors});
  await page.close();
 }
 console.log(JSON.stringify({synthetic_browser:true,provider_io:false,physical_device_verified:false,results},null,2));
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
