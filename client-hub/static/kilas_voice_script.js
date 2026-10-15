(() => {
  const t=(message,values)=>window.KilasUI ? window.KilasUI.t(message,values) : Object.entries(values||{}).reduce((text,[key,value])=>text.replaceAll('{'+key+'}',String(value)),message);
  const setup=document.querySelector('#personal-voice-setup');if(!setup)return;
  const original=document.querySelector('#audio-script'),toggle=document.querySelector('#voice-translate-toggle'),options=document.querySelector('#voice-translation-options');
  const target=document.querySelector('#voice-translation-target'),result=document.querySelector('#voice-translated-result'),edited=document.querySelector('#voice-translated-script');
  const button=document.querySelector('#voice-translate-preview'),status=document.querySelector('#voice-translation-status'),error=document.querySelector('#voice-translation-error');
  const language=document.querySelector('#voice-language'),source=document.querySelector('#voice-translation-source');
  let version=0,busy=false;
  function state(){
    setup.dataset.translationReady=String(!toggle.checked||(!result.hidden&&edited.value.trim().length>0&&!busy));document.dispatchEvent(new Event('voice-translation-state'));
  }
  function invalidate(){version++;options.hidden=!toggle.checked;result.hidden=true;edited.required=false;language.value=toggle.checked?target.value:'auto';source.value='auto';status.hidden=true;error.hidden=true;state();}
  toggle.addEventListener('change',invalidate);target.addEventListener('change',invalidate);original.addEventListener('input',()=>{if(toggle.checked)invalidate();});edited.addEventListener('input',state);invalidate();
  button.addEventListener('click',async()=>{
    if(busy||!toggle.checked)return;
    if(!original.value.trim()){original.reportValidity();return;}
    const current=++version;busy=true;button.disabled=true;error.hidden=true;status.hidden=false;status.textContent=t('Menerjemahkan naskah...');state();
    const data=new FormData();data.append('script',original.value);data.append('language',target.value);data.append('csrf_token',document.querySelector('#voiceover-panel [name=csrf_token]').value);
    try{
      const response=await fetch('/kilas-translator/voice-script/translate',{method:'POST',body:data,credentials:'same-origin'});
      if(response.redirected)throw Error(t('Sesi berakhir. Masuk kembali untuk melanjutkan.'));
      const body=await response.json();if(!response.ok)throw Error(body.error||t('Terjemahan belum berhasil. Coba lagi.'));
      if(current!==version)return;
      edited.value=body.text;source.value=body.source_language;language.value=target.value;edited.required=true;result.hidden=false;status.textContent=t('Terjemahan siap diperiksa. Belum ada suara yang dibuat.');
    }catch(e){if(current===version){error.textContent=e instanceof SyntaxError||e instanceof TypeError?t('Terjemahan belum berhasil. Naskah asli tetap aman.'):e.message;error.hidden=false;status.hidden=true;}}
    finally{busy=false;button.disabled=false;state();}
  });
  document.querySelector('#voiceover-panel form[data-audio-form]').addEventListener('submit',event=>{if(toggle.checked&&(result.hidden||busy||!edited.value.trim())){event.preventDefault();event.stopImmediatePropagation();error.textContent=t('Terjemahkan dan periksa naskah sebelum membuat suara.');error.hidden=false;}},true);
})();
