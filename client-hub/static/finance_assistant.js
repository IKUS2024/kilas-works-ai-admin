'use strict';
(() => {
  const el=id=>document.getElementById(id), composer=el('assistant-composer');
  if(!composer)return;
  const log=el('assistant-result'),files=el('assistant-files'),camera=el('assistant-camera'),text=el('assistant-text'),
        mode=el('assistant-mode'),status=el('assistant-status'),sendButton=el('assistant-send');
  let busy=false,pending=null,docWorkflow=null,uploadInstruction='',documentContext='',queryContext='';
  const confirmWords=/^\s*((?:oke|ok|iya|ya|yes|benar|betul|sip|lanjut|catat|simpan|gas)(?:\s+(?:ya|aja|saja|deh|dong|simpan|catat|lanjut))?|(?:sudah|udah)\s+(?:benar|betul))[.! ]*$/i;
  const cancelWords=/^\s*((?:batal|cancel|ga jadi|gak jadi|nggak jadi|tidak jadi|skip|stop)(?:\s+(?:ya|aja|saja|deh|dong))?|jangan(?:\s+(?:simpan|disimpan|catat|dicatat))?(?:\s+(?:ya|aja|saja|deh|dong))?)[.! ]*$/i;
  const setStatus=(message,error=false)=>{status.textContent=message||'';status.classList.toggle('is-error',!!error);};
  const setBusy=value=>{
    busy=value;composer.setAttribute('aria-busy',String(value));
    for(const node of [sendButton,el('assistant-clear'),camera,files,text,mode])if(node)node.disabled=value;
    document.querySelectorAll('[data-assistant-prompt]').forEach(node=>node.disabled=value);
    sendButton.textContent=value?'Memproses…':'Kirim';
    if(!value)sendButton.disabled=!text.value.trim()&&!files.files.length;
  };
  const send=async(url,body)=>{
    const multipart=body instanceof FormData;
    const response=await fetch(url,{method:'POST',credentials:'same-origin',cache:'no-store',
      headers:multipart?{'X-CSRF-Token':composer.dataset.csrf}:{'Content-Type':'application/json','X-CSRF-Token':composer.dataset.csrf},
      body:multipart?body:JSON.stringify(body)});
    if(response.redirected)throw new Error('Sesi berubah. Muat ulang lalu masuk kembali.');
    let data;try{data=await response.json();}catch(_){throw new Error('Respons belum dapat dibaca. Coba lagi.');}
    if(!response.ok)throw new Error(data.error||'Permintaan belum dapat diproses. Coba lagi.');
    return data;
  };
  const node=(tag,className,textValue)=>{
    const item=document.createElement(tag);if(className)item.className=className;if(textValue!==undefined)item.textContent=textValue;return item;
  };
  const scroll=()=>{const last=log.lastElementChild;if(last&&last.scrollIntoView)last.scrollIntoView({behavior:'smooth',block:'nearest'});};
  const appendUser=(message,names=[])=>{
    const turn=node('article','assistant-turn assistant-turn-user'),bubble=node('div','assistant-bubble');
    bubble.append(node('div','assistant-speaker','Kamu'));
    if(message)bubble.append(node('p','',message));
    if(names.length){const chips=node('div','assistant-message-files');for(const name of names)chips.append(node('span','','📎 '+name));bubble.append(chips);}
    turn.append(bubble);log.append(turn);scroll();
  };
  const currentValues=data=>Object.fromEntries((data?.fields||[]).map(field=>[field.key,field.value==null?'':String(field.value)]));
  const missingSelect=data=>(data?.fields||[]).find(field=>(!data.next_field||field.key===data.next_field)&&field.required!==false&&field.type==='select'&&!field.value&&Array.isArray(field.options)&&field.options.length);
  const quickButton=(label,handler,primary=false)=>{
    const button=node('button',primary?'primary':'',label);button.type='button';button.addEventListener('click',handler);return button;
  };
  const appendAssistant=(data,options={})=>{
    // A button belongs to one response, never to whichever draft is active later.
    document.querySelectorAll('.assistant-quick-replies button').forEach(button=>button.disabled=true);
    const turn=node('article','assistant-turn assistant-turn-ai'+(options.success?' assistant-turn-success':'')+(options.error?' assistant-turn-error':''));
    const avatar=node('div','assistant-avatar','K');avatar.setAttribute('aria-hidden','true');
    const bubble=node('div','assistant-bubble');bubble.append(node('div','assistant-speaker','Kilas AI'));
    if(data.title)bubble.append(node('h2','',data.title));
    bubble.append(node('p','',data.message||''));
    if(Array.isArray(data.preview)&&data.preview.length){
      const dl=node('dl','assistant-preview');
      for(const pair of data.preview){const dt=node('dt','',String(pair[0]??'')),dd=node('dd','',String(pair[1]??''));dl.append(dt,dd);}
      bubble.append(dl);
    }
    if(data.hint)bubble.append(node('p','assistant-hint',data.hint));
    const actions=node('div','assistant-quick-replies');
    for(const choice of (data.choices||[]).slice(0,8))actions.append(quickButton(choice,()=>submitQuick(choice)));
    const select=missingSelect(data);
    if(select){
      for(const option of (select.options||[]).slice(0,8)){
        actions.append(quickButton(option.label,()=>chooseField(select.key,String(option.value),option.label)));
      }
    }else if(data.ready&&data.token){
      const confirmLabel='Konfirmasi';
      actions.append(quickButton(confirmLabel,()=>submitQuick('oke'),true),quickButton('Batal',()=>submitQuick('batal')));
    }
    if(data.kind==='branch_choice'){
      for(const branch of data.branches||[])actions.append(quickButton(branch.name,async()=>{
        if(busy)return;setBusy(true);
        try{
          // Navigate the real workspace so header, navigation and server scope
          // agree. Never switch only the chat endpoints behind an aggregate UI.
          const destination=new URL(location.href);destination.searchParams.set('branch_id',branch.id);
          location.assign(destination.pathname+destination.search);
        }catch(error){appendError(error.message);}finally{setBusy(false);}
      }));
    }
    if(data.kind==='needs_document_choice'){
      actions.append(
        quickButton('Struk',()=>processDocument('RECEIPT')),
        quickButton('Mutasi bank',()=>processDocument('BANK_STATEMENT')),
        quickButton('Catatan keuangan',()=>processDocument('HANDWRITTEN_NOTE'))
      );
    }
    if(actions.children.length)bubble.append(actions);
    turn.append(avatar,bubble);log.append(turn);scroll();
    if(data.query_context)queryContext=data.query_context;
    if(['review','bank_review','document_account'].includes(data.kind)){pending=data;queryContext='';}
    else if(data.state==='CANCELLED'){pending=null;queryContext='';}
    else if(data.kind==='success'){pending=null;if(!data.query_context)queryContext='';}
    else if(!options.keepPending&&!data.keep_pending)pending=null;
    const draftStatus=el('assistant-draft-status');
    if(draftStatus){draftStatus.textContent=pending?(pending.ready?'Draft siap dikonfirmasi':'Draft belum selesai')+' · '+(pending.title||'Dokumen'):'';}
  };
  const appendError=message=>appendAssistant({title:'Belum berhasil',message:message||'Coba lagi sebentar. Belum ada data yang diubah.'},{error:true,keepPending:true});
  const clearFiles=()=>{files.value='';try{files.files=[];}catch(_){}if(camera)camera.value='';el('assistant-file-list').replaceChildren();};
  const uploadBody=()=>{
    const body=new FormData();body.append('csrf_token',composer.dataset.csrf);body.append('text',uploadInstruction||'');
    for(const file of files.files)body.append('sources',file);return body;
  };
  const refreshFiles=()=>{
    const list=el('assistant-file-list');list.replaceChildren();
    for(const file of files.files)list.append(node('li','','📎 '+file.name));
    setBusy(false);
  };
  const chooseField=async(key,value,label)=>{
    if(busy||!pending)return;
    appendUser(label);setBusy(true);setStatus('Kilas AI sedang memperbarui ringkasan…');
    try{
      if(pending.kind==='document_account'){await processDocument(docWorkflow,value);return;}
      const values=currentValues(pending);values[key]=value;
      const data=await send(composer.dataset.review,{context:pending.context,values});appendAssistant(data);
    }catch(error){appendError(error.message);}
    finally{setStatus('');setBusy(false);}
  };
  const confirmPending=async()=>{
    if(!pending?.token)return;
    const same=pending;setBusy(true);setStatus('Menyimpan setelah konfirmasi kamu…');
    try{
      const data=await send(composer.dataset.confirm,{token:same.token,confirm:true});
      if(['review','answer','clarification'].includes(data.kind)){appendAssistant(data);return;}
      pending=null;appendAssistant({...data,kind:'success',title:'Berhasil',message:data.message||'Sudah disimpan di Kilas Finance.'},{success:true});clearFiles();
    }catch(error){pending=same;appendError(error.message+' Kamu bisa balas “oke” lagi dengan draft yang sama setelah koneksi normal.');}
    finally{setStatus('');setBusy(false);}
  };
  const followPending=async message=>{
    if(pending?.context){
      const payload={text:message,context:pending.context,confirmation:pending.token||null};
      if(queryContext)payload.query_context=queryContext;
      const data=await send(composer.dataset.message,payload);
      appendAssistant(data,{success:data.kind==='success'});return;
    }
    if(cancelWords.test(message)){pending=null;clearFiles();appendAssistant({message:'Oke, draft tadi dibatalkan. Mau catat atau cek apa lagi?'});return;}
    if(confirmWords.test(message)&&pending?.token){await confirmPending();return;}
    if(pending?.kind==='document_account'){
      const payload={text:message,document_pending:true};if(queryContext)payload.query_context=queryContext;
      const data=await send(composer.dataset.message,payload);
      if(data.kind==='document_selection'){await processDocument(docWorkflow,data.account_id);return;}
      if(data.kind==='review')clearFiles();
      appendAssistant(data,{keepPending:data.kind!=='review'});return;
    }
    // Bank review tokens stay pending while a separate question uses the same
    // authenticated, scoped message endpoint.
    const payload={text:message};if(queryContext)payload.query_context=queryContext;
    const data=await send(composer.dataset.message,payload);
    appendAssistant(data,{keepPending:!['review','success'].includes(data.kind)});
  };
  const processDocument=async(workflow,accountId='',accountMessage='')=>{
    docWorkflow=workflow;setStatus('Kilas AI sedang membaca dokumen…');
    const body=uploadBody();if(accountMessage)body.set('text',accountMessage);body.append('workflow',workflow);if(documentContext)body.append('document_context',documentContext);if(accountId)body.append('account_id',accountId);
    const data=await send(composer.dataset.document,body);
    appendAssistant(data);
    if(data.kind!=='document_account')clearFiles();
  };
  const run=async manual=>{
    if(busy)return;
    const message=text.value.trim(),hasFiles=files.files.length>0;
    if(!message&&!hasFiles){setStatus('Tulis pesan atau pilih file.');return;}
    if(text.value.length>2000||files.files.length>10){appendError('Maksimal 2.000 karakter dan 10 file.');return;}
    const selected=Array.from(files.files);
    if(selected.some(file=>(file.size||0)>20*1024*1024)||selected.reduce((n,file)=>n+(file.size||0),0)>25*1024*1024){appendError('Lampiran terlalu besar. Maksimal 20 MiB per foto dan 25 MiB total.');return;}
    if(pending&&(!hasFiles||pending.kind==='document_account')){
      appendUser(message);text.value='';setBusy(true);setStatus('Kilas AI sedang memahami balasanmu…');
      try{await followPending(message);}catch(error){appendError(error.message);}finally{setStatus('');setBusy(false);}return;
    }
    if(pending&&hasFiles){appendAssistant({message:'Masih ada draft yang belum selesai. Balas “oke” atau “batal” dulu sebelum mengirim dokumen baru.'},{keepPending:true});return;}
    appendUser(message,selected.map(file=>file.name));documentContext='';uploadInstruction=message;text.value='';setBusy(true);
    try{
      if(!hasFiles){
        setStatus('Kilas AI sedang memahami pesanmu…');
        const payload={text:message};if(queryContext)payload.query_context=queryContext;
        appendAssistant(await send(composer.dataset.message,payload));return;
      }
      let workflow={receipt:'RECEIPT',bank:'BANK_STATEMENT',notes:'HANDWRITTEN_NOTE'}[manual||mode.value];
      if(!workflow){
        setStatus('Kilas AI sedang mengenali dokumen…');
        const recognition=await send(composer.dataset.recognize,uploadBody());
        if(recognition.kind==='branch_choice'){appendAssistant(recognition);return;}
        workflow=recognition.workflow;documentContext=recognition.document_context||'';
      }
      if(!['RECEIPT','BANK_STATEMENT','HANDWRITTEN_NOTE'].includes(workflow)){
        appendAssistant({kind:'needs_document_choice',title:'Saya belum yakin jenis dokumennya',message:'File sudah diterima. Pilih apakah ini struk, mutasi bank, atau catatan keuangan. Belum ada data yang dicatat.'},{keepPending:true});return;
      }
      await processDocument(workflow);
    }catch(error){appendError(error.message);}
    finally{setStatus('');setBusy(false);}
  };
  const submitQuick=value=>{if(busy)return;text.value=value;setBusy(false);composer.dispatchEvent(new Event('submit',{cancelable:true}));};
  composer.addEventListener('submit',event=>{event.preventDefault();run();});
  text.addEventListener('input',()=>setBusy(false));
  text.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();if(!sendButton.disabled)composer.dispatchEvent(new Event('submit',{cancelable:true}));}});
  files.addEventListener('change',refreshFiles);
  camera.addEventListener('change',()=>{
    if(busy)return;
    try{
      if(typeof DataTransfer==='function'){const transfer=new DataTransfer();for(const file of camera.files)transfer.items.add(file);files.files=transfer.files;}
      else files.files=camera.files;
      files.dispatchEvent(new Event('change'));
    }catch(_){appendError('Foto belum dapat dipindahkan. Gunakan tombol File / PDF untuk memilih foto ini.');}
  });
  document.querySelectorAll('[data-assistant-prompt]').forEach(button=>button.addEventListener('click',()=>{if(busy||pending)return;text.value=button.dataset.assistantPrompt||'';setBusy(false);text.focus();}));
  el('assistant-clear').addEventListener('click',()=>{
    if(busy)return;pending=null;docWorkflow=null;documentContext='';uploadInstruction='';queryContext='';text.value='';clearFiles();log.replaceChildren();setStatus('');mode.value='auto';setBusy(false);text.focus();
    if(el('assistant-draft-status'))el('assistant-draft-status').textContent='';
  });
  if(el('assistant-remove-files'))el('assistant-remove-files').addEventListener('click',()=>{if(!busy){if(pending?.kind==='document_account'){pending=null;if(el('assistant-draft-status'))el('assistant-draft-status').textContent='';}clearFiles();setBusy(false);}});
  setBusy(false);
})();
