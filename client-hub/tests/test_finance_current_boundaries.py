"""Current free manual Finance and retired provider boundaries; synthetic SQLite only.

These supplement the legacy baseline. They never enable an archived provider,
remove a legacy check, or substitute a test permission for production auth.
"""
import io
import os
import unittest
from unittest.mock import patch

import test_finance_phase2a as fixture
import db
import finance_entitlements as entitlement


class CurrentFinanceBoundaryTests(unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        self.flags=patch.dict(os.environ,{
            'KILAS_FINANCE_BETA':'off', 'KILAS_FINANCE_ACCESS_MODE':'internal_beta',
            'KILAS_FINANCE_ANALYST_ENABLED':'true', 'KILAS_FINANCE_OPERATOR_ENABLED':'true',
            'KILAS_FINANCE_ANALYST_BUSINESS_IDS':str(self.b),
            'KILAS_FINANCE_OPERATOR_BUSINESS_IDS':str(self.b),
            'KILAS_FINANCE_EMERGENCY_DISABLE':'false'})
        self.flags.start();self.addCleanup(self.flags.stop)
        fixture.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        with self.client.session_transaction() as session:
            session['_csrf_token']='current-finance-qa'
        self.headers={'X-CSRF-Token':'current-finance-qa','Accept':'application/json'}

    def snapshot(self):
        return '\n'.join(db.get_connection().iterdump())

    def test_paid_provider_pages_stay_retired_without_database_writes(self):
        before=self.snapshot()
        for tail in ('assistant','analyst','operator','receipts/new','bank-imports'):
            self.assertEqual(self.client.get(self.url+'/'+tail).status_code,404,tail)
        self.assertEqual(self.snapshot(),before)

    def test_paid_provider_commands_stay_retired_even_with_valid_csrf(self):
        before=self.snapshot()
        payload={'text':'catat pengeluaran 125000','confirm':True,'token':'synthetic-forged',
                 'business_id':self.other,'values':{'amount':'125000'}}
        tails=('assistant/message','assistant/review','assistant/confirm',
               'assistant/recognize','assistant/recurring/draft','assistant/recurring/confirm',
               'analyst','operator/preview','operator/confirm')
        for tail in tails:
            endpoint,_=fixture.app.url_map.bind('localhost').match(self.url+'/'+tail,method='POST')
            self.assertTrue(endpoint.startswith('finance.'),tail)
            response=self.client.post(self.url+'/'+tail,json=payload,headers=self.headers)
            self.assertEqual(response.status_code,404,tail)
            self.assertNotIn('synthetic-forged',response.text)
        self.assertEqual(self.snapshot(),before)

    def test_retired_document_uploads_reject_without_retaining_private_input(self):
        before=self.snapshot()
        for tail,field in (('receipts/analyze','receipt'),('bank-imports/analyze','sources'),
                           ('assistant/document','sources')):
            endpoint,_=fixture.app.url_map.bind('localhost').match(self.url+'/'+tail,method='POST')
            self.assertTrue(endpoint.startswith('finance.'),tail)
            response=self.client.post(self.url+'/'+tail,
                data={'csrf_token':'current-finance-qa',
                      field:(io.BytesIO(b'SYNTHETIC_PRIVATE_DOCUMENT'),'synthetic.csv')},
                headers=self.headers)
            self.assertEqual(response.status_code,404,tail)
            self.assertNotIn('SYNTHETIC_PRIVATE_DOCUMENT',response.text)
        self.assertEqual(self.snapshot(),before)

    def test_csrf_and_foreign_membership_remain_authoritative(self):
        before=self.snapshot()
        self.assertEqual(self.client.post(self.url+'/assistant/message',json={'text':'x'}).status_code,400)
        self.assertEqual(self.client.post(f'/business/{self.other}/finance/assistant/message',
                                         json={'text':'x'},headers=self.headers).status_code,404)
        self.assertEqual(self.client.get(f'/business/{self.other}/finance').status_code,404)
        self.assertEqual(fixture.app.test_client().get(self.url).status_code,302)
        self.assertEqual(self.snapshot(),before)

    def test_free_access_preserves_historical_entitlements_and_never_grants_ai(self):
        before=self.snapshot()
        self.assertEqual(entitlement.state(self.b)['status'],'FREE')
        for capability in ('analyst','operator','receipts','bank_import'):
            self.assertFalse(entitlement.capability(self.b,capability))
            with self.assertRaisesRegex(fixture.f.FinanceError,'finance_ai_unavailable'):
                entitlement.require_ai(self.b,self.uid,capability)
        self.assertEqual(self.snapshot(),before)

    def test_manual_cash_entry_remains_exact_and_emergency_veto_writes(self):
        expense=fixture.f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        data=dict(direction='EXPENSE',amount='123.45',account_id=str(self.a),category_id=str(expense),
                  occurred_on='2026-09-17',csrf_token='current-finance-qa')
        response=self.client.post(self.url+'/transactions',data=data)
        self.assertEqual(response.status_code,303)
        rows=fixture.f.list_transactions(self.b,actor_user_id=self.uid)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['amount_minor'],rows[0]['currency']),(12345,'IDR'))
        before=self.snapshot()
        with patch.dict(os.environ,{'KILAS_FINANCE_EMERGENCY_DISABLE':'true'}):
            self.assertEqual(self.client.get(self.url).status_code,200)
            rejected=self.client.post(self.url+'/transactions',data=data)
            self.assertEqual(rejected.status_code,303)
            self.assertIn('finance-subscription',rejected.location)
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
