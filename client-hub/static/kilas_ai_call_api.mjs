import {requestJSON} from './kilas_live_translator_api.mjs?v=app-language-20261015';

// Call readiness carries JSON metadata; shared Translator requests stay intact.
export function requestCallJSON(url,{json,fetcher=(...args)=>fetch(...args),...options}={}){
 return requestJSON(url,{...options,...(json===undefined?{}:{body:JSON.stringify(json)}),
  fetcher:(path,init)=>fetcher(path,{...init,headers:{...init.headers,...(json===undefined?{}:{'Content-Type':'application/json'})}})});
}
