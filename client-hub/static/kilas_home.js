/* Presentation only. Chat retains its existing transport; other tasks open their own forms. */
(()=>{
  const root=document.querySelector('.kilas-home-workspace');if(!root)return;
  const t=message=>window.KilasUI?window.KilasUI.t(message):message;
  const form=root.querySelector('#ai-composer'),input=root.querySelector('#ai-input'),value=root.querySelector('#home-task-value'),send=root.querySelector('#ai-send'),notice=root.querySelector('#ai-notice'),context=root.querySelector('#home-task-context');
  const drafts={chat:'',video:'',translate:'',voiceover:''};let current='chat';
  const tasks={
    chat:{label:'Tulis pesan',placeholder:'Tulis pesan untuk Kilas AI...',button:'Kirim',limit:12000},
    video:{title:'Naskah & ide video',description:'Susun naskah, storyboard, dan prompt. Produksi video dilakukan di tool eksternal.',label:'Ceritakan ide videomu',placeholder:'Produk, tujuan, penonton, atau ide yang ingin dikembangkan...',button:'Buka Video Plan',limit:2400},
    translate:{title:'Terjemahkan audio/video',description:'Pilih bahasa dan unggah audio atau video di formulir terjemahan.',label:'Catatan untuk terjemahan (opsional)',placeholder:'Bahasa tujuan atau catatan yang ingin kamu bawa...',button:'Buka formulir terjemahan',limit:2400},
    voiceover:{title:'Buat suara',description:'Bawa naskahmu, lalu pilih bahasa dan suara di formulir voiceover.',label:'Naskah suara (opsional)',placeholder:'Tulis naskah yang ingin dibacakan...',button:'Buka formulir suara',limit:4000}
  };
  function select(next){
    if(!(next in tasks))return;
    if(next!==current&&(send.disabled||root.querySelector('#ai-pending').children.length)){
      notice.textContent=t('Selesaikan chat atau hapus lampiran sebelum mengganti tugas.');return;
    }
    drafts[current]=input.value;current=next;value.value=next;input.value=drafts[next];const task=tasks[next];
    input.maxLength=task.limit;input.placeholder=t(task.placeholder);root.querySelector('[data-home-input-label]').textContent=t(task.label);send.textContent=t(task.button);
    context.hidden=next==='chat';root.querySelector('[data-home-context-title]').textContent=t(task.title||'');root.querySelector('[data-home-context-description]').textContent=t(task.description||'');
    root.querySelector('[data-home-attachment]').hidden=next!=='chat';root.querySelector('#ai-files').disabled=next!=='chat';root.querySelector('[data-home-hint]').hidden=next!=='chat';notice.textContent='';
    root.querySelectorAll('[data-home-task]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.homeTask===next)));
  }
  root.querySelectorAll('[data-home-task]').forEach(button=>button.addEventListener('click',()=>select(button.dataset.homeTask)));
  root.querySelector('[data-home-cancel]').addEventListener('click',()=>{select('chat');input.focus();});
  // Capture runs before the legacy chat submit handler. Native POST preserves CSRF and back navigation.
  form.addEventListener('submit',event=>{
    if(current==='chat')return;
    event.stopImmediatePropagation();
    if(send.disabled||root.querySelector('#ai-pending').children.length){event.preventDefault();return;}
    drafts[current]=input.value;
  },true);
  const initial=new URLSearchParams(location.search).get('task');if(initial)select(initial);
  // Reconcile controls after a browser restores this page from its back/forward cache.
  window.addEventListener('pageshow',event=>{if(event.persisted){send.disabled=false;input.disabled=false;select(current);}});
})();
