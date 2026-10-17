"""Independent exact image models, account access and transparent output-rate previews.

Only native image endpoints are offered. No text-model alias, credentials write,
inference access probe, automatic provider fallback or provider tools.
"""
import hashlib,json,os,re,threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from time import monotonic
import requests
from . import chat_models
SelectionError=chat_models.SelectionError
# id: provider, display, text input, image input, image output, text/thought output,
# comparable configured image OUTPUT estimate (USD; excludes prompt/reference/thinking).
CATALOG={
 'gpt-image-1-mini':('openai','GPT Image 1 Mini','2','2.5','8','0','.005'),
 'gpt-image-2.5-sunburst':('openai','GPT Image 2.5 Sunburst','5','8','30','0','.00588'),
 'gpt-image-2.5-flare':('openai','GPT Image 2.5 Flare','5','8','30','0','.00588'),
 'gpt-image-2':('openai','GPT Image 2','5','8','30','0','.006'),
 'gemini-3.1-flash-lite-image':('google','Gemini 3.1 Flash Lite Image','.25','.25','30','1.5','.0336'),
 'gemini-3-pro-image':('google','Gemini 3 Pro Image','2','2','120','12','.1344'),
}
_cache={};_lock=threading.Lock()


def spec(model):
 if not isinstance(model,str) or model not in CATALOG:raise SelectionError('Model gambar tidak valid.')
 p,name,ti,ii,io,to,price=CATALOG[model]
 return {'id':model,'provider':p,'name':name,'output_usd':format(Decimal(price),'f'),'size':'1024x1024','quality':'low' if p=='openai' else 'native 1K',
         'text_input_per_million':format(Decimal(ti),'f'),'image_input_per_million':format(Decimal(ii),'f'),'image_output_per_million':format(Decimal(io),'f'),'thinking_output_per_million':format(Decimal(to),'f'),
         'pricing_checked_on':'2026-10-17'}


def check(model):
 item=spec(model);key=os.environ.get(chat_models.KEYS[item['provider']],'').strip();fingerprint=hashlib.sha256(key.encode()).digest()
 with _lock:
  prior=_cache.get(model)
  if prior and prior['fingerprint']==fingerprint and monotonic()-prior['at']<(600 if prior['available'] else 30):return {k:v for k,v in prior.items() if k not in ('at','fingerprint')}
 result={**item,'available':False,'status':'not_configured'}
 if key:
  try:
   if item['provider']=='openai':
    headers={'Authorization':'Bearer '+key};url='https://api.openai.com/v1/models/'+model
    if os.environ.get('OPENAI_PROJECT_ID'):headers['OpenAI-Project']=os.environ['OPENAI_PROJECT_ID']
   else:headers={'x-goog-api-key':key};url='https://generativelanguage.googleapis.com/v1beta/models/'+model
   response=requests.get(url,headers=headers,timeout=(3,5))
   if response.status_code==200:
    data=response.json();actual=data.get('id') if item['provider']=='openai' else data.get('name','').removeprefix('models/')
    exact=isinstance(actual,str) and (actual==model or re.fullmatch(re.escape(model)+r'-(?:20\d\d-\d\d-\d\d|\d{3})',actual))
    ready=exact and (item['provider']=='openai' or 'generateContent' in data.get('supportedGenerationMethods',[]))
    result.update(available=bool(ready),status='verified' if ready else 'unsupported')
   else:result['status']='access_unavailable' if response.status_code in (401,403,404) else 'check_unavailable'
  except (requests.RequestException,ValueError,TypeError,AttributeError):result['status']='check_unavailable'
 with _lock:_cache[model]={**result,'fingerprint':fingerprint,'at':monotonic()}
 return result


def cached_metadata(model):
 return chat_models._cached_metadata(model,_cache,_lock,spec)


def catalog(*,cache_only=False):
 if cache_only:
  checked=[cached_metadata(model) for model in CATALOG]
  if any(item is None for item in checked):return None
 else:
  with ThreadPoolExecutor(max_workers=4) as pool:checked=list(pool.map(check,CATALOG))
 # Never advertise unsupported/unverified choices as image-generation options.
 items=sorted((m for m in checked if m['available']),key=lambda m:(m['provider'],Decimal(m['output_usd'])))
 configured=os.environ.get('KILAS_AI_OPENAI_IMAGE_MODEL','gpt-image-2').strip()
 default=next((m['id'] for m in items if m['id']==configured),None) or next((m['id'] for m in items),None)
 return {'models':items,'default':default,'pricing_checked_on':'2026-10-17'}


def warmup():
 def run():
  with ThreadPoolExecutor(max_workers=4) as pool:items=list(pool.map(check,CATALOG))
  print('KILAS_IMAGE_MODELS '+json.dumps({m['id']:m['status'] for m in items},separators=(',',':')),flush=True)
 threading.Thread(target=run,name='kilas-image-access',daemon=True).start()


def preference(owner,surface,ident):
 import db
 chat_models.owned(owner,surface,ident)
 row=db.query_one('SELECT model FROM kilas_ai_image_model_selections WHERE user_id=? AND surface=? AND conversation_id=?',(owner,surface,ident))
 return row['model'] if row else None


def choose(owner,surface,ident,model):
 import db
 chat_models.owned(owner,surface,ident)
 if not check(model)['available']:raise SelectionError('Model gambar pilihan belum tersedia. Permintaan tidak dialihkan.')
 db.execute('INSERT INTO kilas_ai_image_model_selections(user_id,surface,conversation_id,model) VALUES (?,?,?,?) ON CONFLICT(user_id,surface,conversation_id) DO UPDATE SET model=excluded.model',(owner,surface,ident,model))
 return model


def requested(owner,surface,ident,value=None,*,required=False):
 model=value or preference(owner,surface,ident)
 if model:spec(model)
 if required:
  if not model or not check(model)['available']:raise SelectionError('Pilih model gambar yang tersedia sebelum membuat gambar.')
  choose(owner,surface,ident,model)
 return model


def forecast(model):
 p=spec(model)
 # Conservative capacity forecast, not a supplier-dollar hard limit or invoice.
 return Decimal(p['output_usd'])+(Decimal(16000)*Decimal(p['text_input_per_million'])+Decimal(64000)*Decimal(p['image_input_per_million'])+Decimal(8192)*Decimal(p['thinking_output_per_million']))/Decimal(1000000)


def cost(model,raw):
 try:return _cost(model,raw)
 except (TypeError,ValueError,AttributeError,OverflowError):return None


def _cost(model,raw):
 p=spec(model)
 if not raw:return None
 if p['provider']=='openai':
  details=raw.get('input_tokens_details') or {};text=details.get('text_tokens');images=details.get('image_tokens');output=raw.get('output_tokens')
  if None in (text,images,output):return None
  if min(int(text),int(images),int(output))<0 or int(text)+int(images)!=int(raw.get('input_tokens',int(text)+int(images))):return None
  return (Decimal(int(text))*Decimal(p['text_input_per_million'])+Decimal(int(images))*Decimal(p['image_input_per_million'])+Decimal(int(output))*Decimal(p['image_output_per_million']))/Decimal(1000000)
 details=raw.get('candidatesTokensDetails') or []
 if not details:return None
 image_out=sum(int(d.get('tokenCount',0)) for d in details if d.get('modality')=='IMAGE')
 text_out=sum(int(d.get('tokenCount',0)) for d in details if d.get('modality')=='TEXT')
 if min(image_out,text_out,int(raw.get('promptTokenCount',0)),int(raw.get('thoughtsTokenCount',0)))<0 or image_out+text_out!=int(raw.get('candidatesTokenCount',0)):return None
 return (Decimal(int(raw.get('promptTokenCount',0)))*Decimal(p['text_input_per_million'])+Decimal(image_out)*Decimal(p['image_output_per_million'])+Decimal(text_out+int(raw.get('thoughtsTokenCount',0)))*Decimal(p['thinking_output_per_million']))/Decimal(1000000)
