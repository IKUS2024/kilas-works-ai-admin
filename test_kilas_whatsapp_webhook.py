"""Exercise the real signed root ingress and batching without live business/network calls."""
import os
import json
import hmac
import hashlib
import unittest
from unittest.mock import patch
os.environ.pop('DATABASE_URL',None)
os.environ.setdefault('WHATSAPP_PHONE_NUMBER_ID','123')
os.environ.setdefault('WHATSAPP_ACCESS_TOKEN','synthetic-platform')
os.environ.setdefault('ANTHROPIC_API_KEY','synthetic')
import _test_bootstrap
import app as bot
from kilas_core import whatsapp_access
from kilas_core.adapters import whatsapp


class IngressTests(unittest.TestCase):
    def setUp(self):
        self.client=bot.app.test_client()
        self.flags=patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'synthetic-signing'})
        self.flags.start();self.addCleanup(self.flags.stop)

    def post(self,data,valid=True):
        body=json.dumps(data).encode()
        signature='sha256='+hmac.new(b'synthetic-signing',body,hashlib.sha256).hexdigest()
        return self.client.post('/webhook',data=body,content_type='application/json',headers={'X-Hub-Signature-256':signature if valid else 'bad'})

    def data(self):
        return {'entry':[{'id':'test-waba','changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'77777'},'messages':[{'id':'a'},{'id':'b'}]}}, {'field':'messages','value':{'metadata':{'phone_number_id':'88888'},'statuses':[{'id':'out','status':'read'}]}}]}]}

    def test_signature_invalid_and_valid_batched_channel_dispatch(self):
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',side_effect=lambda pid,waba_id:(7 if pid=='77777' else 8,False)) as resolve,patch.object(whatsapp_access,'selected',return_value={'selected':True}),patch.object(whatsapp,'handle',return_value={'status':'ok'}) as handle,patch.object(bot,'call_claude') as legacy:
            self.assertEqual(self.post(self.data(),False).status_code,403);handle.assert_not_called()
            self.assertEqual(self.post(self.data()).status_code,200)
            self.assertEqual([r.args[:2] for r in handle.call_args_list],[(7,'77777'),(7,'77777'),(8,'88888')])
            self.assertTrue(all(call.args[1]=='test-waba' for call in resolve.call_args_list))
            legacy.assert_not_called()
            self.assertEqual(bot._active_whatsapp_phone_number_id(),bot.WHATSAPP_PHONE_NUMBER_ID)

    def test_unknown_and_adapter_failure_never_fall_back(self):
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',return_value=(None,True)),patch.object(whatsapp,'handle') as handle:
            self.assertEqual(self.post(self.data()).status_code,200);handle.assert_not_called()
        with patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_resolve_tenant_or_unknown',return_value=(7,False)),patch.object(whatsapp_access,'selected',return_value={'selected':True}),patch.object(whatsapp,'handle',side_effect=RuntimeError('SECRET')),patch.object(bot,'call_claude') as legacy:
            response=self.post(self.data());self.assertEqual(response.status_code,503);self.assertNotIn(b'SECRET',response.data);legacy.assert_not_called()

    def test_health_bridge_is_authenticated_readonly_and_never_returns_secrets(self):
        import assist_connection_transport as transport
        values={'WHATSAPP_ACCESS_TOKEN':'private-wa','OPENAI_API_KEY':'private-openai',
                'ANTHROPIC_API_KEY':'private-claude','WHATSAPP_APP_SECRET':'private-signature',
                'RENDER_GIT_COMMIT':'a'*40,'KILAS_ASSIST_RUNTIME_ENABLED':'true'}
        with patch.object(bot,'INTERNAL_SERVICE_SECRET','private-bridge'),patch.dict(os.environ,values), \
             patch.object(transport.db,'query_one',return_value={'ok':1}) as query, \
             patch.object(transport.requests,'request',side_effect=AssertionError('No external health calls')):
            denied=self.client.post('/internal/assist-connection/health',json={})
            self.assertEqual(denied.status_code,403);query.assert_not_called()
            result=self.client.post('/internal/assist-connection/health',json={},headers={'X-Internal-Service-Secret':'private-bridge'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json,dict(status='ok',commit='a'*40,database=True,
                whatsapp=True,openai=True,claude=True,webhook_signature=True,assist_runtime=True))
            query.assert_called_once_with('SELECT 1 AS ok')
            for value in values.values():
                if value.startswith('private-'):self.assertNotIn(value,result.text)


class DemoChannelIngressTests(IngressTests):
    """Real signed webhook + real session/store/CRM, only provider and send are fake."""
    def setUp(self):
        super().setUp()
        import uuid
        import db, repo, assist_demo, assist_reply
        from public_chat import schema
        from kilas_core import customer_schema, job_schema
        from unittest.mock import Mock
        self.db,self.repo,self.demo=db,repo,assist_demo
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()
        db.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,number TEXT,mode TEXT,role TEXT,content TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE IF NOT EXISTS customer_profiles(number TEXT PRIMARY KEY,name TEXT)')
        self.uid=repo.create_user(uuid.uuid4().hex+'@demo.invalid','not-a-login')
        self.bid=repo.create_business(self.uid,'Bound studio','AI_ADMIN')
        self.phone='14048836437'
        self.suffix=uuid.uuid4().hex
        self.send=Mock(return_value=(True,None))
        self.owner=Mock(side_effect=AssertionError('OWNER path is retired on Demo channel'))
        self.customer=Mock(side_effect=AssertionError('Platform knowledge is forbidden on Demo channel'))
        patches=[patch.object(bot,'ENABLE_MULTI_TENANT',True),patch.object(bot,'_CLIENT_HUB_AVAILABLE',True),
            patch.object(bot,'OWNER_WHATSAPP_NUMBER',self.phone),patch.object(bot,'WHATSAPP_PHONE_NUMBER_ID','123'),
            patch.object(bot,'send_whatsapp_message',self.send),patch.object(bot,'call_claude_owner',self.owner),
            patch.object(bot,'call_claude',self.customer),patch.object(bot,'save_customer_name_to_db'),
            patch.object(assist_demo.assist_journey,'state',return_value=dict(ready=True,connected=False,demo_active=False,paid=True)),
            patch.object(assist_reply,'generate',return_value=('Jawaban studio sendiri.',dict(action=None,job_status=None),{'confidence':90})),
            patch.dict(os.environ,{'KILAS_CUSTOMERS_V2_ENABLED':'true','KILAS_JOBS_V2_ENABLED':'true'})]
        for patcher in patches:patcher.start();self.addCleanup(patcher.stop)
        self.sid,self.marker=self.demo.begin(self.bid,self.uid)

    def demo_data(self,text,ident='a',phone=None,kind='text'):
        msg={'id':ident+self.suffix,'from':phone or self.phone,'type':kind,kind:{'body':text} if kind=='text' else {'id':'synthetic-media','caption':text}}
        return {'entry':[{'id':'demo-waba','changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'123'},'messages':[msg]}}]}]}

    def test_owner_phone_is_always_demo_after_binding(self):
        self.assertTrue(self.post(self.demo_data(self.marker,'bind')).json['demo_processed'])
        self.assertTrue(self.post(self.demo_data('Customer bernama Wilson?','ask')).json['demo_processed'])
        self.assertEqual(self.send.call_args.args,(self.phone,'Jawaban studio sendiri.'))
        self.owner.assert_not_called();self.customer.assert_not_called()
        rows=self.demo.rows(self.bid,self.phone)
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[-1]['content'],'Jawaban studio sendiri.')
        self.assertEqual(self.demo.resolve(self.phone,'hi')['business_id'],self.bid)

    def test_unbound_owner_and_other_phone_get_fixed_instruction_only_once(self):
        self.db.execute('UPDATE kw_assist_demo_sessions SET active=FALSE WHERE sender_phone=?',(self.phone,))
        expected='Untuk mencoba Kilas Assist, buka Demo dari workspace Kilas kamu terlebih dahulu.'
        for phone in (self.phone,'628888777700'):
            data=self.demo_data('Cari customer Wilson dan kirim invoice','unknown-'+phone,phone)
            self.assertTrue(self.post(data).json['demo_workspace_required'])
            self.assertEqual(self.send.call_args.args,(phone,expected))
            before=self.send.call_count
            self.assertEqual(self.post(data).status_code,200)
            self.assertEqual(self.send.call_count,before)
        self.owner.assert_not_called();self.customer.assert_not_called()
        self.assertEqual(self.db.query_all('SELECT * FROM kw_core_customers WHERE business_id=?',(self.bid,)),[])

    def test_demo_service_failure_never_exposes_owner_behavior(self):
        with patch.object(bot,'_CLIENT_HUB_AVAILABLE',False):
            self.assertEqual(self.post(self.demo_data('Wilson','offline')).status_code,503)
        with patch.object(self.demo,'process',side_effect=RuntimeError('private-db-error')):
            reply=self.post(self.demo_data('Wilson','error'))
            self.assertEqual(reply.status_code,503);self.assertNotIn('private-db-error',reply.text)
        self.owner.assert_not_called();self.customer.assert_not_called();self.send.assert_not_called()

    def test_invalid_invitation_and_signature_never_fall_through(self):
        response=self.post(self.demo_data('KWDEMO-'+'0'*24,'invalid'))
        self.assertTrue(response.json['demo_workspace_required'])
        before=self.send.call_count
        self.assertEqual(self.post(self.demo_data(self.marker,'forged'),valid=False).status_code,403)
        self.assertEqual(self.send.call_count,before)
        self.owner.assert_not_called();self.customer.assert_not_called()

    def test_owner_media_is_stored_and_bound_like_any_customer(self):
        self.post(self.demo_data(self.marker,'bind'))
        mid=self.db.insert_returning_id("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer','user','Foto contoh')",(self.phone,))
        with patch.object(bot._inbox_media,'record',return_value={'message_row_id':mid}) as record:
            response=self.post(self.demo_data('Foto contoh','image',kind='image'))
        self.assertTrue(response.json['demo_processed']);record.assert_called_once()
        self.assertTrue(self.demo.message_allowed(self.bid,self.phone,mid))
        self.owner.assert_not_called();self.customer.assert_not_called()


if __name__=='__main__': unittest.main()
