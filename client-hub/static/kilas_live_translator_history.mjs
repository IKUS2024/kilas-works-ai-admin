import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
// Page/session-local only. Audio eviction keeps the complete text and labels;
// no old button can point at a newer turn or cause paid regeneration.
export class TranslatorHistory {
 constructor({element,languageName,replay,available}){Object.assign(this,{element,languageName,replay,available});this.rows=new Map();this.pending=new Map();}
 add(result,first){
  if(result.status==='PROCESSING'&&result.translation_ready===true&&typeof result.translation_key==='string'&&result.translated_text){
   if(!this.pending.has(result.translation_key))this.pending.set(result.translation_key,this.createRow(result,first));
   return;
  }
  if(result.status!=='COMPLETED'||typeof result.audio_url!=='string'||!result.translated_text)return;
  if(this.rows.has(result.audio_url))return;
  const row=this.pending.get(result.translation_key)||this.createRow(result,first);this.pending.delete(result.translation_key);
  const button=document.createElement('button');button.type='button';button.className='live-replay';button.setAttribute('aria-label',t('Putar ulang audio'));button.title=t('Putar ulang audio');button.textContent='▶';button.disabled=Boolean(this.isBusy)||!this.available(result.audio_url);button.addEventListener('click',()=>this.replay(result.audio_url));
  row.append(button);this.rows.set(result.audio_url,{row,button});this.element.scrollTop=this.element.scrollHeight;
 }
 createRow(result,first){
  const row=document.createElement('article');row.className='live-message '+(result.source_language===first?'live-message-first':'live-message-second');
  const label=document.createElement('p');label.className='live-message-language';label.textContent=this.languageName(result.source_language)+' → '+this.languageName(result.target_language);
  const source=document.createElement('p');source.className='live-message-original';source.textContent=result.source_text||'';source.lang=result.source_language;
  const text=document.createElement('p');text.className='live-message-translated';text.textContent=result.translated_text;text.lang=result.target_language;
  row.append(label,source,text);this.element.append(row);this.element.scrollTop=this.element.scrollHeight;return row;
 }
 stored(url){const value=this.rows.get(url);if(value)value.button.disabled=Boolean(this.isBusy);}
 remove(url){const value=this.rows.get(url);if(value){value.button.disabled=true;value.button.title=t('Audio tersimpan sudah tidak tersedia. Audio tidak dibuat ulang.');value.button.setAttribute('aria-label',value.button.title);}}
 clear(){this.element.replaceChildren();this.rows.clear();this.pending.clear();}
 busy(value){this.isBusy=value;for(const [url,{button}] of this.rows)button.disabled=value||!this.available(url);}
}
