"""Transport recovery uses synthetic sockets, existing capabilities and no paid IO."""
import unittest
import json
from uuid import uuid4
from unittest.mock import Mock, patch
import test_kilas_ai_call as fixture
from kilas_ai import ai_call as calls

class RecoveryTests(unittest.TestCase):
    def make(self):
        call=calls.Call(1,'a'*32,object(),settings={'mode':'learning','target_language':'ja'})
        call.check=Mock();call.transport_check=Mock();call.ws=Mock()
        return call

    def test_lost_ack_is_idempotent_and_changed_or_old_payload_rejected(self):
        call=self.make();raw=b'\x01\x00'*100
        call.accept(0,raw);call.accept(0,raw)
        self.assertEqual(call.expected,1);self.assertEqual(call.input_bytes,len(raw));self.assertEqual(call.queue.qsize(),1)
        with self.assertRaises(calls.CallError):call.accept(0,b'\x02\x00'*100)
        call.accept(1,raw)
        with self.assertRaises(calls.CallError):call.accept(0,raw)

    def test_checkpoint_transport_recovery_retains_mode_and_capability_no_replay(self):
        call=self.make();capability=call.capability
        call.receive(json.dumps({'sessionResumptionUpdate':{'resumable':True,'newHandle':'checkpoint'}}))
        call.recover_transport();self.assertEqual(call.state,'RECONNECTING')
        self.assertFalse(call.public_search.closed);self.assertEqual(call.frames[-1]['type'],'reset');self.assertTrue(call.renewing.is_set())
        socket=Mock();socket.recv.return_value='{"setupComplete":{}}'
        with patch.object(calls.wire,'connect',side_effect=[OSError('offline'),socket]) as connect,patch.object(calls.budget,'claim') as claim,patch.object(calls.budget,'dispatch') as dispatch:
            call.resume()
        self.assertEqual(connect.call_count,2);claim.assert_not_called();dispatch.assert_not_called()
        self.assertIs(call.capability,capability);self.assertEqual(call.state,'LISTENING')
        payload=json.loads(socket.send.call_args.args[0]);self.assertEqual(payload['setup']['sessionResumption'],{'handle':'checkpoint'})
        self.assertIn('Japanese',payload['setup']['systemInstruction']['parts'][0]['text'])
        self.assertEqual(socket.send.call_count,1)

    def test_worker_resumes_socket_loss_without_repeating_budget_dispatch(self):
        call=self.make();first=Mock();second=Mock()
        first.recv.side_effect=['{"setupComplete":{}}','{"sessionResumptionUpdate":{"resumable":true,"newHandle":"checkpoint"}}',OSError('lost socket')]
        def finish():call.closed.set();return '{}'
        events=iter(['{"setupComplete":{}}',None])
        second.recv.side_effect=lambda:next(events) or finish()
        with patch.object(calls.wire,'connect',side_effect=[first,second]) as connect,patch.object(calls.budget,'dispatch') as dispatch,patch.object(calls.budget,'finish'),patch.object(calls.Thread,'start'),patch.object(calls,'Timer'),patch.object(calls.db,'_discard_cached_connection'),patch('builtins.print'):
            call.run()
        self.assertEqual(connect.call_count,2);self.assertEqual(dispatch.call_count,1)
        self.assertEqual(call.recovery_count,1);self.assertEqual(second.send.call_count,1)
        self.assertEqual(json.loads(second.send.call_args.args[0])['setup']['sessionResumption'],{'handle':'checkpoint'})

    def test_no_checkpoint_or_revoked_checkpoint_never_reconnects(self):
        for revoke in (False,True):
            call=self.make()
            if revoke:
                call.receive('{"sessionResumptionUpdate":{"resumable":true,"newHandle":"old"}}')
                call.receive('{"sessionResumptionUpdate":{"resumable":false}}')
            with patch.object(calls.wire,'connect') as connect,self.assertRaises(calls.CallError) as error:call.recover_transport()
            self.assertEqual(error.exception.code,'call_provider_disconnected');connect.assert_not_called()

    def test_recovery_rate_is_bounded_and_end_cancels_backoff(self):
        call=self.make()
        for _ in range(2):
            call.resume_handle='checkpoint';call.resume_pending=False;call.recover_transport()
        call.resume_handle='checkpoint';call.resume_pending=False
        with self.assertRaises(calls.CallError):call.recover_transport()
        call=self.make();call.resume_handle='checkpoint';call.recover_transport()
        def unavailable():call.closed.set();raise OSError('offline')
        with patch.object(calls.wire,'connect',side_effect=unavailable) as connect,self.assertRaises(calls.CallError):call.resume()
        self.assertEqual(connect.call_count,1)

    def test_uncertain_setup_is_not_retried_and_late_end_never_sends(self):
        call=self.make();call.resume_handle='checkpoint';call.recover_transport()
        socket=Mock();socket.send.side_effect=OSError('uncertain')
        with patch.object(calls.wire,'connect',return_value=socket) as connect,self.assertRaises(OSError):call.resume()
        self.assertEqual(connect.call_count,1)
        call=self.make();call.resume_handle='checkpoint';call.recover_transport()
        socket=Mock()
        def late():call.closed.set();return socket
        with patch.object(calls.wire,'connect',side_effect=late),self.assertRaises(calls.CallError):call.resume()
        socket.send.assert_not_called();socket.shutdown.assert_called_once()

    def test_deliberate_end_and_client_fault_have_distinct_allowlisted_reasons(self):
        for reason,expected in [('call_ended','call_ended'),('request_timeout','request_timeout'),('private transcript','call_transport')]:
            call=self.make()
            with patch.dict(calls._calls,{(1,call.ident):call}),patch.object(calls.budget,'end'),patch.object(calls,'Timer'):
                calls.end(1,call.ident,reason)
            self.assertEqual(call.code,expected);self.assertTrue(call.closed.is_set());self.assertIsNone(call.resume_handle)

class AccessTests(unittest.TestCase):
    setUp=fixture.CallTests.setUp
    config=fixture.CallTests.config
    shared=fixture.CallTests.shared
    lifetime=fixture.CallTests.lifetime
    enabled=fixture.CallTests.enabled
    login_other=fixture.CallTests.login_other

    def test_authenticated_role_matrix_and_anonymous_denial(self):
        with self.enabled(),patch.object(calls.Thread,'start'),patch.object(calls.wire,'connect') as connect:
            for role in ('CLIENT_MEMBER','KILAS_ADMIN','MEMBER'):
                self.login_other(role);ident=uuid4().hex
                self.assertEqual(self.client.get('/kilas-ai/call').status_code,200)
                self.assertEqual(self.client.get('/kilas-ai/threads/999999').status_code,404)
                response=self.client.post('/kilas-ai/call/'+ident,headers={'X-CSRF-Token':'audio-csrf'},data={'settings':json.dumps({'mode':'learning'})})
                self.assertEqual(response.status_code,202,(role,response.json))
                calls.end(self.other,ident);calls._calls.pop((self.other,ident),None)
            with self.client.session_transaction() as session:session.clear()
            self.assertNotEqual(self.client.post('/kilas-ai/call/'+uuid4().hex).status_code,202)
            connect.assert_not_called()

    def test_each_eligible_account_can_admit_with_mode_but_cannot_access_other_call(self):
        with self.enabled(),patch.object(calls.Thread,'start'):
            for owner,ident in [(self.user,uuid4().hex),(self.other,uuid4().hex)]:
                call=calls.start(owner,ident,{'mode':'learning','target_language':'en'})
                try:
                    self.assertEqual(call.owner,owner);self.assertEqual(call.settings['mode'],'learning')
                    other=self.other if owner==self.user else self.user
                    with self.assertRaises(calls.CallError):calls.get(other,ident)
                finally:calls.end(owner,ident);calls._calls.pop((owner,ident),None)

if __name__=='__main__':unittest.main()
