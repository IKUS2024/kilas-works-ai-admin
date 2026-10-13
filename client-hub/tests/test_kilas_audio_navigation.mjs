// Production navigation script in a Node VM with synthetic page nodes. No browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../static/kilas_audio.js',import.meta.url),'utf8');
function page({mode='voiceover',voiceOnly=false,url='https://synthetic.test/kilas-translator?mode=voiceover'}={}){
 const events=new Map(),writes=[],nodes=new Map();
 const node=()=>({value:'',dataset:{},handlers:new Map(),hidden:false,textContent:'',attrs:{},addEventListener(type,fn){this.handlers.set(type,fn);},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},focus(){}});
 const heading=node();heading.textContent=mode==='voiceover'?'Voice Over':'Kilas Translator';
 const tabs=(voiceOnly?['voiceover']:['translate','voiceover']).map(kind=>{const n=node();n.id=kind+'-tab';n.attrs['aria-controls']=kind+'-panel';n.attrs['aria-selected']=String(kind===mode);const panel=node();panel.hidden=kind!==mode;nodes.set(kind+'-panel',panel);return n;});
 const root=node();root.dataset={activeMode:mode,maxSeconds:'600'};root.querySelectorAll=selector=>selector==='[role=tab]'?tabs:[];root.querySelector=selector=>selector==='.audio-heading h1'?heading:{value:'synthetic-csrf'};
 const doc={hidden:false,title:heading.textContent+' · Kilas Works',querySelector(selector){if(selector==='#audio-studio')return root;if(selector==='#audio-file')return null;if(selector==='[data-kilas-feature][aria-current]')return null;if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);},getElementById:id=>nodes.get(id),querySelectorAll:()=>[],addEventListener:(type,fn)=>events.set('document:'+type,fn)};
 const location={href:url};const window={addEventListener:(type,fn)=>events.set(type,fn)};
 vm.runInNewContext(source,{document:doc,window,location,history:{state:{preserved:true},replaceState(state,_,next){writes.push({state,url:String(next)});location.href=String(next);}},URL,sessionStorage:{getItem:()=>null},setTimeout(){},clearTimeout(){}});
 return {root,tabs,heading,doc,nodes,events,writes,location};
}
test('Voice Over hydration preserves the server selected panel and heading without changing URL',()=>{
 const p=page();assert.equal(p.root.dataset.activeMode,'voiceover');assert.equal(p.nodes.get('translate-panel').hidden,true);assert.equal(p.nodes.get('voiceover-panel').hidden,false);assert.equal(p.heading.textContent,'Voice Over');assert.equal(p.doc.title,'Voice Over · Kilas Works');assert.equal(p.writes.length,0);
});
test('tab navigation updates mode URL/title and back navigation restores Voice Over presentation',()=>{
 const p=page();p.tabs[0].handlers.get('click')();assert.equal(p.nodes.get('voiceover-panel').hidden,true);assert.equal(p.nodes.get('translate-panel').hidden,false);assert.equal(p.doc.title,'Kilas Translator · Kilas Works');assert.equal(new URL(p.location.href).searchParams.get('mode'),'translate');assert.deepEqual(p.writes[0].state,{preserved:true});
 p.location.href='https://synthetic.test/kilas-translator?mode=voiceover';p.events.get('popstate')();assert.equal(p.nodes.get('voiceover-panel').hidden,false);assert.equal(p.nodes.get('translate-panel').hidden,true);assert.equal(p.doc.title,'Voice Over · Kilas Works');assert.equal(p.writes.length,1);
});
test('voice-only offering remains Voice Over on refresh even for historical translate query',()=>{
 const p=page({voiceOnly:true,url:'https://synthetic.test/kilas-translator?mode=translate'});assert.equal(p.nodes.get('voiceover-panel').hidden,false);assert.equal(p.root.dataset.activeMode,'voiceover');assert.equal(p.heading.textContent,'Voice Over');assert.equal(p.writes.length,0);
});
