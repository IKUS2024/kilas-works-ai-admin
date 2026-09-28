"""Focused checks for the product picker, Services page, and customer session patch."""
import unittest
from urllib.parse import parse_qs, urlparse

from unittest.mock import patch

import test_finance_phase2a as fixture
import finance_entitlements as entitlements
import finance_service
import db
import repo
import security


app = fixture.app


class FastProductServicesPatchTests(unittest.TestCase):
    def setUp(self):
        # Windows keeps the fixture SQLite file locked while its cached connection is open.
        db.reset_connection_for_new_db_path()
        fixture.fixture.reset_db()
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS'] = False
        self.addCleanup(lambda: app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=False))

    def owner(self, email, business_name=None, package='NONE'):
        password='password123'
        uid=repo.create_user(email,security.hash_password(password),role='CLIENT_OWNER',full_name='Owner')
        bid=repo.create_business(uid,business_name,package=package) if business_name else None
        return uid,bid,password

    def logged_in(self, uid):
        client=app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid,role='CLIENT_OWNER')
        return client

    def test_fresh_customer_login_is_session_only_clears_product_state_and_opens_picker(self):
        uid,_,password=self.owner('fresh-login@example.test')
        client=app.test_client()
        with client.session_transaction() as session:
            session.update(active_product='finance',product_intent='brain',workspace_ai_business=999)
        response=client.post('/login',data={'email':'fresh-login@example.test','password':password})
        self.assertTrue(response.location.endswith('/products/start'))
        session_cookie=next(value for value in response.headers.getlist('Set-Cookie') if value.startswith('session='))
        self.assertNotIn('Expires=',session_cookie)
        self.assertNotIn('Max-Age=',session_cookie)
        with client.session_transaction() as session:
            self.assertEqual(session['user_id'],uid)
            self.assertFalse(session.get('_permanent'))
            for stale in ('active_product','product_intent','workspace_ai_business'):
                self.assertNotIn(stale,session)
        page=client.get('/products/start')
        for title in ('Kilas Assist','Kilas Finance','Kilas Services'):
            self.assertIn(title,page.text)

    def test_existing_authorized_permanent_browser_session_is_not_invalidated(self):
        uid,_,_=self.owner('trusted-work-browser@example.test')
        client=app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid,role='CLIENT_OWNER',_permanent=True)
        self.assertEqual(client.get('/products/start').status_code,200)
        with client.session_transaction() as session:
            self.assertTrue(session.get('_permanent'))

    def test_existing_assist_and_finance_entries_reuse_owned_businesses(self):
        assist_uid,assist_bid,_=self.owner('assist-existing@example.test','Assist Existing','AI_ADMIN')
        assist=self.logged_in(assist_uid)
        before=len(repo.list_businesses_for_user(assist_uid))
        response=assist.post('/products/start',data={'product':'assist'})
        self.assertTrue(response.location.endswith('/workspace/ai'))
        self.assertEqual(len(repo.list_businesses_for_user(assist_uid)),before)
        with assist.session_transaction() as session:
            self.assertEqual(session['workspace_ai_business'],assist_bid)

        finance_uid,finance_bid,_=self.owner('finance-existing@example.test','Finance Existing')
        finance_service.ensure_finance_defaults(finance_bid,actor_user_id=finance_uid)
        with patch.dict(__import__('os').environ,{'KILAS_FINANCE_ACCESS_MODE':'self_service'}):
            entitlements.start_trial(finance_bid,finance_uid)
            finance=self.logged_in(finance_uid)
            before=len(repo.list_businesses_for_user(finance_uid))
            response=finance.post('/products/start',data={'product':'finance'})
        self.assertIn(f'/business/{finance_bid}/finance/workspaces',response.location)
        self.assertEqual(len(repo.list_businesses_for_user(finance_uid)),before)

    def test_new_product_entries_ask_for_business_but_services_does_not(self):
        uid,_,_=self.owner('new-products@example.test')
        client=self.logged_in(uid)
        assist=client.post('/products/start',data={'product':'assist'})
        finance=client.post('/products/start',data={'product':'finance'})
        services=client.post('/products/start',data={'product':'services'})
        self.assertTrue(assist.location.endswith('/products/assist?step=business'))
        self.assertTrue(finance.location.endswith('/products/finance?step=business'))
        self.assertTrue(services.location.endswith('/products/services'))
        page=client.get(services.location)
        self.assertEqual(page.status_code,200)
        self.assertNotIn('name="business_name"',page.text)
        self.assertNotIn('Rp',page.text)
        self.assertNotIn('checkout',page.text.casefold())

    def test_services_has_four_exact_whatsapp_handoffs_and_required_disclosures(self):
        uid,_,_=self.owner('services@example.test')
        page=self.logged_in(uid).get('/products/services')
        self.assertEqual(page.status_code,200)
        links=[]
        import re
        for href in re.findall(r'href="([^"]*wa\.me[^"]*)"',page.text):
            parsed=urlparse(href.replace('&amp;','&'))
            self.assertEqual(parsed.netloc,'wa.me')
            self.assertEqual(parsed.path,'/14048836437')
            links.append(parse_qs(parsed.query)['text'][0])
        self.assertEqual(links,[
            'Halo Kilas Works, saya ingin konsultasi Visa & Document Assistance. Negara tujuan saya:',
            'Halo Kilas Works, saya membutuhkan bantuan Form & Online Assistance. Yang ingin saya urus:',
            'Halo Kilas Works, saya ingin konsultasi Content Studio. Kebutuhan konten saya:',
            'Halo Kilas Works, saya membutuhkan Talent Management. Jenis talent/kebutuhan saya:',
        ])
        for text in ('bukan kedutaan','Keputusan visa sepenuhnya','Persetujuan Anda diperlukan','Konsultasi via WhatsApp'):
            self.assertIn(text,page.text)

    def test_product_header_exposes_change_service_in_assist_and_finance(self):
        uid,bid,_=self.owner('switcher@example.test','Both','AI_ADMIN')
        finance_service.ensure_finance_defaults(bid,actor_user_id=uid)
        client=self.logged_in(uid)
        assist=client.get('/workspace/ai')
        with patch.dict(__import__('os').environ,{'KILAS_FINANCE_ACCESS_MODE':'self_service'}):
            entitlements.start_trial(bid,uid)
            finance=client.get(f'/business/{bid}/finance/workspaces',follow_redirects=True)
        self.assertIn('Ganti Layanan',assist.text)
        self.assertIn('Ganti Layanan',finance.text)
        picker=client.get('/products/start')
        self.assertEqual(picker.status_code,200)
        self.assertIn('Kilas Services',picker.text)
        self.assertEqual(client.get('/products/services').status_code,200)


if __name__ == '__main__':
    unittest.main()
