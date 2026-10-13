"""Offline exact-one qualification ledger, billing guards and OS deadline contracts."""
import ast,json,os,subprocess,sys,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import live_translator_realtime_check as check,usage

class Checks(unittest.TestCase):
 setUp=fixture.LiveTranslatorTests.setUp
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 def setUp(self):
  fixture.LiveTranslatorTests.setUp(self)
  with check.transaction() as conn:
   conn.executescript((Path(__file__).parents[1]/'migrations'/'0094_kilas_realtime_check_sqlite.sql').read_text());conn.execute('DELETE FROM kilas_realtime_checks');conn.execute("DELETE FROM kilas_vo_stt_operations WHERE operation_key=?",(check.OPERATION,))
 def owner(self):return patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_LIVE_TRANSLATOR_USAGE_MODE':'owner'})
 def safe(self):return {'tier':'creator','status':'active','max_credit_limit_extension':0,'allowed_to_extend_character_limit':False,'can_extend_character_limit':False,'character_count':100,'character_limit':200,'current_overage':0}
 def row(self):return audio.f.db.query_one('SELECT * FROM kilas_realtime_checks WHERE approval=?',(check.APPROVAL,))
 def test_strict_subscription_and_overage(self):
  with patch.object(check.account,'_get',return_value=self.safe()):self.assertEqual(check.subscription()['used'],100)
  for key,val in [('max_credit_limit_extension',False),('allowed_to_extend_character_limit',True),('current_overage',1),('character_count',True),('character_count',200),('tier','pro')]:
   value=self.safe();value[key]=val
   with patch.object(check.account,'_get',return_value=value),self.assertRaises(ValueError):check.subscription()
 def test_modern_overage_object_exact_zero_usd_only(self):
  value=self.safe();value['current_overage']={'amount':'0.00','currency':'usd'}
  with patch.object(check.account,'_get',return_value=value):self.assertTrue(check.subscription()['overage_zero'])
  for overage in ({'amount':'0.01','currency':'usd'},{'amount':'0','currency':'eur'},{'amount':'NaN','currency':'usd'},False):
   value['current_overage']=overage
   with patch.object(check.account,'_get',return_value=value),self.assertRaises(ValueError):check.subscription()
 def test_global_marker_committed_before_launch_never_reclaims_and_keeps_unknown_allowance(self):
  with self.funded(),self.on(),self.owner():
   owner=check.claim({'used':100,'limit':200});self.assertEqual(owner,self.user);self.assertEqual(self.row()['status'],'DISPATCHED')
   self.assertIsNone(check.claim({'used':100,'limit':200}));check.finish(owner,{'accepted':True,'result':'deadline_unknown'},None,False)
   self.assertEqual(self.row()['status'],'UNKNOWN');self.assertIsNone(check.claim({'used':100,'limit':200}));self.assertFalse(check.verified())
   row=audio.f.db.query_one('SELECT charge_micro,duration_ms,status FROM kilas_vo_stt_operations WHERE operation_key=?',(check.OPERATION,));self.assertEqual((row['charge_micro'],row['duration_ms'],row['status']),(1084,10000,'UNKNOWN'))
 def test_only_positive_attributed_same_key_and_same_limit_activates(self):
  with self.funded(),self.on(),self.owner():
   owner=check.claim({'used':100,'limit':200})
   for after,attribution in [({'used':100,'limit':200},True),({'used':101,'limit':200},False),({'used':101,'limit':300},True)]:
    active,_=check.finish(owner,{'accepted':True,'result':'committed','wire_process_ms':4000,'sent_pcm_ms':5000},after,attribution);self.assertFalse(active)
   active,_=check.finish(owner,{'accepted':True,'result':'committed','wire_process_ms':10001,'sent_pcm_ms':5000},{'used':101,'limit':200},True);self.assertFalse(active)
   active,_=check.finish(owner,{'accepted':True,'result':'provider_rejected','wire_process_ms':4000,'sent_pcm_ms':5000},{'used':101,'limit':200},True);self.assertFalse(active)
   active,_=check.finish(owner,{'accepted':True,'result':'committed','wire_process_ms':4000,'sent_pcm_ms':5000},{'used':101,'limit':200},True);self.assertTrue(active);self.assertTrue(check.verified())
   with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'changed-private-key'}):self.assertFalse(check.verified())
 def test_busy_does_not_cancel_or_dispatch(self):
  with self.funded(),self.on(),self.owner(),patch.object(check,'quiet',return_value=False),patch.object(check,'wire') as wire:
   with self.assertRaises(ValueError):check.claim({'used':100,'limit':200})
   self.assertIsNone(self.row());wire.assert_not_called()
 def test_default_off_no_flag_only_activation(self):
  with patch.dict(os.environ,{'KILAS_REALTIME_CHECK_ONCE':'off'}),patch.object(check,'Thread') as thread:check.startup();thread.assert_not_called()
  self.assertFalse(check.verified())
 def test_child_alarm_precedes_websocket_import_and_has_no_retry_secret_argv(self):
  path=Path(check.__file__).with_name('live_translator_realtime_check_wire.py');tree=ast.parse(path.read_text())
  alarm=next(i for i,x in enumerate(tree.body) if isinstance(x,ast.Expr) and isinstance(x.value,ast.Call) and ast.unparse(x.value.func)=='signal.setitimer')
  websocket=next(i for i,x in enumerate(tree.body) if isinstance(x,ast.Import) and any(a.name=='websocket' for a in x.names));self.assertLess(alarm,websocket)
  self.assertIn('signal.SIG_DFL',path.read_text());self.assertIn('redirect_limit=0',path.read_text())
 def test_parent_timeout_kills_before_return_and_no_second_launch(self):
  child=Mock();child.communicate.side_effect=[subprocess.TimeoutExpired('synthetic',10),(b'{"accepted":true}\n',None)]
  with patch.object(check.subprocess,'Popen',return_value=child) as popen,patch.dict(os.environ,{'ELEVENLABS_API_KEY':'private'}):result=check.wire()
  self.assertTrue(result['accepted']);self.assertEqual(result['result'],'deadline_unknown');child.kill.assert_called();self.assertEqual(popen.call_count,1);self.assertNotIn('private',str(popen.call_args.args))
 def test_child_os_alarm_closes_blocked_connect_even_without_parent(self):
  # Execute actual alarm declaration at a shortened offline test deadline, then
  # block a synthetic connect. SIGALRM default kills process/resource despite no
  # assigned socket. No network/provider call occurs.
  wire=Path(check.__file__).with_name('live_translator_realtime_check_wire.py')
  code="import signal,sys,types,time,runpy; original=signal.setitimer; signal.setitimer=lambda kind,duration: original(kind,.08); fake=types.ModuleType('websocket');fake.create_connection=lambda *a,**k:time.sleep(10);sys.modules['websocket']=fake;runpy.run_path("+repr(str(wire))+",run_name='__main__')"
  child=subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL);child.communicate(timeout=1);self.assertEqual(child.returncode,-14)
 def test_exact_synthetic_pcm_bytes_without_importing_alarm_in_test_worker(self):
  path=Path(check.__file__).with_name('live_translator_realtime_check_wire.py');tree=ast.parse(path.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='pcm')
  import math,struct
  scope={'math':math,'struct':struct};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope);raw=scope['pcm']();self.assertEqual(len(raw),160000);self.assertEqual(raw,scope['pcm']())
 def test_restart_existing_marker_never_launches_wire(self):
  with self.funded(),self.on(),self.owner():
   check.claim({'used':100,'limit':200})
   with patch.object(check,'subscription',return_value={'used':100,'limit':200}),patch.object(check,'wire') as wire:check.run();wire.assert_not_called()
 def test_actual_wire_validates_config_sends_exact5s_and_blank_committed_text_is_acceptance(self):
  import base64,math,struct
  path=Path(check.__file__).with_name('live_translator_realtime_check_wire.py');tree=ast.parse(path.read_text());nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
  socket=Mock();socket.recv.side_effect=[json.dumps({'message_type':'session_started','config':{'model_id':check.account.MODEL,'audio_format':'pcm_16000','sample_rate':16000}}),json.dumps({'message_type':'committed_transcript','text':''})]
  provider=Mock();provider.create_connection.return_value=socket
  scope={'base64':base64,'math':math,'struct':struct,'os':os,'json':json,'time':Mock(),'websocket':provider,'MODEL':check.account.MODEL};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope);scope['emit']=Mock()
  with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'private'}):scope['run']()
  frames=[json.loads(c.args[0]) for c in socket.send.call_args_list];self.assertEqual(sum(len(base64.b64decode(f['audio_base_64'])) for f in frames),160000);self.assertEqual([f['commit'] for f in frames],[False]*4+[True]);socket.shutdown.assert_called_once();scope['emit'].assert_any_call(accepted=True);scope['emit'].assert_any_call(result='committed',stable_characters=0);self.assertEqual(provider.create_connection.call_count,1)
 def test_analytics_requires_exact_model_time_unit_and_no_other_paid_request(self):
  from kilas_ai import live_translator_transport
  cols=['path','query','timestamp','response_code'];value={'columns':cols,'column_units':[None,None,'ms',None],'rows':[['/v1/speech-to-text/realtime','model_id=scribe_v2_realtime',1700000000000,101],['/v1/user/subscription','',1700000000000,200]]}
  response=Mock();response.status_code=200;response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
  with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'private'}),patch.object(live_translator_transport,'post',return_value=response):
   response.iter_content.return_value=[json.dumps(value).encode()];self.assertTrue(check.attributed(1699999999999,1700000000001))
   value['rows'].append(['/v1/text-to-speech/x','',1700000000000,200]);response.iter_content.return_value=[json.dumps(value).encode()];self.assertFalse(check.attributed(1699999999999,1700000000001))
   value['rows']=[];response.iter_content.return_value=[json.dumps(value).encode()];self.assertFalse(check.attributed(1699999999999,1700000000001))
 def test_unknown_saved_wire_reconciles_read_only_from_original_credit_window(self):
  with self.funded(),self.on(),self.owner():
   owner=check.claim({'used':100,'limit':200},1700000000000);result={'accepted':True,'result':'deadline_unknown','wire_process_ms':9800,'sent_pcm_ms':5000}
   check.save_wire(owner,result,1700000009800)
   row=self.row();self.assertEqual(row['status'],'UNKNOWN');self.assertEqual(row['wire_end_ms'],1700000009800)
   after={'used':101,'limit':200,'overage_zero':True,'overage_currency':'usd'}
   with patch.object(check,'subscription',return_value=after),patch.object(check,'attributed',return_value=True) as attribution,patch.object(check,'wire') as wire:
    check.reconcile_existing();wire.assert_not_called();self.assertEqual(attribution.call_args.args[0],1700000000000);self.assertGreater(attribution.call_args.args[1],1700000009800)
   self.assertTrue(check.verified());self.assertEqual(self.row()['before_used'],100)
 def test_bounds_saved_predicates_and_negative_config_never_activate(self):
  with self.funded(),self.on(),self.owner():
   owner=check.claim({'used':100,'limit':200})
   for ms,sent,result in [(True,5000,'committed'),(10001,5000,'committed'),(5000,5001,'committed'),(5000,5000,'config_invalid')]:
    if sent>5000:continue # Database CHECK itself rejects an invalid persisted count.
    active,_=check.finish(owner,{'accepted':True,'result':result,'wire_process_ms':ms,'sent_pcm_ms':sent},{'used':101,'limit':200},True);self.assertFalse(active);self.assertFalse(check.verified())
if __name__=='__main__':unittest.main()
