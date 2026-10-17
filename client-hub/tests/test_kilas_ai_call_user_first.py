"""User-requested rollback: no automatic opening, no provider or private IO."""
import json
import unittest
from unittest.mock import Mock,patch
import test_kilas_ai_call as fixture
from kilas_ai import ai_call as calls,ai_call_budget as budget,ai_call_readiness


class UserFirstTests(unittest.TestCase):
    setUp=fixture.CallTests.setUp
    config=fixture.CallTests.config
    shared=fixture.CallTests.shared
    lifetime=fixture.CallTests.lifetime
    enabled=fixture.CallTests.enabled
    make=fixture.CallTests.make
    login_other=fixture.CallTests.login_other

    def test_connected_idle_session_sends_only_setup_and_never_an_opening(self):
        call=calls.Call(self.user,'a'*32,object());call.check=Mock();call.transport_check=Mock()
        sent=[]
        class Socket:
            reads=0
            def send(self,raw):sent.append(json.loads(raw))
            def settimeout(self,value):pass
            def shutdown(self):pass
            def recv(self):
                self.reads+=1
                if self.reads==1:return '{"setupComplete":{}}'
                self_case.assertEqual(len(sent),1)
                self_case.assertIn('setup',sent[0])
                call.stop();return '{}'
        self_case=self
        with self.enabled(),patch.object(calls.wire,'connect',return_value=Socket()),patch.object(calls.Thread,'start'), \
                patch.object(calls,'Timer'),patch.object(calls.budget,'dispatch'),patch.object(calls.budget,'finish'),patch.object(calls.db,'_discard_cached_connection'):
            call.run()
        self.assertEqual(len(sent),1);self.assertNotIn('clientContent',sent[0])

    def test_previous_audio_policy_and_natural_context_policy_without_forced_guidance(self):
        setup=calls.setup()['setup'];prompt=setup['systemInstruction']['parts'][0]['text']
        self.assertEqual(setup['realtimeInputConfig']['activityHandling'],'NO_INTERRUPTION')
        self.assertIn('Wait silently for intelligible speech',prompt)
        self.assertIn('clear, natural short sentences',prompt)
        self.assertIn('Distinguish uncertainty from established knowledge',prompt)
        self.assertIn('details, constraints, decisions and references from earlier turns',prompt)
        self.assertNotIn('APP_CALL_OPENING',prompt)
        self.assertNotIn('guiding question',prompt)

    def test_opening_handshake_and_diagnostic_routes_are_removed_without_admission(self):
        with self.enabled(),patch.object(calls,'start') as start,patch.object(calls.wire,'connect') as connect:
            before=budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n']
            self.assertEqual(self.client.get('/kilas-ai/call/audio-check').status_code,404)
            self.assertEqual(self.client.post('/kilas-ai/call/'+'a'*32+'/ready',json={
                'language':'id','user_started_speaking':False},headers={'X-CSRF-Token':'audio-csrf'}).status_code,404)
            self.assertEqual(budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n'],before)
            start.assert_not_called();connect.assert_not_called()

    def test_release_reports_user_first_and_preserves_capped_search_contract(self):
        with self.enabled(),patch.object(calls.wire,'connect') as connect:
            report=ai_call_readiness.report()
            self.assertEqual(report['conversation_contract'],'user-first-v1')
            self.assertFalse(report['automatic_opening']);self.assertFalse(report['paid_qa'])
            self.assertEqual(report['public_search_contract'],'activity-public-fx-v3-capped-complete')
            self.assertFalse(report['public_search_live_verified']);connect.assert_not_called()


if __name__=='__main__':unittest.main()
