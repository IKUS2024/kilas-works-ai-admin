function bind(root) {
  let busy=false,controller=null,generation=0;
  const status=root.querySelector('[data-project-status]'),abort=root.querySelector('[data-project-abort]');
  const choice=root.querySelector('select[name="project_id"]'),newProject=root.querySelector('[data-project-new]'),title=newProject.querySelector('input[name="title"]');
  const toggle=()=>{newProject.hidden=choice.value!=='';title.required=!newProject.hidden;};
  choice.addEventListener('change',toggle);toggle();
  const unlock=()=>{busy=false;abort.hidden=true;root.querySelectorAll('[data-project-form] button[type="submit"]').forEach(b=>b.disabled=false);};
  const hide=()=>{++generation;controller?.abort();};
  abort.addEventListener('click',()=>{++generation;controller?.abort();unlock();status.textContent='Permintaan dibatalkan di browser. Muat ulang untuk memeriksa apakah server sudah menyimpan perubahan.';});
  root.addEventListener('submit',async event=>{
    const form=event.target;if(!form.matches('[data-project-form]'))return;
    event.preventDefault();if(busy)return;
    const body=new FormData(form),ticket=++generation;busy=true;controller=new AbortController();
    root.querySelectorAll('[data-project-form] button[type="submit"]').forEach(b=>b.disabled=true);
    abort.hidden=false;status.textContent='Menyimpan perubahan proyek…';
    try {
      const response=await fetch(form.action,{method:'POST',body,headers:{Accept:'application/json'},signal:controller.signal});
      if(!response.ok)throw Error(response.status===409?'Proyek atau naskah berubah. Muat ulang chat sebelum menyimpan.':'Permintaan belum berhasil. Muat ulang untuk memeriksa perubahan.');
      const data=await response.json();if(ticket!==generation||!root.isConnected)return;
      const doc=new DOMParser().parseFromString(data.panel_html,'text/html'),incoming=doc.querySelector('[data-chat-projects]');
      if(!incoming||incoming.dataset.conversation!==root.dataset.conversation)throw Error('Respons percakapan tidak cocok. Muat ulang chat.');
      const url=new URL(location.href);if(data.script_version)url.searchParams.set('chat_script_version',data.script_version);else url.searchParams.delete('chat_script_version');history.replaceState(null,'',url);
      window.removeEventListener('pagehide',hide);root.replaceWith(incoming);bind(incoming);
    } catch(error) {if(ticket===generation&&root.isConnected)status.textContent=error.name==='AbortError'?'Permintaan dibatalkan. Muat ulang untuk memeriksa perubahan.':error.message;}
    finally {if(ticket===generation&&root.isConnected)unlock();}
  });
  window.addEventListener('pagehide',hide,{once:true});
}
const root=document.querySelector('[data-chat-projects]');if(root)bind(root);
