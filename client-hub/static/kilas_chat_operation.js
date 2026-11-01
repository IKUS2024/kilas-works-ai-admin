/* An uncertain retry keeps its key; a changed payload or terminal result does not. */
((root)=>{
  const random=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  function create(initial){
    let key=initial||random(),previous=null;
    const snapshot=data=>[...data.entries()].filter(([name,value])=>!['csrf_token','operation_key'].includes(name)&&(typeof value==='string'||value.name));
    const equal=(a,b)=>a.length===b.length&&a.every(([name,value],i)=>name===b[i][0]&&value===b[i][1]);
    return {
      begin(data){const next=snapshot(data);if(previous&&!equal(previous,next))key=random();previous=next;return key;},
      terminal(){key=random();previous=null;return key;}
    };
  }
  if(typeof module!=='undefined')module.exports={create};else {
    root.KilasChatOperation={create};
    const t=(key)=>root.KilasUI?root.KilasUI.t(key):key;
    let expired=false;
    root.KilasChatRecovery={
      check(response){
        if(response.status===401 || (response.redirected && new URL(response.url,location.href).pathname==='/login')){
          expired=true;const error=new Error(t('Sesi akun berakhir. Masuk kembali.'));error.sessionExpired=true;throw error;
        }
      },
      show(error,node){
        node.textContent=error.message;
        if(error.sessionExpired){const link=document.createElement('a');link.href='/login';link.target='_blank';link.rel='noopener';link.textContent=t('Masuk kembali');node.append(' ',link);}
      },
      async session(signal){
        if(!expired)return;
        const response=await fetch(location.href,{cache:'no-store',headers:{'X-Chat-Request':'1'},signal});
        this.check(response);if(!response.ok)throw new Error(t('Chat belum dapat dimuat. Coba lagi.'));
        const doc=new DOMParser().parseFromString(await response.text(),'text/html');
        const token=doc.querySelector('meta[name="csrf-token"]')?.content || doc.querySelector('input[name="csrf_token"]')?.value;
        if(!token)throw new Error(t('Sesi akun berakhir. Masuk kembali.'));
        document.querySelectorAll('input[name="csrf_token"]').forEach(e=>e.value=token);
        const meta=document.querySelector('meta[name="csrf-token"]');if(meta)meta.content=token;
        expired=false;
      }
    };
  }
})(typeof window==='undefined'?globalThis:window);
