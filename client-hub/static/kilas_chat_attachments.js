/* UI-only previews. Durable files keep the existing authenticated download routes. */
(()=>{'use strict';
 const t=(key,values)=>window.KilasUI?window.KilasUI.t(key,values):key;
 const urls=new WeakMap();
 const isImage=file=>/^image\/(?:jpeg|png|webp)$/.test(file.type||file.mime_type||'')||/\.(?:jpe?g|png|webp)$/i.test(file.name||file.filename||'');
 function unavailable(image){const card=image.closest('.chat-upload-image');if(!card)return;image.hidden=true;card.classList.add('is-unavailable');if(!card.querySelector('.chat-upload-unavailable')){const text=document.createElement('span');text.className='chat-upload-unavailable';text.textContent=t('Tidak tersedia');card.append(text);}}
 function image(file,url){const card=document.createElement('a');card.className='chat-upload-image';card.href=url;card.target='_blank';card.rel='noopener';card.setAttribute('aria-label',t('Gambar dalam chat'));const img=document.createElement('img');img.src=url;img.alt=t('Gambar dalam chat');img.width=180;img.height=140;img.decoding='async';img.addEventListener('error',()=>unavailable(img));card.append(img);return card;}
 function preview(selected){const group=document.createElement('div');group.className='chat-user-attachments';group.dataset.attachmentState='pending';group.setAttribute('role','group');group.setAttribute('aria-label',t('Lampiran terkirim'));const owned=[];
  for(const file of selected){if(isImage(file)){const url=URL.createObjectURL(file);owned.push(url);group.append(image(file,url));}else{const card=window.KilasArtifacts.card({filename:file.name,byte_size:file.size});card.querySelector('.ai-file-unavailable')?.remove();group.append(card);}}
  urls.set(group,owned);return group;
 }
 function release(group){for(const url of urls.get(group)||[])URL.revokeObjectURL(url);urls.delete(group);}
 function pendingImage(file){const group=preview([file]);const card=group.firstElementChild;card.removeAttribute('href');card.removeAttribute('target');card.removeAttribute('aria-label');card.tabIndex=-1;urls.set(card,urls.get(group));urls.delete(group);return card;}
 document.addEventListener('error',event=>{if(event.target.matches?.('.chat-upload-image img'))unavailable(event.target);},true);
 document.querySelectorAll('.chat-upload-image img').forEach(img=>{if(img.complete&&!img.naturalWidth)unavailable(img);});
 window.KilasChatAttachments={preview,release,isImage,pendingImage};
})();
