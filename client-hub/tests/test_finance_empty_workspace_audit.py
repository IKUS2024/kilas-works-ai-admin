"""Fresh-workspace GET is read-only; populated transfer scope stays enforced."""
import unittest
from flask import template_rendered
import test_finance_approved_revisions as fixture
import finance_service as f
import finance_branches as branches
import db,repo


class EmptyWorkspaceTests(unittest.TestCase):
    setUp=fixture.ApprovedFinanceTests.setUp

    def financial_rows(self):
        names=[r['name'] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'finance_%' ORDER BY name")]
        return {name:db.query_all('SELECT * FROM '+name) for name in names}

    def page(self,business,**query):
        contexts=[]
        def capture(sender,template,context,**kwargs):contexts.append(context)
        with template_rendered.connected_to(capture,fixture.app):
            response=self.client.get(f'/business/{business}/finance',query_string=query)
        return response,contexts[-1] if contexts else {}

    def test_fresh_workspace_repeated_get_renders_onboarding_without_financial_writes(self):
        empty=repo.create_business(self.uid,'Truly fresh workspace')
        for table in ('finance_branches','finance_accounts','finance_transactions'):
            self.assertEqual(db.query_all('SELECT * FROM '+table+' WHERE business_id=?',(empty,)),[])
        before=self.financial_rows()
        for _ in range(2):
            response,context=self.page(empty)
            self.assertEqual(response.status_code,200)
            self.assertIn('Mulai Kilas Finance',response.text)
            self.assertIn(f'action="/business/{empty}/finance/start"',response.text)
            self.assertEqual(context['internal_transfers'],[])
            self.assertEqual(context['finance_branches'],[])
            self.assertEqual(self.financial_rows(),before)

    def test_populated_workspace_still_renders_its_transfer_history(self):
        with branches.scope(self.b,self.branch,self.uid):
            ident=f.record_internal_transfer(self.b,self.a,self.dest,12345,'2026-09-10',actor_user_id=self.uid,idempotency_key='e'*32)
        before=self.financial_rows()
        response,context=self.page(self.b,branch_id=self.branch,view='accounts')
        self.assertEqual(response.status_code,200)
        self.assertEqual([r['id'] for r in context['internal_transfers']],[ident])
        self.assertIn('Synthetic reserve',response.text)
        self.assertIn('123,45',response.text)
        self.assertEqual(self.financial_rows(),before)

    def test_foreign_fresh_workspace_denied_without_financial_writes(self):
        foreign=repo.create_business(self.other_uid,'Foreign fresh workspace')
        before=self.financial_rows()
        response,_=self.page(foreign)
        self.assertEqual(response.status_code,404)
        self.assertNotIn('Mulai Kilas Finance',response.text)
        self.assertEqual(self.financial_rows(),before)

    def test_transfer_service_still_rejects_missing_branch(self):
        before=self.financial_rows()
        with branches.scope(self.b,None,self.uid):
            with self.assertRaisesRegex(f.FinanceError,'branch_unavailable'):
                f.list_internal_transfers(self.b,actor_user_id=self.uid)
            with self.assertRaisesRegex(f.FinanceError,'branch_unavailable'):
                f.record_internal_transfer(self.b,self.a,self.dest,100,'2026-09-10',actor_user_id=self.uid,idempotency_key='d'*32)
        self.assertEqual(self.financial_rows(),before)
