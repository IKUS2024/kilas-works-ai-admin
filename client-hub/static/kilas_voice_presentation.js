/* Read-only presentation; no capture, playback, translation or provider mutations. */
(()=>{
 const history=document.querySelector('#audio-history');
 function dates(){history?.querySelectorAll('[data-audio-local-date]').forEach(node=>{const date=new Date(node.dateTime);if(!Number.isNaN(date.valueOf()))node.textContent=new Intl.DateTimeFormat(document.documentElement.lang||'en',{dateStyle:'medium',timeStyle:'short'}).format(date);node.removeAttribute('data-audio-local-date');});}
 dates();if(history)new MutationObserver(dates).observe(history,{childList:true,subtree:true});
})();
