// Synthetic DOM and stylesheet contracts only; no browser, microphone or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {TranslatorCallLayout} from '../static/kilas_live_translator_call_layout.mjs';

class Element {
 constructor(tagName='DIV'){this.tagName=tagName;this.children=[];this.attributes=new Map();this.focused=0;const classes=new Set();this.classList={add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)};}
 get nextSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)+1]||null;}
 appendChild(node){return this.insertBefore(node,null);}
 insertBefore(node,next){if(node.parentNode)node.parentNode.children.splice(node.parentNode.children.indexOf(node),1);const index=next?this.children.indexOf(next):this.children.length;this.children.splice(index,0,node);node.parentNode=this;return node;}
 getAttribute(name){return this.attributes.get(name)??null;}
 setAttribute(name,value){this.attributes.set(name,value);}
 removeAttribute(name){this.attributes.delete(name);}
 focus(){this.focused++;}
}
function fixture(){const body=new Element('BODY'),shell=new Element(),nav=new Element('NAV'),root=new Element('SECTION'),tail=new Element('SCRIPT'),end=new Element('BUTTON'),start=new Element('BUTTON');body.appendChild(shell);body.appendChild(tail);shell.appendChild(nav);shell.appendChild(root);return {body,shell,nav,root,tail,end,start,layout:new TranslatorCallLayout({document:{body,activeElement:start},root,endButton:end})};}

test('call occupies the body while shell is hidden/inert, then exact placement and background attributes return',()=>{
 const f=fixture();f.shell.setAttribute('aria-hidden','false');f.layout.setActive(true);
 assert.equal(f.root.parentNode,f.body);assert.equal(f.body.classList.contains('kilas-translator-call-active'),true);assert.equal(f.shell.getAttribute('inert'),'');assert.equal(f.shell.getAttribute('aria-hidden'),'true');assert.equal(f.tail.getAttribute('inert'),null);assert.equal(f.end.focused,1);
 f.layout.setActive(false);assert.deepEqual(f.shell.children,[f.nav,f.root]);assert.equal(f.root.parentNode,f.shell);assert.equal(f.shell.getAttribute('inert'),null);assert.equal(f.shell.getAttribute('aria-hidden'),'false');assert.equal(f.shell.getAttribute('data-kilas-translator-call-background'),null);assert.equal(f.body.classList.contains('kilas-translator-call-active'),false);assert.equal(f.start.focused,1);
});
test('repeated active state cannot lose original shell or pre-existing inert state',()=>{
 const f=fixture();f.shell.setAttribute('inert','');f.layout.setActive(true);f.layout.setActive(true);assert.equal(f.end.focused,1);f.layout.setActive(false);f.layout.setActive(false);assert.equal(f.shell.getAttribute('inert'),'');assert.equal(f.start.focused,1);f.layout.setActive(true);f.layout.setActive(false);assert.equal(f.root.parentNode,f.shell);
});
test('End restoration succeeds when the original following node was removed during the call',()=>{
 const f=fixture(),following=new Element();f.shell.appendChild(following);f.layout.setActive(true);f.body.appendChild(following);f.layout.setActive(false);assert.equal(f.root.parentNode,f.shell);assert.equal(f.shell.children.at(-1),f.root);
});
test('an unavailable DOM adapter never interferes with session startup or requests fullscreen permission',()=>{
 const layout=new TranslatorCallLayout({document:{},root:{},endButton:{}});layout.setActive(true);layout.setActive(false);assert.equal(layout.active,false);
});
test('responsive call and icon contracts preserve accessible cancellation, errors, safe areas, and bounded content',()=>{
 const css=readFileSync(new URL('../static/kilas_live_translator.css',import.meta.url),'utf8'),html=readFileSync(new URL('../templates/kilas_translator/live.html',import.meta.url),'utf8'),runtime=readFileSync(new URL('../static/kilas_live_translator.mjs',import.meta.url),'utf8');
 assert.match(css,/body\.kilas-translator-call-active>\.kilas-live-translator\{[^}]*position:fixed;inset:0/);assert.match(css,/height:100vh;height:100dvh/);for(const side of ['top','bottom','left','right'])assert.ok(css.includes('env(safe-area-inset-'+side+')'));
 assert.match(css,/#live-end\.live-hangup\{[^}]*width:64px;height:64px/);assert.match(css,/#live-end\.live-hangup:focus-visible/);assert.match(css,/call-active[^\n]*#live-error[^\n]*color:#ffafb6/);assert.match(html,/id="live-end"[^>]*aria-label="Akhiri sesi"[^>]*title="Akhiri sesi"><svg/);assert.match(html,/<svg[^>]*aria-hidden="true"[^>]*focusable="false"/);assert.doesNotMatch(html,/>End<\/button>/);
 assert.match(runtime,/callLayout\.setActive\(state!=='ended'\)/);assert.match(runtime,/#live-end'\)\.addEventListener\('click',\(\)=>session\.end\(\)\)/);assert.doesNotMatch(runtime,/requestFullscreen\s*\(/);assert.match(html,/v='call-viewport-20261013'/);
});
