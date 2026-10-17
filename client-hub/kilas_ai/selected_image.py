"""Exact native image dispatch, one image/request, no retries or model fallback."""
import base64,io,os
import requests
from PIL import Image
from . import image_models,selected_provider,tools


def generate(model,prompt,source=None,request_timeout=120):
 item=image_models.spec(model);provider=item['provider']
 if not image_models.check(model)['available']:raise tools.ToolUnavailable('Model gambar pilihan tidak tersedia.',model=model)
 used={'selected_image_model':model,'billing_unknown':True};metadata={'requested_model':model,'returned_model':'unreported','provider':provider}
 data=None
 try:
  if provider=='openai':
   headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'].strip()}
   if os.environ.get('OPENAI_PROJECT_ID'):headers['OpenAI-Project']=os.environ['OPENAI_PROJECT_ID']
   payload={'model':model,'prompt':prompt[:4000],'size':'1024x1024','quality':'low','n':1}
   if source is None:response=requests.post('https://api.openai.com/v1/images/generations',headers=headers,json=payload,timeout=(10,request_timeout))
   else:response=requests.post('https://api.openai.com/v1/images/edits',headers=headers,data={**payload,'n':'1'},files={'image':(source['filename'],bytes(source['content']),source['mime_type'])},timeout=(10,request_timeout))
   response.raise_for_status();data=response.json();raw_usage=data.get('usage') or {}
   used.update(input_tokens=raw_usage.get('input_tokens',0),output_tokens=raw_usage.get('output_tokens',0),image_token_usage=raw_usage)
   encoded=data['data'][0]['b64_json']
  else:
   parts=[{'text':prompt[:4000]}]
   if source:parts.append({'inlineData':{'mimeType':source['mime_type'],'data':base64.b64encode(bytes(source['content'])).decode()}})
   payload={'contents':[{'role':'user','parts':parts}],'generationConfig':{'responseModalities':['TEXT','IMAGE'],'candidateCount':1,'maxOutputTokens':8192,'imageConfig':{'aspectRatio':'1:1','imageSize':'1K'}}}
   response=requests.post('https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',headers={'x-goog-api-key':os.environ['GEMINI_API_KEY'].strip()},json=payload,timeout=(10,request_timeout))
   response.raise_for_status();data=response.json();raw_usage=data.get('usageMetadata') or {}
   used.update(input_tokens=raw_usage.get('promptTokenCount',0),output_tokens=int(raw_usage.get('candidatesTokenCount',0))+int(raw_usage.get('thoughtsTokenCount',0)),image_token_usage=raw_usage)
   candidate=(data.get('candidates') or [{}])[0]
   if candidate.get('finishReason')!='STOP':raise ValueError('image_response_incomplete')
   outputs=[p['inlineData'] for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought') and 'inlineData' in p]
   if len(outputs)!=1:raise ValueError('one_image_required')
   encoded=outputs[0]['data']
  returned=data.get('model') if provider=='openai' else data.get('modelVersion')
  if returned:metadata['returned_model']=selected_provider._returned(model,returned)
  raw=base64.b64decode(encoded,validate=True)
  if not raw or len(raw)>8*1024*1024:raise ValueError('image_size')
  with Image.open(io.BytesIO(raw)) as pic:
   mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(pic.format)
   if not mime or (pic.width,pic.height)!=(1024,1024):raise ValueError('image_format')
   pic.verify()
  used['billing_unknown']=image_models.cost(model,used.get('image_token_usage')) is None
  return {'raw':raw,'mime':mime,'model':model,'provider':provider,'usage':used,'model_provenance':metadata}
 except (requests.RequestException,ValueError,TypeError,KeyError,IndexError,selected_provider.providers.ProviderError):
  used['billing_unknown']=image_models.cost(model,used.get('image_token_usage')) is None
  raise tools.ToolUnavailable('Gambar belum dapat dibuat dengan model pilihan; permintaan tidak dialihkan.',model=model,usage=used) from None
