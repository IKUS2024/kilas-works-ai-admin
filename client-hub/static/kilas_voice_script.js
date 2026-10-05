(() => {
  const setup=document.querySelector('#personal-voice-setup');if(!setup)return;
  const original=document.querySelector('#audio-script'),toggle=document.querySelector('#voice-translate-toggle'),options=document.querySelector('#voice-translation-options');
  const target=document.querySelector('#voice-translation-target'),result=document.querySelector('#voice-translated-result'),edited=document.querySelector('#voice-translated-script');
  const button=document.querySelector('#voice-translate-preview'),status=document.querySelector('#voice-translation-status'),error=document.querySelector('#voice-translation-error');
  const language=document.querySelector('#voice-language'),source=document.querySelector('#voice-translation-source');
  let version=0,busy=false;
  function state(){
    setup.dataset.translationReady=String(!toggle.checked||(!result.hidden&&edited.value.trim().length>0&&!busy));document.dispatchEvent(new Event('voice-translation-state'));
    const text=(toggle.checked&&!result.hidden?edited.value:original.value).trim(),words=text?text.split(/\s+/).length:0;
    const seconds=text?Math.max(1,Math.ceil(Math.max(words/2.3,text.length/13))):0,reserve=text?Math.min(Number(document.querySelector('#audio-studio').dataset.maxSeconds),Math.ceil(Math.max(words/0.8,text.length/4)+10)):0;
    document.querySelector('#voice-estimate').textContent=toggle.checked&&result.hidden?'Periksa hasil terjemahan sebelum membuat suara.':`Estimasi ${seconds}s · reservasi hingga ${reserve}s. Pemakaian akhir mengikuti MP3 aktual; sisa reservasi dikembalikan.`;
  }
  function invalidate(){version++;options.hidden=!toggle.checked;result.hidden=true;edited.required=false;language.value=toggle.checked?target.value:'auto';source.value='auto';status.hidden=true;error.hidden=true;state();}
  toggle.addEventListener('change',invalidate);target.addEventListener('change',invalidate);original.addEventListener('input',()=>{if(toggle.checked)invalidate();});edited.addEventListener('input',state);invalidate();
  button.addEventListener('click',async()=>{
    if(busy||!toggle.checked)return;
    if(!original.value.trim()){original.reportValidity();return;}
    const current=++version;busy=true;button.disabled=true;error.hidden=true;status.hidden=false;status.textContent='Menerjemahkan naskah...';state();
    const data=new FormData();data.append('script',original.value);data.append('language',target.value);data.append('csrf_token',document.querySelector('#voiceover-panel [name=csrf_token]').value);
    try{
      const response=await fetch('/kilas-translator/voice-script/translate',{method:'POST',body:data,credentials:'same-origin'});
      if(response.redirected)throw Error('Sesi berakhir. Masuk kembali untuk melanjutkan.');
      const body=await response.json();if(!response.ok)throw Error(body.error||'Terjemahan belum berhasil. Coba lagi.');
      if(current!==version)return;
      edited.value=body.text;source.value=body.source_language;language.value=target.value;edited.required=true;result.hidden=false;status.textContent='Terjemahan siap diperiksa. Belum ada suara yang dibuat.';
    }catch(e){if(current===version){error.textContent=e instanceof SyntaxError||e instanceof TypeError?'Terjemahan belum berhasil. Naskah asli tetap aman.':e.message;error.hidden=false;status.hidden=true;}}
    finally{busy=false;button.disabled=false;state();}
  });
  document.querySelector('#voiceover-panel form').addEventListener('submit',event=>{if(toggle.checked&&(result.hidden||busy||!edited.value.trim())){event.preventDefault();event.stopImmediatePropagation();error.textContent='Terjemahkan dan periksa naskah sebelum membuat suara.';error.hidden=false;}},true);
})();
