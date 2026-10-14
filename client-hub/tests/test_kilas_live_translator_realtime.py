"""Offline synthetic PCM/socket contracts and actual disposable SQLite ledger."""
import base64,io,json,os,time,unittest
from datetime import datetime,timezone,timedelta
from queue import Queue
from threading import Thread,Event
from unittest.mock import patch,Mock
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime as rt,live_translator_realtime_budget as budget
from kilas_ai import audio_transcription_budget as batch,live_translator as live,live_translator_store as sessions,usage
from kilas_ai import providers,audio_branded_voices as branded,live_translator_segments as segments,audio_store

class Socket:
 def __init__(self,texts,hold_final=None):
  self.queue=Queue();self.queue.put(json.dumps({'message_type':'session_started','config':{'model_id':'scribe_v2_realtime','audio_format':'pcm_16000','sample_rate':16000}}))
  self.texts=iter(texts);self.sent=[];self.commits=0;self.closed=False;self.hold_final=hold_final
 def settimeout(self,seconds):self.timeout=seconds
 def recv(self):
  value=self.queue.get(timeout=2)
  if value is None:raise OSError('synthetic socket closed')
  return value
 def send(self,message):
  value=json.loads(message);raw=base64.b64decode(value['audio_base_64']);self.sent.append(raw)
  if value['commit']:
   self.commits+=1;text=next(self.texts)
   if self.hold_final and self.commits==3:
    def late():self.hold_final.wait(2);self.queue.put(json.dumps({'message_type':'committed_transcript','text':text}))
    Thread(target=late,daemon=True).start()
   else:self.queue.put(json.dumps({'message_type':'committed_transcript','text':text}))
  else:self.queue.put(json.dumps({'message_type':'partial_transcript','text':'unstable never translated'}))
 def shutdown(self):self.closed=True;self.queue.put(None)

class RealtimeTests(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 session=fixture.LiveTranslatorTests.session
 key=fixture.LiveTranslatorTests.key
 credit=fixture.LiveTranslatorTests.credit
 def owner(self):return patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_LIVE_TRANSLATOR_USAGE_MODE':'owner'})
 def make(self):
  self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);cap=budget.claim(self.user,ident,key);self.assertTrue(rt._slots.acquire(blocking=False));relay=rt.Relay(self.user,ident,key,info,cap);self.addCleanup(lambda:rt._slots.release() if not relay.finished else None);return relay
 def row(self,key=None):return audio.f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,budget.ledger_key(key or self.key())))
 def run_audio(self,relay,raw):
  for index,offset in enumerate(range(0,len(raw),32000)):
   data=raw[offset:offset+32000]
   while relay.queued_bytes+len(data)>rt.QUEUE_BYTES and not relay.closed.is_set():time.sleep(.001)
   relay.accept(index,data)
  relay.commit(relay.expected)
 def test_gate_does_not_infer_entitlement_from_flags_or_existing_ready_account(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt.account,'verified',return_value=False),patch.object(rt,'connect') as connect:
   with self.assertRaises(audio.store.AudioError) as error:rt.start(self.user,self.session(),self.key())
   self.assertEqual(error.exception.code,'realtime_unverified');connect.assert_not_called();self.assertIsNone(self.row())
 def test_durable_marker_precedes_handshake_and_failure_retains_full_lease(self):
  with self.funded(),self.on(),self.owner(),patch.object(live,'process') as process:
   relay=self.make()
   def failed():self.assertEqual(self.row()['status'],'DISPATCHED');raise OSError('synthetic handshake unknown')
   with patch.object(rt,'connect',side_effect=failed):relay.run()
   row=self.row();self.assertEqual(row['status'],'UNKNOWN');self.assertEqual(row['charge_micro'],budget.RESERVE_MICRO);process.assert_not_called()
 def test_undispatched_end_releases_only_internal_reservation_no_handshake(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect') as connect:
   relay=self.make();sessions.cancel_turn(self.user,relay.ident,relay.key);relay.run()
   self.assertEqual(self.row()['status'],'CANCELLED');self.assertEqual(self.row()['charge_micro'],0);connect.assert_not_called()
 def test_https_session_setup_failure_settles_reservation_and_releases_relay_slot(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt.transport.requests,'Session',side_effect=RuntimeError('synthetic session setup')),patch.object(rt,'connect') as connect:
   relay=self.make()
   with rt._lock:rt._relays[(self.user,relay.ident,relay.key)]=relay
   relay.run()
   self.assertTrue(relay.finished);self.assertTrue(relay.closed.is_set());self.assertEqual(self.row()['status'],'CANCELLED');self.assertEqual(self.row()['charge_micro'],0)
   self.assertEqual(sessions.result(self.user,relay.ident,relay.key)['status'],'FAILED');connect.assert_not_called()
   with rt._lock:self.assertNotIn((self.user,relay.ident,relay.key),rt._relays)
   self.assertTrue(rt._slots.acquire(blocking=False));rt._slots.release()
 def test_long_more_than_36s_stable_pieces_and_identical_words_all_reach_translation_after_final_ack(self):
  final=Event();socket=Socket(['Repeat this.','Repeat this.','最后一句。'],final)
  raw=b'\x01\x00'*(50*16000+137)
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect',return_value=socket),patch.object(live,'process') as process:
   relay=self.make();worker=Thread(target=relay.run);worker.start();self.run_audio(relay,raw)
   limit=time.monotonic()+2
   while socket.commits<3 and time.monotonic()<limit:time.sleep(.001)
   self.assertEqual(socket.commits,3);process.assert_not_called();final.set();worker.join(3);self.assertFalse(worker.is_alive())
   self.assertEqual(b''.join(socket.sent),raw);self.assertTrue(socket.closed);self.assertEqual(process.call_args.kwargs['committed_text'],'Repeat this. Repeat this. 最后一句。')
   self.assertTrue(process.call_args.kwargs['whole_output']);self.assertFalse(process.call_args.kwargs.get('stream_output',False))
   self.assertEqual(process.call_args.kwargs['timings']['realtime_input_ms'],len(raw)/32);self.assertGreaterEqual(process.call_args.kwargs['started'],relay.started);self.assertEqual(self.row()['status'],'COMPLETED')
 def test_chunk_indices_lengths_queue_and_final_count_are_strict(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make()
   for index,raw in [(True,b'12'),(1,b'12'),(0,b'1'),(0,b'1'*32002)]:
    with self.assertRaises(audio.store.AudioError):relay.accept(index,raw)
   relay.accept(0,b'12')
   with self.assertRaises(audio.store.AudioError):relay.accept(0,b'12')
   with self.assertRaises(audio.store.AudioError):relay.commit(0)
   relay.commit(1)
   with self.assertRaises(audio.store.AudioError):relay.accept(1,b'12')
   budget.finish(relay.capability,False)
 def test_queue_overflow_cannot_submit_a_partial_prefix(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make()
   for index in range(4):relay.accept(index,b'1'*32000)
   with self.assertRaises(audio.store.AudioError) as error:relay.accept(4,b'1'*32000)
   self.assertEqual(error.exception.code,'realtime_queue_full');budget.finish(relay.capability,False)
 def test_unexpected_commit_and_delayed_timestamp_events_do_not_duplicate_text(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make();socket=Socket([]);socket.queue.get();relay.ws=socket
   socket.queue.put(json.dumps({'message_type':'committed_transcript_with_timestamps','text':'ignored duplicate'}));socket.queue.put(json.dumps({'message_type':'committed_transcript','text':'unexpected auto prefix'}));relay.receive()
   self.assertEqual(relay.error.code,'realtime_commit_unexpected');self.assertEqual(relay.pieces,[]);budget.finish(relay.capability,False)
 def test_missing_worker_cancels_shared_turn_without_another_handshake(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect') as connect:
   relay=self.make()
   with self.assertRaises(audio.store.AudioError) as error:rt.owned(self.user,relay.ident,relay.key)
   self.assertEqual(error.exception.code,'realtime_worker_unavailable');self.assertEqual(sessions.result(self.user,relay.ident,relay.key)['status'],'CANCELLED');connect.assert_not_called();budget.finish(relay.capability,False)
 def test_other_worker_end_closes_socket_via_shared_fence(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make();socket=Socket([]);relay.ws=socket;watch=Thread(target=relay.watch);watch.start();sessions.end(self.user,relay.ident);watch.join(2)
   self.assertFalse(watch.is_alive());self.assertTrue(socket.closed);budget.finish(relay.capability,False)
 def test_realtime_lease_survives_120s_but_batch_recovers_after_240s_without_refund(self):
  with self.funded(),self.on(),self.owner():
   relay=self.make();budget.dispatch(relay.capability)
   audio.f.db.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE user_id=?',((datetime.now(timezone.utc)-timedelta(seconds=130)).isoformat(),self.user))
   with self.assertRaises(batch.BudgetError) as error:batch.claim(self.user,self.key(2),'a'*64,1000)
   self.assertEqual(error.exception.code,'already_processing');self.assertEqual(self.row()['status'],'DISPATCHED')
   audio.f.db.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE user_id=?',((datetime.now(timezone.utc)-timedelta(seconds=250)).isoformat(),self.user))
   _,cap=batch.claim(self.user,self.key(2),'a'*64,1000);self.assertIsNotNone(cap);self.assertEqual(self.row()['status'],'UNKNOWN');self.assertEqual(self.row()['charge_micro'],budget.RESERVE_MICRO);batch.cancel(self.user,self.key(2))
 def test_batch_and_realtime_share_existing_caps_in_both_admission_directions(self):
  for reverse in [False,True]:
   with self.funded(50000,50000),self.on(),self.owner():
    key=self.key(7 if reverse else 5)
    if reverse:
     _,cap=batch.claim(self.user,key,'a'*64,600000);batch.dispatch(cap,'a'*64,600000);batch.finish(cap,True)
     with self.assertRaises(batch.BudgetError) as error:budget.claim(self.user,'c'*48,self.key(8))
    else:
     cap=budget.claim(self.user,'c'*48,key);budget.dispatch(cap);budget.finish(cap,False)
     with self.assertRaises(batch.BudgetError) as error:batch.claim(self.user,self.key(6),'a'*64,600000)
    self.assertEqual(error.exception.code,'budget_limit')
    audio.f.db.execute('DELETE FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))
 def test_http_auth_csrf_gate_and_pcm_validation_no_client_transcript(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect') as connect:
   ident=self.session();url='/kilas-translator/live/sessions/'+ident+'/turns/'+self.key()
   self.assertEqual(self.client.post(url+'/input/start',data={'csrf_token':'audio-csrf','text':'injected transcript'}).status_code,503);connect.assert_not_called()
   self.assertEqual(self.client.post(url+'/input/start').status_code,400)
   from auth_test_helpers import authenticate
   authenticate(self.client,__import__('repo').get_user_by_id(self.other),_csrf_token='audio-csrf')
   self.assertEqual(self.client.post(url+'/input/start',data={'csrf_token':'audio-csrf'}).status_code,503)

 def test_provider_quota_closes_without_batch_fallback_or_translation(self):
  socket=Socket([]);socket.queue.put(json.dumps({'message_type':'quota_exceeded','error':'private provider message'}))
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect',return_value=socket) as connect,patch.object(live,'process') as process:
   relay=self.make();relay.run();self.assertTrue(socket.closed);self.assertEqual(self.row()['status'],'UNKNOWN');self.assertEqual(self.row()['charge_micro'],budget.RESERVE_MICRO);process.assert_not_called();connect.assert_called_once()
   self.assertEqual(sessions.result(self.user,relay.ident,relay.key)['error_code'],'realtime_quota')
 def test_no_final_ack_times_out_truthfully_retains_unknown_dispatch_and_never_translates(self):
  socket=Socket([])
  def send(message):socket.sent.append(base64.b64decode(json.loads(message)['audio_base_64']))
  socket.send=send
  with self.funded(),self.on(),self.owner(),patch.object(rt,'connect',return_value=socket),patch.object(live,'process') as process:
   relay=self.make();relay.accept(0,b'12'*16000);relay.commit(1);original=relay.acknowledge
   def no_ack():
    with patch.object(relay,'check',return_value=None),patch.object(rt,'monotonic',side_effect=[0,9]):original()
   with patch.object(relay,'acknowledge',side_effect=no_ack):relay.run()
   self.assertEqual(relay.error.code,'realtime_commit_timeout');self.assertTrue(socket.closed);self.assertEqual(self.row()['status'],'UNKNOWN');process.assert_not_called()
 def test_independent_deadline_closes_socket_without_waiting_for_database_check(self):
  with self.funded(),self.on(),self.owner(),patch.object(rt,'Timer') as timer:
   relay=self.make();socket=Socket([]);relay.ws=socket;relay.arm_deadline()
   with patch.object(sessions,'check') as check:
    callback=timer.call_args.args[1];callback(*timer.call_args.kwargs['args']);check.assert_not_called()
   self.assertTrue(socket.closed);self.assertEqual(relay.error.code,'realtime_deadline');self.assertTrue(timer.return_value.daemon);budget.finish(relay.capability,False);timer.return_value.cancel()
 def test_end_after_dispatch_and_final_commit_retains_cost_and_blocks_luna(self):
  with self.funded(),self.on(),self.owner(),patch.object(live,'process') as process:
   relay=self.make();socket=Socket([])
   def send(message):
    value=json.loads(message);socket.sent.append(base64.b64decode(value['audio_base_64']))
    if value['commit']:sessions.end(self.user,relay.ident)
   socket.send=send;relay.accept(0,b'12'*16000);relay.commit(1)
   with patch.object(rt,'connect',return_value=socket):relay.run()
   self.assertTrue(socket.closed);self.assertEqual(self.row()['status'],'UNKNOWN');self.assertEqual(self.row()['charge_micro'],budget.RESERVE_MICRO);process.assert_not_called()
 def test_actual_complete_output_pipeline_uses_stable_text_without_any_batch_stt(self):
  text='Ulangi ini. Ulangi ini. Kalimat terakhir.';translated='Repeat this. Repeat this. Last sentence.'
  def stream(*args,**kwargs):
   self.assertEqual(args[2][0]['content'],text);self.assertEqual(args[0],'gpt-6-luna');self.assertEqual(kwargs['profile']['effort'],'none');self.assertIn('faithfully',kwargs['system'])
   yield {'type':'delta','text':json.dumps({'text':translated,'source_language':'id','target_language':'en'})}
   yield {'type':'finish','reason':'stop'}
  with self.funded(),self.on(),self.owner(),patch.object(branded,'resolve',return_value=fixture.VOICE),patch.object(live.stt,'normalize') as normalize,patch.object(live.stt,'transcribe') as transcribe,patch.object(batch,'claim') as claim,patch.object(providers,'_openai',side_effect=stream) as luna,patch.object(segments,'speech',return_value=audio.mp3(.6)):
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);job=live.process(self.user,ident,key,None,info,committed_text=text,stream_output=True)
   normalize.assert_not_called();transcribe.assert_not_called();claim.assert_not_called();luna.assert_called_once();row=audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(job,));self.assertEqual(row['status'],'COMPLETED');self.assertEqual(row['original_script'],translated);self.assertEqual(row['source_language'],'id');self.assertEqual(row['target_language'],'en');self.assertGreater(row['seconds_charged'],0)
   result=self.client.get('/kilas-translator/live/sessions/'+ident+'/turns/'+key).json;self.assertEqual(result['translated_text'],translated);self.assertEqual(result['segments'][-1]['translated_text'],translated)
 def test_end_before_stable_handoff_blocks_actual_luna_and_tts(self):
  with self.funded(),self.on(),self.owner(),patch.object(branded,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai') as luna,patch.object(segments,'speech') as tts,patch.object(live.audio_provider,'speech') as standard:
   self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);sessions.end(self.user,ident)
   with self.assertRaises(audio_store.AudioError):live.process(self.user,ident,key,None,info,committed_text='Stable whole text.',stream_output=True)
   luna.assert_not_called();tts.assert_not_called();standard.assert_not_called()

 def test_postgres_expiry_contract_binds_typed_price_versions_as_values(self):
  executed=[]
  class Cursor:
   def execute(self,sql,params):
    self_assert.assertEqual(sql.count('%s'),len(params));self_assert.assertNotIn('live-%-rt',sql);executed.append((sql,params))
   def close(self):pass
  class Connection:
   def cursor(self):return Cursor()
  self_assert=self
  with patch.object(audio.f.db,'BACKEND','postgres'):batch._expire(Connection(),owner=42)
  self.assertEqual(len(executed),2);self.assertIn('NOT IN (SELECT',executed[0][0]);self.assertIn('IN (SELECT',executed[1][0]);self.assertEqual(executed[0][1][0],budget.PRICE_VERSION);self.assertEqual(executed[1][1][0],budget.PRICE_VERSION)

 def test_batch_120s_expiry_cannot_be_retyped_by_a_realtime_looking_caller_key(self):
  with self.funded(),self.on(),self.owner():
   key=self.key()+'-rt';_,cap=batch.claim(self.user,key,'a'*64,1000);batch.dispatch(cap,'a'*64,1000)
   audio.f.db.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE user_id=?',((datetime.now(timezone.utc)-timedelta(seconds=130)).isoformat(),self.user))
   self.assertEqual(batch.owned(self.user,key)['status'],'UNKNOWN')
   self.assertEqual(audio.f.db.query_one('SELECT price_version FROM kilas_vo_stt_campaigns WHERE id=?',(batch.policy()['id'],))['price_version'],batch.PRICE_VERSION)

 def test_stale_batch_lease_recovers_on_realtime_admission_without_refunding_cost(self):
  with self.funded(),self.on(),self.owner():
   key=self.key(3);_,cap=batch.claim(self.user,key,'a'*64,1000);batch.dispatch(cap,'a'*64,1000)
   audio.f.db.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE user_id=?',((datetime.now(timezone.utc)-timedelta(seconds=130)).isoformat(),self.user))
   realtime=budget.claim(self.user,'c'*48,self.key(4))
   row=audio.f.db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,key))
   self.assertEqual(row['status'],'UNKNOWN');self.assertEqual(row['charge_micro'],batch.reserve_micro(1000));budget.finish(realtime,False)

if __name__=='__main__':unittest.main()
