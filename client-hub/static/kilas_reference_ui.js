/* UI-only helpers; existing request, capture and generation handlers own all work. */
(()=>{
 const t=(key)=>window.KilasUI?window.KilasUI.t(key):key;
 const script=document.querySelector('#audio-script'),count=document.querySelector('#reference-script-count');
 if(script&&count){
  const update=()=>{count.textContent=new Intl.NumberFormat(document.documentElement.lang||'en').format(script.value.length)+' / '+new Intl.NumberFormat(document.documentElement.lang||'en').format(script.maxLength);};
  script.addEventListener('input',update);document.addEventListener('voice-script-edit',update);update();
 }
 const record=document.querySelector('#dictation-start');if(record){const label=document.createElement('span');label.textContent=t('Record Script');record.append(label);}
 const history=document.querySelector('#audio-history'),historyToggle=document.querySelector('.reference-history-toggle');
 historyToggle?.addEventListener('click',()=>{history.hidden=!history.hidden;historyToggle.setAttribute('aria-expanded',String(!history.hidden));if(!history.hidden)history.scrollIntoView({block:'nearest',behavior:'instant'});});
 document.querySelector('[data-reference-my-voice]')?.addEventListener('click',()=>{const mine=document.querySelector('[name=voice_kind][value=personal]');if(mine){mine.checked=true;mine.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#saved-voice-choice')?.focus();}});
})();
