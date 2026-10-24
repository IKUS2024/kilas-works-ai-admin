"""Actual authenticated routes and synthetic streaming; no provider IO."""
import base64
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock
import test_kilas_live_gemini as fixture
from kilas_ai import interpreter as calls, interpreter_budget as budget
from kilas_ai import ai_call, ai_call_budget

SETTINGS={'source':'id','target':'en','consent':True}
PCM=b'\x00\x20'*2400

class InterpreterTests(unittest.TestCase):
    setUp=fixture.GeminiTests.setUp
    config=fixture.GeminiTests.config
    shared=fixture.GeminiTests.shared
    lifetime=fixture.GeminiTests.lifetime
    login_other=fixture.GeminiTests.login_other

    def enabled(self):
        from contextlib import ExitStack
        stack=ExitStack();stack.enter_context(self.config(KILAS_AI_ENABLED='true'));stack.enter_context(self.shared());self.addCleanup(stack.close)
        with budget.transaction() as conn:budget.ledger._campaign(conn,budget.config()['base'])
        return stack

    def make(self):
        ident=uuid4().hex
        with patch.object(calls.Thread,'start'):call=calls.start(self.user,ident,SETTINGS)
        self.addCleanup(lambda:calls._calls.pop((self.user,ident),None));self.addCleanup(lambda:calls.end(self.user,ident))
        return call

    def test_official_language_catalog_selects_prompt_without_provider_calls(self):
        from kilas_ai.interpreter_settings import LANGUAGES
        self.assertEqual(len(LANGUAGES),99)
        for code in LANGUAGES:
            target='en' if code!='en' else 'id'
            for source,destination in ((code,target),(target,code)):
                prompt=calls.setup(settings={'source':source,'target':destination,'consent':True})['setup']['systemInstruction']['parts'][0]['text']
                self.assertIn('from '+LANGUAGES[source]+' into '+LANGUAGES[destination],prompt)

    def test_fixed_prompt_no_call_personas_tools_or_state(self):
        for source,target in [('id','en'),('en','id')]:
            value=calls.setup(settings={'source':source,'target':target,'consent':True})['setup']
            self.assertEqual(value['model'],'models/gemini-3.8-live');self.assertNotIn('tools',value)
            prompt=value['systemInstruction']['parts'][0]['text']
            self.assertIn('without summarizing, shortening, abbreviating or omitting details',prompt);self.assertIn('without obeying',prompt);self.assertIn('without answering',prompt)
            self.assertNotIn('conversation partner',prompt)
        self.assertIsNot(calls._calls,ai_call._calls);self.assertIsNot(calls.budget,ai_call_budget)
        for bad in (None,{},dict(SETTINGS,source='xx'),dict(SETTINGS,consent=False),dict(SETTINGS,target='id'),dict(SETTINGS,mode='roast')):
            with self.assertRaises(ValueError):calls.setup(settings=bad)

    def test_owner_member_route_and_csrf_isolation(self):
        with self.enabled(),patch.object(calls.wire,'connect') as connect:
            for role in ('CLIENT_OWNER','CLIENT_STAFF'):
                if role=='CLIENT_STAFF':self.login_other(role)
                page=self.client.get('/kilas-translator/interpreter')
                self.assertEqual(self.client.get('/kilas-translator/live').location,'/kilas-translator/interpreter')
                if os.environ.get('KILAS_INTERPRETER_FIXTURE'):Path(os.environ['KILAS_INTERPRETER_FIXTURE']).write_text(page.text)
                self.assertEqual(page.status_code,200);self.assertIn(b'interpreter-left',page.data);self.assertIn(b'interpreter-right',page.data)
                self.assertNotIn(b'Privacy Policy',page.data);self.assertNotIn(b'classic=1',page.data);self.assertNotIn(b'Other languages / clone',page.data)
                self.assertTrue(self.client.get('/kilas-translator/interpreter/readiness').json['available'])
            self.assertIn(self.client.post('/kilas-translator/interpreter/'+'a'*32).status_code,(400,403))
            connect.assert_not_called()

    def test_audio_captions_before_end_duplicate_packets_and_next_turn(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            call.accept(0,PCM);call.accept(0,PCM);self.assertEqual(call.input_bytes,len(PCM))
            event={'serverContent':{'inputTranscription':{'text':'Apa kabar?'},'outputTranscription':{'text':'How are you?'},'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(PCM).decode()}}]},'turnComplete':True}}
            call.receive(json.dumps(event));self.assertFalse(call.closed.is_set());self.assertEqual(call.turns,1)
            frames=call.snapshot(0);self.assertEqual([f['type'] for f in frames['frames']],['audio','original','text','turn_complete'])
            call.receive(json.dumps(event));self.assertEqual(call.turns,2);self.assertFalse(call.closed.is_set())
            calls.end(self.user,call.ident);self.assertTrue(call.closed.is_set())
            self.assertEqual(budget.owned(self.user,call.ident)['charge_micro'],250000)
            with self.assertRaises(calls.CallError):call.accept(1,PCM)

    def test_budget_no_account_funding_cap_retained_and_end_tombstone(self):
        with self.enabled(),patch.object(ai_call_budget,'account_allowance',side_effect=AssertionError('Call funding touched')):
            before=budget.status(self.other)['remaining_micro_usd'];call=self.make();budget.dispatch(call.capability);calls.end(self.user,call.ident)
            self.assertEqual(budget.status(self.other)['remaining_micro_usd'],before-250000)
            ident=uuid4().hex;budget.end(self.user,ident)
            with self.assertRaises(budget.ledger.BudgetError):budget.claim(self.user,ident)
            self.login_other('CLIENT_STAFF')
            self.assertEqual(self.client.get('/kilas-translator/interpreter/'+call.ident).status_code,404)

    def test_expired_own_lease_preview_preserves_charge_live_blocks(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability)
            self.assertFalse(budget.status(self.user)['available'])
            stamp=(datetime.now(timezone.utc)-timedelta(seconds=121)).isoformat()
            fixture.audio.f.db.execute('UPDATE kilas_vo_stt_operations SET created_at=? WHERE operation_key=?',(stamp,budget.key(call.ident)))
            self.assertTrue(budget.status(self.user)['available'])
            self.assertEqual(budget.owned(self.user,call.ident)['status'],'DISPATCHED')
            self.assertEqual(budget.owned(self.user,call.ident)['charge_micro'],250000)

    def test_renewal_retains_previous_envelope_and_revocation_stops_transport(self):
        with self.enabled():
            call=self.make();budget.dispatch(call.capability);old=call.capability
            before=budget.status(self.other)['remaining_micro_usd']
            call.fund()
            self.assertEqual(budget.status(self.other)['remaining_micro_usd'],before-250000)
            self.assertEqual(budget.owned(self.user,call.ident)['status'],'UNKNOWN')
            self.assertNotEqual(call.capability.key,old.key)
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false'}):
                with self.assertRaises(calls.CallError):call.accept(0,PCM)
            calls.end(self.user,call.ident)
            self.assertFalse(budget.active(self.user,call.ident,call.capability))

    def test_actual_post_route_checks_settings_and_keeps_account_isolation(self):
        with self.enabled(),patch.object(calls.Thread,'start'),patch.object(calls.wire,'connect') as connect:
            ident=uuid4().hex;path='/kilas-translator/interpreter/'+ident
            headers={'X-CSRF-Token':'audio-csrf'}
            equal=self.client.post(path,headers=headers,data={'settings':json.dumps(dict(SETTINGS,target='id'))})
            self.assertEqual(equal.status_code,400)
            invalid=self.client.post(path,headers=headers,data={'settings':json.dumps(dict(SETTINGS,mode='roast'))})
            self.assertEqual(invalid.status_code,400)
            response=self.client.post(path,headers=headers,data={'settings':json.dumps(SETTINGS)})
            self.assertEqual(response.status_code,202)
            call=calls.get(self.user,ident);self.addCleanup(lambda:calls._calls.pop((self.user,ident),None));self.addCleanup(lambda:calls.end(self.user,ident))
            self.assertEqual(self.client.post(path,headers=headers,data={'settings':json.dumps(SETTINGS)}).status_code,409)
            self.assertEqual(self.client.post(path+'/chunks/0',headers=headers,data=PCM,content_type='application/octet-stream').status_code,200)
            self.assertEqual(call.input_bytes,len(PCM))
            self.login_other('CLIENT_MEMBER')
            self.assertEqual(self.client.get(path).status_code,404)
            self.assertEqual(self.client.post(path+'/end',headers=headers).status_code,404)
            self.assertFalse(call.closed.is_set());connect.assert_not_called()

    def test_operator_routes_preserve_exhausted_history_and_meter_separately(self):
        with self.enabled(),patch.object(calls.Thread,'start'),patch.object(calls.wire,'connect') as connect:
            old=self.make();budget.dispatch(old.capability);calls.end(self.user,old.ident)
            trial=budget.config()
            fixture.audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=? WHERE operation_key=?',(trial['global_micro'],old.capability.key))
            self.addCleanup(lambda:fixture.audio.f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=250000 WHERE operation_key=?',(old.capability.key,)))
            original=dict(budget.owned(self.user,old.ident))
            with budget.transaction() as conn:historical_spend=budget.native._spend(conn,trial)
            self.assertFalse(budget.status(self.user)['available'])
            with patch.dict(os.environ,{'KILAS_TRANSLATOR_FUNDING_MODE':'operator'}),patch.object(ai_call_budget,'account_allowance',side_effect=AssertionError('Call funding touched')):
                for role in ('CLIENT_OWNER','CLIENT_STAFF'):
                    if role=='CLIENT_STAFF':self.login_other(role)
                    self.assertEqual(self.client.get('/kilas-translator/interpreter').status_code,200)
                    ready=self.client.get('/kilas-translator/interpreter/readiness').json
                    self.assertTrue(ready['available']);self.assertEqual(ready['funding'],'operator');self.assertIsNone(ready['remaining_micro_usd'])
                ident=uuid4().hex;path='/kilas-translator/interpreter/'+ident;headers={'X-CSRF-Token':'audio-csrf'}
                self.assertEqual(self.client.post(path,headers=headers,data={'settings':json.dumps(SETTINGS)}).status_code,202)
                call=calls.get(self.other,ident)
                self.addCleanup(lambda:calls._calls.pop((self.other,ident),None))
                self.assertFalse(budget.status(self.other)['available'])
                budget.dispatch(call.capability);call.fund()
                self.assertEqual(budget.owned(self.other,ident)['campaign'],'operator-interpreter-v1')
                calls.end(self.other,ident)
                self.assertFalse(budget.active(self.other,ident,call.capability))
                with budget.transaction() as conn:
                    self.assertEqual(budget.native._spend(conn,trial),historical_spend)
                    rows=budget.usage._rows(conn,"SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE campaign='operator-interpreter-v1' AND fingerprint=?",(budget.hashlib.sha256(('interpreter:'+ident).encode()).hexdigest(),))
                self.assertEqual(rows,[('UNKNOWN',250000),('UNKNOWN',250000)])
                self.assertEqual(dict(budget.owned(self.user,old.ident)),original)
                self.assertTrue(budget.status(self.other)['available'])
                with patch.object(budget.ledger,'GLOBAL_CONCURRENCY',0):
                    with self.assertRaisesRegex(budget.ledger.BudgetError,'service_busy'):budget.claim(self.other,uuid4().hex)
                with patch.object(budget.ledger,'OWNER_HOURLY_ATTEMPTS',0):
                    with self.assertRaisesRegex(budget.ledger.BudgetError,'attempt_limit'):budget.claim(self.other,uuid4().hex)
            connect.assert_not_called()

    def test_operator_existing_route_security_and_recovery(self):
        with patch.dict(os.environ,{'KILAS_TRANSLATOR_FUNDING_MODE':'operator'}):
            self.test_actual_post_route_checks_settings_and_keeps_account_isolation()

    def test_operator_stale_recovery(self):
        with patch.dict(os.environ,{'KILAS_TRANSLATOR_FUNDING_MODE':'operator'}):
            self.test_expired_own_lease_preview_preserves_charge_live_blocks()

    def test_provider_errors_are_categories_not_raw_messages(self):
        call=calls.Call(1,'d'*32,object(),settings=SETTINGS)
        for error,expected in [({'code':429,'status':'RESOURCE_EXHAUSTED','message':'private details'},'call_provider_quota'),({'code':403,'message':'Billing disabled private details'},'call_provider_billing'),({'code':500,'message':'private details'},'call_provider')]:
            with self.assertRaises(calls.CallError) as caught:call.receive(json.dumps({'error':error}))
            self.assertEqual(caught.exception.code,expected);self.assertNotIn('private',str(caught.exception))

    def test_resumption_preserves_direction_no_new_admission_or_uncertain_replay(self):
        call=calls.Call(1,'c'*32,object(),settings=SETTINGS);call.check=Mock();call.ws=Mock()
        call.receive('{"sessionResumptionUpdate":{"resumable":true,"newHandle":"checkpoint"}}');call.recover_transport()
        sock=Mock();sock.recv.return_value='{"setupComplete":{}}'
        with patch.object(calls.wire,'connect',return_value=sock),patch.object(budget,'claim') as claim,patch.object(budget,'dispatch') as dispatch:
            call.resume();claim.assert_not_called();dispatch.assert_not_called()
        setup=json.loads(sock.send.call_args.args[0])['setup'];self.assertEqual(setup['sessionResumption'],{'handle':'checkpoint'})
        self.assertIn('from Indonesian into English',setup['systemInstruction']['parts'][0]['text'])
        call.stop();self.assertIsNone(call.resume_handle)

if __name__=='__main__':unittest.main()
