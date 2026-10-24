// Actual Flask-rendered pages in jsdom; no browser or microphone capture.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const pages=JSON.parse(readFileSync(process.env.KILAS_AI_CALL_UI_FIXTURE_PATH,'utf8'));
const {JSDOM}=createRequire(pathToFileURL(join(process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-gemini-dom','package.json')))('jsdom');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
for(const locale of ['en','id','es','zh'])test(`Call ${locale} actual chat placement, import idle, explicit modal and background cleanup`,async t=>{
 const dom=new JSDOM(pages[locale],{url:'https://app.example.test/kilas-ai',runScripts:'outside-only',pretendToBeVisual:true});
 t.after(()=>dom.window.close());const {window}=dom,{document}=window;
 window.eval(readFileSync(new URL('../static/ui_i18n.js',import.meta.url),'utf8'));
 const button=document.querySelector('[data-ai-call-launch]'),dialog=document.querySelector('#ai-call-dialog'),end=document.querySelector('#ai-call-end');
 // Load the actual conflicting global theme and Call styles; earlier tests
 // only checked HTML and therefore missed the dialog's size/color cascade.
 // Mirror production order: the mobile footer rule is in base.html's head,
 // and the component stylesheet loads after it. jsdom is not a browser cascade.
 const mobileRule=document.createElement('style');mobileRule.textContent='.customer-ui footer{display:none;padding:14px}';document.head.append(mobileRule);
 for(const path of ['kilas_premium.css','kilas_home.css','kilas_chat.css','kilas_ai_call.css']){const style=document.createElement('style');style.textContent=readFileSync(new URL('../static/'+path,import.meta.url),'utf8');document.head.append(style);}
 assert.equal(button.type,'button');assert.equal(button.parentElement.lastElementChild,button);assert.ok(button.previousElementSibling.matches('.ai-stop'));assert.ok(button.previousElementSibling.previousElementSibling.matches('.ai-send[type=submit]'));assert.equal(button.closest('form').querySelector('[name=csrf_token]')?.value,'audio-csrf');
 assert.equal(button.textContent.trim(),'');assert.ok(button.getAttribute('aria-label'));
 const composer=button.closest('.ai-composer'),actions=button.parentElement,input=composer.querySelector('textarea');
 assert.equal(input.placeholder,{en:'Message',id:'Pesan',es:'Mensaje',zh:'消息'}[locale]);
 assert.equal(window.getComputedStyle(composer).display,'grid');assert.equal(window.getComputedStyle(actions).display,'flex');assert.equal(window.getComputedStyle(actions).gridColumn,'3');assert.equal(window.getComputedStyle(input).gridColumn,'2');assert.equal(window.getComputedStyle(button).width,'44px');
 const attach=composer.querySelector('[data-work-attach],.ai-attach');
 assert.ok(attach.compareDocumentPosition(input)&window.Node.DOCUMENT_POSITION_FOLLOWING);
 assert.ok(input.compareDocumentPosition(actions.querySelector('.ai-send'))&window.Node.DOCUMENT_POSITION_FOLLOWING);
 assert.equal(window.getComputedStyle(input).minHeight,'44px');assert.equal(window.getComputedStyle(input).paddingTop,'10px');assert.equal(window.getComputedStyle(input).resize,'none');assert.equal(window.getComputedStyle(input).lineHeight,'24px');
 assert.equal(window.getComputedStyle(input).whiteSpace,'pre');assert.equal(window.getComputedStyle(input).overflow,'hidden');
 // jsdom does not update :placeholder-shown for value changes. Remove the
 // placeholder to inspect the filled-state cascade without claiming pixel QA.
 const placeholder=input.getAttribute('placeholder');input.removeAttribute('placeholder');input.value='First line\nSecond line';input.focus();input.setSelectionRange(5,5);input.setRangeText(' draft');
 assert.equal(input.value,'First draft line\nSecond line');assert.equal(window.getComputedStyle(input).whiteSpace,'pre-wrap');assert.equal(window.getComputedStyle(input).overflow,'auto');
 input.value='';input.setAttribute('placeholder',placeholder);input.blur();
 assert.equal(dialog.getAttribute('aria-describedby'),null);assert.equal(dialog.querySelectorAll('.ai-call-note,#ai-call-privacy').length,0);assert.ok(end.getAttribute('aria-label'));assert.equal(document.querySelectorAll('#ai-call-dialog').length,1);
 assert.equal(dialog.querySelectorAll('audio,video').length,0);
 assert.equal(dialog.hidden,true);assert.equal(window.getComputedStyle(dialog).display,'none');
 const viewport=new window.EventTarget();Object.assign(viewport,{height:740,width:393,offsetTop:0,offsetLeft:0});window.visualViewport=viewport;
 let microphones=0,contexts=0,requests=0;
 dialog.showModal=()=>{dialog.setAttribute('open','');};dialog.close=()=>{dialog.removeAttribute('open');dialog.dispatchEvent(new window.Event('close'));};
 const values={window,document,KilasUI:window.KilasUI,FormData:window.FormData,
  navigator:{mediaDevices:{getUserMedia(){microphones++;throw Error('Forbidden media QA');}},sendBeacon(){throw Error('No provider admission');}},
  fetch:async()=>{requests++;return {ok:true,redirected:false,json:async()=>({available:false,reason:'budget_limit'})};}};
 window.AudioContext=class{constructor(options){assert.equal(options.latencyHint,'playback');contexts++;this.state='running';}createGain(){return {gain:{value:1},connect(){}};}resume(){return Promise.resolve();}close(){return Promise.resolve();}addEventListener(){}};
 const previous={};for(const [key,value] of Object.entries(values)){previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});}
 t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}});
 await import('../static/kilas_ai_call.mjs?dom-'+locale);await tick();
 assert.equal(microphones,0);assert.equal(contexts,0);assert.equal(requests,0);assert.equal(dialog.open,false);
 assert.equal(dialog.parentNode,document.body);assert.equal(dialog.hidden,true);
 button.click();await tick();assert.equal(dialog.open,true);assert.equal(document.activeElement,dialog.querySelector('#ai-call-start'));assert.equal(contexts,0);assert.equal(requests,0);dialog.querySelector('#ai-call-start').click();await tick();assert.equal(contexts,1);assert.equal(microphones,0);assert.equal(requests,1);
 assert.equal(dialog.hidden,false);
 const computed=window.getComputedStyle(dialog);assert.equal(computed.display,'grid');assert.equal(computed.position,'fixed');assert.equal(computed.maxWidth,'none');assert.equal(computed.maxHeight,'none');assert.equal(parseFloat(computed.borderRadius),0);assert.equal(computed.backgroundColor,'rgb(17, 24, 32)');
 const footer=end.closest('footer');assert.equal(footer.parentNode,dialog);assert.equal(window.getComputedStyle(footer).display,'flex');assert.equal(window.getComputedStyle(footer).padding,'0px');assert.equal(dialog.querySelector('#ai-call-privacy'),null);assert.equal(parseFloat(window.getComputedStyle(dialog.querySelector('.ai-call-body')).minHeight),0);
 assert.equal(dialog.style.getPropertyValue('--ai-call-height'),'740px');assert.equal(dialog.style.getPropertyValue('--ai-call-width'),'393px');
 Object.assign(viewport,{height:390,width:740,offsetTop:5,offsetLeft:2});viewport.dispatchEvent(new window.Event('resize'));
 assert.equal(dialog.style.getPropertyValue('--ai-call-height'),'390px');assert.equal(dialog.style.getPropertyValue('--ai-call-top'),'5px');assert.equal(dialog.style.getPropertyValue('--ai-call-width'),'740px');assert.equal(dialog.style.getPropertyValue('--ai-call-left'),'2px');
 assert.equal(dialog.classList.contains('ai-call-compact'),true);assert.equal(window.getComputedStyle(end).minHeight,'56px');
 Object.assign(viewport,{height:240,width:320,offsetTop:0,offsetLeft:0});viewport.dispatchEvent(new window.Event('resize'));assert.equal(dialog.style.getPropertyValue('--ai-call-height'),'240px');assert.equal(window.getComputedStyle(footer).display,'flex');assert.equal(window.getComputedStyle(end).minHeight,'56px');
 assert.equal(dialog.querySelector('#ai-call-error').textContent,window.KilasUI.t('Batas biaya tercapai. Panggilan dihentikan.'));
 assert.equal(dialog.dataset.state,'ended');
 document.dispatchEvent(new window.Event('visibilitychange'));await tick();assert.equal(dialog.open,true);
 Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new window.Event('visibilitychange'));assert.equal(dialog.open,false);assert.equal(dialog.hidden,true);assert.equal(window.getComputedStyle(dialog).display,'none');assert.equal(document.body.classList.contains('kilas-ai-call-open'),false);
 button.click();await tick();window.dispatchEvent(new window.Event('pagehide'));assert.equal(dialog.open,false);assert.equal(microphones,0);
});
