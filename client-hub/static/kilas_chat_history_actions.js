/* Owned sidebar actions; touch gestures never replace ordinary link navigation. */
(()=>{'use strict';
const rail=document.querySelector('[data-chat-sidebar]'),list=rail?.querySelector('.ai-history'),menu=document.querySelector('[data-chat-context-menu]'),rename=document.querySelector('[data-chat-rename-dialog]'),remove=document.querySelector('[data-chat-delete-dialog]');
if(!list||!menu||!rename||!remove)return;
document.body.append(menu,rename,remove); // Top layer stays outside sidebar inert/overflow boundaries.
const dialogs=[menu,rename,remove];let target=null,press=null,suppressed=null,pending=false;
function identify(link){
 if(!link||!list.contains(link))return null;const url=new URL(link.href,location.origin);if(url.origin!==location.origin)return null;
 const thread=url.pathname.match(/^\/kilas-ai\/threads\/([1-9]\d*)$/),conversation=url.pathname==='/kilas-ai/agent'&&url.searchParams.get('conversation');
 const kind=thread?'thread':conversation&&/^[1-9]\d*$/.test(conversation)?'conversation':null;if(!kind)return null;
 const id=thread?thread[1]:conversation;return {link,kind,id,href:url.href,title:link.textContent.trim(),base:kind==='thread'?'/kilas-ai/threads/'+id:'/kilas-ai/agent/conversations/'+id};
}
function decorate(){for(const link of list.querySelectorAll('a'))if(identify(link)){link.setAttribute('aria-haspopup','menu');link.setAttribute('aria-controls','chat-history-menu');link.setAttribute('aria-keyshortcuts','Shift+F10');}}
decorate();new MutationObserver(decorate).observe(list,{childList:true});
function restore(){const link=[...list.querySelectorAll('a')].find(a=>a.href===target?.href);(link||rail.querySelector('[data-chat-history-toggle]'))?.focus({preventScroll:true});}
function clearPress(block=false){if(press){clearTimeout(press.timer);if(block)suppressed={href:press.target.href,until:performance.now()+800};press=null;}}
function show(link,x,y){const item=identify(link);if(!item||pending)return;target=item;clearPress();if(menu.open)return;
 menu.showModal();const box=menu.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(x,innerWidth-box.width-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-box.height-8))+'px';menu.querySelector('[role=menuitem]').focus();}
list.addEventListener('pointerdown',e=>{
 const item=identify(e.target.closest('a'));if(!item)return;if(!menu.open)suppressed=null;if(!['touch','pen'].includes(e.pointerType)||!e.isPrimary||e.button!==0)return;clearPress();
 const gesture={target:item,x:e.clientX,y:e.clientY,id:e.pointerId};gesture.timer=setTimeout(()=>{if(press!==gesture)return;suppressed={href:item.href,until:Infinity};show(item.link,gesture.x,gesture.y);},550);press=gesture;
},{passive:true});
document.addEventListener('pointermove',e=>{if(press&&e.pointerId===press.id&&Math.hypot(e.clientX-press.x,e.clientY-press.y)>10)clearPress(true);},{passive:true});
for(const name of ['pointerup','pointercancel'])document.addEventListener(name,()=>{clearPress();if(suppressed&&suppressed.until===Infinity)suppressed.until=performance.now()+800;},{passive:true});
list.addEventListener('scroll',()=>clearPress(true),{passive:true});
window.addEventListener('click',e=>{const a=e.target.closest?.('a');if(a&&suppressed?.href===a.href&&performance.now()<suppressed.until){e.preventDefault();e.stopImmediatePropagation();suppressed=null;}},true);
list.addEventListener('contextmenu',e=>{const link=e.target.closest('a');if(!identify(link))return;e.preventDefault();if(suppressed?.href===link.href&&performance.now()<suppressed.until&&!menu.open&&['touch','pen'].includes(e.pointerType))return;if(press)suppressed={href:link.href,until:Infinity};const r=link.getBoundingClientRect();show(link,e.clientX||r.left+16,e.clientY||r.bottom);});
list.addEventListener('keydown',e=>{if(e.key==='ContextMenu'||(e.key==='F10'&&e.shiftKey)){const link=e.target.closest('a');if(!identify(link))return;e.preventDefault();const r=link.getBoundingClientRect();show(link,r.left+16,r.bottom);}});
menu.addEventListener('keydown',e=>{
 if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=[...menu.querySelectorAll('[role=menuitem]')];let i=items.indexOf(document.activeElement);i=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items[i].focus();}
});
for(const dialog of dialogs){
 dialog.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if(!pending){dialog.close();restore();}}});
 dialog.addEventListener('cancel',e=>{e.preventDefault();if(!pending){dialog.close();restore();}});
 dialog.addEventListener('click',e=>{if(e.target===dialog&&!pending){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){dialog.close();restore();}}});
 dialog.querySelectorAll('[data-chat-action-cancel]').forEach(b=>b.addEventListener('click',()=>{if(!pending){dialog.close();restore();}}));
}
menu.addEventListener('click',e=>{const action=e.target.closest('[data-chat-action]')?.dataset.chatAction;if(!action||!target)return;menu.close();
 if(action==='rename'){const field=rename.querySelector('[name=title]');field.value=target.title;field.maxLength=target.kind==='thread'?100:60;rename.querySelector('[data-chat-action-error]').hidden=true;rename.showModal();field.focus();field.select();}
 else{remove.querySelector('[data-chat-delete-title]').textContent=target.title;remove.querySelector('[data-chat-delete-permanent]').hidden=target.kind!=='thread';remove.querySelector('[data-chat-delete-archive]').hidden=target.kind==='thread';remove.querySelector('[data-chat-action-error]').hidden=true;remove.showModal();remove.querySelector('[data-chat-action-cancel]').focus();}
});
async function mutate(e,action,dialog){
 e.preventDefault();if(pending||!target)return;const current=target;const title=action==='rename'?dialog.querySelector('[name=title]').value.trim():null;if(action==='rename'&&!title)return;
 pending=true;const buttons=[...dialog.querySelectorAll('button,input')];buttons.forEach(b=>b.disabled=true);const error=dialog.querySelector('[data-chat-action-error]');error.hidden=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
 try{const data=new URLSearchParams({csrf_token:document.querySelector('meta[name=csrf-token]')?.content||rail.querySelector('[name=csrf_token]')?.value||''});if(title!==null)data.set('title',title);
  const response=await fetch(current.base+'/'+action,{method:'POST',credentials:'same-origin',headers:{Accept:'application/json'},body:data,signal:controller.signal,redirect:'error'});if(!response.ok)throw Error('action');const result=await response.json();
  if(action==='rename'){window.KilasChatHistory?.rename(current.href,result.title);dialog.close();restore();}
  else{const active=current.kind==='thread'?document.querySelector('[data-ai-shell]')?.dataset.threadId===current.id:document.querySelector('#agent-chat-form [name=conversation_id]')?.value===current.id;window.KilasChatHistory?.remove(current.href);dialog.close();
   if(active){const next=new URL(result.next_url,location.origin);if(next.origin!==location.origin||!next.pathname.startsWith('/kilas-ai'))throw Error('redirect');document.dispatchEvent(new Event('kilas:conversation-deleted'));location.assign(next.href);}else restore();}
 }catch(_){error.hidden=false;}finally{clearTimeout(timeout);pending=false;buttons.forEach(b=>b.disabled=false);}
}
rename.querySelector('form').addEventListener('submit',e=>mutate(e,'rename',rename));remove.querySelector('form').addEventListener('submit',e=>mutate(e,'delete',remove));
window.addEventListener('resize',()=>{clearPress();if(menu.open){menu.close();restore();}});
})();
