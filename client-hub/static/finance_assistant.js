'use strict';
(() => {
  const el=id=>document.getElementById(id), composer=el('assistant-composer');
  if(!composer)return;
  const log=el('assistant-result'),files=el('assistant-files'),camera=el('assistant-camera'),text=el('assistant-text'),
        mode=el('assistant-mode'),status=el('assistant-status'),sendButton=el('assistant-send');
  let busy=false,pending=null,docWorkflow=null,uploadInstruction='';
  const confirmWords=/^\s*(oke|ok|iya|ya|yes|benar|betul|sip|lanjut|catat|simpan|gas)(\s+(ya|aja|saja))?[.! ]*$/i;
  const cancelWords=/^\s*(batal|cancel|jangan|ga jadi|gak jadi|nggak jadi|tidak jadi)[.! ]*$/i;
  const normalize=value=>(value||'').toString().trim().toLowerCase();
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
  const missingSelect=data=>(data?.fields||[]).find(field=>field.required!==false&&field.type==='select'&&!field.value&&Array.isArray(field.options)&&field.options.length);
  const quickButton=(label,handler,primary=false)=>{
    const button=node('button',primary?'primary':'',label);button.type='button';button.addEventListener('click',handler);return button;
  };
  const appendAssistant=(data,options={})=>{
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
    const select=missingSelect(data);
    if(select){
      for(const option of (select.options||[]).slice(0,8)){
        actions.append(quickButton(option.label,()=>chooseField(select.key,String(option.value),option.label)));
      }
    }else if(data.ready&&data.token){
      const confirmLabel=['Customer baru','Biaya rutin'].includes(data.title)?'Oke, simpan':'Oke, catat';
      actions.append(quickButton(confirmLabel,()=>submitQuick('oke'),true),quickButton('Batal',()=>submitQuick('batal')));
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
    if(['review','bank_review','document_account'].includes(data.kind))pending=data;
    else if(!options.keepPending)pending=null;
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
  const localDate=offset=>{
    const d=new Date();d.setDate(d.getDate()+offset);
    const p=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());
  };
  const applyNaturalEdits=(message,data)=>{
    const values=currentValues(data),lower=normalize(message);let changed=false;
    const has=key=>Object.prototype.hasOwnProperty.call(values,key);
    const setValue=(key,value)=>{
      if(!has(key)||value===undefined||value===null)return;
      const clean=String(value).trim();
      if(values[key]!==clean){values[key]=clean;changed=true;}
    };
    const optionMatch=(key,phrase)=>{
      const field=(data.fields||[]).find(item=>item.key===key&&item.type==='select'&&Array.isArray(item.options));
      if(!field||!phrase)return;
      const wanted=normalize(phrase).replace(/^(?:ke|pakai|gunakan)\s+/,'').trim();
      const hits=field.options.filter(option=>{
        const label=normalize(option.label),head=label.split('·')[0].trim();
        return wanted===label||wanted===head||label.includes(wanted)||head.includes(wanted)||(wanted.length>=3&&wanted.includes(head));
      });
      if(hits.length===1)setValue(key,String(hits[0].value));
    };

    // Explicit reference phrases are preferred over broad fuzzy matching.
    const referencePatterns=[
      ['account_id',/(?:rekening|akun|kas)(?:nya)?\s*(?:jadi|pakai|gunakan|ke|:|=)?\s+(.+)/i],
      ['category_id',/kategori(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i],
      ['project_id',/proyek(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i],
      ['customer_id',/(?:customer|pelanggan)(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i]
    ];
    for(const [key,pattern] of referencePatterns){
      const match=message.match(pattern);if(match)optionMatch(key,match[1]);
    }

    // Also allow typing an exact visible option such as "BCA" or "Transport".
    for(const field of data.fields||[]){
      if(field.type!=='select'||!Array.isArray(field.options)||field.required===false)continue;
      const hits=field.options.filter(option=>{
        const label=normalize(option.label),head=label.split('·')[0].trim();
        return lower===label||lower===head||(lower.length>=3&&(label.includes(lower)||head.includes(lower)));
      });
      if(hits.length===1)setValue(field.key,String(hits[0].value));
    }

    if(has('amount')){
      const match=message.match(/(?:rp\.?\s*)?\d[\d.,]*(?:\s*(?:ribu|rb|juta|jt))?|(?:usd|idr|sgd|myr|eur|gbp|aud|jpy|cny|hkd|thb)\s+\d[\d.,]*/i);
      if(match&&!/^\d{4}-\d{2}-\d{2}$/.test(match[0]))setValue('amount',match[0]);
    }
    if(has('currency')){
      const code=(message.match(/\b(USD|IDR|SGD|MYR|EUR|GBP|AUD|JPY|CNY|HKD|THB)\b/i)||[])[1];
      if(code)setValue('currency',code.toUpperCase());
    }
    if(has('date')){
      let date=(message.match(/\b\d{4}-\d{2}-\d{2}\b/)||[])[0];
      if(/hari ini|sekarang/i.test(message))date=localDate(0);
      else if(/kemarin/i.test(message))date=localDate(-1);
      else if(has('cadence')){
        const dayMatch=message.match(/\btanggal\s+([0-9]{1,2})\b/i);
        if(dayMatch){
          const day=Number(dayMatch[1]),d=new Date();
          if(day>=1&&day<=31){
            if(day<d.getDate())d.setMonth(d.getMonth()+1);
            const target=new Date(d.getFullYear(),d.getMonth(),day);
            if(target.getMonth()===d.getMonth()){
              const p=n=>String(n).padStart(2,'0');date=target.getFullYear()+'-'+p(target.getMonth()+1)+'-'+p(target.getDate());
            }
          }
        }
      }
      if(date)setValue('date',date);
    }
    if(has('end_on')){
      const endMatch=message.match(/(?:sampai|berakhir(?:\s+tanggal)?|end)\s+(\d{4}-\d{2}-\d{2})/i);
      if(endMatch)setValue('end_on',endMatch[1]);
    }
    if(has('cadence')){
      const cadence=/minggu/i.test(message)?'WEEKLY':/bulan/i.test(message)?'MONTHLY':'';
      if(cadence)setValue('cadence',cadence);
    }

    const phoneMatch=message.match(/(?:nomor|no(?:mor)?(?:\s+hp)?|wa|whatsapp|whatsap|telepon|phone)(?:nya)?\s*(?:jadi|:|=)?\s*(\+?[0-9][0-9\s-]{5,})/i);
    if(phoneMatch&&has('phone'))setValue('phone',phoneMatch[1].replace(/[\s-]+/g,''));

    const email=(message.match(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/)||[])[0];
    if(email&&has('email'))setValue('email',email);

    const nameMatch=message.match(/(?:^|\b)(?:nama(?:nya)?|atas\s+nama)(?:\s+(?:jadi|adalah))?\s*[:=]?\s+(.+)/i);
    if(nameMatch&&has('name')){
      const name=nameMatch[1].replace(/\s+(?:ya|dong|weh)[.! ]*$/i,'').trim();
      if(name)setValue('name',name);
    }

    const counterparty=message.match(/(?:vendor|penerima|pihak\s+terkait)(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i);
    if(counterparty&&has('counterparty_name'))setValue('counterparty_name',counterparty[1].trim());

    const note=message.match(/(?:catatan|note)(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i);
    if(note&&has('notes'))setValue('notes',note[1].trim());
    else if(note&&has('description'))setValue('description',note[1].trim());

    const description=message.match(/(?:deskripsi|keterangan)(?:nya)?\s*(?:jadi|:|=)?\s+(.+)/i);
    if(description&&has('description'))setValue('description',description[1].trim());

    return {values,changed};
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
      pending=null;appendAssistant({title:'Berhasil',message:data.message||'Sudah disimpan di Kilas Finance.'},{success:true});clearFiles();
    }catch(error){pending=same;appendError(error.message+' Kamu bisa balas “oke” lagi dengan draft yang sama setelah koneksi normal.');}
    finally{setStatus('');setBusy(false);}
  };
  const followPending=async message=>{
    if(cancelWords.test(message)){pending=null;clearFiles();appendAssistant({message:'Oke, draft tadi dibatalkan. Mau catat atau cek apa lagi?'});return;}
    if(confirmWords.test(message)&&pending?.token){await confirmPending();return;}
    if(pending?.kind==='document_account'){
      const spec=missingSelect(pending),lower=normalize(message);
      const hits=(spec?.options||[]).filter(option=>normalize(option.label).includes(lower)||lower.includes(normalize(option.label).split('·')[0].trim()));
      if(hits.length===1){await chooseField(spec.key,String(hits[0].value),hits[0].label);return;}
      appendAssistant({message:'Saya masih perlu tahu rekening yang dipakai. Pilih salah satu pilihan di bawah atau ketik nama rekeningnya.',kind:'document_account',fields:pending.fields},{keepPending:true});return;
    }
    if(pending?.context){
      const edit=applyNaturalEdits(message,pending);
      if(!edit.changed){
        appendAssistant({message:pending.ready?'Saya belum menangkap bagian yang ingin diubah. Coba tulis spesifik, misalnya “WhatsApp 0822…”, “nama jadi Irvan”, “pakai BCA”, “vendor Telkom”, “ubah jadi 300 ribu”, atau “batal”.':(pending.message||'Masih ada data yang perlu dilengkapi. Pilih opsi yang saya tampilkan atau ketik nilainya.')},{keepPending:true});
        return;
      }
      const data=await send(composer.dataset.review,{context:pending.context,values:edit.values});appendAssistant(data);return;
    }
    appendAssistant({message:'Selesaikan draft ini dulu dengan “oke” atau “batal”.'},{keepPending:true});
  };
  const processDocument=async(workflow,accountId='')=>{
    docWorkflow=workflow;setStatus('Kilas AI sedang membaca dokumen…');
    const body=uploadBody();body.append('workflow',workflow);if(accountId)body.append('account_id',accountId);
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
    if(pending&&!hasFiles){
      appendUser(message);text.value='';setBusy(true);setStatus('Kilas AI sedang memahami balasanmu…');
      try{await followPending(message);}catch(error){appendError(error.message);}finally{setStatus('');setBusy(false);}return;
    }
    if(pending&&hasFiles){appendAssistant({message:'Masih ada draft yang belum selesai. Balas “oke” atau “batal” dulu sebelum mengirim dokumen baru.'},{keepPending:true});return;}
    appendUser(message,selected.map(file=>file.name));uploadInstruction=message;text.value='';setBusy(true);
    try{
      if(!hasFiles){setStatus('Kilas AI sedang memahami pesanmu…');appendAssistant(await send(composer.dataset.message,{text:message}));return;}
      let workflow={receipt:'RECEIPT',bank:'BANK_STATEMENT',notes:'HANDWRITTEN_NOTE'}[manual||mode.value];
      if(!workflow){
        setStatus('Kilas AI sedang mengenali dokumen…');
        workflow=(await send(composer.dataset.recognize,uploadBody())).workflow;
      }
      if(!['RECEIPT','BANK_STATEMENT','HANDWRITTEN_NOTE'].includes(workflow)){
        appendAssistant({kind:'needs_document_choice',title:'Saya belum yakin jenis dokumennya',message:'File sudah diterima. Pilih apakah ini struk, mutasi bank, atau catatan keuangan. Belum ada data yang dicatat.'},{keepPending:true});return;
      }
      await processDocument(workflow);
    }catch(error){appendError(error.message);clearFiles();}
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
    if(busy)return;pending=null;docWorkflow=null;uploadInstruction='';text.value='';clearFiles();log.replaceChildren();setStatus('');mode.value='auto';setBusy(false);text.focus();
  });
  setBusy(false);
})();
