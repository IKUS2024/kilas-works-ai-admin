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
            for tail in ('','?view=accounts','?view=transactions','/receivables?section=invoices','/operations','/reports','/invoices/settings','/assistant'):
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

    def test_revoked_finance_access_keeps_core_job_readable_without_leaking_invoice(self):
        self.login()
        fixture.BridgeTests.connect(self)
        fixture.BridgeTests.customer(self)
        result=fixture.BridgeTests.draft(self)
        db.execute('DELETE FROM business_memberships WHERE business_id=? AND user_id=?',(self.target,self.actor))
        page=self.client.get(f'/business/{self.source}/jobs/{self.jid}')
        self.assertEqual(page.status_code,200)
        self.assertNotIn('Buat Invoice',page.text)
        self.assertNotIn(result['invoice']['invoice_number'],page.text)
        self.assertEqual(self.client.get(self.base+'/jobs/'+self.jid).status_code,404)

    def test_deal_full_editor_draft_issue_failure_payment_and_replay(self):
        from kilas_core import jobs
        self.login();fixture.BridgeTests.connect(self)
        db.execute("UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",(self.source,self.jid))
        job=f'/business/{self.source}/jobs/{self.jid}'
        page=self.client.get(job)
        self.assertIn('Tugas manusia · Invoice',page.text)
        csrf=re.search(r'name="csrf_token" value="([^"]*)"',page.text)[1]
        start=self.client.post(self.base+'/jobs/'+self.jid+'/invoice/start',data={'csrf_token':csrf})
        self.assertEqual(start.status_code,303)
        editor_url=start.location
        page=self.client.get(editor_url)
        self.assertEqual(page.status_code,200)
        self.assertIn('invoice-editor-form',page.text)
        self.assertRegex(page.text,r'<select id="customer" name="customer_id" disabled>')
        linked=bridge.customer_links(self.source,self.actor,self.cid)[0]
        customer_id=linked['link']['finance_customer_id'] if 'link' in linked else linked['finance_customer_id']
        data=dict(csrf_token=csrf,submission_key='d'*32,revision='0',customer_id=str(customer_id),
            issue_date='2026-09-01',due_date='2026-09-30',currency='IDR',notes='Job invoice',
            item_description='Photo service',quantity='2',unit_price='500',
            sender_name='Studio',sender_address='Tangerang',sender_phone='628123456789',
            recipient_name='Wilson',payment_method='Transfer',payment_bank='BCA',
            payment_account_number='12345',payment_account_holder='Studio')
        with patch.object(bridge,'attach_existing_invoice',side_effect=bridge.BridgeError('stale_connection',409)):
            self.assertEqual(self.client.post(editor_url,data=data).status_code,400)
        self.assertEqual(len(f.list_finance_invoices(self.target,actor_user_id=self.actor)),0)
        saved=self.client.post(editor_url,data=data)
        self.assertEqual(saved.status_code,303,saved.text)
        self.assertIn(job,saved.location)
        invoice=bridge.read_invoice(self.source,self.actor,self.jid)['invoice']
        self.assertEqual(invoice['total_minor'],100000)
        self.assertEqual(invoice['status'],'DRAFT')
        issued=self.client.post(self.base+'/jobs/'+self.jid+'/invoice/publish',data={'csrf_token':csrf})
        self.assertEqual(issued.status_code,303)
        page=self.client.get(issued.location)
        self.assertIn('conversation_unavailable',page.text)
        self.assertNotIn('Invoice sudah dikirim',page.text)
        self.assertIn('Customer sudah bayar?',page.text)
        options=bridge.payment_options(self.source,self.actor,self.jid)
        payment=dict(csrf_token=csrf,paid_on='2026-09-10',account_id=options['accounts'][0]['id'],
            category_id=options['categories'][0]['id'],note='Received',payment_key='e'*32)
        for _ in range(2):
            self.assertEqual(self.client.post(self.base+'/jobs/'+self.jid+'/invoice/paid',data=payment).status_code,303)
        rows=f.list_transactions(self.target,actor_user_id=self.actor)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['direction'],'INCOME')
        self.assertEqual(rows[0]['source_type'],'FINANCE_INVOICE_PAYMENT')
        self.assertIn('Lunas · pembayaran sudah masuk sebagai pemasukan di Kilas Finance.',self.client.get(job).text)

    def test_platform_admin_job_finance_is_automatic_and_customer_follows_job(self):
        import platform_workspace

        # Reuse the synthetic Core business as the hidden Kilas Works operator scope.
        db.execute("DELETE FROM platform_workspace_scope")
        db.execute(
            "INSERT INTO platform_workspace_scope(singleton,business_id) VALUES (1,?)",
            (self.source,),
        )
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?", (self.actor,))
        db.execute(
            "UPDATE kw_core_jobs SET status='IN_PROGRESS' WHERE business_id=? AND id=?",
            (self.source, self.jid),
        )
        self.login()

        # Merely opening Admin pages must not create Finance state or show the old destination picker.
        settings = self.client.get(self.base)
        self.assertEqual(settings.status_code, 200)
        self.assertIn('Koneksi otomatis', settings.text)
        self.assertNotIn('Pilih tujuan', settings.text)
        self.assertNotIn('Bisnis dan cabang Finance', settings.text)
        self.assertIsNone(bridge.connection(self.source, self.actor))

        customer_page = self.client.get(self.base + '/customers/' + self.cid)
        self.assertEqual(customer_page.status_code, 200)
        self.assertIn('tidak perlu dipilih manual', customer_page.text)
        self.assertNotIn('Pilih Customer Finance', customer_page.text)

        job_url = f'/business/{self.source}/jobs/{self.jid}'
        job_page = self.client.get(job_url)
        self.assertEqual(job_page.status_code, 200)
        self.assertIn('Buat Invoice', job_page.text)
        self.assertNotIn('Hubungkan Kilas Finance', job_page.text)
        self.assertIsNone(bridge.connection(self.source, self.actor))

        csrf = re.search(r'name="csrf_token" value="([^"]*)"', job_page.text)[1]
        started = self.client.post(
            self.base + '/jobs/' + self.jid + '/invoice/start',
            data={'csrf_token': csrf},
        )
        self.assertEqual(started.status_code, 303)
        mapping = bridge.connection(self.source, self.actor)
        self.assertIsNotNone(mapping)
        self.assertTrue(mapping['enabled'])
        self.assertEqual(mapping['finance_business_id'], self.source)
        branch = db.query_one(
            "SELECT * FROM finance_branches WHERE business_id=? AND id=?",
            (self.source, mapping['finance_branch_id']),
        )
        self.assertIsNotNone(branch)
        self.assertTrue(branch['is_active'])

        # The Job's Core Customer is the only source of customer identity; no manual chooser.
        links = bridge.customer_links(self.source, self.actor, self.cid)
        self.assertEqual(len(links), 1)
        linked = links[0]
        linked_customer = linked['customer'] if 'customer' in linked else f.get_customer(
            self.source, linked['finance_customer_id'], actor_user_id=self.actor
        )
        self.assertEqual(linked_customer['name'], 'Wilson')
        self.assertIn(f'/business/{self.source}/finance/invoices/new', started.location)

    def test_protected_boundary_no_direct_finance_writes_or_payment_actions(self):
        root=Path(__file__).resolve().parents[1]/'kilas_core'
        for name in ('finance_bridge.py','finance_bridge_routes.py','finance_bridge_schema.py'):
            text=(root/name).read_text()
            self.assertIsNone(re.search(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+finance_',text,re.I))
            for action in ('create_transaction(', 'record_currency_exchange(', '_insert_transaction('):
                self.assertNotIn(action,text)

if __name__=='__main__':unittest.main()
