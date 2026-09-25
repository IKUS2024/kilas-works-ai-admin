(() => {
  for(const box of document.querySelectorAll('[data-web-share]:not([data-ready])')){
    box.dataset.ready='1';let busy=false;
    for(const action of ['open','copy']) box.querySelector('[data-share-'+action+']').addEventListener('click',async()=>{
      if(busy)return;busy=true;
      const status=box.querySelector('[data-share-status]');let opened=null;
      if(action==='open'){opened=window.open('about:blank','_blank');if(opened)opened.opener=null;}
      try{
        const response=await fetch(box.dataset.url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':box.dataset.csrf},body:'{}'});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error==='business_setup_required'?'Lengkapi pengetahuan bisnis terlebih dahulu.':'Link chat belum tersedia.');
        const url=new URL(data.path,window.location.origin).href;
        if(action==='open'){if(opened)opened.location=url;else window.location.assign(url);}
        else{
          try{await navigator.clipboard.writeText(url);status.textContent='Link disalin.';}
          catch(error){const field=box.querySelector('[data-share-link]');field.hidden=false;field.value=url;field.select();status.textContent='Salin link di atas.';}
        }
      }catch(error){if(opened)opened.close();status.textContent=error.message;}
      finally{busy=false;}
    });
  }
})();
