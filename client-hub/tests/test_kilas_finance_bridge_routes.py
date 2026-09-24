"""Real Flask owner forms, CSRF and standalone independence."""
import re
import unittest
from unittest.mock import patch
from pathlib import Path
import os
import test_kilas_finance_bridge as fixture
import db, repo, finance_service as f
from kilas_core import finance_bridge as bridge

class BridgeRoutesTests(unittest.TestCase):
    setUp=fixture.BridgeTests.setUp
    seed_bridge=fixture.BridgeTests.seed_bridge

    def login(self,actor=None):
        with self.client.session_transaction() as session:
            session['user_id']=actor or self.actor
            session['active_product']='brain'
        self.base=f'/business/{self.source}/finance-bridge'
        fixture.fixture.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True

    def form(self,path):
        page=self.client.get(path)
        self.assertEqual(page.status_code,200,page.data[:400])
        self.assertEqual(page.headers['Cache-Control'],'private, no-store')
        return dict(re.findall(r'name="(csrf_token|operation_key|version)" value="([^"]*)"',page.text))

    def test_owner_forms_explicit_mapping_customer_draft_and_readback(self):
        self.login()
        form=dict(self.form(self.base),destination=f'{self.target}:{self.branch}',enabled='yes',confirmed='yes')
        self.assertEqual(self.client.post(self.base,data=form).status_code,303)
        customer=self.base+'/customers/'+self.cid
        form=dict(self.form(customer),customer_choice='new',name='Reviewed name',phone='',email='',confirmed='yes')
        self.assertEqual(self.client.post(customer,data=form).status_code,303)
        job=self.base+'/jobs/'+self.jid
        form=dict(self.form(job),currency='IDR',issue_date='2026-09-01',due_date='2026-09-30',
                  description_0='Owner work',quantity_0='2',price_0='500',confirmed='yes')
        self.assertEqual(self.client.post(job,data=form).status_code,303)
        self.assertEqual(self.client.post(job,data=form).status_code,303)
        result=bridge.read_invoice(self.source,self.actor,self.jid)
        self.assertEqual(result['invoice']['total_minor'],100000)
        self.assertEqual(result['invoice']['status'],'DRAFT')
        page=self.client.get(job)
        self.assertIn(b'Buka invoice di Finance',page.data)
        self.assertEqual(self.client.get(f'/business/{self.source}/jobs/{self.jid}').status_code,200)
        self.assertEqual(self.client.get(f'/business/{self.source}/customers/{self.cid}').status_code,200)

    def test_csrf_payload_limit_owner_confirmation_and_foreign_access(self):
        self.login()
        form=dict(self.form(self.base),destination=f'{self.target}:{self.branch}',enabled='yes',confirmed='yes')
        for change in ({'csrf_token':'bad'},{'confirmed':'no'},{'payment_status':'PAID'},{'destination':f'{self.foreign}:{self.foreign_branch}'}):
            self.assertIn(self.client.post(self.base,data={**form,**change}).status_code,(400,404))
        self.assertEqual(self.client.post(self.base,data={**form,'extra':'x'*25000}).status_code,413)
        self.assertIsNone(bridge.connection(self.source,self.actor))
        self.login(self.foreign_actor)
        for path in (self.base,self.base+'/customers/'+self.cid,self.base+'/jobs/'+self.jid):
            self.assertEqual(self.client.get(path).status_code,404)

    def test_standalone_zero_bridge_rows_no_ai_product_or_flags(self):
        self.login()
        standalone_actor=repo.create_user('finance-only@example.test','unused')
        self.target=repo.create_business(standalone_actor,'Finance only',package='NONE')
        f.ensure_finance_defaults(self.target,actor_user_id=standalone_actor)
        self.actor=standalone_actor
        with self.client.session_transaction() as session:
            session['user_id']=standalone_actor
            session['active_product']='finance'
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM business_memberships WHERE user_id=?',(standalone_actor,))['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kw_core_finance_connections')['n'],0)
        self.assertEqual(db.query_one('SELECT package FROM businesses WHERE id=?',(self.target,))['package'],'NONE')
        with patch.dict(os.environ,{'KILAS_FINANCE_BRIDGE_ENABLED':'false','KILAS_CORE_V2_ENABLED':'false'}):
            for tail in ('','/accounts','/transactions','/categories','/invoices','/operations','/reports','/settings','/assistant'):
                response=self.client.get(f'/business/{self.target}/finance'+tail,follow_redirects=True)
                self.assertEqual(response.status_code,200,(tail,response.status_code))
            customer=f.create_customer(self.target,'Independent',actor_user_id=self.actor)
            invoice=f.create_finance_invoice(self.target,customer,actor_user_id=self.actor,**self.invoice)
            f.issue_finance_invoice(self.target,invoice,actor_user_id=self.actor)
            self.assertEqual(f.get_invoice_totals(self.target,invoice,self.actor)['outstanding_minor'],100000)
            with self.client.session_transaction() as session:session['active_product']='brain'
            self.assertEqual(self.client.get(self.base).status_code,404)
        for table in ('connections','customer_links','invoice_links','operations'):
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kw_core_finance_'+table)['n'],0)

    def test_protected_boundary_no_direct_finance_writes_or_payment_actions(self):
        root=Path(__file__).resolve().parents[1]/'kilas_core'
        for name in ('finance_bridge.py','finance_bridge_routes.py','finance_bridge_schema.py'):
            text=(root/name).read_text()
            self.assertIsNone(re.search(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+finance_',text,re.I))
            for action in ('record_invoice_payment(', 'issue_finance_invoice(', 'record_currency_exchange('):
                self.assertNotIn(action,text)

if __name__=='__main__':unittest.main()
