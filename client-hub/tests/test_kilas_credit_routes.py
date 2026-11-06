"""Authenticated manual credit routes; temporary DB and synthetic proof only."""
import io
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_ai_single_plan_console as fixture
from kilas_ai import credit_wallet_schema as schema, usage, credit_wallet as wallet


class CreditRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SinglePlanConsoleTests.setUpClass()
        cls.app=fixture.SinglePlanConsoleTests.app
        cls.owner=fixture.SinglePlanConsoleTests.owner
        cls.other=fixture.SinglePlanConsoleTests.other
        cls.admin=fixture.SinglePlanConsoleTests.admin
        conn=usage._connect()
        try:schema.apply(conn);conn.commit()
        finally:conn.close()

    def client_for(self,user,role='CLIENT_OWNER'):
        return fixture.SinglePlanConsoleTests.client_for(self,user,role)

    def setUp(self):
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes'})
        self.flags.start()

    def tearDown(self):self.flags.stop()

    def create(self,key):
        c=self.client_for(self.owner)
        response=c.post('/kilas-ai/credits/orders',data={'csrf_token':'console-csrf','acknowledge':'yes','request_key':key})
        self.assertEqual(response.status_code,303)
        return c,response.location.rsplit('/',1)[-1]

    def test_disabled_routes_and_legacy_preview_preserved(self):
        c=self.client_for(self.owner)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            self.assertEqual(c.post('/kilas-ai/credits/orders',data={'csrf_token':'console-csrf'}).status_code,404)
            self.assertIn('subscription-design-preview',c.get('/kilas-ai/usage').get_data(as_text=True))

    def test_csrf_confirmation_and_foreign_order_protection(self):
        c=self.client_for(self.owner)
        self.assertEqual(c.post('/kilas-ai/credits/orders',data={'acknowledge':'yes','request_key':'csrf'}).status_code,400)
        self.assertEqual(c.post('/kilas-ai/credits/orders',data={'csrf_token':'console-csrf','request_key':'ack'}).status_code,400)
        c,ident=self.create('isolated')
        other=self.client_for(self.other)
        self.assertEqual(other.get('/kilas-ai/credits/orders/'+ident).status_code,404)
        self.assertEqual(other.get('/kilas-ai/credits/orders/'+ident+'/proof').status_code,404)
        self.assertEqual(other.post('/kilas-ai/credits/orders/'+ident+'/proof',data={'csrf_token':'console-csrf','proof':(io.BytesIO(b'private'),'p.png')}).status_code,404)

    def test_proof_access_is_private_owner_or_authorized_reviewer(self):
        c,ident=self.create('private-proof')
        before=wallet.balance(self.owner)
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):
            response=c.post('/kilas-ai/credits/orders/'+ident+'/proof',data={'csrf_token':'console-csrf','proof':(io.BytesIO(b'synthetic private receipt'),'proof.png','image/png')})
        self.assertEqual(response.status_code,303)
        self.assertEqual(before,wallet.balance(self.owner))
        for client,path in ((c,'/kilas-ai/credits/orders/'),(self.client_for(self.admin,'KILAS_ADMIN'),'/admin/kilas-ai/credits/orders/')):
            result=client.get(path+ident+'/proof')
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.data,b'synthetic private receipt')
            self.assertIn('no-store',result.headers['Cache-Control'])
            self.assertEqual(result.headers['X-Content-Type-Options'],'nosniff')
            self.assertIn('sandbox',result.headers['Content-Security-Policy'])
        self.assertEqual(self.client_for(self.other).get('/admin/kilas-ai/credits/orders/'+ident+'/proof').status_code,404)
        admin=self.client_for(self.admin,'KILAS_ADMIN')
        response=admin.post('/admin/kilas-ai/credits/orders/'+ident+'/review',data={'csrf_token':'console-csrf','decision':'VERIFIED'})
        self.assertEqual(response.status_code,400)
        for _ in range(2):
            response=admin.post('/admin/kilas-ai/credits/orders/'+ident+'/review',data={'csrf_token':'console-csrf','decision':'VERIFIED','transfer_reference':'TEST-TX-'+ident})
            self.assertEqual(response.status_code,303)
        self.assertEqual(wallet.balance(self.owner)['balance_milli']-before['balance_milli'],2000000)

    def test_localized_payment_routes_keep_active_plan(self):
        c,ident=self.create('languages')
        for lang,heading in [('en','Credit &amp; Usage'),('id','Kredit &amp; Penggunaan'),('es','Créditos y uso'),('zh','积分与用量')]:
            c.set_cookie('kilas_language',lang)
            for path in ('/kilas-ai/usage','/kilas-ai/credits/orders/'+ident):
                response=c.get(path)
                self.assertEqual(response.status_code,200)
                self.assertIn(heading,response.get_data(as_text=True))
                self.assertNotIn('Preview only',response.get_data(as_text=True))

    def test_actual_usage_admission_and_terminal_retry_do_not_redispatch(self):
        flags={'KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'CHAT':{'milli':1000,'units':1}},'limits':{'CHAT':{'models':['gpt-6-luna'],'input_tokens':100,'output_tokens':100}}})}
        profile={'model':'gpt-6-luna','input_token_bound':32,'output_tokens':32,'credit_fingerprint':'a'*64}
        with patch.dict(os.environ,flags):
            _,ops=usage.reserve(self.other,None,'wallet-real-usage','FAST','CHAT',profile=profile)
            self.assertEqual(ops,('CHAT',))
            usage.finish(self.other,'wallet-real-usage',ops,success=True,model='gpt-6-luna',provider='openai',usage={'input_tokens':1,'output_tokens':2})
            self.assertEqual(usage.reserve(self.other,None,'wallet-real-usage','FAST','CHAT',profile=profile),(None,()))
            with self.assertRaises(usage.UsageLimit):usage.reserve(self.other,None,'wallet-real-usage','FAST','CHAT',profile={**profile,'credit_fingerprint':'b'*64})

if __name__=='__main__':unittest.main()
