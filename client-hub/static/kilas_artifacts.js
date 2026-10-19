(()=>{
  const t=message=>window.KilasUI?window.KilasUI.t(message):message;
  const card=(payload,{openUrl=null}={})=>{
    const name=typeof payload.filename==='string'&&payload.filename.trim()?payload.filename:t('File hasil');
    const suffix=name.includes('.')?name.split('.').pop().toUpperCase():'';
    const kind=/^[A-Z0-9]{1,7}$/.test(suffix)?suffix:'FILE';
    const root=document.createElement('div');root.className='ai-file-card';
    const badge=document.createElement('span');badge.className='ai-file-kind';badge.setAttribute('aria-hidden','true');badge.textContent=kind;
    const details=document.createElement('span');details.className='ai-file-details';
    const filename=document.createElement('strong');filename.textContent=name;
    const metadata=document.createElement('small');
    const size=Number.isFinite(payload.byte_size)&&payload.byte_size>=0?' · '+(payload.byte_size/1024).toFixed(1)+' '+t('KB'):'';
    metadata.textContent=kind+size;details.append(filename,metadata);root.append(badge,details);
    if(typeof payload.url==='string'&&payload.url){
      const actions=document.createElement('span');actions.className='ai-file-actions';
      for(const [label,url] of [[t('Buka'),openUrl],[t('Download'),payload.url]]){
        if(!url)continue;
        const link=document.createElement('a');link.textContent=label;link.href=url;link.setAttribute('aria-label',label+': '+name);
        if(url===openUrl){link.target='_blank';link.rel='noopener';}
        actions.append(link);
      }
      root.append(actions);
    }else{
      const unavailable=document.createElement('span');unavailable.className='ai-file-unavailable';unavailable.textContent=t('Tidak tersedia');root.append(unavailable);
    }
    return root;
  };
  window.KilasArtifacts={card};
})();
