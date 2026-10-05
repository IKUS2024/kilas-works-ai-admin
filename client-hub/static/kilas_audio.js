(() => {
  const root=document.querySelector('#audio-studio'); if(!root) return;
  const tabs=[...root.querySelectorAll('[role=tab]')];
  function tab(index,focus=false){tabs.forEach((t,i)=>{t.setAttribute('aria-selected',String(i===index));t.tabIndex=i===index?0:-1;document.getElementById(t.getAttribute('aria-controls')).hidden=i!==index;});if(focus)tabs[index].focus();}
  tabs.forEach((t,i)=>{t.addEventListener('click',()=>tab(i));t.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();tab(e.key==='Home'?0:e.key==='End'?1:1-i,true);}});});
  if(root.dataset.activeMode==='voiceover')tab(1);
  const progress=document.querySelector('#audio-progress'),error=document.querySelector('#audio-error'),purchase=document.querySelector('#audio-error-purchase');
  let busy=false,inspecting=false,fileVersion=0,inspected=false;
  function message(text){progress.textContent=text;progress.hidden=false;error.hidden=true;purchase.hidden=true;}
  function failure(text,buy=false){progress.hidden=true;error.textContent=text;error.hidden=false;purchase.hidden=!buy;}
  const csrf=root.querySelector('[name=csrf_token]').value;
  async function post(url,data){const response=await fetch(url,{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':csrf}});if(response.redirected&&new URL(response.url).pathname==='/login')throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');let body;try{body=await response.json();}catch{throw Error('Audio belum dapat diproses. Coba lagi nanti.');}if(!response.ok){const e=Error(body.error||'Audio belum dapat diproses.');e.purchase=response.status===402;throw e;}return body;}
  const file=document.querySelector('#audio-file');
  file.addEventListener('change',async()=>{const version=++fileVersion;inspected=false;inspecting=false;if(!file.files.length)return;const chosen=file.files[0],video=/\.mp4$/i.test(chosen.name),cap=Number(video?file.dataset.maxFileMb:file.dataset.maxAudioMb);if(!/\.(mp4|mp3|wav|m4a)$/i.test(chosen.name)){failure('Format tidak didukung. Pilih MP4, MP3, WAV, atau M4A.');return;}if(chosen.size>cap*1024*1024){failure(`File maksimal ${cap} MB.`);return;}inspecting=true;message('Membaca audio…');const data=new FormData();data.append('file',file.files[0]);data.append('csrf_token',csrf);try{const r=await post('/kilas-translator/inspect',data);if(version!==fileVersion)return;document.querySelector('#audio-duration').textContent=`${r.filename} · ${r.duration_label} · memakai ${r.required_seconds}s saldo`;inspected=true;progress.hidden=true;}catch(e){if(version===fileVersion)failure(e.message,e.purchase);}finally{if(version===fileVersion)inspecting=false;}});
  const script=document.querySelector('#audio-script');script.addEventListener('input',()=>{const text=script.value.trim(),words=text?text.split(/\s+/).length:0;const seconds=text?Math.max(1,Math.ceil(Math.max(words/2.3,text.length/13))):0;const reserve=text?Math.min(Number(root.dataset.maxSeconds),Math.ceil(Math.max(words/0.8,text.length/4)+10)):0;document.querySelector('#voice-estimate').textContent=`Estimasi ${seconds}s · reservasi hingga ${reserve}s. Pemakaian akhir mengikuti MP3 aktual; sisa reservasi dikembalikan.`;});
  const feedbackKey='kilas-audio-generation-feedback';
  function pendingFeedback(value){try{if(value)sessionStorage.setItem(feedbackKey,'pending');else sessionStorage.removeItem(feedbackKey);}catch{}}
  function hasPendingFeedback(){try{return sessionStorage.getItem(feedbackKey)==='pending';}catch{return false;}}
  root.querySelectorAll('[data-audio-form]').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;
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
  async function poll(){if(document.hidden||polling||!result.dataset.statusUrl||!['QUEUED','PROCESSING'].includes(result.dataset.jobStatus))return;polling=true;try{const r=await fetch(result.dataset.statusUrl,{credentials:'same-origin',cache:'no-store'});if(!r.ok||r.redirected)return;const body=await r.json();if(body.status!==result.dataset.jobStatus||!result.querySelector('audio'))result.innerHTML=body.html;result.dataset.jobStatus=body.status;resultFeedback();root.querySelector('.audio-balance').innerHTML=body.balance_html;const entry=root.querySelector(`[data-audio-history="${body.id}"]`);if(entry){entry.querySelector('[data-audio-history-status]').textContent=body.status_label;entry.querySelector('[data-audio-history-duration]').textContent=body.duration_label;}if(!['QUEUED','PROCESSING'].includes(body.status)){clearTimeout(timer);return;}}catch{}finally{polling=false;if(['QUEUED','PROCESSING'].includes(result.dataset.jobStatus)&&!document.hidden)timer=setTimeout(poll,10000);}}
  document.addEventListener('visibilitychange',()=>{clearTimeout(timer);if(!document.hidden)poll();});window.addEventListener('focus',()=>{clearTimeout(timer);poll();});poll();
})();
