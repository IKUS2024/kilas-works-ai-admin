function bind(root) {
  let busy=false,controller=null,generation=0;
  const status=root.querySelector('[data-demo-status]'),abort=root.querySelector('[data-demo-abort]');
  const unlock=()=>{busy=false;abort.hidden=true;root.querySelectorAll('[data-demo-form] button[type="submit"]').forEach(b=>b.disabled=false);};
  const hide=()=>{++generation;controller?.abort();};
  abort.addEventListener('click',()=>{++generation;controller?.abort();unlock();status.textContent='Dibatalkan di browser. Muat ulang untuk memeriksa apakah server sudah menyimpan hasil mock.';});
  root.addEventListener('submit',async event=>{
    const form=event.target;if(!form.matches('[data-demo-form]'))return;
    event.preventDefault();if(busy)return;
    const body=new FormData(form),ticket=++generation;busy=true;controller=new AbortController();
    root.querySelectorAll('[data-demo-form] button[type="submit"]').forEach(b=>b.disabled=true);
    abort.hidden=false;status.textContent='Menyimpan tindakan mock yang kamu pilih…';
    try {
      const response=await fetch(form.action,{method:'POST',body,headers:{Accept:'application/json'},signal:controller.signal});
      if(!response.ok)throw Error(response.status===409?'Versi berubah. Muat ulang chat sebelum melanjutkan.':'Permintaan belum berhasil. Periksa pilihan dan muat ulang chat.');
      const data=await response.json();
      if(ticket!==generation||!root.isConnected)return;
      const doc=new DOMParser().parseFromString(data.panel_html,'text/html');const incoming=doc.querySelector('[data-chat-content]');
      if(!incoming||incoming.dataset.conversation!==root.dataset.conversation)throw Error('Respons percakapan tidak cocok. Muat ulang chat.');
      window.removeEventListener('pagehide',hide);root.replaceWith(incoming);bind(incoming);
    } catch(error) {if(ticket===generation&&root.isConnected)status.textContent=error.name==='AbortError'?'Permintaan dibatalkan. Muat ulang untuk memeriksa hasil mock.':error.message;}
    finally {if(ticket===generation&&root.isConnected)unlock();}
  });
  window.addEventListener('pagehide',hide,{once:true});
}
const root=document.querySelector('[data-chat-content]');if(root)bind(root);
