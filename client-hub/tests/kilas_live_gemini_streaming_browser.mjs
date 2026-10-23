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
  // Exercise the exact production layout + captions with synthetic content.
  await page.evaluate(async()=>{
   const {TranslatorCallLayout}=await import('/static/kilas_live_translator_call_layout.mjs');
   const {GeminiCaptions}=await import('/static/kilas_live_gemini_captions.mjs');
   document.querySelector('#live-setup').hidden=true;document.querySelector('#live-active').hidden=false;
   new TranslatorCallLayout({document,root:document.querySelector('[data-gemini-live]'),endButton:document.querySelector('#live-end')}).setActive(true);
   const captions=new GeminiCaptions({root:document.querySelector('#native-captions'),document,labels:{en:'Indonesia → English',id:'English → Indonesia',original:'Teks asli',translation:'Terjemahan'}});
   captions.update('',{operation:'one',streams:{en:{source_text:'Di mana pintu keberangkatan?',translated_text:'Where is the departure gate?'}}});
   captions.update('',{operation:'two',streams:{id:{source_text:'Continue straight, then turn left.',translated_text:'Lanjutkan lurus, lalu belok kiri.'}}});
   document.querySelector('#native-caption-empty').hidden=true;document.querySelector('#live-state').textContent='Mendengarkan';
  });
  const geometry=await page.evaluate(()=>{const r=document.querySelector('#live-end').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>innerWidth+1,endVisible:r.top>=0&&r.bottom<=innerHeight&&r.right<=innerWidth,stateText:document.querySelector('#live-state').textContent,stateStyle:getComputedStyle(document.querySelector('#live-state')).color,stateHidden:document.querySelector('#live-state').hidden,captions:document.querySelector('#native-captions').clientHeight};});
  assert.equal(geometry.overflow,false);assert.equal(geometry.endVisible,true);assert.ok(geometry.captions>50);assert.equal(geometry.stateStyle,'rgb(85, 93, 103)');
  if(process.env.KILAS_TRANSLATOR_SCREENSHOTS==='1'&&(width===390||width===1440))await page.screenshot({path:`/tmp/translator-active-${width}.png`});
  assert.deepEqual(errors,[]);report.push({width,height,...geometry,swap:true});await page.close();
 }
 await writeFile('/tmp/translator-browser-evidence.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();server.close();}
