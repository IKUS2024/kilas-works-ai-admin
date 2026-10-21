const {chromium}=require('playwright');
const fs=require('fs'),assert=require('assert');
const url=process.env.PREVIEW_URL || 'http://127.0.0.1:8775/';
const out=process.env.OUTPUT_DIR || '/tmp/creative-services-grouping';fs.mkdirSync(out,{recursive:true});
// Verified against the first Creative Services source, commit 4467e3c7, rather than inferred from thumbnail subjects.
const original={event:[['1_RhxZwkV-XnmrJ4ygHAtJ3rZRMqwJOA3','event-first-drive.jpg'],['CzHI2JkPo5Q','event-01.jpg'],['Cs5lhuyg_qB','event-02.jpg'],['CuY-v6tg-NV','event-03.jpg'],['1NUKvbCyoEIfsM39rVF3M96FICKMIowtt','event-04.jpg'],['Cdw6-xnJ0bI','event-05.jpg'],['CSrOzSYp9-G','event-06.jpg']],social:[['CuGo_oHg2tY','social-01.jpg'],['Cs2pwEHAdxT','social-02.jpg'],['CsxdzFyg5aA','social-03.jpg'],['CsxiIxAAC-w','social-04.jpg'],['CsxhaufgmkQ','social-05.jpg'],['CvJQ3l_BIrN','social-06.jpg']]};
(async()=>{
 const b=await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',args:['--no-sandbox']});const p=await b.newPage();const errors=[],checks=[];p.on('pageerror',e=>errors.push(e.message));
 async function settle(){await p.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].filter(x=>x.getClientRects().length).map(async x=>{x.loading='eager';try{await x.decode()}catch{}}));await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame)});}
 async function anchorCheck(){return await p.evaluate(()=>({headerBottom:document.querySelector('.header').getBoundingClientRect().bottom,titleTop:document.querySelector('#portfolio-title').getBoundingClientRect().top,scroll:scrollY}));}
 async function groupCheck(group,overview){return await p.locator(`[data-portfolio-service=${group}]`).evaluate((entry,{group,overview})=>{
  const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right}},heading=entry.querySelector('h3'),description=entry.querySelector('.cs-portfolio-heading>p:not(.eyebrow)'),media=entry.querySelector('.cs-portfolio-media'),actions=entry.querySelector('.cs-portfolio-actions');
  const mediaItems=[...media.querySelectorAll('img')].filter(e=>e.getClientRects().length);const actionItems=[...actions.querySelectorAll('a')].filter(e=>e.getClientRects().length);
  return {group,overview,title:heading.textContent.trim(),entry:rect(entry),heading:rect(heading),description:rect(description),media:rect(media),firstAction:actionItems.length?rect(actionItems[0]):null,border:getComputedStyle(entry).borderTopWidth,mediaOwnership:mediaItems.map(img=>({src:img.getAttribute('src'),owner:img.closest('[data-portfolio-service]').dataset.portfolioService,rect:rect(img)})),labelledBy:entry.getAttribute('aria-labelledby'),headingId:heading.id};
 },{group,overview});}
 function assertOwnership(c){assert.equal(c.labelledBy,c.headingId);assert(c.heading.bottom<=c.description.top+1);assert(c.description.bottom<=c.media.top+1);assert(parseFloat(c.border)>=1);for(const m of c.mediaOwnership){assert.equal(m.owner,c.group);assert(m.rect.top>=c.description.bottom-1);assert(m.rect.left>=c.entry.left-1&&m.rect.right<=c.entry.right+1);assert(m.rect.bottom<=c.entry.bottom+1);}if(c.firstAction)assert(c.media.bottom<=c.firstAction.top+1);}
 for(const width of [320,360,390,768,820,1024,1440])for(const lang of ['id','en']){
  await p.setViewportSize({width,height:width<500?844:1000});await p.goto(url);await p.locator(`[data-cs-language=${lang}]`).click();await settle();
  assert.equal(await p.locator('.cs-hero-work img').getAttribute('src'),'assets/portfolio/event-04.jpg','Hero uses the existing event gathering poster');
  assert.equal(await p.locator('.cs-hero-cover').getAttribute('href'),'#event-portfolio');
  assert.equal(await p.locator('iframe').count(),0,'Provider media remains lazy');
  assert.equal(await p.locator('[data-consultation]').getAttribute('href'),await p.locator('#cs-contact-whatsapp').getAttribute('href'));
  const heroCTA=await p.locator('[data-consultation]').boundingBox();assert(heroCTA.y+heroCTA.height<=844||width>=500,'Consultation is visible on arrival on mobile');
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width,'No overview overflow');
  const choices=await p.locator('[data-service-choice]').evaluateAll(es=>es.map(e=>({text:e.querySelector('h2').textContent.trim(),top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom})));assert.equal(choices.length,2);assert(choices.every(x=>x.bottom>x.top),'Both service choices remain available');
  await p.evaluate(()=>scrollTo({top:0,behavior:'instant'}));await p.screenshot({path:`${out}/home-${width}-${lang}.png`,fullPage:true});
  const overview=[];for(const group of ['event','social']){const c=await groupCheck(group,true);assertOwnership(c);overview.push(c);}
  if(width<651)assert(overview[0].entry.bottom<overview[1].entry.top,'Distinct vertical category boundaries');
  await p.locator('.focused-header-links>a[href="#portfolio"]').click();await settle();let anchor=await anchorCheck();assert(anchor.titleTop>=anchor.headerBottom+8);await p.screenshot({path:`${out}/overview-anchor-${width}-${lang}.png`});await p.locator('#cs-portfolio-groups').screenshot({path:`${out}/portfolio-overview-${width}-${lang}.png`});
  checks.push({width,lang,view:'overview',overview,anchor,choices});
  for(const group of ['event','social']){
   await p.locator(`[data-portfolio-category=${group}]`).click();await p.waitForURL('**/#'+group+'-portfolio');await settle();anchor=await anchorCheck();assert(anchor.titleTop>=anchor.headerBottom+8);
   assert.equal(await p.locator(`[data-portfolio-category=${group}]`).getAttribute('aria-current'),'page');assert.equal(await p.locator('[data-portfolio-service]:visible').count(),1);
   const c=await groupCheck(group,false);assertOwnership(c);
   const media=p.locator(`[data-portfolio-videos=${group}] .cs-video-card`);assert.equal(await media.count(),original[group].length);
   for(let i=0;i<original[group].length;i++){const card=p.locator(`[data-video-id=${group}-${String(i+1).padStart(2,'0')}]`);assert((await card.getAttribute('data-video-source')).includes(original[group][i][0]));assert((await card.locator('img').getAttribute('src')).endsWith(original[group][i][1]));}
   if(group==='event'){assert.equal(await media.first().getAttribute('data-video-id'),'event-05');assert.equal(await media.last().getAttribute('data-video-id'),'event-01');assert.equal(await media.last().locator('.cs-video-caption>span').first().innerText(),'Company profile');const extra=await p.locator('.cs-additional-work').boundingBox(),profile=await media.last().boundingBox();assert(extra.y+extra.height<=profile.y,'Company profile follows a separate heading');}
   assert.equal(await p.locator('#cs-'+group+' .cs-card').count(),3);
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),width);
   await p.screenshot({path:`${out}/${group}-anchor-${width}-${lang}.png`});await p.locator('#cs-portfolio-groups').screenshot({path:`${out}/${group}-gallery-${width}-${lang}.png`});checks.push({width,lang,view:group,ownership:c,anchor});
  }
  // A direct hash visit is tested without resetting scroll, so sticky-header overlap cannot be masked.
  await p.goto(url+'#social-portfolio');await p.reload();await settle();anchor=await anchorCheck();assert(anchor.titleTop>=anchor.headerBottom+8);
  await p.locator('[data-portfolio-category=social]').click();await settle();anchor=await anchorCheck();assert(anchor.titleTop>=anchor.headerBottom+8);
 }
 // All six package actions still prepare their original WhatsApp payload; external navigation is prevented.
 await p.goto(url+'#cs-event');await p.evaluate(()=>document.querySelectorAll('[data-service-id]').forEach(a=>a.addEventListener('click',e=>e.preventDefault())));
 for(const group of ['event','social']){await p.goto(url+'#cs-'+group);for(const a of await p.locator('#cs-'+group+' [data-service-id]').all()){const href=await a.getAttribute('href');await a.click();assert.equal(await p.locator('#cs-contact-whatsapp').getAttribute('href'),href);}}
 await p.emulateMedia({reducedMotion:'reduce'});await p.goto(url+'#portfolio');await settle();assert.equal(await p.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
 assert.deepEqual(errors,[]);fs.writeFileSync(out+'/results.json',JSON.stringify({checks,errors,originalMapping:original,summary:'PASS: 42 overview/category states across 7 widths and 2 languages; geometric ownership/order/boundaries; real nav and direct-hash anchor positions; all original mappings and six package handlers; relevant hero preview with visible consultation CTA.'},null,2));await b.close();console.log('PASS: 42 grouping states, original mapping, category navigation/anchors, portfolio hero and package actions.');
})().catch(e=>{console.error(e);process.exit(1)});
