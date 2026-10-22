/* Explicit drafts only: this module never calls an AI or audio-generation endpoint. */
(()=>{
 const root=document.querySelector('.kilas-home-workspace');if(!root)return;
 const t=(key)=>window.KilasUI?window.KilasUI.t(key):key;
 const input=root.querySelector('#ai-input,#agent-message');
 root.querySelectorAll('[data-home-starter]').forEach(button=>button.addEventListener('click',()=>{
   if(input.disabled)return;
   if(input.value.trim()){
     const notice=root.querySelector('#ai-notice,#agent-chat-error');
     if(notice){notice.hidden=false;notice.textContent=t('Draf kamu tetap ada. Kosongkan pesan untuk memilih starter.');}input.focus();return;
   }
   input.value=button.dataset.homeStarter;input.dispatchEvent(new Event('input'));input.focus();
   if(button.hasAttribute('data-starter-document'))root.querySelector('#ai-files,#work-source-files')?.click();
 }));
 let busy=false;
 const raw=body=>window.KilasMarkdown?.source(body)??body.textContent;
 function addActions(){
  root.querySelectorAll('.ai-assistant,.agent-message-assistant').forEach(article=>{
   const body=article.querySelector('.ai-message-text,.agent-message-text');if(!body||article.querySelector('.chat-voice-draft'))return;
   const text=raw(body);if(!text||text.trim().length<20||/^\s*```/.test(text))return;
   const button=document.createElement('button');button.type='button';button.className='chat-voice-draft';button.textContent=t('Jadikan Voice Over');
   button.title=t('Bawa jawaban atau teks yang dipilih ke editor. Belum membuat suara.');
   button.addEventListener('click',()=>{
    if(busy)return;
    const selection=window.getSelection();
    const selected=selection&&!selection.isCollapsed&&body.contains(selection.anchorNode)&&body.contains(selection.focusNode)?selection.toString():null;
    const script=selected??raw(body),notice=root.querySelector('#ai-notice,#agent-chat-error');
    if(script.length>4000){if(notice){notice.hidden=false;notice.textContent=t('Pilih bagian naskah maksimal 4.000 karakter untuk Voice Over.');}return;}
    if(!script.trim())return;
    const form=document.createElement('form');form.method='post';form.action='/kilas-ai/home-task';form.hidden=true;
    const token=document.querySelector('meta[name=csrf-token]')?.content||root.querySelector('[name=csrf_token]')?.value;
    for(const [name,value] of Object.entries({csrf_token:token,task:'voiceover',brief:script,return_to:location.pathname+location.search})){const field=document.createElement('input');field.type='hidden';field.name=name;field.value=value;form.append(field);}
    button.disabled=true;document.body.append(form);form.submit();
   });article.append(button);
  });
 }
 document.addEventListener('kilas:request-started',()=>{busy=true;root.querySelectorAll('.chat-voice-draft').forEach(b=>b.disabled=true);});
 document.addEventListener('kilas:request-finished',()=>{busy=false;addActions();root.querySelectorAll('.chat-voice-draft').forEach(b=>b.disabled=false);});
 window.addEventListener('pageshow',()=>root.querySelectorAll('.chat-voice-draft').forEach(b=>b.disabled=false));
 addActions();
})();
