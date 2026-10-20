(() => {
  const t=(message,values)=>window.KilasUI ? window.KilasUI.t(message,values) : Object.entries(values||{}).reduce((text,[key,value])=>text.replaceAll('{'+key+'}',String(value)),message);
  const root=document.querySelector('#audio-studio'); if(!root) return;
  const tabs=[...root.querySelectorAll('[role=tab]')];
  function tab(index,focus=false,updateUrl=true){tabs.forEach((t,i)=>{t.setAttribute('aria-selected',String(i===index));t.tabIndex=i===index?0:-1;document.getElementById(t.getAttribute('aria-controls')).hidden=i!==index;});if(focus)tabs[index].focus();const mode=tabs[index].id==='voiceover-tab'?'voiceover':'translate';root.dataset.activeMode=mode;document.dispatchEvent(new Event('audio-mode-change'));const title=mode==='voiceover'?'Voice Over':'Kilas Translator';root.querySelector('.audio-heading h1').textContent=title;document.title=title+' · Kilas Works';document.querySelectorAll('[data-kilas-feature]').forEach(a=>{if(a.dataset.kilasFeature===mode)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});const active=document.querySelector('[data-kilas-feature][aria-current]'),row=active?.parentElement;if(active&&row){const a=active.getBoundingClientRect(),r=row.getBoundingClientRect();if(a.right>r.right)row.scrollLeft+=a.right-r.right;if(a.left<r.left)row.scrollLeft-=r.left-a.left;}if(updateUrl){const url=new URL(location.href);url.searchParams.set('mode',mode);history.replaceState(history.state,'',url);}}
  tabs.forEach((t,i)=>{t.addEventListener('click',()=>tab(i));t.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();tab(e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length,true);}});});
  const modeIndex=mode=>Math.max(0,tabs.findIndex(t=>t.id===mode+'-tab'));
  tab(modeIndex(root.dataset.activeMode),false,false);window.addEventListener('popstate',()=>tab(modeIndex(new URL(location.href).searchParams.get('mode')),false,false));
  const progress=document.querySelector('#audio-progress'),error=document.querySelector('#audio-error'),purchase=document.querySelector('#audio-error-purchase');
  let busy=false,inspecting=false,fileVersion=0,inspected=false;
  function message(text){progress.textContent=text;progress.hidden=false;error.hidden=true;purchase.hidden=true;}
  function failure(text,buy=false){progress.hidden=true;error.textContent=t(text);error.hidden=false;purchase.hidden=true;}
  const csrf=root.querySelector('[name=csrf_token]').value;
  async function timedFetch(url,options={},timeout=90000){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);try{const response=await fetch(url,{...options,signal:controller.signal});if(response.redirected)throw Error(t('Sesi berakhir. Masuk kembali untuk melanjutkan.'));let body;try{body=await response.json();}catch(error){if(error.name==='AbortError')throw error;throw Error(t('Audio belum dapat diproses. Coba lagi nanti.'));}if(!body||typeof body!=='object')throw Error(t('Audio belum dapat diproses. Coba lagi nanti.'));return {response,body};}finally{clearTimeout(timer);}}
  async function post(url,data){const {response,body}=await timedFetch(url,{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});if(response.redirected&&new URL(response.url).pathname==='/login')throw Error(t('Sesi berakhir. Masuk kembali untuk melanjutkan.'));if(!response.ok){const e=Error(body.error||t('Audio belum dapat diproses.'));e.purchase=response.status===402;throw e;}return body;}
  const file=document.querySelector('#audio-file');
  file?.addEventListener('change',async()=>{const version=++fileVersion;inspected=false;inspecting=false;if(!file.files.length)return;const chosen=file.files[0],video=/\.mp4$/i.test(chosen.name),cap=Number(video?file.dataset.maxFileMb:file.dataset.maxAudioMb);if(!/\.(mp4|mp3|wav|m4a)$/i.test(chosen.name)){failure(t('Format tidak didukung. Pilih MP4, MP3, WAV, atau M4A.'));return;}if(chosen.size>cap*1024*1024){failure(t("File maksimal {value0} MB.", {value0: (cap)}));return;}inspecting=true;message(t('Membaca audio…'));const data=new FormData();data.append('file',file.files[0]);data.append('csrf_token',csrf);try{const r=await post('/kilas-translator/inspect',data);if(version!==fileVersion)return;document.querySelector('#audio-duration').textContent=t("{value0} · {value1} · memakai {value2}s saldo", {value0: (r.filename), value1: (r.duration_label), value2: (r.required_seconds)});inspected=true;progress.hidden=true;}catch(e){if(version===fileVersion)failure(e.message,e.purchase);}finally{if(version===fileVersion)inspecting=false;}});
  const script=document.querySelector('#audio-script');let scriptVersion=0;script.addEventListener('input',()=>scriptVersion++);
  let editing=false;
  const editControls='#voice-translate-toggle,#voice-translation-target,#voice-translated-script,#kilas-voice-choice,#saved-voice-choice,[name=voice_kind],#voice-language';
  ['input','change'].forEach(type=>root.addEventListener(type,event=>{if(event.target.matches(editControls))scriptVersion++;}));
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-audio-edit]');if(!button||busy||editing||document.querySelector('#personal-voice-setup')?.dataset.busy==='true'||document.querySelector('#voice-video-script')?.dataset.busy==='true'||root.dataset.dictationBusy==='true')return;
    const snapshot=script.value,version=scriptVersion;editing=true;root.dataset.scriptEditing='true';button.disabled=true;
    try{
      const {response,body}=await timedFetch(button.dataset.audioEdit,{credentials:'same-origin',cache:'no-store'},15000);
      if(response.redirected)throw Error(t('Sesi berakhir. Masuk kembali untuk mengedit.'));
      if(!response.ok)throw Error(body.error||t('Naskah yang diucapkan tidak tersedia.'));
      if(typeof body.script!=='string'||body.script.length>4000)throw Error(t('Naskah yang diucapkan tidak tersedia.'));
      if(busy||scriptVersion!==version||script.value!==snapshot)throw Error(t('Draf telah berubah. Klik Edit lagi bila ingin menggantinya.'));
      if(snapshot&&snapshot!==body.script&&!confirm(t('Ganti draf yang belum dibuat dengan naskah yang diucapkan pada hasil ini?')))return;
      if(busy||scriptVersion!==version||script.value!==snapshot)throw Error(t('Draf telah berubah. Naskah tidak ditimpa.'));
      if(body.source_kind!=='spoken_script'||typeof body.language!=='string'||(body.language!=='auto'&&![...document.querySelector('#voice-translation-target').options].some(option=>option.value===body.language)))throw Error(t('Naskah yang diucapkan tidak tersedia.'));
      document.querySelector('#voiceover-panel [name=operation_key]').value=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
      document.dispatchEvent(new CustomEvent('voice-script-edit',{detail:body}));
      script.value=body.script;script.dispatchEvent(new Event('input',{bubbles:true}));tab(modeIndex('voiceover'));script.scrollIntoView({block:'center'});script.focus();message(t(body.voiceRestored?'Naskah yang diucapkan siap diedit. Klik Generate Voice Over untuk membuat audio baru.':'Naskah yang diucapkan siap diedit. Suara sebelumnya tidak tersedia; pilih suara sebelum membuat audio baru.'));
    }catch(e){failure(e.message||t('Naskah belum bisa dibuka. Draf kamu tetap aman.'));}
    finally{editing=false;root.dataset.scriptEditing='false';button.disabled=false;}
  });
  const feedbackKey='kilas-audio-generation-feedback';
  function pendingFeedback(value){try{if(value)sessionStorage.setItem(feedbackKey,'pending');else sessionStorage.removeItem(feedbackKey);}catch{}}
  function hasPendingFeedback(){try{return sessionStorage.getItem(feedbackKey)==='pending';}catch{return false;}}
  root.querySelectorAll('[data-audio-form]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy||editing||document.querySelector('#voice-video-script')?.dataset.busy==='true'||root.dataset.dictationBusy==='true')return;
    const mode=form.querySelector('[name=mode]').value;
    if(mode==='voiceover'&&document.querySelector('#personal-voice-setup')?.dataset.busy==='true')return;
    if(mode==='translate'&&(!inspected||inspecting)){failure(t('Tunggu durasi terbaca sebelum Translate.'));return;}
    const data=new FormData(form);busy=true;
    const controls=[...root.querySelectorAll('button,input,textarea,select')],states=controls.map(c=>c.disabled);
    const button=form.querySelector('button[type=submit]'),label=button.textContent;
    controls.forEach(c=>c.disabled=true);button.textContent=t('Sedang memproses...');form.setAttribute('aria-busy','true');
    if(matchMedia('(hover: hover) and (pointer: fine)').matches===false)document.activeElement?.blur();
    message(mode==='translate'?t('Menyiapkan terjemahan...'):t('Sedang membuat voice over...'));
    window.KilasGenerationFeedback?.show('busy',mode==='translate'?t('Menyiapkan terjemahan'):t('Membuat Voice Over'),t('Audio sedang diproses dan hasil akan disimpan. Tidak perlu klik Generate lagi.'));pendingFeedback(true);
    try{const r=await post(form.action,data);location.assign(r.url);}
    catch(e){pendingFeedback(false);failure(e.name==='AbortError'?t('Periksa riwayat sebelum mencoba lagi. Permintaan mungkin masih diproses.'):e.message,e.purchase);window.KilasGenerationFeedback?.show('error',t('Audio belum berhasil diproses'),e.message);controls.forEach((c,i)=>c.disabled=states[i]);button.textContent=label;form.removeAttribute('aria-busy');busy=false;}
  }));
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-audio-alternate]');
    if(!button||busy||editing||root.dataset.dictationBusy==='true'||document.querySelector('#personal-voice-setup')?.dataset.busy==='true'||document.querySelector('#voice-video-script')?.dataset.busy==='true')return;
    // Retry only on an explicit click, with the same key after ambiguous transport failure.
    const storageKey='kilas-voice-alternate:'+button.dataset.audioAlternate;
    try{button.dataset.operationKey ||= sessionStorage.getItem(storageKey)||crypto.randomUUID();sessionStorage.setItem(storageKey,button.dataset.operationKey);}catch{button.dataset.operationKey ||= crypto.randomUUID();}
    const data=new FormData();data.append('operation_key',button.dataset.operationKey);data.append('csrf_token',csrf);
    const controls=[...root.querySelectorAll('button,input,textarea,select')],states=controls.map(c=>c.disabled),label=button.textContent;
    busy=true;controls.forEach(c=>c.disabled=true);button.textContent=t('Sedang memproses...');button.setAttribute('aria-busy','true');
    message(t('Sedang membuat voice over...'));pendingFeedback(true);
    try{const response=await post(button.dataset.audioAlternate,data);try{sessionStorage.removeItem(storageKey);}catch{}location.assign(response.url);}
    catch(e){pendingFeedback(false);failure(e.name==='AbortError'?t('Periksa riwayat sebelum mencoba lagi. Permintaan mungkin masih diproses.'):e.message);controls.forEach((c,i)=>c.disabled=states[i]);button.textContent=label;button.removeAttribute('aria-busy');busy=false;}
  });
  const result=document.querySelector('#audio-result');let timer=null,polling=false;
  function resultFeedback(){
    if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus)){
      window.KilasGenerationFeedback?.show('busy',t('Audio sedang diproses'),t('Hasil akan disimpan dan muncul otomatis setelah selesai. Tidak perlu mengirim ulang.'));
    }else if(hasPendingFeedback()){
      pendingFeedback(false);
      if(result.dataset.jobStatus==='COMPLETED')window.KilasGenerationFeedback?.show('success',t('Audio tersimpan'),t('Hasil siap diputar dan diunduh.'));
      else if(result.dataset.jobStatus==='FAILED')window.KilasGenerationFeedback?.show('error',t('Audio belum berhasil diproses'),result.querySelector('p')?.textContent||t('Periksa status hasil sebelum mencoba lagi.'));
    }
  }
  if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus))pendingFeedback(true);
  resultFeedback();
  result.addEventListener('error',event=>{if(!event.target.matches('audio,video'))return;if(result.querySelector('[data-audio-reload]'))return;const button=document.createElement('button');button.type='button';button.className='btn secondary';button.dataset.audioReload='true';button.textContent=t('Muat ulang audio');button.addEventListener('click',()=>{event.target.load();button.remove();});event.target.after(button);},true);
  async function poll(){if(document.hidden||polling||!result.dataset.statusUrl||!['QUEUED','PROCESSING'].includes(result.dataset.jobStatus))return;polling=true;try{const {response:r,body}=await timedFetch(result.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'},15000);if(!r.ok||r.redirected)return;if(body.status!==result.dataset.jobStatus||!result.querySelector('audio'))result.innerHTML=body.html;result.dataset.jobStatus=body.status;resultFeedback();const balance=root.querySelector('.audio-balance');if(balance)balance.innerHTML=body.balance_html;const entry=root.querySelector(`[data-audio-history="${body.id}"]`);if(entry){if(body.edit_script_url&&!entry.parentElement.querySelector('[data-audio-edit]')){const button=document.createElement('button');button.type='button';button.className='btn secondary audio-edit-script';button.dataset.audioEdit=body.edit_script_url;button.textContent=t('Edit naskah');entry.after(button);}entry.querySelector('[data-audio-history-status]').textContent=body.status_label;entry.querySelector('[data-audio-history-duration]').textContent=body.duration_label;}if(!['QUEUED','PROCESSING'].includes(body.status)){clearTimeout(timer);return;}}catch{}finally{polling=false;if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus)&&!document.hidden)timer=setTimeout(poll,10000);}}
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)poll();});window.addEventListener('focus',()=>{clearTimeout(timer);poll();});poll();
})();
