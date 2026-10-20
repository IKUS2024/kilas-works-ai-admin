"""Synthetic transport stages, no credentials, sockets or paid provider calls."""
import json,unittest
from unittest.mock import patch
import requests
from kilas_ai import providers

PROFILE={'model':'gpt-6-luna','effort':'low','output_tokens':3500}

class Response:
 def __init__(self,clock,reasoning=77):self.clock=clock;self.reasoning=reasoning;self.closed=False;self.encoding=None
 def __enter__(self):self.clock[0]=.1;return self
 def __exit__(self,*args):self.closed=True
 def raise_for_status(self):pass
 def iter_lines(self,**kwargs):
  self.options=kwargs
  for when,event in [(.2,{'choices':[{'delta':{'role':'assistant'}}]}),(2,{'choices':[{'delta':{'content':'Nama saya Rina, bukan Budi. 最后一句 كاملة.'}}]}),(4,{'choices':[{'delta':{},'finish_reason':'stop'}]}),(4.1,{'usage':{'prompt_tokens':50,'completion_tokens':100,'completion_tokens_details':self.reasoning}})]:
   self.clock[0]=when
   yield ('data: '+json.dumps(event,ensure_ascii=False)).encode()
   yield b''
  yield b'data: [DONE]';yield b''

class AdapterTimingTests(unittest.TestCase):
 def call(self,**kwargs):return providers._openai('gpt-6-luna','synthetic-only',[{'role':'user','content':'Synthetic translation'}],'FAST',profile=PROFILE,event_chunk_size=1,response_format={'type':'json_object'},**kwargs)
 def test_initial_role_frame_is_distinct_from_first_content_and_request_is_identical(self):
  requests_seen=[];outputs=[]
  for observed in [False,True]:
   clock=[0.];timings={};response=Response(clock,{'reasoning_tokens':77})
   with patch.object(providers,'monotonic',side_effect=lambda:clock[0]),patch.object(providers.requests,'post',return_value=response) as post:
    outputs.append(list(self.call(**({'timings':timings} if observed else {}))))
   post.assert_called_once();requests_seen.append(post.call_args);self.assertTrue(response.closed)
   self.assertEqual(response.options,{'decode_unicode':True,'chunk_size':1})
   if observed:
    for field,value in [('translation_http_headers_ms',100),('translation_first_sse_line_ms',200),('translation_first_sse_event_ms',200),('translation_first_content_ms',2000),('translation_reasoning_tokens',77)]:self.assertAlmostEqual(timings[field],value)
    self.assertTrue(all(isinstance(value,(float,int)) for value in timings.values()))
   else:self.assertEqual(timings,{})
  self.assertEqual(outputs[0],outputs[1]);self.assertEqual(requests_seen[0],requests_seen[1])
  self.assertEqual([event['type'] for event in outputs[0]],['delta','finish','usage'])
 def test_missing_or_malformed_reasoning_diagnostic_cannot_change_usage(self):
  for details in [None,[],{'reasoning_tokens':'private-body'},{'reasoning_tokens':True},{'reasoning_tokens':-1}]:
   clock=[0.];response=Response(clock,details);timings={}
   with patch.object(providers,'monotonic',side_effect=lambda:clock[0]),patch.object(providers.requests,'post',return_value=response):events=list(self.call(timings=timings))
   self.assertNotIn('translation_reasoning_tokens',timings);self.assertEqual(events[-1],{'type':'usage','input_tokens':50,'output_tokens':100,'cached_input_tokens':0})
 def test_http_timeout_has_no_retry_or_private_error_body(self):
  with patch.object(providers.requests,'post',side_effect=requests.ReadTimeout('private-provider-body')) as post:
   with self.assertRaises(providers.ProviderError) as error:list(self.call(timings={}))
  post.assert_called_once();self.assertEqual(str(error.exception),'openai_unavailable')
 def test_bad_sse_json_closes_without_retry_or_partial_publication(self):
  response=Response([0.])
  with patch.object(response,'iter_lines',return_value=iter([b'data: private-invalid-json',b''])),patch.object(providers.requests,'post',return_value=response) as post:
   with self.assertRaises(providers.ProviderError) as error:list(self.call(timings={}))
  post.assert_called_once();self.assertTrue(response.closed);self.assertEqual(str(error.exception),'bad_provider_stream')
 def test_close_after_first_content_closes_same_response_without_tail_or_retry(self):
  clock=[0.];response=Response(clock);timings={}
  with patch.object(providers.requests,'post',return_value=response) as post:
   stream=self.call(timings=timings);self.assertEqual(next(stream)['type'],'delta');stream.close()
  post.assert_called_once();self.assertTrue(response.closed);self.assertNotIn('translation_reasoning_tokens',timings)
 def test_uninstrumented_shared_adapter_never_reads_diagnostic_clock(self):
  response=Response([0.])
  with patch.object(providers,'monotonic',side_effect=AssertionError('unrequested timing')),patch.object(providers.requests,'post',return_value=response):list(self.call())
 def test_unterminated_eof_frame_keeps_existing_parser_semantics(self):
  response=Response([0.]);timings={}
  with patch.object(response,'iter_lines',return_value=iter([b'data: {"choices":[]}'])),patch.object(providers,'monotonic',return_value=1):
   self.assertEqual(list(providers._events(response,timings=timings,started=0)),[{'choices':[]}])
  self.assertEqual(timings,{'translation_first_sse_line_ms':1000,'translation_first_sse_event_ms':1000})

if __name__=='__main__':unittest.main()
