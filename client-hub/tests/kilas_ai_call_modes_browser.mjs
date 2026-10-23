// Local rendered templates + synthetic transport/audio only.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const {chromium}=createRequire(process.env.KILAS_CALL_TOOLS||'/tmp/kilas-call-tools/package.json')('playwright');
const root=fileURLToPath(new URL('../',import.meta.url));
const pages=JSON.parse(await readFile(process.env.KILAS_AI_CALL_UI_FIXTURE_PATH,'utf8'));
const surface=pages.id.match(/<dialog id="ai-call-dialog"[\s\S]*?<\/dialog>/)[0];
const html='<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="fixture"><link rel="stylesheet" href="/static/kilas_ai_call.css"><button data-ai-call-launch>Call</button>'+surface+'<script type="module" src="/static/kilas_ai_call.mjs"></script>';
const server=createServer(async(req,res)=>{const path=new URL(req.url,'http://localhost').pathname;if(path==='/'){res.setHeader('Content-Type','text/html');res.end(html);return;}if(!/^\/static\/[a-z0-9_]+\.(mjs|css|webp)$/.test(path)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',path.endsWith('.mjs')?'text/javascript':path.endsWith('.css')?'text/css':'image/webp');res.end(await readFile(root+path));});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
const report=[];
try{
 for(const [width,height] of [[320,640],[390,844],[768,1024],[1440,900],[480,300]]){
  const page=await browser.newPage({viewport:{width,height}});const errors=[];page.on('pageerror',e=>errors.push(e.message));let posts=[],ended=[],polls=0,chunkAttempts=0;const chunks=new Map();
  await page.route('**/kilas-ai/call/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname;
   if(path.endsWith('readiness'))return route.fulfill({json:{available:true}});
   const [,id,suffix]=path.match(/call\/([a-f0-9]{32})(.*)$/);
   if(suffix==='/end'){ended.push(id);return route.fulfill({json:{state:'CLOSED'}});}
   if(suffix.startsWith('/chunks/')){
    const index=Number(suffix.split('/').at(-1)),key=id+':'+index,body=req.postDataBuffer();chunkAttempts++;
    if(chunks.has(key))assert.ok(chunks.get(key).equals(body));else chunks.set(key,body);
    if(chunkAttempts===1)return route.fulfill({status:503,json:{code:'temporary'}});
    return route.fulfill({json:{accepted_index:index}});
   }
   if(req.method()==='POST'){posts.push({id,body:req.postData()});polls=0;return route.fulfill({json:{call_id:id}});}
   const after=Number(new URL(req.url()).searchParams.get('after'));
   const frames=polls++===0?[{index:0,type:'audio',pcm:Buffer.alloc(9600).toString('base64')}]:[];
   return route.fulfill({json:{state:'LISTENING',frames,next_index:after+frames.length,total_frames:1}});
  });
  await page.addInitScript(()=>{const Native=window.AudioContext;window.AudioContext=class extends Native{constructor(...args){super(...args);window.qaContext=this;}};});
  await page.goto(origin);await page.locator('[data-ai-call-launch]').click();assert.equal(posts.length,0);assert.equal(await page.locator('#ai-call-end').isVisible(),false);
  assert.equal(await page.locator('#ai-call-mode').inputValue(),'normal');
  for(const mode of ['learning','roleplay','roast']){
   await page.locator('#ai-call-mode').selectOption(mode);
   assert.equal(await page.locator('#ai-call-learning').evaluate(e=>e.hidden),mode!=='learning');
   assert.equal(await page.locator('#ai-call-roleplay').evaluate(e=>e.hidden),mode!=='roleplay');
  }
  assert.equal(await page.locator('#ai-call-start').isDisabled(),true);await page.locator('#ai-call-roast-opt-in').check();
  const cdp=await page.context().newCDPSession(page);if(width===390)await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:2});
  await page.waitForTimeout(150);assert.ok(await page.locator('#ai-call-start').evaluate(e=>{const r=e.getBoundingClientRect(),v=visualViewport;return r.left>=v.offsetLeft-1&&r.right<=v.offsetLeft+v.width+1&&r.bottom<=v.offsetTop+v.height+1;}));
  if(width===320)await page.screenshot({path:'/tmp/ai-call-modes-mobile.png'});
  await page.locator('#ai-call-start').click();await page.waitForFunction(()=>document.querySelector('#ai-call-dialog').dataset.state==='speaking');
  assert.ok(posts[0].body.includes('"roast_opt_in":true'));assert.ok(posts[0].body.includes('"mode":"roast"'));
  while(chunkAttempts<2)await page.waitForTimeout(50);assert.equal(posts.length,1);
  await page.evaluate(()=>window.qaContext.suspend());await page.waitForFunction(()=>window.qaContext.state==='running');assert.equal(posts.length,1);
  await page.locator('#ai-call-normal').click();
  assert.equal(await page.locator('#ai-call-dialog').getAttribute('data-state'),'ended');assert.equal(await page.locator('#ai-call-end').isVisible(),false);assert.equal(await page.evaluate(()=>window.qaContext.state),'closed');assert.equal(await page.locator('#ai-call-mode').inputValue(),'normal');assert.equal(await page.locator('#ai-call-roast-opt-in').isChecked(),false);
  await page.waitForTimeout(400);assert.equal(ended.length,1);assert.equal(posts.length,1);
  await page.locator('#ai-call-mode').selectOption('learning');await page.locator('#ai-call-target-language').selectOption('ja');await page.locator('#ai-call-explanation-language').selectOption('en');await page.locator('#ai-call-level').selectOption('advanced');
  await page.locator('#ai-call-start').click();await page.waitForFunction(()=>document.querySelector('#ai-call-dialog').dataset.state==='speaking');assert.ok(posts[1].body.includes('"target_language":"ja"'));assert.ok(posts[1].body.includes('"explanation_language":"en"'));assert.ok(posts[1].body.includes('"level":"advanced"'));
  await page.locator('#ai-call-end').click();assert.deepEqual(errors,[]);report.push({width,height,selectors:true,opt_in:true,stop:true,language_payload:true,upload_retry:true,audio_resume:true});await page.close();
 }
 console.log(JSON.stringify(report));
}finally{await browser.close();server.close();}
