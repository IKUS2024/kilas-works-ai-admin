/* Presentation only. Chat retains its existing transport; other tasks open their own forms. */
(()=>{
  const root=document.querySelector('.kilas-home-workspace');if(!root)return;
  // Layout only: visualViewport shrinks when a mobile on-screen keyboard opens.
  const viewport=window.visualViewport;
  let tallestHeight=window.innerHeight;
  let layoutWidth=window.innerWidth;
  const timeline=root.querySelector('#ai-messages,#agent-conversation');
  const options=root.querySelector('.home-chat-options'),optionsPanel=options?.querySelector('.home-chat-options-panel');
  const secondary=[root.querySelector('.home-workspace-top'),root.querySelector('.home-tool-selector'),root.querySelector('[data-ai-call-launch]')].filter(Boolean).map(element=>{
    const place=document.createComment('Chat control position');element.before(place);return {element,place};
  });
  let compact=false,keyboardInline=false,keyboardOpen=false;
  const fitHierarchy=(width,height,scale)=>{
    const next=Boolean(optionsPanel&&(keyboardOpen||(scale>1.01&&width<800)||height<500||width<280));
    const inline=Boolean(next&&keyboardOpen&&scale<=1.01&&width>=280);
    if(next===compact&&inline===keyboardInline)return;compact=next;keyboardInline=inline;
    document.body.classList.toggle('home-chat-compact',compact);options.hidden=!compact;options.open=false;
    document.body.classList.toggle('home-keyboard-inline',keyboardInline);
    // Keep task navigation and composer actions in place while typing. Only
    // model controls use Options; magnified/narrow views retain the full menu.
    for(const {element,place} of secondary){
      const collapse=compact&&(!keyboardInline||element.matches('.home-workspace-top'));
      if(collapse){if(element.parentElement!==optionsPanel)optionsPanel.append(element);}
      else if(element.previousSibling!==place)place.after(element);
    }
  };
  options?.addEventListener('keydown',event=>{if(event.key==='Escape'){options.open=false;options.querySelector('summary').focus();}});
  options?.addEventListener('click',event=>{if(event.target.closest('[data-ai-call-launch],[data-home-task]'))options.open=false;});
  document.querySelector('#ai-call-dialog')?.addEventListener('close',()=>{if(compact)options?.querySelector('summary').focus({preventScroll:true});});
  root.addEventListener('focusin',event=>{if(event.target.matches('#ai-input,#agent-message')&&options)options.open=false;});
  const following=()=>timeline&&timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight<48;
  const fitViewport=()=>{
    const follow=following();
    const height=viewport?viewport.height:window.innerHeight;
    const scale=viewport?.scale||1;
    document.body.classList.toggle('home-viewport-zoomed',scale>1.01);
    // Page zoom/window reflow changes CSS width as well as height. Start a new
    // keyboard baseline there; a keyboard resize keeps the layout width.
    if(Math.abs(window.innerWidth-layoutWidth)>1){layoutWidth=window.innerWidth;tallestHeight=window.innerHeight;keyboardOpen=false;}
    else tallestHeight=Math.max(tallestHeight,window.innerHeight);
    const editing=document.activeElement?.matches?.('#ai-input,#agent-message');
    document.documentElement.style.setProperty('--home-viewport-height',`${height}px`);
    document.documentElement.style.setProperty('--home-viewport-top',`${viewport?viewport.offsetTop:0}px`);
    // Pinch zoom changes both visible dimensions. Reflow inside that rectangle;
    // normalize its height before detecting a keyboard so zoom alone is not one.
    document.documentElement.style.setProperty('--home-viewport-width',`${viewport?viewport.width:window.innerWidth}px`);
    document.documentElement.style.setProperty('--home-viewport-left',`${viewport?viewport.offsetLeft:0}px`);
    const unscaledHeight=height*scale;
    const viewportShrunk=unscaledHeight<window.innerHeight-100||unscaledHeight<tallestHeight-100;
    // Keep the keyboard layout through focus transfers until its viewport
    // recovers, rather than hiding controls on blur or at the 500px boundary.
    keyboardOpen=Boolean(viewportShrunk&&(editing||keyboardOpen||unscaledHeight<window.innerHeight-100));
    document.body.classList.toggle('home-keyboard-open',keyboardOpen);
    fitHierarchy(viewport?viewport.width:window.innerWidth,height,scale);
    document.documentElement.style.setProperty('--home-input-max-height',`${Math.max(44,Math.min(144,height-330))}px`);
    root.dispatchEvent(new Event('home:viewport'));
    if(follow)timeline.scrollTop=timeline.scrollHeight;
  };
  fitViewport();window.addEventListener('resize',fitViewport);
  if(viewport){viewport.addEventListener('resize',fitViewport);viewport.addEventListener('scroll',fitViewport);}
  window.addEventListener('orientationchange',()=>{tallestHeight=window.innerHeight;fitViewport();});
  root.addEventListener?.('focusin',fitViewport);root.addEventListener?.('focusout',fitViewport);
  const t=message=>window.KilasUI?window.KilasUI.t(message):message;
  const form=root.querySelector('#ai-composer,#agent-chat-form'),input=root.querySelector('#ai-input,#agent-message'),value=root.querySelector('#home-task-value')||document.querySelector('#home-task-handoff [name=task]'),send=root.querySelector('#ai-send')||form.querySelector('button[type=submit]'),notice=root.querySelector('#ai-notice,#agent-chat-error'),context=root.querySelector('#home-task-context');
  const agent=form.id==='agent-chat-form',pending=root.querySelector('#ai-pending,#work-pending-files');
  const drafts={chat:'',video:'',translate:'',voiceover:''};let current='chat';
  const tasks={
    chat:{label:'Tulis pesan',placeholder:'Pesan',button:'Kirim',limit:12000},
    video:{title:'Naskah & ide video',description:'Susun naskah, storyboard, dan prompt. Produksi video dilakukan di tool eksternal.',label:'Ceritakan ide videomu',placeholder:'Produk, tujuan, penonton, atau ide yang ingin dikembangkan...',button:'Buka Video Plan',limit:2400},
    translate:{title:'Terjemahkan audio/video',description:'Pilih bahasa dan unggah audio atau video di formulir terjemahan.',label:'Catatan untuk terjemahan (opsional)',placeholder:'Bahasa tujuan atau catatan yang ingin kamu bawa...',button:'Buka formulir terjemahan',limit:2400},
    voiceover:{title:'Buat suara',description:'Bawa naskahmu, lalu pilih bahasa dan suara di formulir voiceover.',label:'Naskah suara (opsional)',placeholder:'Tulis naskah yang ingin dibacakan...',button:'Buka formulir suara',limit:4000}
  };
  function select(next){
    if(!(next in tasks)||!root.querySelector(`[data-home-task="${next}"]`))return;
    if(next!==current&&(send.disabled||pending.children.length)){
      notice.textContent=t('Selesaikan chat atau hapus lampiran sebelum mengganti tugas.');return;
    }
    drafts[current]=input.value;current=next;value.value=next;input.value=drafts[next];const task=tasks[next];
    input.maxLength=next==='chat'&&agent?1200:task.limit;input.required=agent&&next==='chat';input.placeholder=t(task.placeholder);root.querySelector('[data-home-input-label]').textContent=t(task.label);send.setAttribute('aria-label',t(task.button));send.title=t(task.button);input.dispatchEvent(new Event('input'));
    if(context){context.hidden=next==='chat';root.querySelector('[data-home-context-title]').textContent=t(task.title||'');root.querySelector('[data-home-context-description]').textContent=t(task.description||'');}
    const attach=root.querySelector('[data-home-attachment],.work-attachment-bar');attach.hidden=next!=='chat';root.querySelector('#ai-files,#work-source-files').disabled=next!=='chat';const hint=root.querySelector('[data-home-hint]');if(hint)hint.hidden=next!=='chat';notice.textContent='';
    root.querySelectorAll('[data-home-task]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.homeTask===next)));
  }
  root.querySelectorAll('[data-home-task]').forEach(button=>button.addEventListener('click',()=>{
    const next=button.dataset.homeTask;if(next==='chat'){select('chat');input.focus();return;}
    if(send.disabled||pending.children.length){notice.textContent=t('Selesaikan chat atau hapus lampiran sebelum mengganti tugas.');return;}
    if(input.value.length>tasks[next].limit){notice.textContent=t('Draf terlalu panjang untuk fitur ini. Pendekkan teks sebelum membuka fitur.');return;}
    const handoff=agent?document.querySelector('#home-task-handoff'):form;
    handoff.action=next==='video'?'/kilas-ai/video':'/kilas-translator?mode='+next;handoff.elements.task.value=next;handoff.elements.brief.value=input.value;
    handoff.submit();
  }));
  root.querySelector('[data-home-cancel]')?.addEventListener('click',()=>{select('chat');input.focus();});
  // Capture runs before the legacy chat submit handler. Native POST preserves CSRF and back navigation.
  form.addEventListener('submit',event=>{
    if(current==='chat')return;
    event.stopImmediatePropagation();
    if(send.disabled||pending.children.length){event.preventDefault();return;}
    drafts[current]=input.value;
    if(agent){event.preventDefault();const handoff=document.querySelector('#home-task-handoff');handoff.elements.task.value=current;handoff.elements.brief.value=input.value;handoff.submit();}
  },true);
  if(agent){const fit=()=>{const follow=following(),style=getComputedStyle(input),minimum=parseFloat(style.minHeight)||44;input.style.height='auto';input.style.height=(input.value?Math.min(parseFloat(style.maxHeight)||144,Math.max(minimum,input.scrollHeight)):minimum)+'px';if(follow)timeline.scrollTop=timeline.scrollHeight;};input.addEventListener('input',fit);root.addEventListener('home:viewport',fit);fit();}
  const initial=new URLSearchParams(location.search).get('task');if(initial)select(initial);
  // Reconcile controls after a browser restores this page from its back/forward cache.
  window.addEventListener('pageshow',event=>{if(event.persisted){send.disabled=false;input.disabled=false;select(current);}});
})();
