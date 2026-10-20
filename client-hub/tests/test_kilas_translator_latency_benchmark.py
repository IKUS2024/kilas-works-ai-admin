"""One-campaign spend guard; SQLite metadata and synthetic provider responses only."""
import hashlib,io,json,os,sqlite3,tempfile,unittest
from contextlib import ExitStack,redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import test_kilas_live_translator as fixture  # Install the suite's fresh DB before importing db.
from kilas_ai import translator_latency_benchmark as b

class Response:
 def __init__(self,status=200):self.status_code=status;self.closed=False;self.encoding=None
 def __enter__(self):return self
 def __exit__(self,*args):self.closed=True
 def iter_lines(self,**kwargs):
  self.options=kwargs
  value={'text':'My name is Rina, not Budi.','source_language':'id','target_language':'en'}
  for event in [{'model':b.MODEL,'service_tier':'default','choices':[{'delta':{'role':'assistant'}}]},
    {'choices':[{'delta':{'content':json.dumps(value)}}]},
    {'choices':[{'delta':{},'finish_reason':'stop'}]},
    {'usage':{'prompt_tokens':400,'completion_tokens':120,'completion_tokens_details':{'reasoning_tokens':30}}}]:
   yield 'data: '+json.dumps(event);yield ''
  yield 'data: [DONE]';yield ''

class BenchmarkTests(unittest.TestCase):
 def setUp(self):
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  folder=self.stack.enter_context(tempfile.TemporaryDirectory());self.path=str(Path(folder)/'benchmark.db')
  self.stack.enter_context(patch.object(b.db,'BACKEND','sqlite'));self.stack.enter_context(patch.object(b.db,'SQLITE_PATH',self.path))
  self.stack.enter_context(patch.object(b,'_now',return_value=b.START+1000))
  self.stack.enter_context(patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only','KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT':'proj_synthetic'}))
  with sqlite3.connect(self.path) as conn:
   conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT,role TEXT)');conn.execute("INSERT INTO users VALUES (9,'irvankarnavi@gmail.com','CLIENT_OWNER')")
 def row(self):
  with sqlite3.connect(self.path) as conn:conn.row_factory=sqlite3.Row;row=conn.execute('SELECT * FROM kilas_translator_latency_benchmarks').fetchone();return dict(row)
 def execute(self,fake):
  with patch.object(b,'configured',return_value=True),patch.object(b,'_request',side_effect=fake) as request,redirect_stdout(io.StringIO()):b.run()
  return request
 def result(self,index):
  source,effort=b.CASES[index];a,target,text=b.SOURCES[source]
  return {'model':b.MODEL,'effort':effort,'translation':{'text':'Synthetic complete translation','source_language':a,'target_language':target},'usage':{'input_tokens':400,'completion_tokens':120,'reasoning_tokens':0}}
 def test_all_requests_and_inclusive_reasoning_budget_are_bounded_before_dispatch(self):
  bodies=b.preflight();self.assertEqual(b.upper_bound_micro(),33424);self.assertLessEqual(b.upper_bound_micro(),4*b.RESERVE);self.assertLessEqual(4*b.RESERVE,b.CAP)
  self.assertEqual(len(bodies),4);self.assertEqual([x['reasoning_effort'] for x in bodies],['low','none','none','low'])
  for body in bodies:
   self.assertLessEqual(len(json.dumps(body,ensure_ascii=False).encode()),b.MAX_BYTES)
   self.assertEqual((body['model'],body['max_completion_tokens'],body['n'],body['service_tier']),(b.MODEL,3500,1,'default'))
   self.assertNotIn('tools',body);self.assertNotIn('audio',body);self.assertFalse(body['store'])
 def test_shared_prompt_matches_exact_pre_benchmark_production_prompt(self):
  for a,target,digest in [('id','en','8e6c21d50a4a70c71bdcd5055694417124fd96b5097514bd778e5178dd386548'),('en','id','95f45f5a93caaa2389f56902ac9b51a4a490371e9fcdc2c37e3b17226322170e')]:
   self.assertEqual(hashlib.sha256(b.live.translation_system(a,target).encode()).hexdigest(),digest)
 def test_four_attempts_prepaid_irreversible_and_campaign_cannot_restart(self):
  called=[]
  def request(body):
   row=self.row();self.assertEqual(row['attempts'],len(called)+1);self.assertEqual(row['reserved_micro'],40000)
   called.append(body);return self.result(len(called)-1)
  first=self.execute(request);self.assertEqual(first.call_count,4)
  row=self.row();self.assertEqual((row['attempts'],row['status'],len(json.loads(row['results']))),(4,'COMPLETED',4))
  self.execute(request).assert_not_called();self.assertEqual(len(called),4)
 def test_duplicate_foreign_token_out_of_order_and_fifth_attempt_denied(self):
  bodies=b.preflight();self.assertTrue(b._claim('first',bodies));self.assertFalse(b._claim('second',bodies))
  for token,index in [('second',0),('first',1),('first',4)]:
   with self.assertRaises(b.Blocked):b._dispatch(token,index)
  for index in range(4):b._dispatch('first',index)
  for index in [0,3,4]:
   with self.assertRaises(b.Blocked):b._dispatch('first',index)
  self.assertEqual(self.row()['attempts'],4)
 def test_unknown_dispatch_consumes_slot_and_full_reserve_without_resume(self):
  called=[]
  def request(body):
   called.append(body)
   if len(called)==2:raise TimeoutError('private failure detail')
   return self.result(0)
  first=self.execute(request);self.assertEqual(first.call_count,2)
  row=self.row();self.assertEqual((row['attempts'],row['status'],row['reserved_micro']),(2,'FAILED',40000))
  self.assertEqual(json.loads(row['results'])[-1]['code'],'provider_or_parse_failure');self.execute(request).assert_not_called()
 def test_unsupported_none_stops_without_retry_fallback_or_later_calls(self):
  calls=[]
  def request(body):
   calls.append(body['reasoning_effort'])
   if body['reasoning_effort']=='none':raise b.Blocked('http_400')
   return self.result(0)
  self.execute(request);self.assertEqual(calls,['low','none']);self.assertEqual(self.row()['attempts'],2)
 def test_input_or_profile_drift_denies_before_claim_and_network(self):
  for name,change in [('translation_system',lambda *a:'x'*9000),('translation_profile',lambda *a:{'model':b.MODEL,'effort':'low','output_tokens':11000})]:
   with patch.object(b.live,name,side_effect=change):self.execute(lambda _:None).assert_not_called()
  with sqlite3.connect(self.path) as conn:self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='kilas_translator_latency_benchmarks'").fetchone())
 def test_expired_or_wrong_owner_denies_before_provider(self):
  with patch.object(b,'_now',return_value=b.END):self.execute(lambda _:None).assert_not_called()
  with sqlite3.connect(self.path) as conn:conn.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=9")
  self.execute(lambda _:None).assert_not_called()
 def test_uncertain_claim_is_never_repeated_by_run(self):
  def claim(token,bodies):
   original(token,bodies);raise ConnectionError('lost acknowledgement')
  original=b._claim
  with patch.object(b,'_claim',side_effect=claim):self.execute(lambda _:None).assert_not_called()
  self.execute(lambda _:None).assert_not_called();self.assertEqual(self.row()['attempts'],0)
 def test_default_off_and_exact_runtime_scope(self):
  with patch.dict(os.environ,{b.FLAG:b.CAMPAIGN,'RENDER_SERVICE_ID':b.SERVICE,'KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL':b.MODEL}),patch.object(b.db,'BACKEND','postgres'):
   self.assertTrue(b.configured())
   for key,value in [(b.FLAG,''),('RENDER_SERVICE_ID','other'),('OPENAI_API_KEY',''),('KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL','other')]:
    with patch.dict(os.environ,{key:value}):self.assertFalse(b.configured())
  with patch.object(b,'configured',return_value=False),patch.object(b,'Thread') as thread:b.start();thread.assert_not_called()
 def session(self,response,retries=0):
  from unittest.mock import MagicMock
  session=MagicMock();session.__enter__.return_value=session;session.post.return_value=response
  session.get_adapter.return_value.max_retries.total=retries;return session
 def test_actual_transport_one_post_no_redirects_complete_usage_and_synthetic_result(self):
  response=Response();session=self.session(response)
  with patch.object(b.requests,'Session',return_value=session):report=b._request(b.payload(0))
  session.post.assert_called_once();request=session.post.call_args
  self.assertEqual(request.args[0],'https://api.openai.com/v1/chat/completions');self.assertFalse(request.kwargs['allow_redirects'])
  self.assertEqual(response.options,{'decode_unicode':True,'chunk_size':1});self.assertTrue(response.closed)
  self.assertEqual(report['usage'],{'input_tokens':400,'completion_tokens':120,'reasoning_tokens':30});self.assertEqual(report['standard_cost_micro'],100)
 def test_http_error_no_retry_and_nonzero_adapter_retries_deny_before_post(self):
  for retries,status in [(0,400),(1,200)]:
   response=Response(status);session=self.session(response,retries)
   with patch.object(b.requests,'Session',return_value=session),self.assertRaises(b.Blocked):b._request(b.payload(1))
   self.assertEqual(session.post.call_count,1 if retries==0 else 0)

if __name__=='__main__':unittest.main()
