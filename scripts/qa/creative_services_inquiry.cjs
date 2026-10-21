/* Consultation paths are exercised without opening WhatsApp or sending messages. */
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
const url=process.env.PREVIEW_URL||'http://127.0.0.1:8765/';
const out=process.env.OUTPUT_DIR||'/tmp/creative-services-inquiry';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({reducedMotion:'reduce'}),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 for(const width of [320,820,1440]){
  await page.setViewportSize({width,height:width<500?844:1000});await page.goto(url);
  // Prevent outbound navigation but leave all application click handlers active.
  await page.evaluate(()=>document.querySelectorAll('a[href^="https://wa.me/"]').forEach(a=>a.addEventListener('click',e=>e.preventDefault())));
  for(const language of ['id','en']){
   await page.locator(`[data-cs-language=${language}]`).click();
   await page.locator('.cs-header-contact').click();await page.waitForURL('**/#contact');
   assert(await page.locator('#contact-title').isVisible());
   const contactTop=await page.locator('#contact-title').boundingBox(),header=await page.locator('.header').boundingBox();
   assert(contactTop.y>=header.y+header.height,'Contact heading clears sticky header');
   for(const group of ['event','social']){
    await page.goto(url+'#cs-'+group);
    for(const link of await page.locator('#cs-'+group+' [data-service-id]').all()){
     const href=await link.getAttribute('href'),message=new URL(href).searchParams.get('text');
     assert.equal(new URL(href).pathname,'/6282213039137');
     assert(message.includes(await link.getAttribute(language==='en'?'data-service-en':'data-service-id')));
     await link.click();
     assert.equal(await page.locator('#cs-contact-whatsapp').getAttribute('href'),href);
     assert.equal(await page.locator('[data-consultation]').getAttribute('href'),href);
     assert((await page.locator('#selected-service').innerText()).includes(await link.getAttribute(language==='en'?'data-service-en':'data-service-id')));
    }
   }
   await page.goto(url+'#services');await page.locator('[data-consultation]').click();
   assert.equal(page.url(),url+'#services');assert.equal(page.context().pages().length,1);
   checks.push({width,language,allSixPackagePayloads:true,heroContactConsistent:true,contactAnchor:true});
  }
 }
 // The new hero action follows the existing missing-contact fallback.
 const fallback=await browser.newPage();
 await fallback.addInitScript(()=>{let value;Object.defineProperty(window,'KILAS_SERVICES_CONFIG',{get:()=>value,set:config=>{value={...config,whatsapp:''}}});});
 await fallback.goto(url);assert.equal(await fallback.locator('[data-consultation]').getAttribute('href'),'#contact');assert.equal(await fallback.locator('[data-consultation]').getAttribute('target'),null);
 await fallback.locator('[data-consultation]').click();assert(await fallback.locator('#cs-contact-pending').isVisible());assert.equal(await fallback.locator('#cs-contact-whatsapp').isVisible(),false);await fallback.close();
 const nojs=await browser.newPage({javaScriptEnabled:false});await nojs.goto(url);
 assert((await nojs.locator('[data-consultation]').getAttribute('href')).startsWith('https://wa.me/6282213039137?text='));
 await nojs.close();assert.deepEqual(errors,[]);await browser.close();
 fs.writeFileSync(out+'/results.json',JSON.stringify({checks,errors,missingContactFallback:true,noJavaScriptContact:true,externalActions:'No WhatsApp navigation or messages; outbound clicks prevented.'},null,2));
 console.log('PASS: consultation anchors, 36 package payload selections, matching hero/contact links, both languages, missing-contact and no-JS fallback.');
})().catch(e=>{console.error(e);process.exit(1)});
