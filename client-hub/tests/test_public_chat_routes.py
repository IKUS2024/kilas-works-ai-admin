"""Real hub anonymous/owner WEB flow on a fresh disposable DB, external calls denied."""
import os
import unittest
from unittest.mock import patch
import test_kilas_core_simulator as phase1


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase1.RouteTests.setUpClass.__func__(cls)
        global schema, store
        from public_chat import schema, store
        schema.apply_schema()
    tearDown = phase1.RouteTests.tearDown

    def setUp(self):
        with store.transaction() as tx:
            for table in ('kw_web_messages','kw_web_events','kw_web_conversations','kw_web_channels','kw_web_limits'):
                tx.execute('DELETE FROM '+table)
        phase1.RouteTests.setUp(self)
        self.db.get_connection().set_authorizer(None)
        self.web_flag = patch.dict(os.environ, {'KILAS_WEB_CHAT_ENABLED':'true'})
        self.web_flag.start(); self.addCleanup(self.web_flag.stop)
        self.slug = store.ensure_channel(7)['slug']
        self.other_slug = store.ensure_channel(8)['slug']
        self.visitor = self.app.test_client()
        self.headers = {'Origin':'http://localhost','X-Web-Chat':'1'}

    def start(self, slug=None, client=None):
        return (client or self.visitor).post('/chat/'+(slug or self.slug)+'/session', json={}, headers=self.headers)

    def test_valid_invalid_disabled_slug_and_rollout(self):
        self.assertEqual(self.visitor.get('/chat/'+self.slug).status_code,200)
        self.assertEqual(self.visitor.get('/chat/unknown').status_code,404)
        with store.transaction() as tx:
            tx.execute('UPDATE kw_web_channels SET enabled=0 WHERE business_id=7')
        self.assertEqual(self.visitor.get('/chat/'+self.slug).status_code,404)
        with patch.dict(os.environ,{'KILAS_WEB_CHAT_ENABLED':'false'}):
            self.assertEqual(self.visitor.get('/chat/'+self.other_slug).status_code,404)

    def test_anonymous_cookie_hash_and_continuity(self):
        first=self.start()
        self.assertEqual(first.status_code,200)
        self.assertIn('HttpOnly',first.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',first.headers['Set-Cookie'])
        self.assertEqual(first.json['channel'],'WEB')
        self.assertEqual(first.json['conversation_id'],self.start().json['conversation_id'])
        self.assertNotIn('visitor_hash',first.json)

    def test_same_origin_required_even_without_login(self):
        for headers in ({}, {'Origin':'https://evil.test','X-Web-Chat':'1'}, {'Origin':'http://localhost'}):
            self.assertEqual(self.visitor.post('/chat/'+self.slug+'/session',json={},headers=headers).status_code,403)

    def test_forged_business_and_conversation_reads_blocked(self):
        cid=self.start().json['conversation_id']
        self.assertEqual(self.visitor.get(f'/chat/{self.slug}/{cid}/messages').status_code,200)
        self.assertEqual(self.visitor.get(f'/chat/{self.other_slug}/{cid}/messages').status_code,404)
        stranger=self.app.test_client()
        self.assertEqual(stranger.get(f'/chat/{self.slug}/{cid}/messages').status_code,404)
        other=self.start(self.other_slug).json['conversation_id']
        self.assertNotEqual(cid,other)

    def test_public_channel_does_not_inherit_owner_finance_session(self):
        with self.client.session_transaction() as session:
            session['active_product']='finance'
        self.assertEqual(self.client.get('/chat/'+self.slug).status_code,200)
        self.assertEqual(self.start(client=self.client).status_code,200)
        self.assertEqual(self.client.post('/business/7/simulate/message',json={'message':'hi'},
                                         headers={'X-CSRF-Token':'csrf-test'}).status_code,303)

    def test_rate_limit_and_no_cache(self):
        for _ in range(30): self.assertEqual(self.start().status_code,200)
        blocked=self.start()
        self.assertEqual(blocked.status_code,429)
        self.assertEqual(blocked.headers['Cache-Control'],'no-store')
        self.assertEqual(blocked.headers['Retry-After'],'60')

    def send(self, identity, text='Halo', event='event-00000000001', slug=None, extra=None):
        payload=dict(message=text,event_id=event)
        payload.update(extra or {})
        return self.visitor.post(f"/chat/{slug or self.slug}/{identity['conversation_id']}/messages",json=payload,
                                 headers={**self.headers,'X-Web-CSRF':identity['csrf']})

    def test_shared_core_actual_provider_and_duplicate(self):
        from kilas_core import service
        identity=self.start().json
        with patch.object(self.ai,'_call_claude',return_value=('Halo dari bisnis 7','end_turn',None)) as model, \
                patch.object(service,'process_message',wraps=service.process_message) as core:
            first=self.send(identity)
            second=self.send(identity)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json)
        model.assert_called_once();core.assert_called_once()
        self.assertEqual(core.call_args.args[0].channel,'web')
        self.assertIn('Tenant 7',model.call_args.args[0])
        rows=store.thread(7,identity['conversation_id'])
        self.assertEqual([r['content'] for r in rows],['Halo','Halo dari bisnis 7'])
        self.assertEqual(self.send(identity,text='Changed').status_code,409)

    def test_provider_failure_and_retry_do_not_duplicate_or_spend_again(self):
        identity=self.start().json
        with patch.object(self.ai,'_call_claude',side_effect=RuntimeError('SECRET')) as model:
            first=self.send(identity);second=self.send(identity)
        self.assertEqual(first.status_code,502);self.assertEqual(first.json,second.json)
        model.assert_called_once()
        self.assertEqual(len(store.thread(7,identity['conversation_id'])),1)
        self.assertNotIn('SECRET',str(first.json))

    def test_write_csrf_and_forged_scope_rejected(self):
        identity=self.start().json
        with patch.object(self.ai,'_call_claude') as model:
            self.assertEqual(self.send(dict(identity,csrf='wrong')).status_code,403)
            self.assertEqual(self.send(identity,slug=self.other_slug).status_code,404)
            self.assertEqual(self.send(identity,extra={'business_id':8}).status_code,400)
            self.assertEqual(self.send(identity,extra={'media':['a.jpg']}).status_code,400)
        model.assert_not_called()
        self.assertEqual(store.thread(7,identity['conversation_id']),[])


if __name__=='__main__': unittest.main()
