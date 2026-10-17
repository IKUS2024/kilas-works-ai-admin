"""Call-only browser readiness route: real auth/ownership, no provider IO."""
import unittest
from unittest.mock import patch

import test_kilas_ai_call as fixture
from kilas_ai import ai_call as calls, ai_call_budget as budget, ai_call_readiness


class ReadyRouteTests(unittest.TestCase):
    setUp=fixture.CallTests.setUp
    config=fixture.CallTests.config
    shared=fixture.CallTests.shared
    lifetime=fixture.CallTests.lifetime
    enabled=fixture.CallTests.enabled
    make=fixture.CallTests.make
    login_other=fixture.CallTests.login_other

    def send(self,call,value=None,csrf=True):
        return self.client.post('/kilas-ai/call/'+call.ident+'/ready',json=value or {
            'language':'en','user_started_speaking':False},headers={'X-CSRF-Token':'audio-csrf'} if csrf else {})

    def test_ready_is_csrf_protected_owned_and_never_opens_another_session(self):
        with self.enabled():
            call=self.make()
            with patch.object(call,'client_ready',create=True) as ready,patch.object(calls.wire,'connect') as connect:
                before=budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n']
                self.assertIn(self.send(call,csrf=False).status_code,(400,403))
                ready.assert_not_called()
                for _ in range(2):
                    response=self.send(call)
                    self.assertEqual(response.status_code,200);self.assertTrue(response.json['ready'])
                    self.assertIn('no-store',response.headers['Cache-Control'])
                self.assertEqual(budget.ledger.db.query_one('SELECT COUNT(*) AS n FROM kilas_vo_stt_operations')['n'],before)
                self.login_other('CLIENT_OWNER')
                self.assertEqual(self.send(call).status_code,404)
                self.assertEqual(ready.call_count,2);connect.assert_not_called()

    def test_ready_uses_explicit_ui_cookie_and_passes_only_a_boolean_speech_veto(self):
        with self.enabled():
            call=self.make()
            with patch.object(call,'client_ready',create=True) as ready:
                self.client.set_cookie('kilas_language','id')
                response=self.send(call,{'language':'en','user_started_speaking':True})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json['language'],'id')
                ready.assert_called_once_with('id',user_started_speaking=True)
                for locale in ('en','es','zh'):
                    self.client.set_cookie('kilas_language',locale)
                    self.assertEqual(self.send(call).status_code,200)
                    self.assertEqual(ready.call_args.args,(locale,))

    def test_bad_readiness_cannot_inject_a_prompt_or_dispatch_the_greeting(self):
        with self.enabled():
            call=self.make()
            with patch.object(call,'client_ready',create=True) as ready:
                for value in ({'language':'xx','user_started_speaking':False},
                        {'language':'id','user_started_speaking':'false'},
                        {'language':'id','user_started_speaking':0},
                        {'language':['id'],'user_started_speaking':False},
                        {'language':'id','user_started_speaking':False,'prompt':'arbitrary instructions'},
                        {'language':'id'}):
                    self.assertEqual(self.send(call,value).status_code,400)
                response=self.client.post('/kilas-ai/call/'+call.ident+'/ready',data='{}',
                    headers={'X-CSRF-Token':'audio-csrf'})
                self.assertEqual(response.status_code,400);ready.assert_not_called()

    def test_ready_after_end_cannot_reopen_provider_or_reserve_usage(self):
        with self.enabled():
            call=self.make();calls.end(call.owner,call.ident)
            with patch.object(call,'client_ready',side_effect=calls.CallError('call_ended',409),create=True), \
                    patch.object(calls.wire,'connect') as connect:
                self.assertEqual(self.send(call).status_code,409);connect.assert_not_called()

    def test_release_readiness_reports_configuration_without_claiming_spoken_validation(self):
        with self.enabled(),patch.object(calls.wire,'connect') as connect:
            report=ai_call_readiness.report()
            self.assertEqual(report['conversation_contract'],'ready-once-guidance-v1')
            self.assertTrue(report['barge_in_configured'])
            self.assertFalse(report['opening_live_verified'])
            self.assertFalse(report['barge_in_live_verified'])
            self.assertEqual(report['public_search_contract'],'activity-public-fx-v3-capped-complete')
            connect.assert_not_called()


if __name__=='__main__':unittest.main()
