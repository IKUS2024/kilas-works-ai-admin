"""Exact native image dispatch, one image/request, no retries or model fallback."""
import base64,io,os,re
import requests
from PIL import Image
from . import image_models,selected_provider,tools


def generate(model,prompt,source=None,request_timeout=120):
 item=image_models.spec(model);provider=item['provider']
 if not image_models.check(model)['available']:raise tools.ToolUnavailable('Model gambar pilihan tidak tersedia.',model=model)
 sources=source if isinstance(source,list) else [source] if source else []
 if len(sources)>5:raise tools.ToolUnavailable('Maksimal lima gambar referensi untuk permintaan ini.',model=model)
 ratio=next(iter(re.findall(r'\b(1:1|3:2|2:3|3:4|4:3|4:5|5:4|9:16|16:9|21:9)\b',prompt)),'1:1')
 explicit_size=re.search(r'\b(\d{3,4})\s*[x×]\s*(\d{3,4})\b',prompt)
 size={'1:1':'1024x1024','3:2':'1536x1024','2:3':'1024x1536'}.get(ratio)
 if explicit_size:size=explicit_size[1]+'x'+explicit_size[2]
 if provider=='google' and explicit_size and size!='1024x1024':raise tools.ToolUnavailable('Rasio ini belum tersedia pada model pilihan. Gunakan 1:1, 3:2, atau 2:3.',model=model)
 if provider=='openai' and size not in ('1024x1024','1536x1024','1024x1536'):
  raise tools.ToolUnavailable('Rasio ini belum tersedia pada model pilihan. Gunakan 1:1, 3:2, atau 2:3.',model=model)
 transparent=bool(re.search(r'(?i)\b(?:transparent|transparan|transparente)\b|透明',prompt))
 if transparent and model!='gpt-image-1-mini':raise tools.ToolUnavailable('Transparansi belum tersedia pada model pilihan. Pilih GPT Image 1 Mini untuk PNG transparan.',model=model)
 if re.search(r'(?i)\b(?:quality|kualitas|calidad)\s*[:=]?\s*(?:high|medium)|\b[24]K\b',prompt):
  raise tools.ToolUnavailable('Kualitas ini belum tersedia pada alur hemat. Gunakan low / 1K.',model=model)
 for reference in sources:
  if reference.get('normalized') or reference['mime_type'] not in ('image/png','image/jpeg','image/webp') or len(reference['content'])>5*1024*1024:raise tools.ToolUnavailable('Gambar asli belum kompatibel dengan model pilihan.',model=model)
 used={'selected_image_model':model,'billing_unknown':True};metadata={'requested_model':model,'returned_model':'unreported','provider':provider}
 data=None
 try:
  if provider=='openai':
   headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'].strip()}
   if os.environ.get('OPENAI_PROJECT_ID'):headers['OpenAI-Project']=os.environ['OPENAI_PROJECT_ID']
   payload={'model':model,'prompt':prompt[:4000],'size':size,'quality':'low','n':1}
   if transparent:payload.update(background='transparent',output_format='png')
   if not sources:response=requests.post('https://api.openai.com/v1/images/generations',headers=headers,json=payload,timeout=(10,request_timeout))
   else:
    files={'image':(sources[0]['filename'],bytes(sources[0]['content']),sources[0]['mime_type'])} if len(sources)==1 else [('image[]',(s['filename'],bytes(s['content']),s['mime_type'])) for s in sources]
    response=requests.post('https://api.openai.com/v1/images/edits',headers=headers,data={**payload,'n':'1'},files=files,timeout=(10,request_timeout))
   response.raise_for_status();data=response.json();raw_usage=data.get('usage') or {}
   used.update(input_tokens=raw_usage.get('input_tokens',0),output_tokens=raw_usage.get('output_tokens',0),image_token_usage=raw_usage)
   encoded=data['data'][0]['b64_json']
  else:
   parts=[{'text':prompt[:4000]}]
   for reference in sources:parts.append({'inlineData':{'mimeType':reference['mime_type'],'data':base64.b64encode(bytes(reference['content'])).decode()}})
   payload={'contents':[{'role':'user','parts':parts}],'generationConfig':{'responseModalities':['TEXT','IMAGE'],'candidateCount':1,'maxOutputTokens':8192,'imageConfig':{'aspectRatio':ratio,'imageSize':'1K'}}}
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
   if not mime or pic.width*pic.height>4_000_000 or min(pic.width,pic.height)<256:raise ValueError('image_format')
   if provider=='openai' and (pic.width,pic.height)!=tuple(map(int,size.split('x'))):raise ValueError('image_dimensions')
   if provider=='google':
    w,h=map(int,ratio.split(':'))
    if abs(pic.width/pic.height-w/h)>.04:raise ValueError('image_ratio')
   if transparent and (pic.mode not in ('RGBA','LA') or pic.getextrema()[-1][0]==255):raise ValueError('transparency_missing')
   dimensions=[pic.width,pic.height]
   pic.verify()
  used['billing_unknown']=image_models.cost(model,used.get('image_token_usage')) is None
  return {'raw':raw,'mime':mime,'model':model,'provider':provider,'usage':used,'model_provenance':metadata,'image_options':{'dimensions':dimensions,'aspect_ratio':ratio,'quality':'low' if provider=='openai' else '1K','transparent':transparent,'reference_count':len(sources),'input_bytes_preserved':True}}
 except (requests.RequestException,ValueError,TypeError,KeyError,IndexError,selected_provider.providers.ProviderError):
  used['billing_unknown']=image_models.cost(model,used.get('image_token_usage')) is None
  raise tools.ToolUnavailable('Gambar belum dapat dibuat dengan model pilihan; permintaan tidak dialihkan.',model=model,usage=used) from None
