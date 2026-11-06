"""Inactive receipt charging contract; real Flask DB, synthetic pixels/provider."""
import io
import json
import os
import unittest
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import FileStorage
import test_kilas_credit_routes as fixture
from test_kilas_credit_adapters import TARIFFS
import db
import finance_receipts as receipt
from kilas_ai import credit_policy as policy, credit_wallet as wallet, providers, chat_models


class ReceiptCreditTests(unittest.TestCase):
    setUpClass=classmethod(fixture.CreditRoutesTests.setUpClass.__func__)

    def setUp(self):
        self.user=fixture.fixture.repo.create_user(self.id()+'@example.test','hash')
        tariffs=json.loads(json.dumps(TARIFFS));tariffs['limits']['RECEIPT']['input_tokens']=32000
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_CREDIT_TARIFFS_JSON':json.dumps(tariffs)})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.ready=patch.object(chat_models,'check',return_value={'available':True,'images':True});self.ready.start();self.addCleanup(self.ready.stop)
        self.branch=patch.object(receipt.branches,'token_branch',return_value=1);self.branch.start();self.addCleanup(self.branch.stop)
        ident=wallet.create_purchase(self.user,'synthetic-funding')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):
            wallet.submit_proof(self.user,ident,FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,self.admin,'VERIFIED',transfer_reference='TEST-RECEIPT-'+ident)
        output=io.BytesIO();Image.new('RGB',(16,16),'white').save(output,'PNG');self.raw=output.getvalue()

    def extract(self,categories=None):
        return receipt.extract(self.raw,'image/png',None,categories or [],business_id=1,user_id=self.user)

    def admit(self):
        with self.assertRaises(policy.ConsentRequired) as caught:self.extract()
        token=policy.persist_consent(caught.exception);policy.consent(self.user,token,True)

    def admission(self):
        return db.query_one('SELECT status FROM kilas_credit_admissions WHERE user_id=?',(self.user,))['status']

    @staticmethod
    def events(result):
        return iter([{'type':'delta','text':json.dumps(result)},{'type':'usage','input_tokens':100,'output_tokens':100},{'type':'finish','reason':'stop'}])

    def test_readable_amount_currency_captures_once_inside_actual_payload_bounds(self):
        result={**receipt.empty_result(),'readable':True,'total_minor':10000,'currency':'IDR'}
        with patch.object(providers,'_openai',return_value=self.events(result)) as dispatch:
            self.admit();dispatch.assert_not_called()
            token=db.query_one('SELECT token FROM kilas_credit_consents WHERE user_id=?',(self.user,))['token']
            for lang,copy in [('en','Only a readable receipt'),('id','Kredit hanya dipakai'),('es','Solo se deducen créditos'),('zh','仅对包含金额')]:
                client=fixture.CreditRoutesTests.client_for(self,self.user);client.set_cookie('kilas_language',lang)
                self.assertIn(copy,client.get('/kilas-ai/credits/consent/'+token).text)
            self.assertTrue(self.extract()['readable'])
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            self.assertEqual(self.admission(),'CAPTURED')
            args=dispatch.call_args
            self.assertEqual(args.kwargs['profile']['input_token_bound'],32000)
            self.assertEqual(args.args[2][0]['content'][0]['image_url']['detail'],'high')
            with self.assertRaisesRegex(receipt.ReceiptError,'already_analyzed'):self.extract()
            dispatch.assert_called_once()

    def test_unreadable_or_readable_without_amount_currency_releases_customer_not_provider_usage(self):
        for complete in (False,True):
            self.raw+=b'\0'  # distinct synthetic request identity, still a valid PNG.
            result={**receipt.empty_result(),'readable':complete}
            with patch.object(providers,'_openai',return_value=self.events(result)):
                self.admit();self.extract()
            self.assertEqual(wallet.balance(self.user)['balance_milli'],2000000)
            self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=? AND status='RELEASED'",(self.user,))['n'],2)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND status='COMPLETE' AND input_tokens=100",(self.user,))['n'],2)

    def test_refusal_invalid_json_and_explicit_rejection_release_without_paid_retry(self):
        outcomes=[iter([{'type':'refusal'}]),iter([{'type':'delta','text':'bad json'},{'type':'finish','reason':'stop'}]),iter([{'type':'delta','text':'x'*6001}]),providers.ProviderQuotaError('synthetic rejection')]
        for outcome in outcomes:
            self.raw+=b'\0'
            self.admit()
            with patch.object(providers,'_openai',**({'side_effect':outcome} if isinstance(outcome,Exception) else {'return_value':outcome})) as dispatch:
                with self.assertRaises(receipt.ReceiptError):self.extract()
                with self.assertRaisesRegex(receipt.ReceiptError,'already_analyzed'):self.extract()
                dispatch.assert_called_once()
            self.assertEqual(wallet.balance(self.user)['available_milli'],2000000)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=? AND status='RELEASED'",(self.user,))['n'],4)

    def test_ambiguous_transport_is_not_captured_or_automatically_released(self):
        self.admit()
        with patch.object(providers,'_openai',side_effect=providers.ProviderError('synthetic ambiguous transport')) as dispatch:
            with self.assertRaises(receipt.ReceiptError):self.extract()
            with self.assertRaisesRegex(receipt.ReceiptError,'already_analyzed'):self.extract()
            dispatch.assert_called_once()
        self.assertEqual(wallet.balance(self.user)['balance_milli'],2000000)
        self.assertEqual(wallet.balance(self.user)['reserved_milli'],1000)
        self.assertEqual(self.admission(),'RESERVED')
        row=db.query_one('SELECT operation_key FROM kilas_credit_admissions WHERE user_id=?',(self.user,))
        policy.reconcile(self.user,row['operation_key'],self.admin,'NOT_DELIVERED',0,'synthetic reviewed no-delivery evidence')
        self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)

    def test_image_category_and_unverified_accounting_limits_deny_before_quote_or_dispatch(self):
        with patch.object(providers,'_openai') as dispatch:
            for size in ((2049,1),(16,2049)):
                output=io.BytesIO();Image.new('RGB',size,'white').save(output,'PNG');self.raw=output.getvalue()
                with self.assertRaisesRegex(receipt.ReceiptError,'capacity_unavailable'):self.extract()
            output=io.BytesIO();Image.new('RGB',(16,16),'white').save(output,'PNG');self.raw=output.getvalue()
            with self.assertRaisesRegex(receipt.ReceiptError,'capacity_unavailable'):self.extract(['x']*65)
            with self.assertRaisesRegex(receipt.ReceiptError,'capacity_unavailable'):self.extract(['汉'*160]*64)
            tariffs=json.loads(os.environ['KILAS_CREDIT_TARIFFS_JSON']);del tariffs['limits']['RECEIPT']['input_accounting_verified']
            with patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(tariffs)}):
                with self.assertRaisesRegex(receipt.ReceiptError,'capacity_unavailable'):self.extract()
            dispatch.assert_not_called()
        self.assertEqual(wallet.balance(self.user)['available_milli'],2000000)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=?',(self.user,))['n'],0)

    def test_existing_paid_plan_keeps_its_legacy_receipt_profile_and_accounting(self):
        from datetime import timedelta
        from kilas_ai import usage
        now=usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PRO','ACTIVE',?,?)",(self.user,(now-timedelta(days=1)).isoformat(),(now+timedelta(days=30)).isoformat()))
        image=io.BytesIO();Image.new('RGB',(2049,16),'white').save(image,'PNG');self.raw=image.getvalue()
        with patch.object(providers,'_openai',return_value=self.events(receipt.empty_result())) as dispatch:
            self.extract()
            self.assertEqual(dispatch.call_args.kwargs['profile']['input_token_bound'],200000)
        row=db.query_one('SELECT operation_type FROM kilas_ai_usage WHERE user_id=?',(self.user,))
        self.assertEqual(row['operation_type'],'CHAT')
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=?',(self.user,))['n'],0)
        self.assertEqual(wallet.balance(self.user)['balance_milli'],2000000)


if __name__=='__main__':unittest.main()
