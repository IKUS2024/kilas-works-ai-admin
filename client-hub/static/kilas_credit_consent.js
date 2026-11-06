/* One exact request retry after explicit same-origin, account-bound consent. */
(()=>{'use strict';
 const result=document.querySelector('#credit-consent-result');
 if(result&&window.opener){window.opener.postMessage({type:'kilas-credit-consent',token:result.dataset.token,state:result.dataset.state},location.origin);return;}
 if(window.kilasCreditConsentInstalled)return;
 window.kilasCreditConsentInstalled=true;
 const nativeFetch=window.fetch.bind(window);
 window.fetch=async(input,options)=>{
   const request=new Request(input,options),url=new URL(request.url,location.href);
   if(url.origin!==location.origin||!/^\/kilas-(ai|translator)\//.test(url.pathname)||request.method==='GET')return nativeFetch(request);
   const retry=request.clone(),response=await nativeFetch(request);
   if(response.status!==402)return response;
   let data;try{data=await response.clone().json();}catch{return response;}
   const target=new URL(data.credit_consent_url||'',location.href);
   if(target.origin!==location.origin||!/^\/kilas-ai\/credits\/consent\/[a-f0-9]{64}$/.test(target.pathname))return response;
   const labels=document.querySelector('[data-credit-consent-labels]');
   const dialog=document.createElement('dialog'),message=document.createElement('p'),approve=document.createElement('button'),decline=document.createElement('button');
   message.textContent=labels?.dataset.message||'Credit approval required';approve.textContent=labels?.dataset.approve||'Review maximum charge';decline.textContent=labels?.dataset.decline||'Decline';
   dialog.className='kilas-credit-dialog';dialog.append(message,approve,decline);document.body.append(dialog);dialog.showModal();
   const accepted=await new Promise(resolve=>{
     let popup,finished=false;
     const finish=ok=>{if(finished)return;finished=true;clearTimeout(timer);window.removeEventListener('message',receive);retry.signal.removeEventListener('abort',onAbort);dialog.close();dialog.remove();resolve(ok);};
     const onAbort=()=>finish(false);
     const receive=event=>{if(event.origin===location.origin&&event.source===popup&&event.data?.type==='kilas-credit-consent'&&event.data.token===target.pathname.split('/').pop())finish(event.data.state==='APPROVED');};
     const timer=setTimeout(()=>finish(false),240000);
     window.addEventListener('message',receive);retry.signal.addEventListener('abort',onAbort,{once:true});
     if(retry.signal.aborted){finish(false);return;}
     approve.onclick=()=>{popup=window.open(target.href,'kilas-credit-consent','popup,width=520,height=660');};
     decline.onclick=()=>finish(false);dialog.addEventListener('cancel',()=>finish(false));
   });
   if(!accepted||retry.signal.aborted)return response;
   retry.headers.set('X-Kilas-Credit-Consent',target.pathname.split('/').pop());
   return nativeFetch(retry);
 };
})();
