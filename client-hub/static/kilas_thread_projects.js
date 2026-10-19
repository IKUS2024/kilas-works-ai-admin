(()=>{
  const t=message=>window.KilasUI?window.KilasUI.t(message):message;
  const csrf=()=>document.querySelector('meta[name="csrf-token"]').content;
  const headers=()=>({'Content-Type':'application/json','X-CSRF-Token':csrf(),'X-Workspace-Async':'1'});
  const wait=(ms,signal)=>new Promise((resolve,reject)=>{const timer=setTimeout(resolve,ms);signal?.addEventListener('abort',()=>{clearTimeout(timer);reject(new DOMException('Stopped','AbortError'));},{once:true});});
  const file=item=>{const card=window.KilasArtifacts.card(item);card.dataset.artifactId=item.id;return card;};
  window.KilasThreadProjects={
    async watch(payload,body,signal){
      const article=body.closest('.ai-message');article.dataset.workspaceJob=payload.url;
      let activity=article.querySelector('.ai-activity');if(!activity){activity=document.createElement('div');activity.className='ai-activity';activity.setAttribute('role','status');body.before(activity);}
      let after=0;
      for(let index=0;index<600;index++){
        if(signal?.aborted)throw new DOMException('Stopped','AbortError');
        const response=await fetch(payload.url+'?after='+after,{signal,cache:'no-store'});
        if(!response.ok)throw new Error(t('Hasil pekerjaan belum dapat dimuat. Muat ulang chat untuk melanjutkan.'));
        const result=await response.json();
        for(const event of result.events){after=event.id;activity.textContent=t(event.label);activity.hidden=false;}
        for(const item of result.files){if(!article.querySelector('[data-artifact-id="'+item.id+'"]'))article.append(file(item));}
        if(['COMPLETED','FAILED','STOPPED','WAITING','NEEDS_APPROVAL','PAUSED'].includes(result.state)){
          activity.hidden=true;window.KilasMarkdown.render(body,t(result.state==='STOPPED'?'Jawaban dihentikan.':result.text));
          window.KilasMarkdown.finish(body);return result;
        }
        activity.hidden=false;
        const started=await fetch(payload.url+'/start',{method:'POST',headers:headers(),body:'{}',signal});
        if(!started.ok){const problem=await started.json().catch(()=>({}));throw new Error(t(problem.error||'Hasil pekerjaan belum dapat dimuat. Muat ulang chat untuk melanjutkan.'));}
        await wait(1000,signal);
      }
      activity.hidden=true;throw new Error(t('Hasil pekerjaan belum dapat dimuat. Muat ulang chat untuk melanjutkan.'));
    },
    stop(payload){return fetch(payload.url+'/stop',{method:'POST',headers:headers(),body:'{}',keepalive:true});}
  };
  document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('[data-workspace-job]').forEach(article=>{const body=article.querySelector('.ai-message-text');window.KilasThreadProjects.watch({url:article.dataset.workspaceJob},body).catch(error=>{const notice=document.querySelector('#ai-notice');if(notice)notice.textContent=error.message;});});});
})();
