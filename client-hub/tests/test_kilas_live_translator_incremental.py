"""Actual disposable SQLite/PCM/socket pipeline; providers synthetic, no paid QA."""
import io,json,os,struct,time,unittest
from threading import Event,Thread
from unittest.mock import patch
import test_kilas_live_translator as fixture
import test_kilas_live_translator_realtime as relay_fixture
import test_kilas_audio as audio
from kilas_ai import live_translator as live,live_translator_incremental as inc
from kilas_ai import live_translator_realtime as rt,live_translator_store as sessions
from kilas_ai import providers,audio_store,live_translator_output as temporary

FIRST='Saya pesan dua tiket.'
SECOND='Untuk hari Jumat.'
ONE={'source':FIRST,'text':'I ordered two tickets.','source_language':'id','target_language':'en'}
TWO={'source':SECOND,'text':'For Friday.','source_language':'id','target_language':'en'}


class IncrementalTests(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 session=fixture.LiveTranslatorTests.session
 key=fixture.LiveTranslatorTests.key
 credit=fixture.LiveTranslatorTests.credit
 claim=fixture.LiveTranslatorTests.claim
 make=relay_fixture.RealtimeTests.make
 row=relay_fixture.RealtimeTests.row
 @classmethod
 def setUpClass(cls):cls.audio=audio.mp3()
 def owner(self):return patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_LIVE_TRANSLATOR_USAGE_MODE':'owner','KILAS_LIVE_INCREMENTAL_ENABLED':'true'})
 def clauses(self):
  ident=self.session();info=self.claim(ident)
  value=inc.Clauses(self.user,ident,self.key(),info);self.addCleanup(value.cancel)
  return value
 def stream(self,value,usage=True):
  yield {'type':'delta','text':json.dumps(value)}
  if usage:yield {'type':'usage','input_tokens':300,'output_tokens':50}
  yield {'type':'finish','reason':'stop'}

 def test_enabled_for_enduring_existing_audience_without_qa_spending_cap(self):
  with patch.dict(os.environ):
   os.environ.pop('KILAS_LIVE_INCREMENTAL_ENABLED',None)
   self.assertTrue(inc.enabled())
   with patch.dict(os.environ,{'KILAS_LIVE_INCREMENTAL_ENABLED':'false'}):self.assertFalse(inc.enabled())

 def test_early_boundaries_keep_three_second_minimum_and_two_commit_ceiling(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make()
   try:
    relay.partial=FIRST;relay.partial_at=time.monotonic()-1;relay.quiet_bytes=32000
    relay.since_commit=3*32000-2;self.assertFalse(relay.early_boundary())
    relay.since_commit=3*32000;self.assertTrue(relay.early_boundary())
    relay.early_commits=2;self.assertFalse(relay.early_boundary())
    relay.early_commits=0;relay.final=True;self.assertFalse(relay.early_boundary())
    relay.quiet_bytes=0;relay.observe_audio(b'\0'*19200);self.assertEqual(relay.quiet_bytes,19200)
    relay.observe_audio(struct.pack('<h',10000)*3200);self.assertEqual(relay.quiet_bytes,0)
   finally:relay.incremental.cancel();rt.budget.finish(relay.capability,False)

 def test_partial_and_duplicate_timestamp_events_cannot_dispatch_a_clause(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make();socket=relay_fixture.Socket([]);socket.queue.get();relay.ws=socket
   try:
    socket.queue.put(json.dumps({'message_type':'partial_transcript','text':FIRST}))
    socket.queue.put(json.dumps({'message_type':'committed_transcript_with_timestamps','text':FIRST}))
    socket.queue.put(None)
    with patch.object(relay.incremental,'offer') as offer:relay.receive()
    offer.assert_not_called();self.assertEqual(relay.pieces,[])
   finally:relay.incremental.cancel();rt.budget.finish(relay.capability,False)

 def test_incomplete_ack_combines_once_with_next_stable_clause_without_repeated_prefix(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make()
   try:
    with patch.object(live,'translation',return_value={'text':'If it is still expensive, do not buy it.','source_language':'id','target_language':'en'}) as translate:
     relay.acks.put('Kalau harganya masih');relay.acknowledge();self.assertEqual(relay.clause_count,0);translate.assert_not_called()
     relay.acks.put('mahal, jangan beli.');relay.acknowledge();self.assertTrue(relay.incremental.done.wait(2))
     self.assertEqual(relay.clause_count,1);translate.assert_called_once()
     self.assertEqual(translate.call_args.args[2],'Kalau harganya masih mahal, jangan beli.')
     self.assertEqual(relay.pieces,['Kalau harganya masih','mahal, jangan beli.'])
   finally:relay.incremental.cancel();rt.budget.finish(relay.capability,False)

 def test_disjoint_serial_clauses_overlap_input_and_final_sees_complete_tail(self):
  entered=Event();release=Event();calls=[]
  with self.funded(),self.on():
   value=self.clauses()
   def translate(owner,key,text,a,b,check,**kwargs):
    check();calls.append((key,text,kwargs))
    if len(calls)==1:entered.set();self.assertTrue(release.wait(3))
    if text==FIRST:return {k:ONE[k] for k in ('text','source_language','target_language')}
    if text==SECOND:return {k:TWO[k] for k in ('text','source_language','target_language')}
    return {'text':'I ordered two tickets for Friday, not Thursday.','source_language':'id','target_language':'en'}
   with patch.object(live,'translation',side_effect=translate):
    self.assertTrue(value.offer(0,FIRST));self.assertTrue(entered.wait(2))
    self.assertTrue(value.offer(1,SECOND,FIRST))
    self.assertFalse(value.offer(1,SECOND,FIRST));self.assertFalse(value.offer(2,'Tidak hari Kamis.'))
    self.assertEqual(len(calls),1);release.set();self.assertTrue(value.done.wait(3))
    source=FIRST+' '+SECOND+' Bukan hari Kamis.'
    output=value.finish(source,value.check,{})
   self.assertEqual([call[1] for call in calls],[FIRST,SECOND,source])
   self.assertEqual(calls[1][2]['clause_context']['text'],ONE['text'])
   self.assertEqual(len(calls[2][2]['drafts']),2)
   self.assertIn('not Thursday',output['text'])

 def test_exact_complete_single_clause_reuses_result_without_paid_final(self):
  with self.funded(),self.on():
   value=self.clauses()
   with patch.object(live,'translation',return_value={k:ONE[k] for k in ('text','source_language','target_language')}) as translate:
    value.offer(0,FIRST);self.assertTrue(value.done.wait(2));timings={}
    result=value.finish(FIRST,value.check,timings)
   translate.assert_called_once();self.assertEqual(result['text'],ONE['text']);self.assertEqual(timings['incremental_reused'],1)

 def test_final_input_skips_queued_undispatched_clause_and_reconciles_its_whole_source(self):
  entered=Event();release=Event();calls=[]
  with self.funded(),self.on():
   value=self.clauses()
   def translate(owner,key,text,a,b,check,**kwargs):
    calls.append(text)
    if len(calls)==1:entered.set();release.wait(3)
    check();return {k:ONE[k] for k in ('text','source_language','target_language')}
   with patch.object(live,'translation',side_effect=translate):
    value.offer(0,FIRST);self.assertTrue(entered.wait(2));value.offer(1,SECOND,FIRST)
    value.freeze();release.set();self.assertTrue(value.done.wait(2));timings={}
    value.finish(FIRST+' '+SECOND,value.check,timings)
   self.assertEqual(calls,[FIRST,FIRST+' '+SECOND]);self.assertEqual(timings['incremental_clauses'],1)

 def test_clauses_with_changed_source_never_reuse_a_stale_translation(self):
  with self.funded(),self.on():
   value=self.clauses();calls=[]
   def translate(owner,key,text,*args,**kwargs):
    calls.append((text,kwargs));return {k:ONE[k] for k in ('text','source_language','target_language')}
   with patch.object(live,'translation',side_effect=translate):
    value.offer(0,FIRST);self.assertTrue(value.done.wait(2))
    revised=FIRST.replace('dua','tiga');value.finish(revised,value.check,{})
   self.assertEqual(len(calls),2);self.assertEqual(calls[1][0],revised);self.assertNotIn('drafts',calls[1][1])

 def test_incomplete_large_out_of_prefix_and_failed_work_never_get_retried(self):
  with self.funded(),self.on():
   value=self.clauses()
   self.assertFalse(value.offer(0,'Kalau harga masih'))
   self.assertFalse(value.offer(0,'a'*1201+'.'))
   with patch.object(live,'translation',side_effect=audio_store.AudioError('not repeated','translation_failed',503)) as translate:
    value.offer(0,FIRST);self.assertTrue(value.done.wait(2))
    with self.assertRaises(audio_store.AudioError):value.finish(FIRST+' '+SECOND,value.check,{})
   translate.assert_called_once()

 def test_wait_timeout_is_bounded_and_does_not_dispatch_a_replacement(self):
  entered=Event();release=Event()
  with self.funded(),self.on():
   value=self.clauses()
   def translate(*args,**kwargs):entered.set();release.wait(3);args[5]();return ONE
   with patch.object(live,'translation',side_effect=translate) as translated,patch.object(inc,'FINAL_WAIT_SECONDS',.01):
    value.offer(0,FIRST);self.assertTrue(entered.wait(2))
    try:
     with self.assertRaises(audio_store.AudioError) as failed:value.finish(FIRST,value.check,{})
     self.assertEqual(failed.exception.code,'turn_timeout');self.assertTrue(value.cancelled.is_set())
    finally:release.set();self.assertTrue(value.done.wait(2))
   translated.assert_called_once();self.assertEqual(value.results,{})

 def test_owner_end_blocks_late_result_and_fresh_provider_fences(self):
  entered=Event();release=Event()
  with self.funded(),self.on():
   value=self.clauses()
   def translate(*args,**kwargs):entered.set();release.wait(3);args[5]();return ONE
   with patch.object(live,'translation',side_effect=translate) as translated:
    value.offer(0,FIRST);self.assertTrue(entered.wait(2));sessions.end(self.user,value.ident);release.set()
    self.assertTrue(value.done.wait(2))
    with self.assertRaises(audio_store.AudioError):value.finish(FIRST,value.check,{})
   translated.assert_called_once();self.assertEqual(value.results,{})

 def test_final_patch_can_keep_prefix_or_revise_all_but_never_drop_tail(self):
  source=FIRST+' '+SECOND
  result=inc.reconcile(source,[ONE],{'keep_clauses':1,'replacement_text':'For Friday.','source_language':'id','target_language':'en'},'id','en')
  self.assertEqual(result['text'],'I ordered two tickets. For Friday.')
  replacement='I ordered two tickets for Friday.'
  self.assertEqual(inc.reconcile(source,[ONE],{'keep_clauses':0,'replacement_text':replacement,'source_language':'id','target_language':'en'},'id','en')['text'],replacement)
  for invalid in ({'keep_clauses':True,'replacement_text':'For Friday.'},
                  {'keep_clauses':2,'replacement_text':'For Friday.'},
                  {'keep_clauses':1,'replacement_text':''}):
   with self.assertRaises(ValueError):inc.reconcile(source,[ONE],{**invalid,'source_language':'id','target_language':'en'},'id','en')
  with self.assertRaises(ValueError):inc.reconcile(source,[ONE],{'keep_clauses':1,'replacement_text':'x','source_language':'en','target_language':'id'},'id','en')
  with self.assertRaises(ValueError):inc.validate_drafts('Revised source.',[ONE],'id','en')

 def test_real_translation_reconciliation_uses_strict_schema_and_billed_operation(self):
  with self.funded(),self.on():
   value=self.clauses();calls=[]
   def stream(*args,**kwargs):
    calls.append((args,kwargs));return self.stream({'keep_clauses':1,'replacement_text':'For Friday.','source_language':'id','target_language':'en'})
   with patch.object(providers,'_openai',side_effect=stream):
    result=live.translation(self.user,self.key(),FIRST+' '+SECOND,'id','en',value.check,drafts=[ONE])
   payload=json.loads(calls[0][0][2][0]['content']);schema=calls[0][1]['response_format']['json_schema']
   self.assertEqual(payload['source_text'],FIRST+' '+SECOND);self.assertEqual(payload['draft_clauses'],[ONE]);self.assertTrue(schema['strict'])
   self.assertEqual(schema['schema']['properties']['keep_clauses']['enum'],[0,1]);self.assertEqual(result['text'],'I ordered two tickets. For Friday.')
   row=audio.f.db.query_one('SELECT status,input_tokens,output_tokens FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.user,self.key()+'-text'))
   self.assertEqual(tuple(row[k] for k in ('status','input_tokens','output_tokens')),('COMPLETE',300,50))

 def test_ambiguous_dispatched_text_retains_existing_reservation_without_faking_usage(self):
  with self.funded(),self.on():
   value=self.clauses()
   with patch.object(providers,'_openai',side_effect=providers.ProviderError('synthetic unknown')) as provider:
    with self.assertRaises(audio_store.AudioError):live.translation(self.user,self.key()+'-clause-0',FIRST,'id','en',value.check)
   row=audio.f.db.query_one('SELECT status,estimated_cost_usd,input_tokens,output_tokens FROM kilas_ai_usage WHERE user_id=?',(self.user,))
   self.assertEqual(row['status'],'FAILED');self.assertGreater(float(row['estimated_cost_usd']),0)
   self.assertEqual(row['input_tokens'],0);self.assertEqual(row['output_tokens'],0);provider.assert_called_once()

 def test_success_without_usage_keeps_forecast_and_duplicate_key_does_not_dispatch(self):
  with self.funded(),self.on():
   value=self.clauses()
   with patch.object(providers,'_openai',side_effect=lambda *a,**k:self.stream({x:ONE[x] for x in ('text','source_language','target_language')},usage=False)) as provider:
    result=live.translation(self.user,self.key(),FIRST,'id','en',value.check)
    with self.assertRaises(audio_store.AudioError) as duplicate:live.translation(self.user,self.key(),FIRST,'id','en',value.check)
   self.assertEqual(duplicate.exception.code,'duplicate_turn');provider.assert_called_once();self.assertEqual(result['text'],ONE['text'])
   row=audio.f.db.query_one('SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=?',(self.user,))
   self.assertEqual(row['status'],'COMPLETE');self.assertGreater(float(row['estimated_cost_usd']),0)

 def test_final_prompt_byte_bound_preserves_input_instead_of_truncating_or_dispatching(self):
  with self.funded(),self.on():
   value=self.clauses()
   huge_context={'source':'語'*10000,'text':'語'*10000}
   # Direct contexts are bounded to 400 chars; provider input is never silently
   # shortened. An overlarge full source is rejected by the byte envelope.
   with patch.object(providers,'_openai') as provider:
    with self.assertRaises(audio_store.AudioError):live.translation(self.user,self.key(),'語'*20001,'id','en',value.check,clause_context=huge_context)
   provider.assert_not_called()

 def test_input_bound_and_denied_existing_quota_never_dispatch(self):
  with self.funded(),self.on():
   value=self.clauses()
   with patch.object(providers,'_openai') as provider,patch.object(live.usage,'reserve',side_effect=live.usage.UsageLimit('existing account quota')):
    with self.assertRaises(live.usage.UsageLimit):live.translation(self.user,self.key(),FIRST,'id','en',value.check)
   provider.assert_not_called()

 def test_realtime_pipeline_translates_before_end_preserves_all_pcm_and_full_ram_output(self):
  entered=Event();release=Event();calls=[];speech=struct.pack('<h',10000)*16000;quiet=b'\0'*32000;tail=speech[:6400]
  with self.funded(),self.on(),self.owner(),patch.object(live.voices,'resolve',return_value=fixture.VOICE):
   relay=self.make();socket=relay_fixture.Socket([FIRST,SECOND])
   def stream(*args,**kwargs):
    calls.append((args,kwargs))
    if len(calls)==1:
     entered.set();self.assertTrue(release.wait(4))
     return self.stream({k:ONE[k] for k in ('text','source_language','target_language')})
    return self.stream({'keep_clauses':1,'replacement_text':'For Friday.','source_language':'id','target_language':'en'})
   with patch.object(rt,'connect',return_value=socket),patch.object(providers,'_openai',side_effect=stream),patch.object(live.stt,'require_subscription_credit'),patch.object(__import__('kilas_ai.live_translator_segments',fromlist=['speech']),'speech',return_value=self.audio) as tts:
    runner=Thread(target=relay.run);runner.start()
    try:
     for index,raw in enumerate([speech,speech,speech,quiet]):relay.accept(index,raw)
     self.assertTrue(entered.wait(3));self.assertFalse(relay.final)
     relay.accept(4,speech);relay.accept(5,tail);relay.commit(6);release.set();runner.join(8)
     self.assertFalse(runner.is_alive())
    finally:
     release.set()
     if runner.is_alive():relay.close(rt.failure('turn_cancelled'));runner.join(3)
   self.assertEqual(b''.join(socket.sent),speech*3+quiet+speech+tail)
   self.assertEqual(relay.early_commits,1);self.assertEqual(len(calls),2);tts.assert_called_once()
   state=sessions.result(self.user,relay.ident,relay.key);self.assertEqual(state['status'],'COMPLETED')
   entry=temporary.get(self.user,relay.ident,relay.key)
   self.assertEqual(entry['text'],'I ordered two tickets. For Friday.');self.assertEqual(entry['raw'],self.audio)
   row=audio.f.db.query_one('SELECT original_script,script,source_content,result_content FROM kilas_audio_jobs WHERE id=?',(state['audio_job_id'],))
   self.assertTrue(all(value is None for value in row.values()))
   operations=audio.f.db.query_all('SELECT operation_key,status FROM kilas_ai_usage WHERE user_id=?',(self.user,))
   self.assertEqual({row['operation_key'] for row in operations},{self.key()+'-clause-0-text',self.key()+'-text'})
   self.assertTrue(all(row['status']=='COMPLETE' for row in operations))


if __name__=='__main__':unittest.main()
