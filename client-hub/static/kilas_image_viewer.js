/* Authenticated, same-site image preview. No provider URLs are accepted. */
(()=>{'use strict';
if(window.KilasImageViewer)return;
const t=s=>window.KilasUI?.t?.(s)||s;
const endpoint=/^\/kilas-ai\/(?:threads\/\d+\/attachments\/\d+|agent\/jobs\/\d+\/artifacts\/\d+)$/;
function safeURL(value){try{const u=new URL(value,location.href);return u.origin===location.origin&&!u.username&&!u.password&&endpoint.test(u.pathname)?u:null;}catch{return null;}}
function downloadURL(value){const u=safeURL(value);if(!u)return null;u.search='';u.hash='';if(u.pathname.includes('/artifacts/'))u.searchParams.set('download','1');return u.href;}
let dialog,picture,status,download,title,opener,controller,objectURL,active=false,closing=false;
const historyKey='kilasImagePreview';
function cleanup(){controller?.abort();controller=null;if(objectURL)URL.revokeObjectURL(objectURL);objectURL=null;picture?.removeAttribute('src');}
function close(fromHistory=false){if(!active)return;active=false;cleanup();dialog.close();document.body.classList.remove('kilas-image-preview-open');if(opener?.isConnected)opener.focus();if(!fromHistory&&history.state?.[historyKey]){closing=true;history.back();}}
function create(){if(dialog)return;dialog=document.createElement('dialog');dialog.className='kilas-image-viewer';dialog.setAttribute('aria-labelledby','kilas-image-viewer-title');
 const header=document.createElement('header');title=document.createElement('h2');title.id='kilas-image-viewer-title';
 const actions=document.createElement('div');actions.className='kilas-image-viewer-actions';download=document.createElement('a');download.textContent=t('Download gambar');download.setAttribute('download','');
 const button=document.createElement('button');button.type='button';button.textContent=t('Tutup');button.addEventListener('click',()=>close());actions.append(download,button);header.append(title,actions);
 const content=document.createElement('div');content.className='kilas-image-viewer-content';picture=document.createElement('img');status=document.createElement('p');status.setAttribute('role','status');content.append(picture,status);dialog.append(header,content);document.body.append(dialog);
 dialog.addEventListener('keydown',event=>{if(event.key!=='Tab')return;const first=download.hidden?button:download,last=button;if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}});
 dialog.addEventListener('cancel',event=>{event.preventDefault();close();});dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}});
}
async function open(anchor){if(closing||active)return;const url=safeURL(anchor.href);if(!url)return;create();cleanup();opener=anchor;active=true;title.textContent=anchor.dataset.imageName||anchor.querySelector('img')?.alt||t('Pratinjau');picture.alt=title.textContent;picture.hidden=true;download.hidden=true;download.href=downloadURL(url.href);status.hidden=false;status.textContent=t('Memuat…');dialog.showModal();document.body.classList.add('kilas-image-preview-open');
 history.pushState({...history.state,[historyKey]:true},'',location.href);controller=new AbortController();const current=controller;
 try{const response=await fetch(url.href,{credentials:'same-origin',redirect:'error',signal:current.signal,cache:'no-store'});if(!response.ok||!/^image\/(png|jpeg|webp|gif|bmp)(?:;|$)/i.test(response.headers.get('content-type')||''))throw Error('unavailable');const blob=await response.blob();if(current!==controller)return;objectURL=URL.createObjectURL(blob);picture.src=objectURL;await picture.decode();if(current!==controller)return;picture.hidden=false;status.hidden=true;download.hidden=false;}catch(error){if(current!==controller||error.name==='AbortError')return;status.textContent=t('Gambar tidak dapat dibuka. Tutup dan coba lagi.');picture.hidden=true;download.hidden=true;}
}
document.addEventListener('click',event=>{const anchor=event.target.closest?.('a[data-kilas-image]');if(!anchor||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();open(anchor);});
window.addEventListener('popstate',()=>{closing=false;if(active)close(true);});
// A restored page cannot restore an in-memory image; discard only our marker.
if(history.state?.[historyKey]){const state={...history.state};delete state[historyKey];history.replaceState(state,'',location.href);}
window.KilasImageViewer={safeURL,downloadURL};
})();
