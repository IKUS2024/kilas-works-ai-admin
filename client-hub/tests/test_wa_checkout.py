import hashlib
import io
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from reportlab.pdfgen import canvas
import test_knowledge_setup_v2 as fixture
import wa_checkout as flow
import payment_service as payment
import quotation_service as quotes
import projects_repo as projects
import catalog_service as catalog
import ai_payment_review

repo,db,hub=fixture.repo,fixture.db,fixture.hub

class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.KnowledgeTests();self.base.setUp()
        self.env=patch.dict(os.environ,{'INTERNAL_SERVICE_SECRET':'x'*48,'PUBLIC_APP_BASE_URL':'https://app.kilasworks.id'})
        self.env.start();self.addCleanup(self.env.stop)
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('no paid API'))
        self.network.start();self.addCleanup(self.network.stop)
        self.client=hub.app.test_client()
        self.phone='6281200000001'

    def start(self,query='Aku mau Content Growth',phone=None):
        flow.intake(phone or self.phone,query)
        return db.query_one('SELECT s.* FROM wa_checkout_sessions s JOIN wa_checkout_customers c ON c.active_session_id=s.session_id WHERE c.phone_hash=?',(flow.sender_hash(phone or self.phone),))

    def open(self,row,client=None):
        client=client or self.client
        client.get('/wa-checkout')
        return client.post('/wa-checkout/access',json={'token':flow.raw_token(row['session_id'])})

    def values(self,row):
        item=catalog.get_catalog_item(row['catalog_key'])
        return {key:(flow.FIELDS[key][1][0] if flow.FIELDS[key][1] else 'Test '+key) for key in flow.fields(item)[0]}

    def submit(self,row):
        self.open(row)
        return self.client.post('/wa-checkout',data=dict(action='brief',**self.values(row)))

    def test_fixed_reuse_and_three_questions_prefill(self):
        row=self.start()
        self.assertEqual(self.start()['project_id'],row['project_id'])
        for answer in ('Kopi Test','Minuman kopi','Instagram'):
            reply=flow.intake(self.phone,answer)
        self.assertIn('/wa-checkout#',reply)
        self.assertEqual(projects.get_project(row['project_id'])['requirements']['name'],'Kopi Test')
        self.assertEqual(projects.get_project(row['project_id'])['status'],'REQUESTED')
        self.open(row)
        page=self.client.get('/wa-checkout').get_data(as_text=True)
        self.assertIn('Kopi Test',page);self.assertIn('Minuman kopi',page)

    def test_explicit_history_prefilled(self):
        reply=flow.intake(self.phone,'mau Content Basic',[{'role':'user','content':'nama: Kopi; produk: Latte; platform: Instagram; lokasi: Tangerang'}])
        self.assertIn('/wa-checkout#',reply)
        row=self.start('mau Content Basic')
        self.assertEqual(projects.get_project(row['project_id'])['requirements']['location'],'Tangerang')

    def test_secure_token_hash_expiry_and_no_login(self):
        row=self.start();raw=flow.raw_token(row['session_id'])
        self.assertNotIn(self.phone,raw);self.assertEqual(row['token_hash'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertNotEqual(row['token_hash'],raw)
        self.assertEqual(self.open(row).status_code,200)
        self.assertEqual(self.client.get('/wa-checkout').status_code,200)
        with self.client.session_transaction() as s:self.assertNotIn('user_id',s)
        db.execute('UPDATE wa_checkout_sessions SET expires_at=0')
        self.assertEqual(self.client.get('/wa-checkout').status_code,410)
        self.assertEqual(self.open(row).status_code,410)

    def test_invalid_and_cross_order_ids(self):
        a=self.start();b=self.start('mau Content Pro','6281200000002')
        self.open(a)
        self.client.post('/wa-checkout',data=dict(action='brief',project_id=b['project_id'],**self.values(a)))
        self.client.post('/wa-checkout',data={'action':'checkout','project_id':b['project_id']})
        self.assertIsNone(payment.get_latest_invoice_for_project(b['project_id']))
        self.assertEqual(projects.get_project(b['project_id'])['status'],'REQUESTED')
        invalid=hub.app.test_client();invalid.get('/wa-checkout')
        self.assertEqual(invalid.post('/wa-checkout/access',json={'token':'a'*90}).status_code,410)

    def test_all_fixed_briefs_before_payment(self):
        for index,name in enumerate(('Content Basic','Landing Page','Company Profile Website','Event Standard','Ads Setup Only','Meta Ads Management')):
            with self.subTest(name=name):
                self.phone='62812000001'+str(index)
                row=self.start('mau '+name)
                self.open(row)
                self.client.post('/wa-checkout',data={'action':'checkout'})
                self.assertIsNone(payment.get_latest_invoice_for_project(row['project_id']))
                self.assertEqual(self.submit(row).status_code,302)
                self.assertIsNone(payment.get_latest_invoice_for_project(row['project_id']))
                self.client.post('/wa-checkout',data={'action':'checkout'})
                inv=payment.get_latest_invoice_for_project(row['project_id'])
                self.assertIsNotNone(inv)
                expected=catalog.get_catalog_item(row['catalog_key'])['price_amount']
                self.assertEqual(inv['amount'],expected)

    def test_ads_setup_included_and_transport_no_addition(self):
        row=self.start('mau Meta Ads Management');self.submit(row)
        page=self.client.get('/wa-checkout').get_data(as_text=True)
        self.assertIn('termasuk setup awal',page);self.assertIn('terpisah',page)
        self.client.post('/wa-checkout',data={'action':'checkout'})
        self.assertEqual(payment.get_latest_invoice_for_project(row['project_id'])['amount'],799000)
        other=self.start('mau Event Premium','6281200000999');self.submit(other)
        self.client.post('/wa-checkout',data={'action':'checkout'})
        self.assertEqual(payment.get_latest_invoice_for_project(other['project_id'])['amount'],4400000)

    def test_custom_quote_approval_payment(self):
        for index,name in enumerate(('Custom Photo','Custom Video','Custom Website','Talent Management')):
            with self.subTest(name=name):
                row=self.start('mau '+name,'62812000002'+str(index));self.submit(row)
                p=projects.get_project(row['project_id'])
                self.assertEqual(p['status'],'WAITING_FOR_QUOTE');self.assertIsNone(p['final_price'])
                self.client.post('/wa-checkout',data={'action':'checkout'})
                self.assertIsNone(payment.get_latest_invoice_for_project(p['id']))
                qid=flow.admin_quote(p['id'],None,scope='Scope',deliverables='Output',quantity=1,final_price=123456,notes='',created_by_user_id=self.base.uid)
                self.assertEqual(flow.admin_quote(p['id'],None,scope='Scope',deliverables='Output',quantity=1,final_price=123456,notes='',created_by_user_id=self.base.uid),qid)
                page=self.client.get('/wa-checkout').get_data(as_text=True);self.assertIn('123.456',page)
                self.assertEqual(self.client.post('/wa-checkout',data={'action':'approve','quotation_id':qid}).status_code,302)
                self.client.post('/wa-checkout',data={'action':'approve','quotation_id':qid})
                self.assertEqual(payment.get_latest_invoice_for_project(p['id'])['amount'],123456)
                self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM invoices WHERE project_id=?',(p['id'],))['n'],1)

    def test_double_submit_checkout_atomic(self):
        row=self.start();self.submit(row)
        def checkout():
            try:
                with db.commerce_transaction(row['phone_hash']):return payment.checkout(row['project_id'],None,None)
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(2) as pool:result=list(pool.map(lambda _:checkout(),range(2)))
        self.assertEqual(result[0],result[1])
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM payments')['n'],1)

    def test_concurrent_intake_reuses_project(self):
        def intake():
            try:return flow.intake(self.phone,'mau Content Growth')
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(2) as pool:list(pool.map(lambda _:intake(),range(2)))
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM wa_checkout_sessions')['n'],1)
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM projects')['n'],1)

    def test_proof_bound_invoice_and_admin_verification(self):
        row=self.start();self.submit(row);self.client.post('/wa-checkout',data={'action':'checkout'})
        b=self.start('mau Content Pro','6281200000998')
        data=io.BytesIO();c=canvas.Canvas(data);c.drawString(40,700,'Proof');c.save()
        with patch.object(ai_payment_review,'extract_payment_proof_fields',side_effect=AssertionError('PDF no AI')):
            response=self.client.post('/wa-checkout',data={'action':'proof','invoice_id':b['project_id'],'proof_file':(io.BytesIO(data.getvalue()),'proof.pdf')})
        self.assertEqual(response.status_code,302)
        inv=payment.get_latest_invoice_for_project(row['project_id']);pay=payment.get_payment_for_invoice(inv['id'])
        self.assertEqual(pay['status'],'UNDER_REVIEW');self.assertEqual(inv['status'],'ISSUED')
        self.assertIsNone(payment.get_latest_invoice_for_project(b['project_id']))
        payment.verify_payment(pay['id'],None,self.base.uid)
        self.assertEqual(payment.get_invoice(inv['id'])['status'],'PAID')
        self.assertIn('telah diverifikasi',self.client.get('/wa-checkout').get_data(as_text=True))

    def test_csrf_and_headers(self):
        row=self.start()
        hub.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        try:
            self.client.get('/wa-checkout')
            self.assertEqual(self.open(row).status_code,400)
            with self.client.session_transaction() as s:csrf=s['_csrf_token']
            self.assertEqual(self.client.post('/wa-checkout/access',json={'token':flow.raw_token(row['session_id'])},headers={'X-CSRF-Token':csrf}).status_code,200)
            self.assertEqual(self.client.post('/wa-checkout',data={'action':'checkout'}).status_code,400)
            response=self.client.get('/wa-checkout')
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
        finally:hub.app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False

    def test_brain_tenant_and_normal_account(self):
        self.assertIsNone(flow.intake(self.phone,'mau Content Growth',tenant=True))
        self.assertIn('Setup Awal',flow.intake(self.phone,'mau Kilas Brain Basic'))
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM wa_checkout_sessions')['n'],0)
        p=projects.create_fixed_price_project(self.base.bid,catalog.get_catalog_item('content_basic'),self.base.uid)
        self.assertIsNotNone(payment.checkout(p,self.base.bid,self.base.uid))

    def test_no_fake_user_or_business_and_safe_attach(self):
        row=self.start()
        self.assertIsNone(projects.get_project(row['project_id'])['business_id'])
        self.assertIsNone(projects.get_project(row['project_id'])['created_by_user_id'])
        self.open(row,self.base.client)
        self.base.client.post('/wa-checkout',data={'action':'attach'})
        self.assertEqual(projects.get_project(row['project_id'])['created_by_user_id'],self.base.uid)

    def test_migration_repeat_preserves_quote_and_invoice(self):
        p=projects.create_custom_project(self.base.bid,'PHOTO','Test',{},None,None,self.base.uid)
        q=quotes.create_quotation(p,self.base.bid,'s','d',1,123,'n',self.base.uid)
        quotes.approve_quotation(q,self.base.bid,self.base.uid)
        inv=payment.checkout(p,self.base.bid,self.base.uid)
        db.init_schema()
        self.assertEqual(quotes.get_quotation(q)['final_price'],123)
        self.assertEqual(payment.get_invoice(inv)['quotation_id'],q)
        self.assertEqual(db.query_all('PRAGMA foreign_key_check'),[])

    def test_natural_explicit_facts_and_active_order_switch(self):
        history=[{'role':'user','content':'Nama brand Kopi Kita. Produk saya minuman kopi. Lokasinya di Tangerang. Untuk Instagram.'}]
        answer=flow.intake(self.phone,'mau Content Growth',history)
        self.assertIn('/wa-checkout#',answer)
        other=self.start('mau Event Standard')
        flow.intake(self.phone,'Pesta kantor')
        self.assertEqual(projects.get_project(other['project_id'])['requirements']['event'],'Pesta kantor')

    def test_expired_quote_and_wrong_quote_cannot_approve(self):
        row=self.start('mau Custom Photo');self.submit(row)
        q=flow.admin_quote(row['project_id'],None,scope='s',deliverables='d',quantity=1,final_price=123,notes='',created_by_user_id=self.base.uid)
        self.client.post('/wa-checkout',data={'action':'approve','quotation_id':q+1})
        self.assertIsNone(payment.get_latest_invoice_for_project(row['project_id']))
        db.execute("UPDATE quotations SET expires_at='2000-01-01 00:00:00' WHERE id=?",(q,))
        self.client.post('/wa-checkout',data={'action':'approve','quotation_id':q})
        self.assertIsNone(payment.get_latest_invoice_for_project(row['project_id']))

    def test_refresh_completion_and_renewal_never_create_order(self):
        row=self.start();self.submit(row);self.client.post('/wa-checkout',data={'action':'checkout'})
        for _ in range(3):self.client.get('/wa-checkout')
        db.execute("UPDATE projects SET status='COMPLETED' WHERE id=?",(row['project_id'],))
        self.assertIn('sudah diproses',flow.intake(self.phone,'mau Content Growth'))
        old=flow.raw_token(row['session_id'])
        new=flow.renew(row['project_id'])
        self.assertNotEqual(flow.raw_token(new['session_id']),old)
        self.assertIsNone(flow.by_hash(flow.digest(old)))
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM projects')['n'],1)
        self.open(new)
        self.assertIn('Project selesai',self.client.get('/wa-checkout').get_data(as_text=True))

    def test_renewed_fragment_can_exchange_after_expired_cookie(self):
        row=self.start();self.open(row)
        flow.renew(row['project_id'])
        response=self.client.get('/wa-checkout')
        self.assertEqual(response.status_code,410)
        self.assertIn(b'wa_checkout.js',response.data)
        renewed=flow.session_for_project(row['project_id'])
        self.assertEqual(self.open(renewed).status_code,200)
        self.assertEqual(self.client.get('/wa-checkout').status_code,200)

    def test_file_scoping_and_rollback(self):
        a=self.start();b=self.start('mau Content Pro','6281200000997')
        fid=db.insert_returning_id("INSERT INTO project_files(project_id,kind,original_filename,mime_type,size_bytes,content) VALUES(?,'REFERENCE','a.pdf','application/pdf',1,?)",(b['project_id'],b'x'))
        self.open(a)
        self.assertEqual(self.client.get('/wa-checkout/file/'+str(fid)).status_code,404)
        with self.assertRaises(ValueError):
            with db.commerce_transaction(a['phone_hash']):
                db.execute("UPDATE projects SET title='Must rollback' WHERE id=?",(a['project_id'],))
                raise ValueError('fail')
        self.assertNotEqual(projects.get_project(a['project_id'])['title'],'Must rollback')

    def test_access_rate_limit_and_normal_checkout_route(self):
        with hub.app.test_request_context('/',environ_base={'REMOTE_ADDR':'127.0.0.1'}):
            fixture.security.clear_login_attempts('wa-checkout-access')
        self.client.get('/wa-checkout')
        for _ in range(10):response=self.client.post('/wa-checkout/access',json={'token':'invalid'})
        self.assertEqual(response.status_code,429)
        with hub.app.test_request_context('/',environ_base={'REMOTE_ADDR':'127.0.0.1'}):
            fixture.security.clear_login_attempts('wa-checkout-access')
        p=projects.create_fixed_price_project(self.base.bid,catalog.get_catalog_item('content_basic'),self.base.uid)
        response=self.base.client.get('/projects/'+str(p)+'/checkout')
        self.assertIn(response.status_code,(200,302))

    def test_platform_integration_guard_and_one_call_unchanged(self):
        import ast
        from pathlib import Path
        source=(Path(__file__).resolve().parents[2]/'app.py').read_text()
        tree=ast.parse(source)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='call_claude')
        gate=next(n for n in fn.body if isinstance(n,ast.If) and 'wa_checkout.intake' in ast.unparse(n))
        test=ast.unparse(gate.test)
        self.assertIn('tenant_id is None',test);self.assertIn('not tenant_context_block',test)
        with patch.object(flow,'purchase_item',side_effect=AssertionError('tenant must not query catalog')):
            self.assertIsNone(flow.intake(self.phone,'mau Content Growth',tenant=True))
        self.assertNotIn('requests.',Path(flow.__file__).read_text())

    def test_admin_guest_brief_reference_and_quote_page(self):
        row=self.start('mau Custom Photo');self.submit(row)
        uid=repo.create_user('guest-admin@test.com',fixture.security.hash_password('password123'))
        db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(uid,))
        admin=hub.app.test_client();admin.post('/login',data={'email':'guest-admin@test.com','password':'password123'})
        fid=db.insert_returning_id("INSERT INTO project_files(project_id,kind,original_filename,mime_type,size_bytes,content) VALUES(?,'REFERENCE','a.pdf','application/pdf',1,?)",(row['project_id'],b'x'))
        response=admin.get('/admin/projects/'+str(row['project_id']))
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Sumber: WhatsApp',response.data)
        self.assertIn(b'Test product',response.data)
        url='/admin/projects/'+str(row['project_id'])+'/reference/'+str(fid)
        self.assertEqual(admin.get(url).status_code,200)
        self.assertNotEqual(self.client.get(url).status_code,200)
        response=admin.post('/admin/projects/'+str(row['project_id'])+'/quote',data={'final_price':'10000','scope':'Scope'})
        self.assertEqual(response.status_code,302)
        self.assertIn(b'10.000',self.client.get('/wa-checkout').data)

    def test_oversize_and_invalid_proof_safe(self):
        row=self.start();self.submit(row);self.client.post('/wa-checkout',data={'action':'checkout'})
        self.assertEqual(self.client.post('/wa-checkout/access',json={'token':'x'*600}).status_code,413)
        self.client.post('/wa-checkout',data={'action':'proof','proof_file':(io.BytesIO(b'<script>bad</script>'),'bad.jpg')})
        inv=payment.get_latest_invoice_for_project(row['project_id'])
        self.assertEqual(payment.get_payment_for_invoice(inv['id'])['status'],'PAYMENT_PENDING')
        self.assertEqual(db.query_one('SELECT COUNT(*) n FROM project_files')['n'],0)

    def test_manual_project_status_does_not_claim_verified_payment(self):
        row=self.start();self.submit(row)
        db.execute("UPDATE projects SET status='IN_PROGRESS' WHERE id=?",(row['project_id'],))
        body=self.client.get('/wa-checkout').get_data(as_text=True)
        self.assertNotIn('Pembayaran telah diverifikasi',body)
        self.assertIn('Project sedang diproses',body)

    def test_pending_intake_allows_link_or_service_question(self):
        row=self.start()
        self.assertIn('/wa-checkout#',flow.intake(self.phone,'linknya?'))
        self.assertIsNone(flow.intake(self.phone,'dapet apa?'))
        self.assertEqual(projects.get_project(row['project_id']).get('requirements') or {},{})
        self.open(row)
        self.client.post('/wa-checkout',data={'action':'checkout'})
        self.assertIsNone(payment.get_latest_invoice_for_project(row['project_id']))

    def test_swallowed_database_error_cannot_commit_partial_order(self):
        row=self.start()
        with self.assertRaises(RuntimeError):
            with db.commerce_transaction(row['phone_hash']):
                try:db.execute('UPDATE nonexistent_commerce_table SET value=1')
                except Exception:pass
                db.execute("UPDATE projects SET title='Partial write' WHERE id=?",(row['project_id'],))
        self.assertNotEqual(projects.get_project(row['project_id'])['title'],'Partial write')

if __name__=='__main__':unittest.main()
