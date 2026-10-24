// Real rendered native surface; synthetic captions. No microphone/provider IO.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile,writeFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const {chromium}=createRequire((process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-gemini-dom')+'/package.json')('playwright');
const root=fileURLToPath(new URL('../',import.meta.url));
const pages=JSON.parse(await readFile(process.env.KILAS_GEMINI_UI_FIXTURE_PATH||'/tmp/kilas-gemini-ui.json','utf8'));
const server=createServer(async(req,res)=>{
 const path=new URL(req.url,'http://localhost').pathname;
 if(path==='/'){res.setHeader('Content-Type','text/html');res.end(pages.id);return;}
 if(!path.startsWith('/static/')||path.includes('..')){res.writeHead(404);res.end();return;}
 try{const data=await readFile(root+path);res.setHeader('Content-Type',/\.(mjs|js)$/.test(path)?'text/javascript':path.endsWith('.css')?'text/css':path.endsWith('.svg')?'image/svg+xml':'application/octet-stream');res.end(data);}catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({executablePath:process.env.KILAS_BROWSER_EXECUTABLE||(existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined),headless:true,args:['--no-sandbox']});
const report=[];
try{
 for(const [width,height] of [[320,640],[390,844],[768,1024],[1440,900],[480,300]]){
  const page=await browser.newPage({viewport:{width,height}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/kilas-translator/live/sessions/active',route=>route.fulfill({json:{session:null}}));
  await page.route('**/kilas-ai/**',route=>route.fulfill({json:{available:false}}));
  await page.goto(origin);await page.waitForFunction(()=>!document.querySelector('#live-setup-form [type=submit]').disabled);
  await page.locator('#native-swap').click();assert.equal(await page.locator('[name=language_a]').inputValue(),'en');
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  if(process.env.KILAS_TRANSLATOR_SCREENSHOTS==='1'&&(width===390||width===1440))await page.screenshot({path:`/tmp/translator-setup-${width}.png`});
  // Drive the actual UI callback without opening a microphone/provider.
  await page.evaluate(async()=>{const {GeminiSession}=await import('/static/kilas_live_gemini_engine.mjs?v=output-boundary-20261024');GeminiSession.prototype.start=function(){this.active=true;this.state('listening');};});
  await page.locator('[name=consent]').check();await page.locator('#live-setup-form [type=submit]').click();
  // Exercise the exact production caption renderer with synthetic content.
  await page.evaluate(async()=>{
   const {GeminiCaptions}=await import('/static/kilas_live_gemini_captions.mjs');
   const captions=new GeminiCaptions({root:document.querySelector('#native-captions'),document,labels:{en:'Indonesia → English',id:'English → Indonesia',original:'Teks asli',translation:'Terjemahan'}});
   captions.update('',{operation:'one',streams:{en:{source_text:'Di mana pintu keberangkatan?',translated_text:'Where is the departure gate?'}}});
   captions.update('',{operation:'two',streams:{id:{source_text:'Continue straight, then turn left.',translated_text:'Lanjutkan lurus, lalu belok kiri.'}}});
   document.querySelector('#native-caption-empty').hidden=true;document.querySelector('#live-state').textContent='Mendengarkan';
  });
  const geometry=await page.evaluate(()=>{const r=document.querySelector('#live-end').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth+1,endVisible:r.top>=0&&r.bottom<=innerHeight&&r.right<=innerWidth,stateText:document.querySelector('#live-state').textContent,stateStyle:getComputedStyle(document.querySelector('#live-state')).color,stateHidden:document.querySelector('#live-state').hidden,captions:document.querySelector('#native-captions').clientHeight};});
  assert.equal(geometry.overflow,false);assert.equal(geometry.endVisible,true);assert.ok(geometry.captions>50);assert.equal(geometry.stateStyle,'rgb(85, 93, 103)');
  if(process.env.KILAS_TRANSLATOR_SCREENSHOTS==='1'&&(width===390||width===1440))await page.screenshot({path:`/tmp/translator-active-${width}.png`});
  if(width===390){const cdp=await page.context().newCDPSession(page);await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:2});await page.waitForTimeout(100);assert.ok(await page.locator('#live-end').evaluate(e=>{const r=e.getBoundingClientRect(),v=visualViewport;return r.right<=v.offsetLeft+v.width+1&&r.bottom<=v.offsetTop+v.height+1;}));await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});}
  await page.locator('#live-end').click();assert.equal(await page.locator('#live-active').isVisible(),false);
  assert.deepEqual(errors,[]);report.push({width,height,...geometry,swap:true});await page.close();
 }
 await writeFile('/tmp/translator-browser-evidence.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();server.close();}
