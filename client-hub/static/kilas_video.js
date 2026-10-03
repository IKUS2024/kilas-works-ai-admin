(() => {
  'use strict';
  const root=document.querySelector('#video-studio');if(!root)return;
  const form=root.querySelector('#video-composer'),input=root.querySelector('#video-idea');
  let pending=[];
  const picker=root.querySelector('#video-references'),previews=root.querySelector('#video-previews');
  function showPending(){
    previews.replaceChildren();
    pending.forEach((file,index)=>{const wrap=document.createElement('div');wrap.className='video-preview';
      const img=document.createElement('img');img.alt=file.name;const url=URL.createObjectURL(file);img.src=url;img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>URL.revokeObjectURL(url);
      const name=document.createElement('span');name.textContent=file.name;
      const remove=document.createElement('button');remove.type='button';remove.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';remove.setAttribute('aria-label','Hapus referensi '+file.name);remove.onclick=()=>{pending.splice(index,1);showPending();};
      wrap.append(img,remove,name);previews.append(wrap);});
  }
  picker?.addEventListener('change',()=>{pending.push(...picker.files);picker.value='';showPending();});
  root.addEventListener('click',async event=>{
    const dialog=root.querySelector('#video-delete-dialog');
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
        copy.textContent=copy.dataset.copyLabel+' · Tersalin';
        status.textContent='Tersalin. Siap ditempel ke tool pilihanmu.';
      }catch{copy.textContent=copy.dataset.copyLabel+' · Belum tersalin';status.textContent='Belum bisa menyalin. Pilih teks prompt lalu salin secara manual.';}
    }
  });
  form?.addEventListener('submit',async event=>{
    event.preventDefault();if(!form.reportValidity())return;
    const button=root.querySelector('#video-submit'),status=root.querySelector('#video-status'),error=root.querySelector('#video-error');
    const data=new FormData(form);data.delete('references');if(!form.elements.project_id.value)pending.forEach(file=>data.append('references',file));
    input.blur();button.disabled=true;picker.disabled=true;form.setAttribute('aria-busy','true');error.hidden=true;status.textContent='Menyusun dan meninjau arahan kreatif, storyboard, dan prompt produksi…';
    try{const response=await fetch(form.action,{method:'POST',body:data,headers:{'Accept':'application/json'}});if(response.redirected){location.assign(response.url);return;}
      const result=await response.json();if(!response.ok){
        form.elements.operation_key.value=crypto.randomUUID().replaceAll('-','');
        if(result.id){form.elements.project_id.value=result.id;form.elements.version.value=result.version;history.replaceState(null,'',result.url);root.querySelector('#video-reference-control').hidden=true;pending=[];showPending();}
        throw new Error(result.error||'Rencana belum dapat disusun. Coba lagi.');
      }
      root.querySelector('#video-result').innerHTML=result.html;
      root.querySelector('#video-active-title').textContent=result.title;
      root.querySelector('#video-active-version').textContent='Versi '+result.version+' · Rencana aktif';
      root.querySelector('#video-revision-context').hidden=false;
      root.querySelector('#video-outline').hidden=false;
      root.querySelector('#video-project-actions').innerHTML=result.manage_html;
      form.elements.project_id.value=result.id;form.elements.version.value=result.version;form.elements.operation_key.value=crypto.randomUUID().replaceAll('-','');
      for(const [key,value] of Object.entries(result.controls))if(form.elements[key])form.elements[key].value=value;
      input.value='';input.placeholder='Contoh: lebih premium, tanpa voice-over, produknya tetap sama.';
      root.querySelector('#video-composer-label').textContent='Ubah atau sempurnakan rencana';
      root.querySelector('#video-reference-control').hidden=true;pending=[];showPending();button.textContent='Perbarui rencana';
      history.replaceState(null,'',result.url);status.textContent='Rencana tersimpan. Kamu bisa menyalin prompt atau meminta revisi.';
      const list=root.querySelector('.video-history>ul')||document.createElement('ul');const link=document.createElement('a');link.href=result.url;link.textContent=result.title;link.setAttribute('aria-current','page');
      list.querySelectorAll('a').forEach(a=>{a.removeAttribute('aria-current');if(a.getAttribute('href')===result.url)a.parentElement.remove();});const item=document.createElement('li');item.append(link);list.prepend(item);
      if(!list.parentElement){root.querySelector('.video-history>p')?.remove();root.querySelector('.video-history>h2').after(list);}
      // No automatic composer focus: completing a plan must not reopen a mobile keyboard.
    }catch(problem){error.textContent=problem.message||'Koneksi terputus. Buka riwayat sebelum mencoba ulang.';error.hidden=false;status.textContent='';}
    finally{button.disabled=false;picker.disabled=false;form.removeAttribute('aria-busy');}
  });
})();
