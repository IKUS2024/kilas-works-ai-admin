(() => {
  const root=document.querySelector('#audio-studio'); if(!root) return;
  const tabs=[...root.querySelectorAll('[role=tab]')];
  function tab(index,focus=false,updateUrl=true){tabs.forEach((t,i)=>{t.setAttribute('aria-selected',String(i===index));t.tabIndex=i===index?0:-1;document.getElementById(t.getAttribute('aria-controls')).hidden=i!==index;});if(focus)tabs[index].focus();const mode=tabs[index].id==='voiceover-tab'?'voiceover':'translate';root.dataset.activeMode=mode;const title=mode==='voiceover'?'Voice Over':'Kilas Translator';root.querySelector('.audio-heading h1').textContent=title;document.title=title+' · Kilas Works';document.querySelectorAll('[data-kilas-feature]').forEach(a=>{if(a.dataset.kilasFeature===mode)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});const active=document.querySelector('[data-kilas-feature][aria-current]'),row=active?.parentElement;if(active&&row){const a=active.getBoundingClientRect(),r=row.getBoundingClientRect();if(a.right>r.right)row.scrollLeft+=a.right-r.right;if(a.left<r.left)row.scrollLeft-=r.left-a.left;}if(updateUrl){const url=new URL(location.href);url.searchParams.set('mode',mode);history.replaceState(history.state,'',url);}}
  tabs.forEach((t,i)=>{t.addEventListener('click',()=>tab(i));t.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();tab(e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length,true);}});});
  const modeIndex=mode=>Math.max(0,tabs.findIndex(t=>t.id===mode+'-tab'));
  tab(modeIndex(root.dataset.activeMode),false,false);window.addEventListener('popstate',()=>tab(modeIndex(new URL(location.href).searchParams.get('mode')),false,false));
  const progress=document.querySelector('#audio-progress'),error=document.querySelector('#audio-error'),purchase=document.querySelector('#audio-error-purchase');
  let busy=false,inspecting=false,fileVersion=0,inspected=false;
  function message(text){progress.textContent=text;progress.hidden=false;error.hidden=true;purchase.hidden=true;}
  function failure(text,buy=false){progress.hidden=true;error.textContent=text;error.hidden=false;purchase.hidden=true;}
  const csrf=root.querySelector('[name=csrf_token]').value;
  async function post(url,data){const response=await fetch(url,{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});if(response.redirected&&new URL(response.url).pathname==='/login')throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');let body;try{body=await response.json();}catch{throw Error('Audio belum dapat diproses. Coba lagi nanti.');}if(!response.ok){const e=Error(body.error||'Audio belum dapat diproses.');e.purchase=response.status===402;throw e;}return body;}
  const file=document.querySelector('#audio-file');
  file?.addEventListener('change',async()=>{const version=++fileVersion;inspected=false;inspecting=false;if(!file.files.length)return;const chosen=file.files[0],video=/\.mp4$/i.test(chosen.name),cap=Number(video?file.dataset.maxFileMb:file.dataset.maxAudioMb);if(!/\.(mp4|mp3|wav|m4a)$/i.test(chosen.name)){failure('Format tidak didukung. Pilih MP4, MP3, WAV, atau M4A.');return;}if(chosen.size>cap*1024*1024){failure(`File maksimal ${cap} MB.`);return;}inspecting=true;message('Membaca audio…');const data=new FormData();data.append('file',file.files[0]);data.append('csrf_token',csrf);try{const r=await post('/kilas-translator/inspect',data);if(version!==fileVersion)return;document.querySelector('#audio-duration').textContent=`${r.filename} · ${r.duration_label} · memakai ${r.required_seconds}s saldo`;inspected=true;progress.hidden=true;}catch(e){if(version===fileVersion)failure(e.message,e.purchase);}finally{if(version===fileVersion)inspecting=false;}});
  const script=document.querySelector('#audio-script');let scriptVersion=0;script.addEventListener('input',()=>scriptVersion++);script.addEventListener('input',()=>{const text=script.value.trim(),words=text?text.split(/\s+/).length:0;const seconds=text?Math.max(1,Math.ceil(Math.max(words/2.3,text.length/13))):0;const reserve=text?Math.min(Number(root.dataset.maxSeconds),Math.ceil(Math.max(words/0.8,text.length/4)+10)):0;document.querySelector('#voice-estimate').textContent=`Estimasi ${seconds}s · reservasi hingga ${reserve}s. Pemakaian akhir mengikuti MP3 aktual; sisa reservasi dikembalikan.`;});
  let editing=false;
  root.addEventListener('click',async event=>{
    const button=event.target.closest('[data-audio-edit]');if(!button||busy||editing||document.querySelector('#voice-video-script')?.dataset.busy==='true'||root.dataset.dictationBusy==='true')return;
    const snapshot=script.value,version=scriptVersion;editing=true;root.dataset.scriptEditing='true';button.disabled=true;
    try{
      const response=await fetch(button.dataset.audioEdit,{credentials:'same-origin',cache:'no-store'});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk mengedit.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Naskah asli tidak tersedia.');
      if(typeof body.script!=='string'||body.script.length>4000)throw Error('Naskah asli tidak tersedia.');
      if(busy||scriptVersion!==version||script.value!==snapshot)throw Error('Draf telah berubah. Klik Edit lagi bila ingin menggantinya.');
      if(snapshot&&snapshot!==body.script&&!confirm('Ganti draf yang belum dibuat dengan naskah asli hasil ini?'))return;
      if(busy||scriptVersion!==version||script.value!==snapshot)throw Error('Draf telah berubah. Naskah tidak ditimpa.');
      script.value=body.script;script.dispatchEvent(new Event('input',{bubbles:true}));tab(modeIndex('voiceover'));script.scrollIntoView({block:'center'});script.focus();message('Naskah asli siap diedit. Generate Voice Over tetap perlu kamu klik sendiri.');
    }catch(e){failure(e.message||'Naskah belum bisa dibuka. Draf kamu tetap aman.');}
    finally{editing=false;root.dataset.scriptEditing='false';button.disabled=false;}
  });
  const feedbackKey='kilas-audio-generation-feedback';
  function pendingFeedback(value){try{if(value)sessionStorage.setItem(feedbackKey,'pending');else sessionStorage.removeItem(feedbackKey);}catch{}}
  function hasPendingFeedback(){try{return sessionStorage.getItem(feedbackKey)==='pending';}catch{return false;}}
  root.querySelectorAll('[data-audio-form]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy||editing||document.querySelector('#voice-video-script')?.dataset.busy==='true'||root.dataset.dictationBusy==='true')return;
    const mode=form.querySelector('[name=mode]').value;
    if(mode==='voiceover'&&document.querySelector('#personal-voice-setup')?.dataset.busy==='true')return;
    if(mode==='translate'&&(!inspected||inspecting)){failure('Tunggu durasi terbaca sebelum Translate.');return;}
    const data=new FormData(form);busy=true;
    const controls=[...root.querySelectorAll('button,input,textarea,select')],states=controls.map(c=>c.disabled);
    const button=form.querySelector('button[type=submit]'),label=button.textContent;
    controls.forEach(c=>c.disabled=true);button.textContent='Sedang memproses...';form.setAttribute('aria-busy','true');
    if(matchMedia('(hover: hover) and (pointer: fine)').matches===false)document.activeElement?.blur();
    message(mode==='translate'?'Menyiapkan terjemahan...':'Sedang membuat voice over...');
    window.KilasGenerationFeedback?.show('busy',mode==='translate'?'Menyiapkan terjemahan':'Membuat Voice Over','Audio sedang diproses dan hasil akan disimpan. Tidak perlu klik Generate lagi.');pendingFeedback(true);
    try{const r=await post(form.action,data);location.assign(r.url);}
    catch(e){pendingFeedback(false);failure(e.message,e.purchase);window.KilasGenerationFeedback?.show('error','Audio belum berhasil diproses',e.message);controls.forEach((c,i)=>c.disabled=states[i]);button.textContent=label;form.removeAttribute('aria-busy');busy=false;}
  }));
  const result=document.querySelector('#audio-result');let timer=null,polling=false;
  function resultFeedback(){
    if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus)){
      window.KilasGenerationFeedback?.show('busy','Audio sedang diproses','Hasil akan disimpan dan muncul otomatis setelah selesai. Tidak perlu mengirim ulang.');
    }else if(hasPendingFeedback()){
      pendingFeedback(false);
      if(result.dataset.jobStatus==='COMPLETED')window.KilasGenerationFeedback?.show('success','Audio tersimpan','Hasil siap diputar dan diunduh.');
      else if(result.dataset.jobStatus==='FAILED')window.KilasGenerationFeedback?.show('error','Audio belum berhasil diproses',result.querySelector('p')?.textContent||'Periksa status hasil sebelum mencoba lagi.');
    }
  }
  if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus))pendingFeedback(true);
  resultFeedback();
  async function poll(){if(document.hidden||polling||!result.dataset.statusUrl||!['QUEUED','PROCESSING'].includes(result.dataset.jobStatus))return;polling=true;try{const r=await fetch(result.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'});if(!r.ok||r.redirected)return;const body=await r.json();if(body.status!==result.dataset.jobStatus||!result.querySelector('audio'))result.innerHTML=body.html;result.dataset.jobStatus=body.status;resultFeedback();const balance=root.querySelector('.audio-balance');if(balance)balance.innerHTML=body.balance_html;const entry=root.querySelector(`[data-audio-history="${body.id}"]`);if(entry){if(body.edit_script_url&&!entry.parentElement.querySelector('[data-audio-edit]')){const button=document.createElement('button');button.type='button';button.className='btn secondary audio-edit-script';button.dataset.audioEdit=body.edit_script_url;button.textContent='Edit naskah';entry.after(button);}entry.querySelector('[data-audio-history-status]').textContent=body.status_label;entry.querySelector('[data-audio-history-duration]').textContent=body.duration_label;}if(!['QUEUED','PROCESSING'].includes(body.status)){clearTimeout(timer);return;}}catch{}finally{polling=false;if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus)&&!document.hidden)timer=setTimeout(poll,10000);}}
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)poll();});window.addEventListener('focus',()=>{clearTimeout(timer);poll();});poll();
})();
