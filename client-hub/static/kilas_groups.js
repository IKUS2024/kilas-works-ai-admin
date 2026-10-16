/* Text-only collaboration. No personal-chat state, uploads or call controls. */
(() => {
  'use strict';
  const root = document.getElementById('group-workspace');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const ui = JSON.parse($('group-ui').textContent);
  const t = s => ui[s] || s;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('input[name="csrf_token"]')?.value;
  const status = s => { $('group-status').textContent = s || ''; };
  async function api(path, data) {
    const response = await fetch(path, {method:data ? 'POST' : 'GET', credentials:'same-origin',cache:'no-store',redirect:'follow',headers:{'Accept':'application/json',...(data ? {'Content-Type':'application/json','X-CSRF-Token':csrf} : {})},...(data ? {body:JSON.stringify(data)} : {})});
    if (response.redirected) {revoke();throw new Error(t('Grup tidak tersedia atau akses sudah dicabut.'));}
    if (response.status === 403 || response.status === 404 || response.status === 401) {
      if (path.includes('/messages') && response.status !== 403) revoke();
    }
    const value = await response.json().catch(() => ({}));
    if (!response.ok) { const error=new Error(value.error || t('Permintaan gagal. Muat ulang halaman lalu coba lagi.'));error.httpStatus=response.status;throw error; }
    return value;
  }
  $('group-create').addEventListener('submit', async event => {
    event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
    try { const result=await api('/kilas-ai/groups',{name:$('group-name').value}); location.assign(result.url); }
    catch (error) {status(error.message);button.disabled=false;}
  });
  const ident=root.dataset.groupId;
  if (!ident) return;
  const path='/kilas-ai/groups/'+ident;
  const user=Number(root.dataset.userId);
  let active=true, polling=false, timer, busy=false, aiEnabled=true, pending=null;
  const rows=new Map();
  function revoke() {
    active=false;clearTimeout(timer);rows.clear();$('group-messages').replaceChildren();
    $('group-members').replaceChildren();$('group-composer').hidden=true;
    $('group-summary').hidden=true;$('group-details').hidden=true;
    status(t('Grup tidak tersedia atau akses sudah dicabut.'));
  }
  function renderMessages(messages) {
    const box=$('group-messages'), nearEnd=box.scrollHeight-box.scrollTop-box.clientHeight<120;
    for (const row of messages) rows.set(row.id,row);
    const fragment=document.createDocumentFragment();
    for (const row of [...rows.values()].sort((a,b)=>a.id-b.id)) {
      const article=document.createElement('article');article.className='group-message'+(row.user_id===user?' group-mine':'');
      const name=document.createElement('strong');name.textContent=row.role==='assistant'?'Kilas AI':row.name || t('Anggota');
      const time=document.createElement('time');time.dateTime=row.created_at;time.textContent=new Date(row.created_at).toLocaleString(document.documentElement.lang,{dateStyle:'short',timeStyle:'short'});
      const text=document.createElement('p');text.textContent=row.content;
      article.append(name,time,text);fragment.append(article);
    }
    const top=box.scrollTop, oldHeight=box.scrollHeight;box.replaceChildren(fragment);
    if (nearEnd) box.scrollTop=box.scrollHeight;
    else box.scrollTop=top+Math.max(0,box.scrollHeight-oldHeight);
    $('group-empty').hidden=rows.size>0;
  }
  function controls() {
    $('group-ask').disabled=!aiEnabled || busy || !!pending;
    $('group-summary').disabled=!aiEnabled || busy || !!pending;
    $('group-busy').hidden=!busy;
    $('group-paused').hidden=aiEnabled;
    if (!aiEnabled) $('group-ask').checked=false;
  }
  function update(value, older=false) {
    if (!active) return;
    renderMessages(value.messages);busy=value.busy;aiEnabled=!!value.ai_enabled;controls();
    if (older || value.messages[0]?.id===Math.min(...rows.keys())) $('group-older').hidden=!value.has_older;
    const members=$('group-members');members.replaceChildren();
    value.members.forEach(person => {
      const li=document.createElement('li'),label=document.createElement('span');label.textContent=person.name || t('Anggota');li.append(label);
      if (person.id===value.owner_id) {const owner=document.createElement('small');owner.textContent=t('Pemilik');li.append(owner);}
      if (value.is_owner && person.id!==user) {
        const button=document.createElement('button');button.type='button';button.textContent=t('Hapus anggota');
        button.addEventListener('click',async()=>{if(!confirm(t('Cabut akses anggota ini ke seluruh riwayat grup?')))return;button.disabled=true;try{await api(path+'/settings',{action:'remove',user_id:person.id});await poll();}catch(error){status(error.message);button.disabled=false;}});li.append(button);
      }
      members.append(li);
    });
    if ($('group-ai-enabled')) {$('group-ai-enabled').checked=aiEnabled;$('group-ai-count').textContent=value.ai_requests;}
  }
  async function poll() {
    if (!active || polling || document.hidden) return;
    polling=true;
    try {const value=await api(path+'/messages?after='+Math.max(0,...rows.keys()));if(active)update(value);}
    catch(error){if(active)status(t('Pembaruan terputus. Mencoba kembali…'));}
    finally {polling=false;}
  }
  async function loop(){await poll();if(active)timer=setTimeout(loop,3000);}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
  window.addEventListener('pagehide',()=>{active=false;clearTimeout(timer);});
  $('group-older').addEventListener('click',async()=>{
    const button=$('group-older');button.disabled=true;
    try {update(await api(path+'/messages?before='+Math.min(...rows.keys())),true);}
    catch(error){status(error.message);}finally{button.disabled=false;}
  });
  async function send(kind) {
    if (pending) {if(pending.kind!==kind || (pending.kind!=='SUMMARY' && pending.content!==$('group-input').value.trim())) {status(t('Kirim ulang pesan yang tertunda sebelum mengubah pesan.'));return;}}
    else pending={kind,content:kind==='SUMMARY'?'':$('group-input').value.trim(),operation_key:crypto.randomUUID().replaceAll('-','')};
    const button=$('group-send');button.disabled=true;$('group-input').readOnly=true;controls();status(t('Mengirim…'));
    try {
      const result=await api(path+'/messages',pending);
      if (!active) return;
      if (result.status==='PENDING' || result.status==='DISPATCHED') {status(t('AI sedang menjawab…'));}
      else {status(result.error || '');}
      if(pending.kind!=='SUMMARY')$('group-input').value='';
      pending=null;await poll();
    } catch(error) {
      if (error.httpStatus && error.httpStatus<500) {pending=null;status(error.message);}
      else status(error.message+' '+t('Kirim ulang untuk memeriksa status tanpa menggandakan pesan.'));
    } finally {button.disabled=!!pending;$('group-retry').hidden=!pending;$('group-input').readOnly=!!pending;controls();}
  }
  $('group-composer').addEventListener('submit',event=>{event.preventDefault();send($('group-ask').checked?'ASK':'TEXT');});
  $('group-summary').addEventListener('click',()=>send('SUMMARY'));
  $('group-retry').addEventListener('click',()=>{if(pending)send(pending.kind);});
  if ($('group-ai-enabled')) {
    $('group-ai-enabled').addEventListener('change',async event=>{
      event.target.disabled=true;
      try {await api(path+'/settings',{action:'ai',enabled:event.target.checked});await poll();}
      catch(error){event.target.checked=!event.target.checked;status(error.message);}finally{event.target.disabled=false;}
    });
    $('group-invite').addEventListener('click',async event=>{
      event.target.disabled=true;
      try{const value=await api(path+'/invitation',{});$('group-invite-url').value=new URL(value.url,location.origin).href;$('group-invite-result').hidden=false;status(t('Tautan baru siap. Tautan sebelumnya tidak berlaku.'));}
      catch(error){status(error.message);}finally{event.target.disabled=false;}
    });
    $('group-revoke').addEventListener('click',async()=>{
      try {await api(path+'/invitation',{revoke:true});$('group-invite-result').hidden=true;$('group-invite-url').value='';status(t('Tautan undangan dicabut.'));}
      catch(error){status(error.message);}
    });
    $('group-copy').addEventListener('click',async()=>{
      try {await navigator.clipboard.writeText($('group-invite-url').value);status(t('Tautan disalin.'));}
      catch { $('group-invite-url').select();status(t('Salin tautan yang dipilih.')); }
    });
  }
  update(JSON.parse($('group-initial').textContent));loop();
})();
