"""Exact document/image authorship and real artifact rendering; no external IO."""
import base64,copy,io,json,os,unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import test_kilas_chat_models as f
from kilas_ai import image_models,selected_image,chat_models,agent_store,usage,work_artifacts,autonomous_store,tools
from kilas_ai.agent_workers import document_worker,image_worker
import db

PDF='# Laporan Sintetis\n\n## Ringkasan\n\nData sintetis menunjukkan 12 tugas selesai dan 3 tugas tersisa. Tinjau hasil ini sebagai contoh, bukan data pelanggan nyata.'

def access(model):return {**image_models.spec(model),'available':True,'status':'verified'}

def response_stream(mode,messages,**kwargs):
 model=messages.selected_model;text=PDF
 if 'Requested deliverable (xlsx)' in str(messages):text='Kategori,Jumlah\nData sintetis,12\n'
 if 'Requested deliverable (pptx)' in str(messages):text='# Presentasi Sintetis\n\n## Ringkasan\n\n- Contoh sintetis: 12 tugas selesai.\n- Tiga tugas tersisa.'
 yield {'type':'provider','provider':chat_models.spec(model)['provider'],'model':model}
 yield {'type':'model_metadata','provider':chat_models.spec(model)['provider'],'requested_model':model,'returned_model':model}
 yield {'type':'delta','text':text}
 yield {'type':'usage','input_tokens':100,'output_tokens':100,'cached_input_tokens':10}
 yield {'type':'finish','reason':'stop'}

class SelectedArtifactTests(unittest.TestCase):
 setUp=f.RouteTests.setUp
 client=f.RouteTests.client
 submit=f.RouteTests.submit
 def setUp(self):
  f.RouteTests.setUp(self)
  p=patch.object(image_models,'check',side_effect=access);p.start();self.addCleanup(p.stop)
 def job(self,model,format='pdf'):
  ident=autonomous_store.create(self.owner,'Buat laporan data sintetis dalam '+format,conversation_id=self.conversation,checkpoint={'author_model':model})
  return dict(autonomous_store.get(self.owner,ident))
 def step(self,key):return {'idempotency_key':key,'attempts':1}
 def test_http_job_snapshots_selected_author_and_image_independently(self):
  r=self.submit('claude-sonnet-5-5','Buat laporan data sintetis dalam PDF',selected_image_model='gpt-image-1-mini')
  self.assertEqual(r.status_code,303)
  job=autonomous_store.list_jobs(self.owner)[0];context=json.loads(job['checkpoint_json'])
  self.assertEqual(context['author_model'],'claude-sonnet-5-5');self.assertEqual(context['image_model'],'gpt-image-1-mini')
  chat_models.choose(self.owner,'conversation',self.conversation,'gemini-4-argon')
  self.assertEqual(json.loads(autonomous_store.get(self.owner,job['id'])['checkpoint_json'])['author_model'],'claude-sonnet-5-5')
 def test_all_ten_document_authors_use_selected_model_with_real_pdf_bytes(self):
  for i,model in enumerate(chat_models.CATALOG):
   job=self.job(model)
   with self.subTest(model=model),patch.object(f.providers,'stream',side_effect=response_stream) as stream:
    result=document_worker.run(job,self.step('doc-selected-'+str(i)),{'format':'pdf','request':job['instruction']})
   self.assertEqual(result.status,'SUCCEEDED');self.assertEqual(stream.call_args.args[1].selected_model,model)
   file=result.artifacts[0]['binary_file'];self.assertTrue(file['content'].startswith(b'%PDF'));work_artifacts.validate(file)
   self.assertEqual(file['model_provenance']['returned_model'],model)
   row=db.query_one('SELECT provider,model,status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,'doc-selected-'+str(i)+'-1'))
   self.assertEqual((row['provider'],row['model'],row['status']),(chat_models.spec(model)['provider'],model,'COMPLETE'));self.assertGreater(Decimal(row['estimated_cost_usd']),0)
 def test_selected_office_renderers_execute_and_provider_failure_never_falls_back(self):
  for i,(model,format) in enumerate([('gpt-6.1-sol','docx'),('claude-opus-5-5','xlsx'),('gemini-4-argon','pptx')]):
   job=self.job(model,format)
   with patch.object(f.providers,'stream',side_effect=response_stream):result=document_worker.run(job,self.step('office-selected-'+str(i)),{'format':format,'request':job['instruction']})
   self.assertEqual(result.status,'SUCCEEDED');work_artifacts.validate(result.artifacts[0]['binary_file'])
  job=self.job('claude-sonnet-5-5')
  with patch.object(f.providers,'stream',side_effect=f.providers.ProviderError('synthetic_failure')) as stream,patch.object(document_worker.content_worker,'text',side_effect=AssertionError('No OpenAI fallback')):
   with self.assertRaises(f.providers.ProviderError):document_worker.run(job,self.step('doc-failure'),{'format':'pdf','request':job['instruction']})
  self.assertEqual(stream.call_count,1)
 def test_unavailable_author_has_no_reservation_or_dispatch(self):
  job=self.job('claude-sonnet-5-5')
  with patch.object(chat_models,'check',return_value={**f.available('claude-sonnet-5-5'),'available':False}),patch.object(f.providers,'stream',side_effect=AssertionError('No dispatch')):
   result=document_worker.run(job,self.step('unavailable-author'),{'format':'pdf','request':job['instruction']})
  self.assertEqual(result.status,'WAITING_CAPABILITY');self.assertFalse(db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,)))
 def test_image_preferences_owner_csrf_no_text_alias_and_comparable_cost_order(self):
  client=self.client();url=f'/kilas-ai/chat/image-models?surface=conversation&conversation_id={self.conversation}'
  response=client.get(url);self.assertEqual(response.status_code,200)
  for p in ('openai','google'):
   costs=[Decimal(m['output_usd']) for m in response.json['models'] if m['provider']==p];self.assertEqual(costs,sorted(costs))
  r=client.post('/kilas-ai/chat/image-model',json={'surface':'conversation','conversation_id':self.conversation,'model':'gemini-3-pro-image'},headers={'X-CSRF-Token':'work-csrf'})
  self.assertEqual(r.status_code,200);self.assertEqual(image_models.preference(self.owner,'conversation',self.conversation),'gemini-3-pro-image')
  self.assertEqual(self.client(self.other).get(url).status_code,404)
  self.assertNotEqual(client.post('/kilas-ai/chat/image-model',json={'model':'gpt-image-2'}).status_code,200)
  with self.assertRaises(chat_models.SelectionError):image_models.spec('gpt-6.1-sol')
 def test_native_image_models_exact_payload_binary_metadata_and_usage(self):
  image=io.BytesIO();Image.new('RGB',(1024,1024),'blue').save(image,format='PNG');encoded=base64.b64encode(image.getvalue()).decode()
  for model in image_models.CATALOG:
   provider=image_models.spec(model)['provider']
   data=({'model':model,'data':[{'b64_json':encoded}],'usage':{'input_tokens':20,'input_tokens_details':{'text_tokens':10,'image_tokens':10},'output_tokens':1120}} if provider=='openai' else
         {'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':encoded}}]}}],'usageMetadata':{'promptTokenCount':20,'candidatesTokenCount':1120,'thoughtsTokenCount':5,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':1120}]}})
   with self.subTest(model=model),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','GEMINI_API_KEY':'synthetic'}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
    result=tools.image('Synthetic image',selected_model=model)
   self.assertEqual(result['model_provenance']['returned_model'],model);self.assertEqual(result['raw'],image.getvalue());self.assertEqual(post.call_count,1)
   payload=post.call_args.kwargs['json'];self.assertNotIn('tools',payload)
   if provider=='openai':self.assertEqual(payload['model'],model);self.assertEqual(payload['quality'],'low');self.assertEqual(payload['size'],'1024x1024')
   else:self.assertIn(model,post.call_args.args[0]);self.assertEqual(payload['generationConfig']['imageConfig']['imageSize'],'1K')
   self.assertGreater(image_models.cost(model,result['usage']['image_token_usage']),0)
 def test_image_unknown_cost_keeps_forecast_and_blocks_model_substitution(self):
  self.assertIsNone(image_models.cost('gpt-image-2',{}))
  self.assertIsNone(image_models.cost('gpt-image-2',{'input_tokens_details':{'text_tokens':'invalid','image_tokens':0},'output_tokens':1}))
  self.assertIsNone(image_models.cost('gemini-3-pro-image',{'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':None}]}))
  with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(selected_image.requests,'post',side_effect=selected_image.requests.ConnectionError()) as post:
   with self.assertRaises(tools.ToolUnavailable) as error:tools.image('Synthetic',selected_model='gpt-image-2')
  self.assertTrue(error.exception.usage['billing_unknown']);self.assertEqual(post.call_count,1)
  model='gemini-3-pro-image';key='image-metered-synthetic'
  _,ops=usage.reserve(self.owner,self.thread,key,'FAST','IMAGE_GENERATE',profile={'image_model':model})
  usage.finish(self.owner,key,ops,success=False,provider='google',model=model,usage={'selected_image_model':model,'billing_unknown':True})
  row=db.query_one('SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,key))
  self.assertEqual(row['status'],'FAILED');self.assertEqual(Decimal(row['estimated_cost_usd']),image_models.forecast(model))

 def test_document_origin_images_and_provenance_are_durable_and_owner_scoped(self):
  from kilas_ai import agent_attachments
  image=io.BytesIO();Image.new('RGB',(32,32),'red').save(image,format='PNG')
  r=self.submit('gemini-4-argon','Buat laporan data sintetis dalam PDF',source_files=[(io.BytesIO(image.getvalue()),'synthetic.png')])
  self.assertEqual(r.status_code,303)
  job=dict(autonomous_store.list_jobs(self.owner)[0]);origin=json.loads(job['checkpoint_json'])['origin_message_id']
  self.assertEqual(agent_attachments.latest_images(self.other,self.conversation,origin),[])
  with patch.object(f.providers,'stream',side_effect=response_stream) as stream:
   result=document_worker.run(job,self.step('document-image-synthetic'),{'format':'pdf','request':job['instruction']})
  self.assertIn('image_url',str(stream.call_args.args[1]))
  with autonomous_store.transaction() as conn:
   sid=usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'DOCUMENT','create','Synthetic','{}','durable-author-test','SUCCEEDED') RETURNING id",(job['id'],),one=True)[0]
   work_artifacts.persist(conn,job,{'id':sid},result.artifacts[0]['binary_file'])
  row=work_artifacts.listing(self.owner,job_id=job['id'])[0]
  self.assertEqual(row['model_provenance']['requested_model'],'gemini-4-argon')
  self.assertEqual(work_artifacts.listing(self.other,job_id=job['id']),[])
 def test_legacy_image_request_dispatches_independent_selected_model(self):
  image=io.BytesIO();Image.new('RGB',(1024,1024),'blue').save(image,format='PNG')
  model='gemini-3-pro-image';raw_usage={'promptTokenCount':10,'candidatesTokenCount':1120,'candidatesTokensDetails':[{'modality':'IMAGE','tokenCount':1120}]}
  result={'raw':image.getvalue(),'mime':'image/png','model':model,'provider':'google','model_provenance':{'requested_model':model,'returned_model':model,'provider':'google'},'usage':{'input_tokens':10,'output_tokens':1120,'selected_image_model':model,'image_token_usage':raw_usage}}
  with patch.object(tools,'image',return_value=result) as dispatch:
   response=self.submit('claude-sonnet-5-5','Buat gambar kucing sintetis',agent=False,selected_image_model=model)
  self.assertEqual(response.status_code,200);self.assertEqual(dispatch.call_args.kwargs['selected_model'],model)
  row=db.query_one('SELECT provider,model,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
  self.assertEqual((row['provider'],row['model']),('google',model));self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('.134420'))
