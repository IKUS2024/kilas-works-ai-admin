"""Customer dashboard actions preserve financial history and require ownership + CSRF."""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import test_knowledge_setup_v2 as fixture
import projects_repo as projects
import payment_service as payment
import quotation_service as quotes
import catalog_service as catalog
import wa_checkout

repo, db, hub, security = fixture.repo, fixture.db, fixture.hub, fixture.security

class DashboardCleanupTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.KnowledgeTests();self.base.setUp()
        self.client=self.base.client;self.uid=self.base.uid;self.bid=self.base.bid
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('no API calls'))
        self.network.start();self.addCleanup(self.network.stop)

    def project(self,status='REQUESTED',business=False,title=None):
        pid=projects.create_fixed_price_project(self.bid if business else None,catalog.get_catalog_item('content_basic'),self.uid,draft=True)
        db.execute('UPDATE projects SET title=?,status=?,requirements_json=? WHERE id=?',
                   (title or 'Order '+str(pid),status,json.dumps({'_app_brief':1,'name':'Brand tersimpan','product':'Kopi','platform':'Instagram','location':'Tangerang'}),pid))
        return pid

    def cancel_url(self,pid,business=False):
        return f'/business/{self.bid}/projects/{pid}/cancel' if business else f'/projects/{pid}/cancel'

    def with_payment(self,status='PAYMENT_PENDING',business=False,payment_status='PAYMENT_PENDING'):
        pid=projects.create_fixed_price_project(self.bid if business else None,catalog.get_catalog_item('content_basic'),self.uid)
        iid=payment.checkout(pid,self.bid if business else None,self.uid)
        pay=payment.get_payment_for_invoice(iid)
        db.execute('UPDATE payments SET status=? WHERE id=?',(payment_status,pay['id']))
        db.execute('UPDATE projects SET status=? WHERE id=?',(status,pid))
        return pid,iid,pay['id']

    def test_active_dashboard_excludes_both_history_states_for_both_scopes(self):
        for business in (False,True):
            for status in ('CANCELLED','COMPLETED','REQUESTED','WAITING_FOR_QUOTE','PAID','IN_PROGRESS'):
                self.project(status,business,title=f'Unique-{business}-{status}')
        body=self.client.get('/dashboard').get_data(as_text=True)
        for business in (False,True):
            for status in ('CANCELLED','COMPLETED'):
                self.assertNotIn(f'Unique-{business}-{status}',body)
            for status in ('REQUESTED','WAITING_FOR_QUOTE','PAID','IN_PROGRESS'):
                self.assertIn(f'Unique-{business}-{status}',body)
        self.assertIn('Riwayat Proyek',body)
        history=self.client.get('/projects?view=history').get_data(as_text=True)
        for business in (False,True):
            self.assertIn(f'Unique-{business}-CANCELLED',history)
            self.assertIn(f'Unique-{business}-COMPLETED',history)
            self.assertNotIn(f'Unique-{business}-REQUESTED',history)

    def test_edit_brief_prefills_same_project_without_invoice(self):
        for business in (False,True):
            pid=self.project(business=business)
            body=self.client.get('/dashboard').get_data(as_text=True)
            self.assertIn(f'/projects/{pid}/brief?edit=1',body)
            self.assertIn('Edit Brief',body)
            before=db.query_one('SELECT COUNT(*) AS n FROM projects')['n']
            page=self.client.get(f'/projects/{pid}/brief?edit=1').get_data(as_text=True)
            self.assertIn('Brand tersimpan',page);self.assertIn('Review Order',page)
            self.assertIsNone(payment.get_latest_invoice_for_project(pid))
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM projects')['n'],before)
            values={'name':'Brand baru','product':'Kopi','platform':'Instagram','location':'Tangerang'}
            self.assertEqual(self.client.post(f'/projects/{pid}/brief?edit=1',data={'action':'brief',**values}).status_code,302)
            self.assertEqual(projects.get_project(pid)['requirements']['name'],'Brand baru')
            self.assertEqual(projects.get_project(pid)['status'],'REQUESTED')
            self.assertIsNone(payment.get_latest_invoice_for_project(pid))

    def test_business_safe_cancel_returns_dashboard(self):
        pid=self.project(business=True)
        response=self.client.post(self.cancel_url(pid,True))
        self.assertEqual(response.status_code,302);self.assertEqual(response.location,'/dashboard')
        self.assertEqual(projects.get_project(pid)['status'],'CANCELLED')
        self.assertIn('PROJECT_STATUS_CHANGED',[r['action'] for r in repo.get_project_audit_log(pid)])

    def test_personal_safe_cancel_is_audited_and_idempotent(self):
        pid=self.project()
        self.assertEqual(self.client.post(self.cancel_url(pid)).location,'/dashboard')
        after=repo.get_project_audit_log(pid)
        self.assertIn('PROJECT_STATUS_CHANGED',[r['action'] for r in after])
        self.client.post(self.cancel_url(pid))
        self.assertEqual(repo.get_project_audit_log(pid),after)
        self.assertEqual(projects.get_project(pid)['status'],'CANCELLED')

    def test_cancel_preserves_quote_invoice_payment_and_project_data(self):
        for business in (False,True):
            bid=self.bid if business else None
            pid=projects.create_custom_project(bid,'VIDEO','Historical scope',{'goal':'Film'},None,None,self.uid,catalog_key='custom_video')
            qid=quotes.create_quotation(pid,bid,'Scope','Output',1,1234567,'Notes',self.uid)
            quotes.approve_quotation(qid,bid,self.uid);iid=payment.checkout(pid,bid,self.uid)
            before={table:db.query_all('SELECT * FROM '+table) for table in ('quotations','invoices','payments')}
            original=projects.get_project(pid)
            self.client.post(self.cancel_url(pid,business))
            self.assertEqual(projects.get_project(pid)['status'],'CANCELLED')
            self.assertEqual(projects.get_project(pid)['requirements'],original['requirements'])
            self.assertEqual(projects.get_project(pid)['final_price'],original['final_price'])
            for table,rows in before.items():self.assertEqual(db.query_all('SELECT * FROM '+table),rows)

    def test_under_review_blocks_every_otherwise_safe_status(self):
        for business in (False,True):
            for status in ('REQUESTED','WAITING_FOR_QUOTE','APPROVED','PAYMENT_PENDING'):
                with self.subTest(business=business,status=status):
                    pid,_,_=self.with_payment(status,business,'UNDER_REVIEW')
                    self.assertFalse(projects.customer_can_cancel(projects.get_project(pid)))
                    self.client.post(self.cancel_url(pid,business))
                    self.assertEqual(projects.get_project(pid)['status'],status)
                    self.assertNotIn(self.cancel_url(pid,business),self.client.get('/dashboard').get_data(as_text=True))

    def test_verified_payment_cannot_cancel_even_in_inconsistent_project_state(self):
        for business in (False,True):
            for status in ('REQUESTED','WAITING_FOR_QUOTE','APPROVED','PAYMENT_PENDING'):
                pid,_,_=self.with_payment(status,business,'VERIFIED')
                self.client.post(self.cancel_url(pid,business))
                self.assertEqual(projects.get_project(pid)['status'],status)

    def test_paid_progress_history_and_unknown_project_states_cannot_cancel(self):
        for business in (False,True):
            for status in ('PAID','IN_PROGRESS','COMPLETED','CANCELLED','WAITING_FOR_CLIENT','REVISION','QUOTED'):
                pid=self.project(status,business)
                self.client.post(self.cancel_url(pid,business))
                self.assertEqual(projects.get_project(pid)['status'],status)
                self.assertFalse(projects.customer_can_cancel(projects.get_project(pid)))

    def test_paid_invoice_and_older_verified_payment_block_cancel(self):
        pid,iid,_=self.with_payment()
        db.execute("UPDATE invoices SET status='PAID' WHERE id=?",(iid,))
        self.client.post(self.cancel_url(pid));self.assertEqual(projects.get_project(pid)['status'],'PAYMENT_PENDING')
        db.execute("UPDATE invoices SET status='CANCELLED' WHERE id=?",(iid,))
        db.execute("UPDATE payments SET status='VERIFIED' WHERE invoice_id=?",(iid,))
        payment.checkout(pid,None,self.uid)  # A newer unpaid invoice must not hide verified money.
        self.client.post(self.cancel_url(pid));self.assertEqual(projects.get_project(pid)['status'],'PAYMENT_PENDING')

    def test_pending_and_rejected_payment_can_cancel(self):
        for business in (False,True):
            for status in ('PAYMENT_PENDING','REJECTED'):
                pid,_,_=self.with_payment(business=business,payment_status=status)
                self.client.post(self.cancel_url(pid,business))
                self.assertEqual(projects.get_project(pid)['status'],'CANCELLED')

    def test_other_customer_cannot_read_history_or_cancel(self):
        personal=self.project(title='Private personal');business=self.project(business=True,title='Private business')
        uid=repo.create_user('other-dashboard@test.com',security.hash_password('password123'))
        other=hub.app.test_client()
        with other.session_transaction() as s:s['user_id']=uid
        for url in (self.cancel_url(personal),self.cancel_url(business,True),self.cancel_url(business)):
            self.assertEqual(other.post(url).status_code,404)
        self.client.post(self.cancel_url(personal));self.client.post(self.cancel_url(business,True))
        for view in ('active','history','all'):
            body=other.get('/projects?view='+view).get_data(as_text=True)
            self.assertNotIn('Private personal',body);self.assertNotIn('Private business',body)
        self.assertEqual(other.get('/business/'+str(self.bid)+'/projects?view=history').status_code,404)

    def test_cancelled_visible_in_history_not_active_dashboard(self):
        for business in (False,True):
            pid=self.project(business=business,title='Cancelled-row-'+str(business))
            self.client.post(self.cancel_url(pid,business))
            self.assertNotIn('Cancelled-row-'+str(business),self.client.get('/dashboard').get_data(as_text=True))
            self.assertIn('Cancelled-row-'+str(business),self.client.get('/projects?view=history').get_data(as_text=True))
            self.assertIn('Cancelled-row-'+str(business),self.client.get('/projects?view=all').get_data(as_text=True))
            if business:self.assertIn('Cancelled-row-True',self.client.get(f'/business/{self.bid}/projects?view=history').get_data(as_text=True))

    def test_cancel_requires_login_and_csrf(self):
        pid=self.project()
        self.assertEqual(hub.app.test_client().post(self.cancel_url(pid)).status_code,302)
        business_pid=self.project(business=True)
        with patch.dict(hub.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
            self.assertEqual(self.client.post(self.cancel_url(pid)).status_code,400)
            self.assertEqual(self.client.post(self.cancel_url(business_pid,True)).status_code,400)
        self.assertEqual(projects.get_project(business_pid)['status'],'REQUESTED')
        self.assertEqual(projects.get_project(pid)['status'],'REQUESTED')

    def test_edit_not_offered_or_applied_after_payment(self):
        pid=self.project('IN_PROGRESS')
        self.assertNotIn(f'/projects/{pid}/brief?edit=1',self.client.get('/dashboard').get_data(as_text=True))
        before=projects.get_project(pid)['requirements']
        self.client.post(f'/projects/{pid}/brief?edit=1',data={'action':'brief','name':'Changed'})
        self.assertEqual(projects.get_project(pid)['requirements'],before)

    def test_customer_confirmation_mobile_and_business_cards_unchanged(self):
        self.project()
        body=self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('Batalkan pesanan ini? Riwayat transaksi tetap tersimpan.',body)
        self.assertIn('@media(max-width:680px)',body);self.assertIn('data-label="Proyek"',body)
        self.assertIn('Knowledge Test',body);self.assertIn('Ajari Kilas Brain',body)
        self.assertNotIn('Hapus permanen',body)

    def test_personal_detail_uses_same_policy(self):
        pid,_,payid=self.with_payment()
        self.assertIn(self.cancel_url(pid),self.client.get(f'/projects/{pid}').get_data(as_text=True))
        db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?",(payid,))
        self.assertNotIn(self.cancel_url(pid),self.client.get(f'/projects/{pid}').get_data(as_text=True))

    def test_concurrent_cancels_preserve_one_status_audit(self):
        pid=self.project();barrier=Barrier(2)
        def cancel(_):
            client=hub.app.test_client()
            with client.session_transaction() as s:s['user_id']=self.uid
            try:
                barrier.wait(timeout=5)
                return client.post(self.cancel_url(pid)).status_code
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(list(pool.map(cancel,range(2))),[302,302])
        self.assertEqual(projects.get_project(pid)['status'],'CANCELLED')
        self.assertEqual(len([r for r in repo.get_project_audit_log(pid) if r['action']=='PROJECT_STATUS_CHANGED']),1)

    def test_edit_marker_accepts_jsonb_and_malformed_is_not_editable(self):
        for value in ({'_app_brief':1},'{"_app_brief":1}',b'{"_app_brief":1}'):
            self.assertTrue(projects.is_editable_app_brief({'status':'REQUESTED','requirements_json':value}))
        for value in ('bad json',[],None):
            self.assertFalse(projects.is_editable_app_brief({'status':'REQUESTED','requirements_json':value}))

if __name__=='__main__':unittest.main()
