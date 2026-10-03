/* Work-only preferences and explicit contextual browser permissions. */
(() => {
  const t=(message, values)=>window.KilasUI ? window.KilasUI.t(message, values) : message;
  const csrf = document.querySelector('input[name="csrf_token"]')?.value;
  const headers = {'Content-Type':'application/json', 'X-CSRF-Token':csrf || ''};
  const composer = document.querySelector('#agent-chat-form');
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (composer) composer.elements.browser_timezone.value = zone;
  let preferences;
  const load = async () => {
    const response = await fetch('/kilas-ai/work/preferences', {method:'POST',headers,body:JSON.stringify({timezone:zone})});
    if (!response.ok) throw new Error('preferences');
    return response.json();
  };
  const settings = document.querySelector('[data-work-preferences]');
  if (settings) {
    settings.addEventListener('submit', async event => {
      event.preventDefault();
      const status=settings.querySelector('[data-preference-status]');
      try {
        const response=await fetch('/kilas-ai/work/preferences',{method:'POST',headers,body:JSON.stringify({timezone:settings.elements.timezone.value,manual:true})});
        status.textContent=response.ok?t('Zona waktu tersimpan.'):t('Pilih zona waktu IANA yang valid.');
      } catch (_) { status.textContent=t('Zona waktu belum tersimpan. Coba lagi.'); }
    });
  }
  document.querySelector('[data-enable-push]')?.addEventListener('click',async () => {
    const status=document.querySelector('[data-push-status]');
    try {
      preferences ||= await load();
      if (!preferences.push_available || !preferences.public_key || !window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window)) {
        status.textContent=t('Notifikasi perangkat belum tersedia. Pengingat tetap tersimpan di Kilas AI.');return;
      }
      if (await Notification.requestPermission() !== 'granted') { status.textContent=t('Izin belum diberikan. Pengingat tetap muncul di Kilas AI.');return; }
      const registration=await navigator.serviceWorker.register('/kilas-ai/work/service-worker.js',{scope:'/kilas-ai/'});
      await navigator.serviceWorker.ready;
      const encoded=preferences.public_key.replace(/-/g,'+').replace(/_/g,'/');
      const key=Uint8Array.from(atob(encoded+'='.repeat((4-encoded.length%4)%4)),c=>c.charCodeAt(0));
      const subscription=await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
      const response=await fetch('/kilas-ai/work/push',{method:'POST',headers,body:JSON.stringify(subscription.toJSON())});
      status.textContent=response.ok?t('Notifikasi perangkat aktif.'):t('Notifikasi belum tersimpan. Coba lagi.');
    } catch (_) { status.textContent=t('Notifikasi belum aktif. Pengingat tetap tersimpan di Kilas AI.'); }
  });
  document.querySelector('[data-notifications-read]')?.addEventListener('click',async () => {
    const response=await fetch('/kilas-ai/work/notifications/read',{method:'POST',headers});
    if(response.ok) location.reload();
  });
  document.addEventListener('click',event => {
    const locationButton=event.target.closest('[data-work-location]');
    if(!locationButton) return;
    if (!navigator.geolocation || !composer) return;
    locationButton.disabled=true;
    navigator.geolocation.getCurrentPosition(position => {
      composer.elements.work_location.value=JSON.stringify({permission_granted:true,latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy,timestamp:position.timestamp});
      composer.elements.message.value=locationButton.dataset.request;
      locationButton.disabled=false;composer.requestSubmit();
    },() => {
      locationButton.disabled=false;
      locationButton.parentElement.querySelector('p').textContent=t('Lokasi tidak dibagikan. Ketik nama daerah yang ingin dicari.');
    },{maximumAge:0,timeout:10000,enableHighAccuracy:false});
  });
  const picker=composer?.querySelector('#work-source-files');
  document.querySelector('[data-work-attach]')?.addEventListener('click',()=>picker.click());
  const pending=document.querySelector('#work-pending-files');
  let files=[];
  const previews=new Map();
  const sentPreviews=new Set();
  function card(file, sentUrl) {
    const row=document.createElement('div');row.className='work-attachment-card';
    if (['image/png','image/jpeg','image/webp'].includes(file.type)) {
      if(!sentUrl && !previews.has(file)) previews.set(file,URL.createObjectURL(file));
      const image=document.createElement('img');image.className='work-attachment-thumbnail';
      image.src=sentUrl || previews.get(file);image.alt=file.name;image.width=64;image.height=64;row.append(image);
    } else {
      const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
      icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.classList.add('work-attachment-icon');
      const path=document.createElementNS(icon.namespaceURI,'path');path.setAttribute('d','M14 3H6v18h12V7zM14 3v5h4M9 12h6M9 16h6');icon.append(path);row.append(icon);
    }
    const info=document.createElement('span');info.className='work-attachment-info';
    const name=document.createElement('span');name.className='work-attachment-name';name.textContent=file.name;name.title=file.name;
    const size=document.createElement('small');size.textContent=`${file.name.split('.').pop().toUpperCase()} · ${Math.max(1,Math.round(file.size/1024))} KB`;
    info.append(name,size);row.append(info);return row;
  }
  // The optimistic card lasts only until the server renders the stored upload.
  window.KilasAttachmentPreview = selected => {
    const group=document.createElement('div');group.className='work-sent-files';group.setAttribute('aria-label',t('Lampiran terkirim'));
    selected.forEach(file=>{
      const url=file.type.startsWith('image/')?URL.createObjectURL(file):null;
      if(url) sentPreviews.add(url);
      const row=card(file,url);row.classList.add('work-sent-file');group.append(row);
    });
    return group;
  };
  window.KilasAttachmentPreview.clear=()=>{sentPreviews.forEach(url=>URL.revokeObjectURL(url));sentPreviews.clear();};
  function render() {
    if(!pending || !picker) return;
    pending.replaceChildren();
    const transfer=new DataTransfer();
    files.forEach((file,index) => {
      transfer.items.add(file);
      const row=card(file);row.classList.add('work-pending-file');
      const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',t('Hapus lampiran {name}',{name:file.name}));
      remove.addEventListener('click',() => { if(previews.has(file)) {URL.revokeObjectURL(previews.get(file));previews.delete(file);} files.splice(index,1);render(); });
      row.append(remove);pending.append(row);
    });
    picker.files=transfer.files;
  }
  picker?.addEventListener('change',() => {files.push(...picker.files);render();});
  composer?.addEventListener('work:accepted',() => {previews.forEach(url=>URL.revokeObjectURL(url));previews.clear();files=[];render();composer.elements.work_location.value='';});
})();
