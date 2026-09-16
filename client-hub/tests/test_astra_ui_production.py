"""Targeted Client Hub production pass: identity, order visibility, upload states."""
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import test_service_selection_purchase_flow as fixture
import db
import repo
import projects_repo
import catalog_service
import app as hub
from flask import render_template

class ClientHubProductionTests(unittest.TestCase):
    def setUp(self): fixture.reset_db()

    def test_orders_without_business_are_visible_only_to_creator(self):
        a=repo.create_user('astra-ui-a@test.com',fixture.security.hash_password('password123'))
        b=repo.create_user('astra-ui-b@test.com',fixture.security.hash_password('password123'))
        item=catalog_service.get_catalog_item('content_basic')
        aid=projects_repo.create_fixed_price_project(None,item,a)
        bid=projects_repo.create_fixed_price_project(None,item,b)
        db.execute('UPDATE projects SET title = ? WHERE id = ?',('A-only-order',aid))
        db.execute('UPDATE projects SET title = ? WHERE id = ?',('B-only-order',bid))
        client=fixture.fresh_client();fixture._login_owner(client,'astra-ui-a@test.com')
        response=client.get('/dashboard');body=response.data.decode()
        self.assertEqual(response.status_code,200)
        self.assertIn('A-only-order',body);self.assertNotIn('B-only-order',body)
        self.assertIn('/projects/'+str(aid),body)

    def test_target_templates_compile_and_public_brand_is_human_readable(self):
        for name in ('base.html','wizard.html','review.html','invoice.html','checkout.html','client_dashboard.html','upload_too_large.html'):
            hub.app.jinja_env.get_template(name)
        self.assertEqual(hub.app.jinja_env.filters['humanize_package']('AI_ADMIN_BASIC'),'Kilas Brain')
        self.assertIn('Bahasa utama',hub.app.jinja_env.filters['missing_fields_sentence'](['primary_language']))

    def test_verified_invoice_does_not_request_another_transfer(self):
        with hub.app.test_request_context('/'):
            body=render_template('invoice.html',invoice={'invoice_number':'TEST','amount':123000,'id':1,'status':'PAID'},payment={'status':'VERIFIED','proof_file_id':None},review_status='VERIFIED',bank={'bank_name':'Test','account_number':'123','account_holder':'Test'})
        self.assertIn('Tidak perlu transfer ulang',body)
        self.assertNotIn('name="proof_file"',body)
        self.assertNotIn('Transfer sesuai total tagihan',body)

    def test_pending_invoice_has_accessible_file_selection_and_busy_state(self):
        with hub.app.test_request_context('/'):
            body=render_template('invoice.html',invoice={'invoice_number':'TEST','amount':123000,'id':1,'status':'PAYMENT_PENDING'},payment={'status':'PAYMENT_PENDING'},review_status='PAYMENT_PENDING',bank={})
        self.assertIn('aria-describedby="proof-file-help"',body)
        self.assertIn('setCustomValidity',body)
        self.assertIn("form.setAttribute('aria-busy', 'true')",body)
        self.assertNotIn(' capture=',body)

    def test_oversized_upload_has_human_error_page(self):
        with hub.app.test_request_context('/'):
            error=hub.app.error_handler_spec[None][413]
            handler=next(iter(error.values()))
            body,status=handler(None)
        self.assertEqual(status,413)
        self.assertIn('File belum tersimpan',body)
        self.assertIn('11MB',body)

if __name__=='__main__':unittest.main(verbosity=2)
