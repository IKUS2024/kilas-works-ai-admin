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
        cls.db.execute('CREATE TABLE subscriptions(business_id INTEGER PRIMARY KEY,status TEXT)')
    tearDown = phase1.RouteTests.tearDown

    def setUp(self):
        with store.transaction() as tx:
            for table in ('kw_web_messages','kw_web_events','kw_web_conversations','kw_web_channels','kw_web_limits'):
                tx.execute('DELETE FROM '+table)
        phase1.RouteTests.setUp(self)
        self.db.get_connection().set_authorizer(None)
        self.db.execute('DELETE FROM subscriptions')
        self.db.execute("INSERT INTO subscriptions VALUES (7,'ACTIVE'),(8,'ACTIVE')")
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
                                         headers={'X-CSRF-Token':'csrf-test'}).status_code,200)

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

    def test_owner_inbox_scoping_and_no_whatsapp_handler(self):
        identity=self.start().json;cid=identity['conversation_id']
        with patch.object(self.ai,'_call_claude',return_value=('Reply','end_turn',None)):
            self.send(identity)
        with patch('inbox_service.list_conversations',side_effect=AssertionError('No WhatsApp reads')) as wa:
            page=self.client.get(f'/business/7/inbox?channel=web&conversation={cid}')
        self.assertEqual(page.status_code,200);self.assertIn(b'WEB',page.data);wa.assert_not_called()
        self.assertEqual(self.client.get(f'/business/8/inbox?channel=web&conversation={cid}').status_code,404)
        self.assertEqual(self.client.get(f'/business/8/web-inbox/{cid}/messages').status_code,404)
        with self.client.session_transaction() as session: session['user_id']=2
        self.assertEqual(self.client.get('/business/7/inbox?channel=web').status_code,404)
        self.assertEqual(self.client.get(f'/business/7/web-inbox/{cid}/messages').status_code,404)

    def test_legacy_whatsapp_view_still_uses_original_service(self):
        with patch('inbox_service.list_conversations',return_value=[]) as wa:
            response=self.client.get('/business/7/inbox')
        self.assertEqual(response.status_code,200)
        wa.assert_called_once_with(7,search='',mode_filter=None)

    def owner_post(self,cid,action,payload,bid=7):
        return self.client.post(f'/business/{bid}/web-inbox/{cid}/{action}',json=payload,headers={'X-CSRF-Token':'csrf-test'})

    def test_human_takeover_reply_return_and_customer_delivery(self):
        identity=self.start().json;cid=identity['conversation_id']
        self.assertEqual(self.owner_post(cid,'reply',{'event_id':'human-00000000001','message':'Hello'}).status_code,409)
        self.assertEqual(self.owner_post(cid,'mode',{'mode':'HUMAN_TAKEOVER'}).status_code,200)
        with patch.object(self.ai,'_call_claude') as model, patch('inbox_service.send_manual_reply') as wa:
            self.assertEqual(self.send(identity).status_code,200)
            first=self.owner_post(cid,'reply',{'event_id':'human-00000000001','message':'Balasan tim'})
            second=self.owner_post(cid,'reply',{'event_id':'human-00000000001','message':'Balasan tim'})
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json)
        model.assert_not_called();wa.assert_not_called()
        delivered=self.visitor.get(f'/chat/{self.slug}/{cid}/messages').json
        self.assertEqual([r['role'] for r in delivered['messages']],['user','human'])
        self.assertEqual(self.owner_post(cid,'reply',{'event_id':'human-00000000001','message':'x'},bid=8).status_code,404)
        self.assertEqual(self.owner_post(cid,'mode',{'mode':'AI_ACTIVE'}).status_code,200)
        with patch.object(self.ai,'_call_claude',return_value=('AI lagi','end_turn',None)) as model:
            self.assertEqual(self.send(identity,event='event-00000000002').status_code,200)
        model.assert_called_once()

    def test_inflight_takeover_fences_ai_even_after_return(self):
        identity=self.start().json;cid=identity['conversation_id']
        def model(*args,**kwargs):
            self.owner_post(cid,'mode',{'mode':'HUMAN_TAKEOVER'})
            self.owner_post(cid,'mode',{'mode':'AI_ACTIVE'})
            return 'Stale AI must not appear','end_turn',None
        with patch.object(self.ai,'_call_claude',side_effect=model): self.send(identity)
        self.assertEqual([r['role'] for r in store.thread(7,cid)],['user'])

    def test_paid_runtime_gate_is_separate_and_fails_closed(self):
        with patch('subscription_service.get_subscription',return_value=None):
            self.assertEqual(self.visitor.get('/chat/'+self.slug).status_code,404)
        with patch('subscription_service.get_subscription',side_effect=RuntimeError('DB unavailable')):
            self.assertEqual(self.start().status_code,404)
        for state,code in [('ACTIVE',200),('GRACE',200),('SUSPENDED',404),('CANCELLED',404)]:
            self.db.execute('UPDATE subscriptions SET status=? WHERE business_id=7',(state,))
            self.assertEqual(self.visitor.get('/chat/'+self.slug).status_code,code)

    def test_web_has_no_finance_or_whatsapp_write_capability(self):
        import sqlite3
        from contextlib import ExitStack
        denied=[]
        def authorize(action,table,*args):
            if action in (sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE):
                if not (table.startswith('kw_web_') or table in ('audit_log','sqlite_sequence','ai_usage_ledger')):
                    denied.append(table);return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        connect=sqlite3.connect
        def guarded(*args,**kwargs):
            connection=connect(*args,**kwargs);connection.set_authorizer(authorize);return connection
        self.db.get_connection().set_authorizer(authorize)
        try:
            with ExitStack() as stack:
                stack.enter_context(patch('sqlite3.connect',side_effect=guarded))
                spies=[stack.enter_context(patch.object(self.finance,name)) for name in
                       ('create_transaction','create_finance_invoice','record_invoice_payment')]
                spies.append(stack.enter_context(patch('inbox_service.send_manual_reply')))
                stack.enter_context(patch.object(self.ai,'_call_claude',return_value=(
                    '[SEND_WHATSAPP] [CREATE_JOB] [PAYMENT]', 'end_turn', None)))
                identity=self.start().json
                self.assertEqual(self.send(identity).status_code,200)
                cid=identity['conversation_id']
                self.assertEqual(self.owner_post(cid,'mode',{'mode':'HUMAN_TAKEOVER'}).status_code,200)
                self.assertEqual(self.owner_post(cid,'reply',{'event_id':'human-00000000001','message':'Hi'}).status_code,200)
                for spy in spies: spy.assert_not_called()
            self.assertEqual(denied,[])
        finally: self.db.get_connection().set_authorizer(None)

    def test_share_controls_scoped_csrf_and_stable_server_slug(self):
        path='/business/7/web-chat/link'
        headers={'X-CSRF-Token':'csrf-test'}
        self.assertEqual(self.client.post(path,json={}).status_code,400)
        first=self.client.post(path,json={'business_id':8},headers=headers)
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.json,{'channel':'WEB','path':'/chat/'+self.slug})
        self.assertEqual(self.client.post(path,json={},headers=headers).json,first.json)
        page=self.client.get('/business/7/inbox?channel=web')
        self.assertIn(b'Copy public chat link',page.data)
        self.assertIn(b'Open as customer',page.data)
        with self.client.session_transaction() as session: session['user_id']=2
        self.assertEqual(self.client.post(path,json={},headers=headers).status_code,404)
        self.assertIn(self.visitor.post(path,json={},headers=headers).status_code,(302,400))

    def test_share_disabled_unconfigured_and_flag_off(self):
        path='/business/7/web-chat/link';headers={'X-CSRF-Token':'csrf-test'}
        with store.transaction() as tx:
            tx.execute('UPDATE kw_web_channels SET enabled=0 WHERE business_id=7')
        self.assertEqual(self.client.post(path,json={},headers=headers).status_code,409)
        self.db.execute("UPDATE ai_settings SET normalized_config_json='{}' WHERE business_id=7")
        self.assertEqual(self.client.post(path,json={},headers=headers).json['error'],'business_setup_required')
        with patch.dict(os.environ,{'KILAS_WEB_CHAT_ENABLED':'false'}):
            self.assertEqual(self.client.post(path,json={},headers=headers).status_code,404)
            with patch('inbox_service.list_conversations',return_value=[]):
                self.assertNotIn(b'Copy public chat link',self.client.get('/business/7/inbox').data)

    def test_public_page_mobile_safe_and_separate_from_owner(self):
        self.db.execute("UPDATE businesses SET business_name='<script>unsafe</script>' WHERE id=7")
        response=self.visitor.get('/chat/'+self.slug)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'width=device-width',response.data)
        self.assertIn(b'public_web_chat.js',response.data)
        self.assertIn(b'&lt;script&gt;unsafe&lt;/script&gt;',response.data)
        self.assertNotIn(b'<script>unsafe</script>',response.data)
        self.assertNotIn(b'Logout',response.data)
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])


if __name__=='__main__': unittest.main()
