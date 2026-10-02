/* Work-only preferences and explicit contextual browser permissions. */
(() => {
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
        status.textContent=response.ok?'Zona waktu tersimpan.':'Pilih zona waktu IANA yang valid.';
      } catch (_) { status.textContent='Zona waktu belum tersimpan. Coba lagi.'; }
    });
  }
  document.querySelector('[data-enable-push]')?.addEventListener('click',async () => {
    const status=document.querySelector('[data-push-status]');
    try {
      preferences ||= await load();
      if (!preferences.push_available || !preferences.public_key || !window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window)) {
        status.textContent='Notifikasi perangkat belum tersedia. Pengingat tetap tersimpan di Work.';return;
      }
      if (await Notification.requestPermission() !== 'granted') { status.textContent='Izin belum diberikan. Pengingat tetap muncul di Work.';return; }
      const registration=await navigator.serviceWorker.register('/kilas-ai/work/service-worker.js',{scope:'/kilas-ai/'});
      await navigator.serviceWorker.ready;
      const encoded=preferences.public_key.replace(/-/g,'+').replace(/_/g,'/');
      const key=Uint8Array.from(atob(encoded+'='.repeat((4-encoded.length%4)%4)),c=>c.charCodeAt(0));
      const subscription=await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});
      const response=await fetch('/kilas-ai/work/push',{method:'POST',headers,body:JSON.stringify(subscription.toJSON())});
      status.textContent=response.ok?'Notifikasi perangkat aktif.':'Notifikasi belum tersimpan. Coba lagi.';
    } catch (_) { status.textContent='Notifikasi belum aktif. Pengingat tetap tersimpan di Work.'; }
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
      locationButton.parentElement.querySelector('p').textContent='Lokasi tidak dibagikan. Ketik nama daerah yang ingin dicari.';
    },{maximumAge:0,timeout:10000,enableHighAccuracy:false});
  });
  const picker=composer?.querySelector('#work-source-files');
  document.querySelector('[data-work-attach]')?.addEventListener('click',()=>picker.click());
  const pending=document.querySelector('#work-pending-files');
  let files=[];
  function render() {
    pending.replaceChildren();
    const transfer=new DataTransfer();
    files.forEach((file,index) => {
      transfer.items.add(file);
      const row=document.createElement('div');row.className='work-pending-file';
      const name=document.createElement('span');name.textContent=file.name;
      const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Hapus lampiran ${file.name}`);
      remove.addEventListener('click',() => { files.splice(index,1);render(); });
      row.append(name,remove);pending.append(row);
    });
    picker.files=transfer.files;
  }
  picker?.addEventListener('change',() => {files.push(...picker.files);render();});
  composer?.addEventListener('work:accepted',() => {files=[];render();composer.elements.work_location.value='';});
})();
