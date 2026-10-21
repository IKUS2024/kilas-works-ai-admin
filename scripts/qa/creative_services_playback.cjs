/* Browser playback UI contract. Provider responses are synthetic, never live proof.
 * Generate a disposable testsrc+sine WebM with ffmpeg and set MEDIA_FIXTURE.
 */
const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert');
const url=process.env.PREVIEW_URL||'http://127.0.0.1:8777/creative-services/';
const out=process.env.OUTPUT_DIR||'/tmp/creative-services-playback';
fs.mkdirSync(out,{recursive:true});
const video=fs.readFileSync(process.env.MEDIA_FIXTURE).toString('base64');
const fixture=`<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>body{margin:0;background:#fff;color:#222;font:14px system-ui}header,p{padding:16px}video{display:block;width:100%;max-height:65vh;background:#161816}button{margin:16px;padding:12px}</style><header>Provider UI test fixture · not a portfolio video</header><video controls playsinline preload="metadata" src="data:video/webm;base64,${video}"></video><p>Synthetic test media. Real provider availability is not verified by this test.</p><button onclick="window.open('https://example.invalid/');try{top.location='https://example.invalid/'}catch(e){}">Test blocked outbound navigation</button></html>`;
const providerPattern=/^https:\/\/(www\.instagram\.com\/.*\/embed\/|drive\.google\.com\/file\/d\/[^/]+\/preview)$/;
const expected={
 'event-01':'https://drive.google.com/file/d/1_RhxZwkV-XnmrJ4ygHAtJ3rZRMqwJOA3/preview',
 'event-02':'https://www.instagram.com/reel/CzHI2JkPo5Q/embed/',
 'event-03':'https://www.instagram.com/reel/Cs5lhuyg_qB/embed/',
 'event-04':'https://www.instagram.com/reel/CuY-v6tg-NV/embed/',
 'event-05':'https://drive.google.com/file/d/1NUKvbCyoEIfsM39rVF3M96FICKMIowtt/preview',
 'event-06':'https://www.instagram.com/reel/Cdw6-xnJ0bI/embed/',
 'event-07':'https://www.instagram.com/tv/CSrOzSYp9-G/embed/',
 'social-01':'https://www.instagram.com/reel/CuGo_oHg2tY/embed/',
 'social-02':'https://www.instagram.com/reel/Cs2pwEHAdxT/embed/',
 'social-03':'https://www.instagram.com/reel/CsxdzFyg5aA/embed/',
 'social-04':'https://www.instagram.com/reel/CsxiIxAAC-w/embed/',
 'social-05':'https://www.instagram.com/reel/CsxhaufgmkQ/embed/',
 'social-06':'https://www.instagram.com/reel/CvJQ3l_BIrN/embed/'
};
(async()=>{
 const b=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const context=await b.newContext({reducedMotion:'reduce'}),p=await context.newPage();
 const errors=[],requests=[],checks=[];let mode='fixture';
 p.on('pageerror',e=>errors.push(e.message));
 await p.route(providerPattern,async route=>{
  requests.push(route.request().url());
  if(mode==='pending') return; // Intentionally stalled provider, for timeout/close behavior.
  if(mode==='unavailable') return route.fulfill({status:403,contentType:'text/html',body:'<h1>Provider requires sign-in or denies embedding</h1>'});
  return route.fulfill({status:200,contentType:'text/html',body:fixture});
 });
 for(const width of (process.env.QA_WIDTHS ? process.env.QA_WIDTHS.split(',').map(Number) : [1440,1280,1024,768,390,360])){
  await p.setViewportSize({width,height:width<500?844:1000});
  await p.goto(url);await p.evaluate(()=>localStorage.clear());await p.reload();
  assert.equal(await p.locator('iframe').count(),0);assert.equal(requests.length,checks.length);
  for(const lang of ['id','en']){
   await p.locator(`[data-cs-language=${lang}]`).click();
   for(const group of ['event','social']){
    await p.goto(url+'#'+group+'-portfolio');await p.evaluate(()=>document.fonts.ready);
    for(const card of await p.locator(`[data-portfolio-videos=${group}] .cs-video-card`).all()){
     const id=await card.getAttribute('data-video-id'),before=p.url(),count=requests.length;
     await card.click();await p.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='loaded');
     assert.equal(p.url(),before);assert.equal(context.pages().length,1);assert.equal(await p.locator('iframe').count(),1);
     assert.equal(requests.length,count+1);assert.equal(requests.at(-1),expected[id]);
     const iframe=p.locator('#cs-player-stage iframe');
     assert.equal(await iframe.getAttribute('src'),expected[id]);assert.equal(await iframe.getAttribute('allow'), 'fullscreen; picture-in-picture; encrypted-media');
     assert(!(await iframe.getAttribute('sandbox')).includes('allow-popups'));assert(!(await iframe.getAttribute('sandbox')).includes('allow-top-navigation'));
     const measurement=await p.evaluate(()=>{
      const dialog=document.querySelector('#cs-video-dialog'),r=dialog.getBoundingClientRect(),close=dialog.querySelector('[data-player-close]').getBoundingClientRect();
      return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,left:r.left,right:r.right,dialogClient:dialog.clientWidth,dialogScroll:dialog.scrollWidth,closeTop:close.top,closeBottom:close.bottom,height:innerHeight,modal:dialog.matches(':modal'),focused:document.activeElement.matches('[data-player-close]')};
     });
     assert(measurement.scroll<=width);assert(measurement.left>=0&&measurement.right<=width);assert(measurement.dialogScroll<=measurement.dialogClient);
     assert(measurement.closeTop>=0&&measurement.closeBottom<=measurement.height);assert(measurement.modal&&measurement.focused);
     assert((await p.locator('#cs-player-note').innerText()).includes(lang==='en'?'unavailable':'belum tersedia'));
     const media=p.frameLocator('#cs-player-stage iframe').locator('video');
     assert.equal(await media.evaluate(v=>v.controls&&v.playsInline&&!v.autoplay),true);
     await media.evaluate(v=>v.play());await p.waitForTimeout(70);
     assert(await media.evaluate(v=>!v.paused&&v.currentTime>0));
     if(id==='social-01'){
      await p.screenshot({path:`${out}/modal-${width}-${lang}-SYNTHETIC-PROVIDER.png`});
      await p.frameLocator('#cs-player-stage iframe').getByRole('button').click();
      assert.equal(p.url(),before);assert.equal(context.pages().length,1);
      await p.locator('[data-player-close]').focus();await p.keyboard.press('Shift+Tab');
      assert(await p.evaluate(()=>document.querySelector('#cs-video-dialog').contains(document.activeElement)));
     }
     await p.keyboard.press('Escape');await p.waitForFunction(()=>!document.querySelector('#cs-video-dialog').open&&document.querySelectorAll('iframe').length===0);
     assert.equal(await card.evaluate(c=>c===document.activeElement),true);
     assert.equal(await p.evaluate(()=>document.documentElement.classList.contains('cs-player-open')),false);
     checks.push({width,lang,id,providerURL:expected[id],nativeFixturePlayback:true,...measurement});
    }
    await p.screenshot({path:`${out}/gallery-${group}-${width}-${lang}.png`});
   }
  }
  console.log(`PASS ${width}: 26 card/player/keyboard/native-fixture cases`);
 }
 // Retry tears down the old browsing context; switching, hash navigation, and
 // backdrop close do likewise, so hidden provider audio cannot be retained.
 await p.goto(url+'#event-portfolio');await p.locator('[data-video-id=event-01]').click();
 await p.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='loaded');
 await p.evaluate(()=>window.__oldFrame=document.querySelector('iframe'));
 await p.locator('[data-player-retry]').click();await p.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='loaded');
 assert(await p.evaluate(()=>!window.__oldFrame.isConnected&&window.__oldFrame!==document.querySelector('iframe')));assert.equal(await p.locator('iframe').count(),1);
 await p.evaluate(()=>document.querySelector('[data-video-id=event-02]').click());
 assert.equal(await p.locator('iframe').count(),1);assert.equal(await p.locator('iframe').getAttribute('src'),expected['event-02']);
 await p.evaluate(()=>location.hash='#services');await p.waitForFunction(()=>!document.querySelector('#cs-video-dialog').open);assert.equal(await p.locator('iframe').count(),0);
 // Cross-origin load events do not prove successful playback. An unavailable
 // provider still keeps the explicit access warning and never claims success.
 await p.goto(url+'#event-portfolio');await p.locator('[data-video-id=event-01]').click();await p.mouse.click(5,5);await p.waitForFunction(()=>!document.querySelector('#cs-video-dialog').open&&document.querySelectorAll('iframe').length===0);
 await p.goto(url+'#event-portfolio');await p.locator('[data-video-id=event-01]').click();
 await p.goto(url+'?pagehide-check=1');await p.goBack();
 assert.equal(await p.locator('iframe').count(),0);assert.equal(await p.locator('#cs-video-dialog').evaluate(d=>d.open),false);
 mode='unavailable';await p.goto(url+'#social-portfolio');await p.locator('[data-video-id=social-01]').click();
 await p.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='loaded');
 assert((await p.locator('#cs-player-status').innerText()).includes('If the video appears'));
 await p.screenshot({path:out+'/provider-unavailable-360.png'});await p.locator('[data-player-close]').click();
 mode='pending';await p.locator('[data-video-id=social-02]').click();
 assert.equal(await p.locator('#cs-player-stage').getAttribute('aria-busy'),'true');
 await p.waitForFunction(()=>document.querySelector('#cs-video-dialog').dataset.playerState==='timeout',null,{timeout:16000});
 assert.equal(await p.locator('#cs-player-stage').getAttribute('aria-busy'),'false');
 assert((await p.locator('#cs-player-status').innerText()).includes('could not be confirmed'));
 await p.screenshot({path:out+'/provider-timeout-360.png'});await p.keyboard.press('Escape');
 await p.waitForFunction(()=>!document.querySelector('#cs-video-dialog').open&&document.querySelectorAll('iframe').length===0);
 // A failed or disabled script never leaves deceptive enabled play controls.
 const nojs=await b.newPage({javaScriptEnabled:false,viewport:{width:360,height:844}});await nojs.goto(url);assert.equal(await nojs.locator('.cs-video-card:disabled').count(),13);await nojs.close();
 assert.deepEqual(errors,[]);
 fs.writeFileSync(out+'/results.json',JSON.stringify({scope:'Synthetic provider UI and native browser media decoding; NOT actual provider/video playback verification',checks,total:checks.length,errors,additional:['lazy requests','one frame only','retry removes old player','switch removes old player','hash cleanup','keyboard Escape/focus restoration','backdrop close','pagehide/back cleanup','sandbox blocks popups/top navigation','provider denial warning','12-second timeout','no-JS disabled cards']},null,2));
 await b.close();console.log(`PASS ${checks.length} responsive card/player cases and failure/lifecycle checks. Actual source availability remains unverified.`);
})().catch(e=>{console.error(e);process.exit(1)});
