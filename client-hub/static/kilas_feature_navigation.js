/* Native links and presentation URL only; never generate or persist a draft. */
(()=>{
 const nav=document.querySelector('.kilas-feature-navigation');if(!nav)return;
 const active=nav.querySelector('[aria-current=page]');if(active){const row=active.parentElement;row.scrollLeft=Math.max(0,active.getBoundingClientRect().right-row.getBoundingClientRect().right);}
 nav.addEventListener('click',event=>{
  const link=event.target.closest('[data-kilas-feature]');if(!link||event.defaultPrevented)return;
  const audio=document.querySelector('#audio-studio'),video=document.querySelector('#video-composer');
  if(audio&&['translate','voiceover'].includes(link.dataset.kilasFeature)){
   event.preventDefault();document.querySelector(link.dataset.kilasFeature==='voiceover'?'#voiceover-tab':'#translate-tab').click();return;
  }
  const busy=audio?.querySelector('[aria-busy=true]')||video?.getAttribute('aria-busy')==='true';
  if(busy){event.preventDefault();return;}
  const fields=audio?[...audio.querySelectorAll('textarea,input[type=file]')]:video?[...video.querySelectorAll('textarea,input[type=file]')]:[];
  const snapshot=fields.map(e=>[e.value,e.files?.length||0]);
  if(snapshot.some(([text,files])=>text.trim()||files)){
   if(!confirm('Tinggalkan draf yang belum dibuat? Teks dan lampiran di layar ini tidak akan dibawa ke fitur lain.'))event.preventDefault();
   if(fields.some((e,i)=>e.value!==snapshot[i][0]||(e.files?.length||0)!==snapshot[i][1]))event.preventDefault();
  }
 });
})();
