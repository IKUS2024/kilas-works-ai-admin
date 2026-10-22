/* Read-only presentation; no capture, playback, translation or provider mutations. */
(()=>{
 const original=document.querySelector('#audio-script'),output=document.querySelector('#voice-script-duration');if(!original||!output)return;
 const t=(key,values)=>window.KilasUI?window.KilasUI.t(key,values):key;
 function duration(){
  const translated=document.querySelector('#voice-translated-script'),useTranslated=document.querySelector('#voice-translate-toggle')?.checked&&!document.querySelector('#voice-translated-result')?.hidden;
  const text=(useTranslated?translated.value:original.value).trim();
  if(!text){output.textContent=t('Durasi perkiraan muncul setelah naskah ditulis.');return;}
  const cjk=(text.match(/[\u3040-\u30ff\u3400-\u9fff]/gu)||[]).length;
  const rest=text.replace(/[\u3040-\u30ff\u3400-\u9fff]/gu,' '),words=(rest.match(/\S+/gu)||[]).length;
  const low=Math.max(1,Math.round(words/170*60+cjk/350*60)),high=Math.max(low,Math.ceil(words/130*60+cjk/250*60));
  output.textContent=t('Perkiraan durasi: {min}–{max} detik.',{min:low,max:high});
 }
 document.querySelector('.voice-script-workspace')?.addEventListener('input',duration);
 document.addEventListener('voice-script-edit',()=>queueMicrotask(duration));document.addEventListener('voice-translation-state',duration);duration();
 const history=document.querySelector('#audio-history');
 function dates(){history?.querySelectorAll('[data-audio-local-date]').forEach(node=>{const date=new Date(node.dateTime);if(!Number.isNaN(date.valueOf()))node.textContent=new Intl.DateTimeFormat(document.documentElement.lang||'en',{dateStyle:'medium',timeStyle:'short'}).format(date);node.removeAttribute('data-audio-local-date');});}
 dates();if(history)new MutationObserver(dates).observe(history,{childList:true,subtree:true});
})();
