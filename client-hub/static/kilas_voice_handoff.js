/* Explicit drafts only: this module never calls an AI or audio-generation endpoint. */
(()=>{
 const root=document.querySelector('.kilas-home-workspace');if(!root)return;
 const t=(key)=>window.KilasUI?window.KilasUI.t(key):key;
 const input=root.querySelector('#ai-input,#agent-message');
 const notice=root.querySelector('#ai-notice,#agent-chat-error');
 const draftWarning=t('Draf kamu tetap ada. Kosongkan pesan untuk memilih starter.');
 let busy=false,applyingStarter=false,starterDraft=null;
 function clearStarterNotice(){
  if(notice?.dataset.starterNotice!=='draft')return;
  // A later upload/model/transport error owns the same region; leave it alone.
  if(notice.textContent===draftWarning){notice.textContent='';if(notice.id==='agent-chat-error')notice.hidden=true;}
  delete notice.dataset.starterNotice;
 }
 input.addEventListener('input',()=>{if(!applyingStarter)starterDraft=null;if(!input.value.trim())clearStarterNotice();});
 root.querySelectorAll('[data-home-starter]').forEach(button=>button.addEventListener('click',()=>{
   if(input.disabled||input.readOnly||busy)return;
   if(starterDraft===input.value&&input.value===button.dataset.homeStarter){clearStarterNotice();input.focus();return;}
   if(input.value.trim()){
     if(notice){notice.hidden=false;notice.dataset.starterNotice='draft';notice.textContent=draftWarning;}input.focus();return;
   }
   clearStarterNotice();input.value=button.dataset.homeStarter;starterDraft=input.value;applyingStarter=true;
   input.dispatchEvent(new Event('input'));applyingStarter=false;input.focus();
   if(button.hasAttribute('data-starter-document'))root.querySelector('#ai-files,#work-source-files')?.click();
 }));
 document.addEventListener('kilas:request-started',()=>{busy=true;clearStarterNotice();});
 document.addEventListener('kilas:request-finished',()=>{busy=false;});
 window.addEventListener('pageshow',()=>{if(!input.value.trim())clearStarterNotice();});
})();
