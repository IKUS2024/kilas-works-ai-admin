/* Wrapper fullscreen is real Chromium fullscreen; provider content is synthetic.
 * Unsupported/rejected API cases deliberately simulate browser capabilities only.
 */
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
const url=process.env.PREVIEW_URL||'http://127.0.0.1:8778/creative-services/';
const out=process.env.OUTPUT_DIR||'/tmp/creative-player-fullscreen';fs.mkdirSync(out,{recursive:true});
const media=fs.readFileSync(process.env.MEDIA_FIXTURE).toString('base64');
const fixture=`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>html,body{height:100%;margin:0;background:#161816;color:white;font:12px system-ui}p{height:24px;margin:0;text-align:center}video{display:block;width:100%;height:calc(100% - 24px);object-fit:contain}</style><p>Synthetic provider fixture · not portfolio playback proof</p><video controls playsinline src="data:video/webm;base64,${media}"></video>`;
const pattern=/^https:\/\/(www\.instagram\.com\/.*\/embed\/|drive\.google\.com\/file\/d\/[^/]+\/preview)$/;
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});const checks=[];
 for(const mode of ['native','unsupported','rejected']){
  const sizes=mode==='native'?[[1440,1000],[1280,1000],[1024,768],[768,1024],[390,844],[360,780],[844,390],[780,360]]:[[390,844],[844,390]];
  for(const [width,height] of sizes)for(const lang of ['id','en'])for(const group of ['event','social']){
   const mobile=width<500||height<500;
   const context=await browser.newContext({viewport:{width,height},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'});
   if(mode!=='native')await context.addInitScript(mode=>{
    if(mode==='unsupported'){Element.prototype.requestFullscreen=undefined;Element.prototype.webkitRequestFullscreen=undefined;}
    else Element.prototype.requestFullscreen=function(){return Promise.reject(new TypeError('Simulated native fullscreen rejection'))};
   },mode);
   const page=await context.newPage();const errors=[];let requests=0;
   page.on('pageerror',e=>errors.push(e.message));
   await page.route(pattern,r=>{requests++;return r.fulfill({contentType:'text/html',body:fixture})});
   await page.goto(url);await page.locator(`[data-cs-language=${lang}]`).click();await page.goto(url+'#'+group+'-portfolio');
   await page.locator(`[data-video-id=${group}-01]`).click();await page.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='loaded');
   const full=page.locator('[data-player-fullscreen]');
   assert.equal(await page.locator('#cs-player-status').isVisible(),false);assert.equal(await page.locator('#cs-player-note').isVisible(),false);assert.equal(await page.locator('[data-player-retry]').isVisible(),false);
   assert.equal(await page.locator('iframe').getAttribute('allowfullscreen'),'');
   assert((await page.locator('iframe').getAttribute('allow')).includes('fullscreen'));
   await page.evaluate(()=>window.__playerBefore=document.querySelector('iframe'));
   if(mobile)await full.tap();else await full.click();
   const expected=mode==='native'?'native':'expanded';
   await page.waitForFunction(expected=>document.querySelector('#cs-video-dialog').dataset.playerView===expected,expected);
   const bounds=await page.evaluate(()=>{
    const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height}};
    return {viewport:[innerWidth,innerHeight],scroll:document.documentElement.scrollWidth,shell:rect(document.querySelector('.cs-player-shell')),stage:rect(document.querySelector('#cs-player-stage')),close:rect(document.querySelector('[data-player-close]')),full:rect(document.querySelector('[data-player-fullscreen]')),nativeElement:document.fullscreenElement?.className||null,provider:document.querySelector('#cs-player-provider').textContent,sameFrame:window.__playerBefore===document.querySelector('iframe')};
   });
   assert(bounds.scroll<=bounds.viewport[0]+1);assert(bounds.shell.left>=-1&&bounds.shell.right<=bounds.viewport[0]+1);assert(bounds.stage.height>70);
   assert(bounds.stage.top>=0&&bounds.stage.bottom<=bounds.viewport[1]+1);
   for(const rect of [bounds.close,bounds.full])assert(rect.top>=0&&rect.bottom<=bounds.viewport[1]&&rect.left>=0&&rect.right<=bounds.viewport[0]+1);
   assert(bounds.sameFrame);assert.equal(requests,1);assert.equal(context.pages().length,1);
   if(mode==='native'){assert.equal(bounds.nativeElement,'cs-player-shell');assert(bounds.provider.includes(lang==='en'?'Full screen':'Layar penuh'));}
   else{assert.equal(bounds.nativeElement,null);assert(bounds.provider.includes(lang==='en'?'Expanded view':'Tampilan diperbesar'));assert(!bounds.provider.includes(lang==='en'?'Full screen':'Layar penuh'));}
   const video=page.frameLocator('#cs-player-stage iframe').locator('video');await video.evaluate(v=>v.play());await page.waitForTimeout(70);assert(await video.evaluate(v=>!v.paused&&v.currentTime>0));
   if(width===390&&lang==='id')await page.screenshot({path:`${out}/${mode}-${group}-390-SYNTHETIC-PROVIDER.png`});
   if(width===390){
    await page.setViewportSize({width:844,height:390});
    const rotated=await page.locator('#cs-player-stage').boundingBox();assert(rotated.y>=0&&rotated.y+rotated.height<=390+1);assert(rotated.height>70);assert.equal(requests,1);
   }
   if(mode==='native')await full.click();else await page.keyboard.press('Escape');
   await page.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerView==='normal');assert.equal(await page.locator('#cs-video-dialog').evaluate(d=>d.open),true);assert.equal(await page.evaluate(()=>document.fullscreenElement),null);
   // Explicit close also exits fullscreen/expanded mode and tears down media.
   await full.click();await page.waitForFunction(expected=>document.querySelector('#cs-video-dialog').dataset.playerView===expected,expected);
   await page.locator('[data-player-close]').click();await page.waitForFunction(()=>!document.querySelector('#cs-video-dialog').open&&!document.fullscreenElement&&!document.querySelector('iframe'));
   assert.deepEqual(errors,[]);checks.push({mode,width,height,lang,group,...bounds});await context.close();
  }
  console.log(`PASS ${mode}: fullscreen/expanded bounds, playback fixture, orientation, exit and close`);
 }
 await browser.close();fs.writeFileSync(out+'/results.json',JSON.stringify({scope:'Real native Chromium wrapper fullscreen plus simulated unsupported/rejected APIs; synthetic provider media only; no real Android/device/provider playback claim',total:checks.length,checks},null,2));console.log(`PASS ${checks.length} fullscreen and honest fallback cases`);
})().catch(e=>{console.error(e);process.exit(1)});
