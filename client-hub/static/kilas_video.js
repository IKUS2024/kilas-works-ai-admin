(() => {
  'use strict';
  const t=(message, values)=>window.KilasUI ? window.KilasUI.t(message, values) : message;

  const root=document.querySelector('#video-studio');if(!root)return;
  const form=root.querySelector('#video-composer'),input=root.querySelector('#video-idea');
  const quotaBlocked=root.dataset.quotaBlocked==='true';
  if(quotaBlocked)root.querySelectorAll('[data-video-regenerate]').forEach(b=>b.disabled=true);
  function splitPreview(){
    const multi=form.elements.plan_mode.value==='multi',totalField=form.elements.total_duration;
    root.querySelector('#video-multi-controls').hidden=!multi;
    totalField.disabled=!multi;totalField.required=multi;form.elements.clip_strategy.disabled=!multi;
    form.elements.duration.disabled=multi;
    totalField.setCustomValidity('');
    const total=Number(totalField.value),strategy=form.elements.clip_strategy.value;
    const preview=root.querySelector('#video-split-preview');
    if(!multi||!Number.isInteger(total)||total<5||total>180){preview.textContent='';return;}
    const count=strategy==='auto'?Math.max(2,Math.ceil(total/10)):Math.ceil(total/Number(strategy));
    if(count>8){const message=t('Maksimal 8 klip per rencana. Kurangi total durasi atau pilih klip lebih panjang.');totalField.setCustomValidity(message);preview.textContent=message;return;}
    if(count<2){const message=t('Tambahkan durasi atau pilih klip lebih pendek agar ada minimal 2 klip.');totalField.setCustomValidity(message);preview.textContent=message;return;}
    const base=Math.floor(total/count),extra=total%count;let start=0;const ranges=[];
    for(let i=0;i<count;i++){const length=strategy==='auto'?base+(i<extra?1:0):Math.min(Number(strategy),total-start);ranges.push(`${start}–${start+length}s`);start+=length;}
    preview.textContent=t('{count} klip · {timeline}',{count,timeline:ranges.join(' / ')});
  }
  form.addEventListener('change',splitPreview);
  form.elements.total_duration.addEventListener('input',splitPreview);splitPreview();
  let pending=[];
  const picker=root.querySelector('#video-references'),previews=root.querySelector('#video-previews');
  function showPending(){
    previews.replaceChildren();
    pending.forEach((file,index)=>{const wrap=document.createElement('div');wrap.className='video-preview';
      const img=document.createElement('img');img.alt=file.name;const url=URL.createObjectURL(file);img.src=url;img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>URL.revokeObjectURL(url);
      const name=document.createElement('span');name.textContent=file.name;
      const remove=document.createElement('button');remove.type='button';remove.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';remove.setAttribute('aria-label',t('Hapus referensi ')+file.name);remove.onclick=()=>{pending.splice(index,1);showPending();};
      wrap.append(img,remove,name);previews.append(wrap);});
  }
  picker?.addEventListener('change',()=>{pending.push(...picker.files);picker.value='';showPending();});
  root.addEventListener('click',async event=>{
    const dialog=root.querySelector('#video-delete-dialog');
    const regenerate=event.target.closest('[data-video-regenerate]');
    if(regenerate){if(form.getAttribute('aria-busy')==='true')return;form.dataset.generation=regenerate.dataset.videoRegenerate;form.noValidate=true;form.requestSubmit();form.noValidate=false;return;}
    if(event.target.closest('[data-video-delete]')){dialog?.showModal();return;}
    if(event.target.closest('[data-video-cancel]')){dialog?.close();return;}
    const example=event.target.closest('[data-video-example]');if(example){input.value=example.dataset.videoExample;input.focus();return;}
    const copy=event.target.closest('[data-video-copy]');if(copy){
      const status=root.querySelector('[data-video-copy-status]');
      root.querySelectorAll('[data-video-copy]').forEach(button=>{if(button.dataset.copyLabel)button.textContent=button.dataset.copyLabel;});
      copy.dataset.copyLabel ||= copy.textContent;
      try{const payload=JSON.parse(root.querySelector('#video-copy-data').textContent);const text=payload[copy.dataset.videoCopy];
        if(!text)throw new Error();
        if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(text);
        else {const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.left='-9999px';document.body.append(area);area.select();const ok=document.execCommand('copy');area.remove();copy.focus({preventScroll:true});if(!ok)throw new Error();}
        copy.textContent=copy.dataset.copyLabel+' · '+t('Tersalin');
        status.textContent=t('Tersalin. Siap ditempel ke tool pilihanmu.');
      }catch{copy.textContent=copy.dataset.copyLabel+' · '+t('Belum tersalin');status.textContent=t('Belum bisa menyalin. Pilih teks prompt lalu salin secara manual.');}
    }
  });
  root.querySelector('#video-retry').addEventListener('click',()=>{form.dataset.generation=form.dataset.retryGeneration||'all';form.noValidate=form.dataset.generation!=='all';form.requestSubmit();form.noValidate=false;});
  form?.addEventListener('submit',async event=>{
    event.preventDefault();const generation=form.dataset.generation||'all';delete form.dataset.generation;
    if(quotaBlocked)return;
    if(form.getAttribute('aria-busy')==='true')return;
    if(generation==='all'&&!form.reportValidity())return;
    const button=root.querySelector('#video-submit'),status=root.querySelector('#video-status'),error=root.querySelector('#video-error');
    const data=new FormData(form);data.delete('references');if(!form.elements.project_id.value)pending.forEach(file=>data.append('references',file));
    data.set('generation',generation);
    if(generation!=='all')data.set('idea',generation==='video'?'Buat ulang prompt video berdasarkan storyboard aktif. Pertahankan semua scene, subjek, identitas, dan durasi.':'Susun ulang storyboard dan prompt gambar untuk konsep aktif, lalu buat prompt video yang sesuai.');
    const regenerators=[...root.querySelectorAll('[data-video-regenerate]')].map(b=>[b,b.disabled]);regenerators.forEach(([b])=>b.disabled=true);
    const originalLabel=button.textContent;
    input.blur();button.disabled=true;button.textContent=t('Sedang memproses…');picker.disabled=true;form.setAttribute('aria-busy','true');error.hidden=true;status.textContent=t('Sedang menyusun dan menyimpan Video Plan…');
    window.KilasGenerationFeedback?.show('busy','Menyusun Video Plan','Kilas sedang membuat dan menyimpan rencana. Tidak perlu klik Generate lagi.');
    try{const response=await fetch(form.action,{method:'POST',body:data,headers:{'Accept':'application/json'}});if(response.redirected){location.assign(response.url);return;}
      const result=await response.json().catch(()=>{throw new Error(t('Video Plan belum berhasil dibuat.'));});if(!response.ok){
        if(result.processing){status.textContent=t(result.error);window.KilasGenerationFeedback?.show('info','Proses masih berjalan',result.error);return;}
        form.dataset.retryGeneration=generation;
        form.elements.operation_key.value=crypto.randomUUID().replaceAll('-','');
        if(result.id){form.elements.project_id.value=result.id;form.elements.version.value=result.version;history.replaceState(null,'',result.url);root.querySelector('#video-reference-control').hidden=true;pending=[];showPending();}
        const problem=new Error(t(result.error||'Video Plan belum berhasil dibuat.'));problem.detail=result.detail;throw problem;
      }
      root.querySelector('#video-result').innerHTML=result.html;
      root.querySelector('#video-active-title').textContent=result.title;
      root.querySelector('#video-active-version').textContent=t('Versi ')+result.version+t(' · Rencana aktif');
      root.querySelector('#video-revision-context').hidden=false;
      root.querySelector('#video-outline').hidden=false;
      root.querySelectorAll('[data-video-multi-link]').forEach(link=>{link.hidden=!root.querySelector('#video-parts');});
      root.querySelector('#video-project-actions').innerHTML=result.manage_html;
      form.elements.project_id.value=result.id;form.elements.version.value=result.version;form.elements.operation_key.value=crypto.randomUUID().replaceAll('-','');
      for(const [key,value] of Object.entries(result.controls))if(form.elements[key])form.elements[key].value=value;
      splitPreview();
      if(generation==='all')input.value='';input.placeholder=t('Contoh: lebih premium, tanpa voice-over, produknya tetap sama.');
      root.querySelector('#video-composer-label').textContent=t('Ubah atau sempurnakan rencana');
      root.querySelector('#video-reference-control').hidden=true;pending=[];showPending();button.textContent=t('Perbarui rencana');
      history.replaceState(null,'',result.url);status.textContent=t('Rencana tersimpan. Kamu bisa menyalin prompt atau meminta revisi.');
      window.KilasGenerationFeedback?.show('success','Video Plan tersimpan','Rencana siap dilihat. Kamu bisa menyalin prompt atau meminta revisi.');
      const list=root.querySelector('.video-history>ul')||document.createElement('ul');const link=document.createElement('a');link.href=result.url;link.textContent=result.title;link.setAttribute('aria-current','page');
      list.querySelectorAll('a').forEach(a=>{a.removeAttribute('aria-current');if(a.getAttribute('href')===result.url)a.parentElement.remove();});const item=document.createElement('li');item.append(link);list.prepend(item);
      if(!list.parentElement){root.querySelector('.video-history>p')?.remove();root.querySelector('.video-history>h2').after(list);}
      // No automatic composer focus: completing a plan must not reopen a mobile keyboard.
    }catch(problem){form.dataset.retryGeneration=generation;if(form.elements.project_id.value)form.elements.operation_key.value=crypto.randomUUID().replaceAll('-','');root.querySelector('#video-error-title').textContent=t('Video Plan belum berhasil dibuat.');root.querySelector('#video-error-detail').textContent=t(problem.detail||(problem.message!=='Video Plan belum berhasil dibuat.'?problem.message:'Ide dan pengaturanmu tetap tersimpan. Coba lagi.'));error.hidden=false;status.textContent='';window.KilasGenerationFeedback?.show('error','Video Plan belum berhasil',root.querySelector('#video-error-detail').textContent);}
    finally{document.dispatchEvent(new Event('kilas:request-finished'));if(button.textContent===t('Sedang memproses…'))button.textContent=originalLabel;button.disabled=false;picker.disabled=false;regenerators.forEach(([b,disabled])=>b.disabled=disabled);form.removeAttribute('aria-busy');}
  });
})();
