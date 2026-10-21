const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert');
// Run a static server for creative-services-site first; requires Playwright and Chromium.
const root=process.env.OUTPUT_DIR || '/tmp/creative-services-qa', url=process.env.PREVIEW_URL || 'http://127.0.0.1:8765/';
fs.mkdirSync(root+'/after',{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 const errors=[],results=[]; const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)errors.push(r.status()+' '+r.url())});
 for(const width of [1440,1280,1024,768,390,360]){
  await page.setViewportSize({width,height:width<500?844:1000});
  await page.goto(url,{waitUntil:'networkidle'});await page.evaluate(()=>localStorage.clear());await page.reload({waitUntil:'networkidle'});
  for(const language of ['id','en']){
   await page.locator(`[data-cs-language=${language}]`).click();
   for(const view of ['home','event','social']){
    await page.goto(url+(view==='home'?'':'#cs-'+view));await page.evaluate(async()=>{await document.fonts.ready; await Promise.all([...document.images].filter(x=>x.getClientRects().length).map(async x=>{x.loading='eager';try{await x.decode()}catch(e){}}));});await page.waitForTimeout(80);
    const measurements=await page.evaluate(()=>{
     const visible=el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
     return {width:innerWidth,scroll:document.documentElement.scrollWidth,fonts:[document.fonts.check('16px Inter'),[...document.fonts].some(face=>face.family==='Inter'&&face.status==='loaded')],headingRoles:[...document.querySelectorAll('h1,h2,h3')].filter(visible).map(el=>{const style=getComputedStyle(el);return {family:style.fontFamily,weight:Number(style.fontWeight),fontStyle:style.fontStyle,fontSize:parseFloat(style.fontSize),stretch:style.fontStretch}}),brokenImages:[...document.images].filter(x=>visible(x)&&(!x.complete||!x.naturalWidth)).map(x=>x.src),overflow:[...document.querySelectorAll('main *')].filter(visible).filter(x=>{const r=x.getBoundingClientRect();return r.right>innerWidth+1||r.left< -1}).map(x=>x.className).slice(0,12),cardHeights:[...document.querySelectorAll('.cs-panel:not([hidden]) .cs-card')].map(x=>Math.round(x.getBoundingClientRect().height)),body:document.body.innerText.length};
    });
    assert(measurements.scroll<=width,`Horizontal overflow ${width} ${view} ${language}`);assert.deepEqual(measurements.overflow,[]);assert.deepEqual(measurements.brokenImages,[]);assert(measurements.fonts.every(Boolean));for(const heading of measurements.headingRoles){assert(heading.family.startsWith('Inter'));assert(heading.weight>=600);assert.equal(heading.fontStyle,'normal');assert(heading.fontSize<=64);assert.equal(heading.stretch,'100%');}
    await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
    await page.screenshot({path:`${root}/after/${view}-${width}-${language}.png`,fullPage:true});
    results.push({width,view,language,...measurements});
   }
  }
 }
 // All existing service cards, portfolio collections, return links and nav destinations.
 for(const width of [1440,1280,1024,768,390,360]){
  await page.setViewportSize({width,height:width<500?844:1000});await page.goto(url);await page.locator('[data-cs-language=id]').click();
  for(const key of ['event','social']){
   await page.locator(`[data-service-choice=${key}]`).click();await page.waitForURL('**/#cs-'+key);await page.locator('#cs-'+key).waitFor({state:'visible'});
   assert.equal(await page.locator('#cs-'+key+' .cs-card').count(),3);
   await page.locator('[data-selected-portfolio]').click();await page.waitForURL('**/#'+key+'-portfolio');
   const cards=page.locator(`[data-portfolio-videos=${key}] .cs-video-card`);assert.equal(await cards.count(),key==='event'?7:6);
   for(const card of await cards.all()){assert(/^https:\/\/(www\.instagram\.com|drive\.google\.com)\//.test(await card.getAttribute('data-video-source')));assert.equal(await card.getAttribute('aria-haspopup'),'dialog');assert.equal(await card.getAttribute('target'),null);assert.equal(await card.isEnabled(),true);}
   await page.locator('#cs-'+key+' .cs-back-services').click();await page.waitForURL('**/#services');await page.locator('[data-service-choice='+key+']').waitFor({state:'visible'});
  }
  await page.locator('.focused-header-links>a[href="#portfolio"]').click();await page.waitForURL('**/#portfolio');
  await page.locator('.brand').click();await page.waitForURL('**/#services');
 }
 // Inspect actual click handling while preventing external navigation / any message sending.
 await page.goto(url+'#cs-event');await page.locator('[data-cs-language=id]').click();
 await page.evaluate(()=>document.querySelectorAll('[data-service-id]').forEach(a=>a.addEventListener('click',e=>e.preventDefault())));
 for(const view of ['event','social']){
  await page.goto(url+'#cs-'+view);
  for(const a of await page.locator('#cs-'+view+' [data-service-id]').all()){
   const href=await a.getAttribute('href');assert(href.startsWith('https://wa.me/6282213039137?text='));
   await a.click();assert.equal(await page.locator('#cs-contact-whatsapp').getAttribute('href'),href);
   assert((await page.locator('#selected-service').innerText()).includes(await a.getAttribute('data-service-id')));
  }
 }
 // Reduced motion, keyboard access, and font fallback with font requests blocked.
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(url);assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
 await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.className),'skip-link');await page.keyboard.press('Enter');assert.equal(await page.evaluate(()=>document.activeElement.id),'main');
 await page.locator('[data-service-choice=event]').focus();await page.screenshot({path:root+'/after/keyboard-focus-360.png'});
 const fallback=await browser.newPage({viewport:{width:360,height:844}});await fallback.route('**/assets/fonts/**',r=>r.abort());await fallback.goto(url,{waitUntil:'networkidle'});assert.equal(await fallback.evaluate(()=>document.documentElement.scrollWidth),360);await fallback.screenshot({path:root+'/after/fallback-360.png',fullPage:true});await fallback.close();
 fs.writeFileSync(root+'/results.json',JSON.stringify({checks:results,errors,interactions:'Passed: all 6 sizes, both service choices, 13 portfolio URLs, nav/back, 6 package click handlers, contact payload, language, reduced motion, keyboard skip, fallback font.',externalActions:'All external WhatsApp clicks prevented; no message sent; no source video fetched.',modalCount:await page.locator('dialog,[role=dialog]').count()},null,2));
 assert.deepEqual(errors,[]);await browser.close();console.log('PASS: 36 responsive views, all navigation / package interactions, font fallback and reduced motion.');
})().catch(e=>{console.error(e);process.exit(1)});
