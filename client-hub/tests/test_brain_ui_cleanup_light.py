"""Presentation-only business cards; no external HTTP or AI calls."""
import re
import unittest
from html import unescape
from unittest.mock import patch
from flask import render_template
import test_single_plan_release as f


class BrainUITests(unittest.TestCase):
    def setUp(self):
        base = f.SinglePlanTests(); base.setUp()
        self.uid, self.bid, self.client = base.uid, base.bid, base.client
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('No HTTP'))
        self.network.start(); self.addCleanup(self.network.stop)

    def render(self, status, package='AI_ADMIN', payment=None, catalog_key=None, business_id=None):
        business = dict(f.repo.get_business(self.bid), status=status, package=package,
                        completion_percent=42, subscription_banner=None, ai_usage=None)
        projects = [] if payment is None else [dict(id=1, business_id=business_id or self.bid,
            catalog_key=catalog_key or package.lower(), payment={'status': payment},
            payment_review_status=payment, status='APPROVED', title='Order', business_name='Business',
            final_price=499000, can_cancel=False, can_edit_brief=False)]
        with f.app.app.test_request_context('/dashboard'):
            return render_template('client_dashboard.html', user={'email':'owner@example.test'},
                                   businesses=[business], my_projects=projects)

    def primary(self, html):
        section = html.split('class="business-actions business-primary"',1)[1].split('</div>',1)[0]
        return re.findall(r'<a class="btn" href="([^"]+)">([^<]+)</a>', section)

    def test_all_package_labels_and_plan_line(self):
        for package in ('AI_ADMIN', 'AI_ADMIN_BASIC', 'AI_ADMIN_PRO'):
            self.assertEqual(f.app.app.jinja_env.filters['humanize_package'](package), 'Kilas Brain')
            html = self.render('ACTIVE', package)
            text = unescape(re.sub(r'<[^>]+>', '', html))
            self.assertIn('Kilas Brain — Rp499.000/bulan', text)
            for forbidden in ('Basic', 'Pro —', 'AI_ADMIN', 'WABA', 'phone_number_id', 'credentials_reference', 'tenant'):
                self.assertNotIn(forbidden, text)

    def test_one_primary_per_status(self):
        expected = {'DRAFT':'Lanjutkan Setup', 'ONBOARDING':'Lanjutkan Setup',
                    'READY_FOR_AI_SETUP':'Lanjutkan Setup','READY_FOR_REVIEW':'Lihat Data',
                    'NEEDS_REVISION':'Perbaiki Data','APPROVED':'Hubungkan WhatsApp',
                    'ACTIVE':'Buka CS Inbox','SUSPENDED':'Invoice &amp; Pembayaran'}
        for status, label in expected.items():
            html = self.render(status, payment='VERIFIED')
            links = self.primary(html)
            self.assertEqual(len(links), 1, status); self.assertEqual(links[0][1], label)
            if status == 'APPROVED': self.assertIn(f'/business/{self.bid}/whatsapp/connect', links[0][0])
            if status == 'ACTIVE': self.assertIn('/inbox', links[0][0])

    def test_unverified_or_wrong_payment_never_connect_cta(self):
        for data in ({}, {'payment':'UNDER_REVIEW'}, {'payment':'AUTO_CHECK_PASSED'},
                     {'payment':'VERIFIED','catalog_key':'website_landing'},
                     {'payment':'VERIFIED','catalog_key':'ai_admin_pro'},
                     {'payment':'VERIFIED','business_id':self.bid+1}):
            html = self.render('APPROVED', **data)
            self.assertEqual(self.primary(html)[0][1], 'Invoice &amp; Pembayaran')
            self.assertNotIn('/whatsapp/connect', html)
            self.assertNotIn('pembayaran sudah diverifikasi', html)

    def test_secondary_destinations_grouped(self):
        html = self.render('ACTIVE')
        details = html.split('<summary>Kelola Bisnis</summary>',1)[1].split('</details>',1)[0]
        for label in ('Ajari Kilas Brain','Pengaturan Operasional','Invoice &amp; Pembayaran',
                      'Semua Proyek','Coba Kilas Brain','Lihat Data'):
            self.assertIn(label, details)
        self.assertEqual(html.count('<summary>Kelola Bisnis</summary>'), 1)
        self.assertNotIn('Buka CS Inbox', details)
        self.assertNotIn('<script', details)

    def test_setup_wording_only_changes_presentation(self):
        for status in ('DRAFT','ONBOARDING','READY_FOR_AI_SETUP'):
            self.assertIn('Setup 42%', self.render(status))
        for status in ('READY_FOR_REVIEW','NEEDS_REVISION','APPROVED','ACTIVE','SUSPENDED'):
            html = self.render(status)
            self.assertIn('Setup selesai', html); self.assertNotIn('Setup 42%', html)

    def test_customer_render_no_database_writes(self):
        before = '\n'.join(f.db.get_connection().iterdump())
        for status in ('DRAFT','APPROVED','ACTIVE','SUSPENDED'): self.render(status)
        self.assertEqual(before, '\n'.join(f.db.get_connection().iterdump()))

    def test_none_keeps_upgrade_and_destinations(self):
        html = self.render('DRAFT', 'NONE')
        self.assertIn('+ Tambah Kilas Brain', html)
        self.assertNotIn('business-primary" style="margin-top:14px;">\n        <a', html)
        self.assertNotIn('Setup selesai', html)
        self.assertNotIn('Setup 42%', html)
        self.assertIn('Semua Proyek', html)

    def test_admin_manual_fallback_and_labels(self):
        f.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?", (self.uid,))
        f.db.execute("UPDATE businesses SET status='APPROVED' WHERE id=?", (self.bid,))
        # Resolve real route rather than relying on a guessed admin URL.
        with f.app.app.test_request_context('/'):
            from flask import url_for
            route = url_for('admin.review_business', business_id=self.bid)
        page = self.client.get(route)
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn('Koneksi WhatsApp — Bantuan Manual', body)
        self.assertIn('name="whatsapp_phone_number_id"', body)
        self.assertIn('name="credentials_reference"', body)
        self.assertIn('name="csrf_token"', body)
        self.assertIn('Gunakan form ini hanya jika proses otomatis membutuhkan bantuan.', body)
        dashboard = self.client.get('/admin/').get_data(as_text=True)
        for label in ('Pembayaran perlu diverifikasi','Bisnis perlu ditinjau','Tenant menunggu koneksi WhatsApp','Proyek perlu tindakan'):
            self.assertIn(label, dashboard)

if __name__ == '__main__': unittest.main()
