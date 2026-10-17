// Public source metadata only. Never insert provider HTML or navigate implicitly.
export function renderCallSources(container,citations=[],checkedOn=null){
 if(!container)return;
 const document=container.ownerDocument;container.replaceChildren();container.hidden=true;
 if(!Array.isArray(citations))return;
 const links=[];
 for(const item of citations.slice(0,3)){
  if(!item||typeof item.url!=='string'||item.url.length>2048||typeof item.title!=='string')continue;
  let url;try{url=new URL(item.url);}catch{continue;}
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password)continue;
  const link=document.createElement('a');link.href=url.href;link.textContent=url.hostname.replace(/^www\./,'');
  link.title=item.title.slice(0,160);link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';
  const row=document.createElement('li');row.append(link);links.push(row);
 }
 if(!links.length)return;
 const locale=(document.documentElement.lang||'en').split('-')[0];
 const label={en:'Sources checked',id:'Sumber diperiksa',es:'Fuentes consultadas',zh:'已查阅来源'}[locale]||'Sources checked';
 const title=document.createElement('span');title.textContent=label+(typeof checkedOn==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(checkedOn)?' · '+checkedOn:'');
 const list=document.createElement('ul');list.setAttribute('aria-label',label);list.append(...links);
 container.append(title,list);container.hidden=false;
}
