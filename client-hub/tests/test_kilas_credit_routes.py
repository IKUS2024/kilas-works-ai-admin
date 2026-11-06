"""Authenticated manual credit routes; temporary DB and synthetic proof only."""
import io
import json
import os
import unittest
from unittest.mock import patch
import test_kilas_ai_single_plan_console as fixture
from kilas_ai import credit_wallet_schema as schema, usage, credit_wallet as wallet
from kilas_ai import credit_policy as policy


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

    def test_voice_route_consent_then_exactly_one_synthetic_dispatch(self):
        from test_kilas_credit_adapters import TARIFFS
        from kilas_ai import audio_provider, audio_service, audio_store
        ident=wallet.create_purchase(self.other,'route-voice-fund')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):
            wallet.submit_proof(self.other,ident,__import__('werkzeug.datastructures',fromlist=['FileStorage']).FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,self.admin,'VERIFIED',transfer_reference='TEST-ROUTE-VOICE')
        client=self.client_for(self.other)
        form={'csrf_token':'console-csrf','operation_key':'route-voice-credit-test','mode':'voiceover','language':'en','voice':'syntheticVoice123','script':'Synthetic speech'}
        with patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)}),patch.object(audio_provider,'configured',return_value=True),patch.object(audio_provider,'voices',return_value=[{'id':'syntheticVoice123','name':'Synthetic'}]),patch.object(audio_service,'estimate',return_value=(30,90)),patch.object(audio_service,'submit') as dispatch:
            result=client.post('/kilas-translator/jobs',data=form)
            self.assertEqual(result.status_code,402,result.data)
            self.assertEqual(dispatch.call_count,0)
            target=result.json['credit_consent_url']
            self.assertEqual(self.client_for(self.owner).get(target).status_code,404)
            for lang,label in [('en','Approve credit use'),('id','Setujui pemakaian kredit'),('es','Aprobar uso de créditos'),('zh','批准使用积分')]:
                client.set_cookie('kilas_language',lang)
                response=client.get(target)
                self.assertEqual(response.status_code,200,response.data)
                self.assertIn(label,response.text)
            self.assertEqual(client.post(target,data={'decision':'approve'}).status_code,400)
            self.assertEqual(client.post(target,data={'csrf_token':'console-csrf','decision':'approve'}).status_code,200)
            token=target.rsplit('/',1)[-1]
            header={'X-Kilas-Credit-Consent':token}
            # Even a valid browser CSRF/session on another account cannot retry
            # an approval obtained on the original account.
            self.assertEqual(self.client_for(self.owner).post('/kilas-translator/jobs',data=form,headers=header).status_code,409)
            self.assertEqual(client.post('/kilas-translator/jobs',data={**form,'operation_key':'another-operation-key'},headers=header).status_code,409)
            self.assertEqual(dispatch.call_count,0)
            result=client.post('/kilas-translator/jobs',data=form)
            self.assertEqual(result.status_code,201,result.data)
            self.assertEqual(dispatch.call_count,1)
            self.assertEqual(client.post('/kilas-translator/jobs',data=form).status_code,200)
            self.assertEqual(dispatch.call_count,1)
            self.assertEqual(client.post('/kilas-translator/jobs',data={**form,'script':'Changed same-price text'}).status_code,409)
            self.assertEqual(dispatch.call_count,1)
            audio_store.fail(self.other,result.json['id'],'synthetic_pre_dispatch')

    def test_receipt_quote_no_provider_before_consent_no_chat_allowance(self):
        import finance_receipts
        from kilas_ai import providers,chat_models
        from test_kilas_credit_adapters import TARIFFS
        # Own synthetic purchase; no real payment or financial data.
        ident=wallet.create_purchase(self.owner,'receipt-route-fund')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):
            wallet.submit_proof(self.owner,ident,__import__('werkzeug.datastructures',fromlist=['FileStorage']).FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,self.admin,'VERIFIED',transfer_reference='TEST-ROUTE-RECEIPT')
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(16,16),'white').save(image,'PNG');image_raw=image.getvalue()
        events=[{'type':'delta','text':json.dumps(finance_receipts.empty_result())},{'type':'usage','input_tokens':10,'output_tokens':10},{'type':'finish','reason':'stop'}]
        with patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)}),patch.object(chat_models,'check',return_value={'available':True,'images':True}),patch.object(finance_receipts.branches,'token_branch',return_value=1),patch.object(providers,'_openai',return_value=iter(events)) as dispatch:
            with self.assertRaises(policy.ConsentRequired) as caught:
                finance_receipts.extract(image_raw,'image/png',None,[],business_id=1,user_id=self.owner)
            self.assertEqual(dispatch.call_count,0)
            token=policy.persist_consent(caught.exception);policy.consent(self.owner,token,True)
            balance_before=wallet.balance(self.owner)['balance_milli']
            result=finance_receipts.extract(image_raw,'image/png',None,[],business_id=1,user_id=self.owner)
            self.assertFalse(result['readable']);self.assertEqual(dispatch.call_count,1)
            self.assertEqual(wallet.balance(self.owner)['balance_milli'],balance_before)
            self.assertEqual(wallet.balance(self.owner)['reserved_milli'],0)
            with self.assertRaisesRegex(finance_receipts.ReceiptError,'already_analyzed'):
                finance_receipts.extract(image_raw,'image/png',None,[],business_id=1,user_id=self.owner)
            self.assertEqual(dispatch.call_count,1)
            with wallet._locked(self.owner) as conn:
                self.assertEqual(policy.remaining_in(conn,self.owner,'CHAT',usage._now()),70)

    def test_activation_retires_only_new_legacy_purchases(self):
        client=self.client_for(self.owner)
        for path in ('/kilas-ai/checkout','/kilas-ai/topups','/kilas-translator/checkout'):
            self.assertEqual(client.post(path,data={'csrf_token':'console-csrf','pack':'MINUTE'}).status_code,410)
        self.assertEqual(client.get('/kilas-ai/usage?view=legacy').status_code,200)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            result=client.post('/kilas-translator/checkout',data={'csrf_token':'console-csrf','pack':'MINUTE'})
            self.assertEqual(result.status_code,303)
        # Existing invoice remains available, even after activating the candidate.
        self.assertEqual(client.get(result.location).status_code,200)

if __name__=='__main__':unittest.main()
