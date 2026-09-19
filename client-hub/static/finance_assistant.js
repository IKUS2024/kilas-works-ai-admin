'use strict';
(() => {
  const el = id => document.getElementById(id), composer = el('assistant-composer');
  if (!composer) return;
  const files = el('assistant-files'), text = el('assistant-text'), mode = el('assistant-mode');
  const status = el('assistant-status');
  let busy = false, result = null, token = null, attempted = false, docWorkflow = null;
  const controls = [];
  const setStatus = (message, error = false) => {
    status.textContent = message || '';
    status.classList.toggle('is-error', !!error);
  };
  const state = value => {
    busy = value; composer.setAttribute('aria-busy', String(value));
    for (const id of ['assistant-send','assistant-clear','assistant-camera','assistant-files','assistant-text','assistant-mode',
                      'assistant-review-send','assistant-confirm','assistant-edit','assistant-result-cancel','assistant-cancel']) {
      if (el(id)) el(id).disabled = value;
    }
    document.querySelectorAll('[data-assistant-choice],[data-assistant-prompt]').forEach(node => { node.disabled = value; });
    el('assistant-result-fields').disabled = value;
    el('assistant-send').textContent = value ? 'Memproses…' : 'Kirim';
    if (!value) el('assistant-send').disabled = !text.value.trim() && !files.files.length;
  };
  const send = async (url, body) => {
    const multipart = body instanceof FormData;
    const response = await fetch(url, {method:'POST',credentials:'same-origin',cache:'no-store',
      headers:multipart ? {'X-CSRF-Token':composer.dataset.csrf} : {'Content-Type':'application/json','X-CSRF-Token':composer.dataset.csrf},
      body:multipart ? body : JSON.stringify(body)});
    if (response.redirected) throw new Error('Sesi berubah. Muat ulang dan masuk kembali.');
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Respons belum dapat dibaca. Muat ulang dan coba lagi.'); }
    if (!response.ok) throw new Error(data.error || 'Permintaan belum dapat diproses. Coba lagi.');
    return data;
  };
  const uploadBody = () => {
    const body = new FormData();
    body.append('csrf_token',composer.dataset.csrf); body.append('text',text.value);
    for (const file of files.files) body.append('sources',file);
    return body;
  };
  const values = () => Object.fromEntries(controls.map(({key,node}) => [key,node.value]));
  const render = data => {
    result = data; token = data.token || null; attempted = false;
    const resultBox = el('assistant-result');
    resultBox.hidden = false; resultBox.dataset.kind = data.kind || '';
    el('assistant-result-title').textContent = data.title || 'Assistant';
    el('assistant-result-message').textContent = data.message || '';
    const hint = el('assistant-result-hint'); hint.textContent = data.hint || ''; hint.hidden = !data.hint;
    el('assistant-result-preview').replaceChildren();
    for (const [label,value] of data.preview || []) {
      const dt=document.createElement('dt'), dd=document.createElement('dd');
      dt.textContent=label;dd.textContent=String(value);el('assistant-result-preview').append(dt,dd);
    }
    controls.length=0; el('assistant-result-fields').replaceChildren();
    for (const spec of data.fields || []) {
      const label=document.createElement('label'), node=document.createElement(spec.type==='select' ? 'select':'input');
      node.id='assistant-field-'+spec.key;label.htmlFor=node.id;label.textContent=spec.label;
      if (spec.type==='select') {
        const empty=document.createElement('option');empty.value='';empty.textContent='Pilih…';node.append(empty);
        for (const option of spec.options || []) { const item=document.createElement('option');item.value=option.value;item.textContent=option.label;node.append(item); }
      } else { node.type=spec.type || 'text';node.maxLength=spec.key==='notes'?4000:500; }
      node.value=spec.value || '';node.required=!!spec.required;
      node.addEventListener('input',()=>{token=null;el('assistant-confirm').hidden=true;el('assistant-review-send').hidden=false;});
      controls.push({key:spec.key,node});el('assistant-result-fields').append(label,node);
    }
    el('assistant-result-fields').hidden=!!data.ready || !controls.length;
    el('assistant-edit').hidden=!data.ready;el('assistant-confirm').hidden=!data.ready;
    el('assistant-review-send').hidden=!controls.length || !!data.ready;
    el('assistant-review-send').textContent=data.kind==='document_account'?'Lanjut membaca dokumen':'Review perubahan';
    el('assistant-review-link').hidden=true;
    if (data.review_url && /^\/business\/\d+\/finance\//.test(data.review_url)) {
      el('assistant-review-link').href=data.review_url;el('assistant-review-link').hidden=false;
    }
    el('assistant-confirm').textContent=data.title==='Customer baru'?'Tambahkan Customer':data.title==='Biaya rutin'?'Aktifkan jadwal':'Konfirmasi';
    el('assistant-result-cancel').textContent=(data.kind==='answer' && !data.ready)?'Pesan baru':'Batal';
    setStatus('');
    resultBox.focus();
    resultBox.scrollIntoView({behavior:'smooth',block:'nearest'});
  };
  const processDocument = async workflow => {
    const body=uploadBody();body.append('workflow',workflow);
    const selected=values().account_id;
    if (result?.kind==='document_account' && selected) body.append('account_id',selected);
    docWorkflow=workflow;
    render(await send(composer.dataset.document,body));
  };
  const showUserMessage = () => {
    const messageText=text.value.trim(), messageFiles=el('assistant-message-files');
    el('assistant-message-text').textContent=messageText;
    el('assistant-message-text').hidden=!messageText;
    messageFiles.replaceChildren();
    for (const file of files.files) {
      const chip=document.createElement('span');chip.textContent='📎 '+file.name;messageFiles.append(chip);
    }
    el('assistant-message').hidden=!messageText && !files.files.length;
  };
  const run = async manual => {
    if (busy) return;
    if (token || result?.kind==='review') { setStatus('Selesaikan atau batalkan review sebelum mengirim pesan baru.');return; }
    if (!text.value.trim() && !files.files.length) { setStatus('Tulis pesan atau pilih file.');return; }
    if (text.value.length>2000 || files.files.length>10) { setStatus('Maksimal 2.000 karakter dan 10 file.',true);return; }
    if (Array.from(files.files).some(f=>f.size>20*1024*1024) || Array.from(files.files).reduce((n,f)=>n+(f.size||0),0)>25*1024*1024) {
      setStatus('Maksimal 20 MiB per foto dan 25 MiB total.',true);return;
    }
    state(true);el('assistant-clarification').hidden=true;setStatus('Kilas AI sedang memahami pesan dan dokumen…');
    showUserMessage();
    try {
      if (!files.files.length) { render(await send(composer.dataset.message,{text:text.value}));return; }
      const workflows={receipt:'RECEIPT',bank:'BANK_STATEMENT',notes:'HANDWRITTEN_NOTE'};
      const choice=manual || mode.value;
      let workflow=workflows[choice];
      if (!workflow) workflow=(await send(composer.dataset.recognize,uploadBody())).workflow;
      if (!['RECEIPT','BANK_STATEMENT','HANDWRITTEN_NOTE'].includes(workflow)) {
        el('assistant-clarification').hidden=false;
        el('assistant-clarification-title').textContent='Saya belum yakin jenis dokumen ini. Pilih yang sesuai ya.';
        document.querySelectorAll('[data-assistant-choice]').forEach(node=>{node.hidden=!workflows[node.dataset.assistantChoice];});
        setStatus('Dokumen belum jelas. Pilih jenisnya atau gunakan foto yang lebih jelas.');return;
      }
      await processDocument(workflow);
    } catch (error) { setStatus(error.message,true); }
    finally { state(false); }
  };
  composer.addEventListener('submit',event=>{event.preventDefault();return run();});
  el('assistant-review-form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !result || attempted)return;
    state(true);setStatus('Memeriksa perubahan…');
    try {
      if (result.kind==='document_account') await processDocument(docWorkflow);
      else render(await send(composer.dataset.review,{context:result.context,values:values()}));
    } catch(error) {setStatus(error.message,true);}
    finally {state(false);}
  });
  el('assistant-edit').addEventListener('click',()=>{
    if(busy || attempted)return;
    token=null;el('assistant-result-fields').hidden=false;el('assistant-confirm').hidden=true;
    el('assistant-review-send').hidden=false;el('assistant-edit').hidden=true;
  });
  el('assistant-confirm').addEventListener('click',async()=>{
    if(busy || !token)return;attempted=true;state(true);setStatus('Menyimpan setelah konfirmasi…');
    try {
      const data=await send(composer.dataset.confirm,{token,confirm:true});
      const technical=/Konfirmasi sudah diproses/i.test(data.message || '');
      render({kind:'answer',title:'Sudah dicatat',message:technical?'Tersimpan di Kilas Finance.':data.message,
        hint:'Konfirmasi yang sama aman dari pencatatan ganda.',completed:true});
    } catch(error) {setStatus(error.message+' Jika belum pasti, ulangi konfirmasi yang sama.',true);}
    finally {state(false);el('assistant-edit').disabled=attempted;}
  });
  const clear = () => {
    if(busy)return;
    const uncertain=attempted;result=null;token=null;attempted=false;docWorkflow=null;controls.length=0;
    text.value='';files.value='';if(el('assistant-camera'))el('assistant-camera').value='';mode.value='auto';
    for(const id of ['assistant-result','assistant-clarification','assistant-message'])el(id).hidden=true;
    for(const id of ['assistant-file-list','assistant-result-fields','assistant-result-preview','assistant-message-files'])el(id).replaceChildren();
    el('assistant-message-text').textContent='';el('assistant-result-hint').textContent='';el('assistant-result-hint').hidden=true;
    setStatus(uncertain?'Periksa catatan Finance sebelum mengirim ulang; konfirmasi sebelumnya mungkin sudah diproses.':'');
    state(false);text.focus();
  };
  for(const id of ['assistant-clear','assistant-cancel','assistant-result-cancel'])el(id).addEventListener('click',clear);
  const refreshFiles = () => {
    el('assistant-file-list').replaceChildren();
    for(const file of files.files){const item=document.createElement('li');item.textContent='📎 '+file.name;el('assistant-file-list').append(item);}
    state(false);
  };
  files.addEventListener('change',refreshFiles);
  text.addEventListener('input',()=>state(false));
  document.querySelectorAll('[data-assistant-choice]').forEach(node=>node.addEventListener('click',()=>run(node.dataset.assistantChoice)));
  document.querySelectorAll('[data-assistant-prompt]').forEach(node=>node.addEventListener('click',()=>{
    if(busy || token || result?.kind==='review')return;
    text.value=node.dataset.assistantPrompt || '';state(false);text.focus();
  }));
  el('assistant-camera').addEventListener('change',()=>{
    const camera=el('assistant-camera');if(busy || token || result?.kind==='review')return;
    try {
      if(typeof DataTransfer==='function'){const transfer=new DataTransfer();for(const file of camera.files)transfer.items.add(file);files.files=transfer.files;}
      else files.files=camera.files;
      files.dispatchEvent(new Event('change'));
    } catch(_){setStatus('Foto belum dapat dipindahkan. Gunakan File untuk memilih foto ini.',true);}
  });
  state(false);
})();
