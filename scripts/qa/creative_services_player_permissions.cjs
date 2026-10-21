/* Real Chromium A/B policy regression using synthetic cross-origin provider media.
 * No provider requests escape the fixture routes; no browser consent is overridden.
 */
const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert'),{execFileSync}=require('child_process');
const url=process.env.PREVIEW_URL||'http://127.0.0.1:8778/creative-services/';
const out=process.env.OUTPUT_DIR||'/tmp/creative-player-permissions';fs.mkdirSync(out,{recursive:true});
const baseline=execFileSync('git',['show','9b77d33f:creative-services-site/assets/portfolio-player.js'],{encoding:'utf8'});
const current=fs.readFileSync('creative-services-site/assets/portfolio-player.js','utf8');
const index=fs.readFileSync('creative-services-site/index.html','utf8');
const media=fs.readFileSync(process.env.MEDIA_FIXTURE).toString('base64');
const html=`<!doctype html><meta charset="utf-8"><video id="media" controls playsinline src="data:video/webm;base64,${media}"></video><button onclick="document.requestStorageAccess().then(()=>window.storageResult='granted').catch(e=>window.storageResult=e.name+': '+e.message)">Request fixture storage access</button><script>window.policy={autoplay:document.featurePolicy.allowsFeature('autoplay'),referrer:document.referrer,storageAPI:typeof document.requestStorageAccess};media.play().then(()=>window.result='playing').catch(e=>window.result=e.name+': '+e.message);</script>`;
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--autoplay-policy=document-user-activation-required']});const checks=[];
 for(const provider of ['drive','instagram']) for(const mode of ['baseline','current']){
  const context=await browser.newContext(),page=await context.newPage();const warnings=[];let referer='';
  page.on('console',m=>{if(/requestStorageAccess|sandbox/.test(m.text()))warnings.push(m.text())});
  // Match the real Flask response's existing referrer header. The iframe element
  // must deliberately send the normal origin referrer on cross-origin navigation.
  await page.route(url,r=>r.fulfill({contentType:'text/html',headers:{'Referrer-Policy':'same-origin'},body:index}));
  await page.route('**/assets/portfolio-player.js',r=>r.fulfill({contentType:'application/javascript',body:mode==='baseline'?baseline:current}));
  await page.route(/^https:\/\/(www\.instagram\.com\/.*\/embed\/|drive\.google\.com\/file\/d\/[^/]+\/preview)$/,r=>{referer=r.request().headers()['referer'];return r.fulfill({contentType:'text/html',body:html})});
  await page.goto(url+(provider==='drive'?'#event-portfolio':'#social-portfolio'));
  await page.locator(`[data-video-id=${provider==='drive'?'event-01':'social-01'}]`).click();
  const frame=page.frameLocator('#cs-player-stage iframe');
  await frame.locator('video').waitFor();
  for(let i=0;i<30;i++){if(await frame.locator('body').evaluate(()=>!!window.result))break;await page.waitForTimeout(100)}
  await page.waitForTimeout(100);
  const playback=await frame.locator('body').evaluate(()=>({policy:window.policy,result:window.result,paused:media.paused,currentTime:media.currentTime}));
  assert.equal(playback.policy.autoplay,mode==='current');
  assert.equal(referer,new URL(url).origin+'/');assert.equal(playback.policy.referrer,referer);
  if(mode==='baseline'){assert(playback.result.startsWith('NotAllowedError'));assert.equal(playback.paused,true);assert.equal(playback.currentTime,0)}
  else{assert.equal(playback.result,'playing');assert.equal(playback.paused,false);assert(playback.currentTime>0)}
  await frame.getByRole('button').click();
  for(let i=0;i<30;i++){if(await frame.locator('body').evaluate(()=>!!window.storageResult))break;await page.waitForTimeout(100)}
  const storageResult=await frame.locator('body').evaluate(()=>window.storageResult);
  const sandboxTokenRejection=warnings.some(m=>m.includes('allow-storage-access-by-user-activation'));
  assert.equal(sandboxTokenRejection,mode==='baseline');
  checks.push({provider,mode,referer,...playback,storageResult,sandboxTokenRejection,warnings});
  await context.close();
 }
 await browser.close();
 fs.writeFileSync(out+'/results.json',JSON.stringify({scope:'Browser policy A/B with synthetic providers, not real portfolio playback. No cookie grants or security flags overridden.',checks},null,2));
 console.log(JSON.stringify(checks,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
