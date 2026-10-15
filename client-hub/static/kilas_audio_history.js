/* Update only Recent. Form, media, capture and result polling keep their nodes. */
(() => {
  const root=document.querySelector('#audio-history'),region=root?.querySelector('[data-audio-history-content]');
  if(!region)return;
  const status=root.querySelector('[data-audio-history-message]');
  let pending=null,version=0;
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-audio-history-page]');
    if(!button||button.disabled||!root.contains(button))return;
    event.preventDefault();
    const state=region.querySelector('[data-audio-history-state]'),page=Number(button.dataset.audioHistoryPage);
    if(!Number.isInteger(page)||page<1||page>Number(state.dataset.pages))return;
    pending?.abort();const controller=new AbortController(),ticket=++version;pending=controller;
    const oldButtons=[...region.querySelectorAll('[data-audio-history-page]')],disabled=oldButtons.map(b=>b.disabled);
    oldButtons.forEach(b=>b.disabled=true);region.setAttribute('aria-busy','true');status.textContent='Memuat riwayat…';
    const timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const url=new URL(root.dataset.historyUrl,location.origin);
      url.searchParams.set('page',String(page));url.searchParams.set('through',state.dataset.through);
      if(root.dataset.selectedJob)url.searchParams.set('selected',root.dataset.selectedJob);
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
      if(!response.ok||response.redirected)throw Error();
      const body=await response.json();
      if(typeof body.html!=='string'||body.html.length>1024*1024)throw Error();
      const fragment=document.createElement('template');fragment.innerHTML=body.html;
      const next=fragment.content.querySelector('[data-audio-history-state]');
      if(!next||!Number.isInteger(body.page)||!Number.isInteger(body.pages)||body.pages<0||body.page<1||body.page>Math.max(1,body.pages)||Number(next.dataset.page)!==body.page)throw Error();
      if(ticket!==version||controller.signal.aborted||!root.isConnected)return;
      const list=region.querySelector('[data-audio-history-list]'),height=list.getBoundingClientRect().height;
      const pagerHeight=region.querySelector('.audio-history-pages')?.getBoundingClientRect().height||0;
      const x=window.scrollX,y=window.scrollY,focusPager=document.activeElement===document.body||region.contains(document.activeElement);
      next.querySelector('[data-audio-history-list]').style.minHeight=`${Math.ceil(height)}px`;
      region.replaceChildren(fragment.content);
      const pager=region.querySelector('.audio-history-pages');
      if(pager)pager.style.minHeight=`${Math.ceil(pagerHeight)}px`;
      if(focusPager&&pager){pager.tabIndex=-1;pager.focus({preventScroll:true});}
      if(window.scrollX!==x||window.scrollY!==y)window.scrollTo({left:x,top:y,behavior:'instant'});
      status.textContent=body.pages?`Halaman ${body.page} dari ${body.pages}.`:'Belum ada riwayat audio.';
    }catch{
      if(ticket===version&&root.isConnected){oldButtons.forEach((b,i)=>b.disabled=disabled[i]);status.textContent='Riwayat belum dapat dimuat. Silakan coba lagi.';}
    }finally{
      clearTimeout(timeout);
      if(ticket===version){pending=null;region.removeAttribute('aria-busy');}
    }
  });
  window.addEventListener('pagehide',()=>{
    version++;pending?.abort();pending=null;region.removeAttribute('aria-busy');status.textContent='';
    const page=region.querySelector('[data-audio-history-state]').dataset.page;
    region.querySelectorAll('[data-audio-history-page]').forEach(button=>button.disabled=button.dataset.audioHistoryPage===page);
  });
})();
