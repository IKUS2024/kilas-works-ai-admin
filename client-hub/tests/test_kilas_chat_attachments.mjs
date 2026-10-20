// Attachment DOM, filename escaping and Blob ownership only; no uploads/provider IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('/tmp/kilas-chat-release-dom/package.json');
const {JSDOM}=require('jsdom');
function fixture(){const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'outside-only',url:'https://synthetic.test'}),w=dom.window,created=[],released=[];
 w.KilasUI={t:s=>s};w.URL.createObjectURL=()=>{const u='blob:synthetic-'+created.length;created.push(u);return u;};w.URL.revokeObjectURL=u=>released.push(u);
 for(const name of ['kilas_artifacts.js','kilas_chat_attachments.js'])w.eval(readFileSync(new URL('../static/'+name,import.meta.url),'utf8'));
 return {dom,w,api:w.KilasChatAttachments,created,released};}
const image={name:'12345.jpg',type:'image/jpeg',size:32};
test('image gallery exposes only images and document names are plain text',()=>{const f=fixture(),name='<img src=x onerror=alert(1)>.txt',group=f.api.preview([image,{...image,name:'987.png',type:'image/png'},{name,type:'text/plain',size:40}]);
 assert.equal(group.querySelectorAll('.chat-upload-image').length,2);assert.equal(group.querySelector('.chat-upload-image').textContent,'');assert.ok(!group.textContent.includes('12345'));
 assert.equal(group.querySelector('.ai-file-details strong').textContent,name);assert.equal(group.querySelectorAll('.ai-file-card img').length,0);f.dom.window.close();});
test('pending images have no actionable link or visible filename and release once',()=>{const f=fixture(),card=f.api.pendingImage(image);assert.equal(card.getAttribute('href'),null);assert.equal(card.textContent,'');assert.equal(card.tabIndex,-1);f.api.release(card);f.api.release(card);assert.deepEqual(f.released,f.created);f.dom.window.close();});
test('replacing a gallery revokes only its own URLs',()=>{const f=fixture(),a=f.api.preview([image]),b=f.api.preview([image]);f.api.release(a);assert.deepEqual(f.released,[f.created[0]]);assert.equal(b.querySelector('img').getAttribute('src'),f.created[1]);f.api.release(b);assert.deepEqual(f.released,f.created);f.dom.window.close();});
test('unavailable image has a generic accessible fallback without filename leakage',()=>{const f=fixture(),group=f.api.preview([image]);f.w.document.body.append(group);const img=group.querySelector('img');img.dispatchEvent(new f.w.Event('error'));assert.equal(img.hidden,true);assert.equal(group.querySelectorAll('.chat-upload-unavailable').length,1);assert.ok(!group.textContent.includes('12345'));f.dom.window.close();});
