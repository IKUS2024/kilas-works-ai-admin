"""Customer Brain navigation and owner Finance integration; offline disposable DB."""
import io
import unittest
from datetime import timedelta
from html.parser import HTMLParser

from flask import template_rendered
import test_final_product_flow as prior
import db
import repo
import finance_entitlements as entitlement
import finance_subscription as billing

app = prior.app


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = {}
        self.href = None
        self.label = ''
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = ''

    def handle_data(self, data):
        if self.href is not None:
            self.label += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links[self.label.strip()] = self.href
            self.href = None


class DashboardIntegrationTests(unittest.TestCase):
    setUp = prior.FinalFlowTests.setUp
    trial = prior.FinalFlowTests.trial
    bill = prior.FinalFlowTests.bill
    proof = prior.FinalFlowTests.proof
    verified = prior.FinalFlowTests.verified
    snapshot = prior.FinalFlowTests.snapshot

    def dashboard(self, status, package='AI_ADMIN'):
        db.execute('UPDATE businesses SET status=?,package=? WHERE id=?', (status, package, self.b))
        with self.client.session_transaction() as session:
            session['dashboard_business_id'] = self.b
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        return response, Links(response.text).links

    def admin_page(self, query=''):
        client = app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = self.admin
        contexts = []
        def capture(sender, template, context, **extra):
            if template.name == 'admin_dashboard.html':
                contexts.append(context)
        with template_rendered.connected_to(capture, app):
            response = client.get('/admin/' + query)
        self.assertEqual(response.status_code, 200)
        return response, contexts[0]

    def assert_brain_controls(self, status):
        response, links = self.dashboard(status)
        for label, suffix in (
            ('Ajari Kilas Brain', '/memory'),
            ('Booking & Pembayaran', '/settings'),
            ('Review & Langkah Berikutnya', '/review'),
            ('Coba Simulasi', '/simulate'),
        ):
            self.assertEqual(links[label], f'/business/{self.b}' + suffix)
        # Existing editors are usable after onboarding as well as after activation.
        for label in ('Ajari Kilas Brain', 'Booking & Pembayaran'):
            self.assertEqual(self.client.get(links[label]).status_code, 200)
        self.assertIn('rekening bisnismu untuk pelanggan', response.text)
        self.assertEqual('Buka Inbox Brain' in links, status == 'ACTIVE')
        if status == 'ACTIVE':
            self.assertEqual(links['Buka Inbox Brain'], f'/business/{self.b}/inbox')

    def test_ready_for_review_brain_controls(self):
        self.assert_brain_controls('READY_FOR_REVIEW')

    def test_approved_brain_controls_without_inbox(self):
        self.assert_brain_controls('APPROVED')

    def test_active_brain_controls_and_inbox(self):
        self.assert_brain_controls('ACTIVE')

    def test_without_brain_hides_all_brain_controls(self):
        _, links = self.dashboard('ACTIVE', 'NONE')
        for label in ('Ajari Kilas Brain', 'Booking & Pembayaran',
                      'Review & Langkah Berikutnya', 'Coba Simulasi', 'Buka Inbox Brain'):
            self.assertNotIn(label, links)

    def test_customer_cannot_open_other_business_editors(self):
        for suffix in ('memory', 'settings'):
            self.assertEqual(self.client.get(f'/business/{self.other}/{suffix}').status_code, 404)

    def test_zero_counts_and_existing_action_center_links(self):
        response, context = self.admin_page()
        self.assertEqual(context['action_center']['finance_trials_active'], 0)
        self.assertEqual(context['action_center']['finance_bills_waiting_review'], 0)
        links = Links(response.text).links
        self.assertEqual(links['0 Finance trial aktif'], '/admin/?finance=trial')
        self.assertEqual(links['0 Pembayaran Finance perlu ditinjau'], '/admin/finance-subscription-bills')
        for url in ('/admin/?status=DRAFT', '/admin/?status=READY_FOR_REVIEW',
                    '/admin/projects?status=WAITING_FOR_QUOTE', '/admin/payments',
                    '/admin/talent', '/admin/projects', '/admin/?status=APPROVED'):
            self.assertIn(url, links.values())

    def test_trial_list_name_status_expiry_read_only(self):
        self.trial()
        before = self.snapshot()
        response, context = self.admin_page('?finance=trial')
        self.assertEqual(context['action_center']['finance_trials_active'], 1)
        self.assertEqual([b['id'] for b in context['businesses']], [self.b])
        self.assertIn(repo.get_business(self.b)['business_name'], response.text)
        self.assertIn('TRIAL_ACTIVE', response.text)
        self.assertIn(entitlement.state(self.b)['until_local'], response.text)
        self.assertIn('Tidak ada persetujuan trial', response.text)
        self.assertEqual(Links(response.text).links['Lihat Finance'], self.setup_url)
        self.assertEqual(before, self.snapshot())

    def test_trial_count_includes_finance_only_and_ignores_brain_filter(self):
        db.execute("UPDATE businesses SET package='NONE' WHERE id=?", (self.b,))
        self.trial()
        entitlement.setup(self.other, self.other_uid, 'Kas', 'CASH')
        entitlement.start_trial(self.other, self.other_uid)
        _, context = self.admin_page('?status=APPROVED')
        self.assertEqual(context['action_center']['finance_trials_active'], 2)

    def test_paid_precedes_trial_and_expired_is_not_counted(self):
        self.trial()
        self.verified()
        _, context = self.admin_page('?finance=trial')
        self.assertEqual(context['action_center']['finance_trials_active'], 0)
        self.assertEqual(context['businesses'], [])
        self.assertEqual(entitlement.state(self.b)['status'], 'PAID_ACTIVE')

    def test_trial_expiry_removes_business_without_admin_action(self):
        self.trial()
        self.time.return_value += timedelta(days=7)
        response, context = self.admin_page('?finance=trial')
        self.assertEqual(context['action_center']['finance_trials_active'], 0)
        self.assertEqual(context['businesses'], [])
        self.assertIn('Belum ada trial Finance aktif.', response.text)

    def test_review_count_tracks_upload_rejection_and_approval(self):
        _, initial = self.admin_page()
        initial = initial['action_center']
        bill_id = self.bill()
        url = f'/business/{self.b}/finance-bills/{bill_id}'
        _, context = self.admin_page()
        self.assertEqual(context['action_center']['finance_bills_waiting_review'], 0)
        response = self.client.post(url, data={'proof_file': (io.BytesIO(self.raw), 'proof.png')})
        self.assertEqual(response.status_code, 303)
        response, context = self.admin_page()
        self.assertEqual(context['action_center']['finance_bills_waiting_review'], 1)
        self.assertNotIn('Tidak ada yang perlu aksi saat ini.', response.text)
        for key, value in initial.items():
            if not key.startswith('finance_'):
                self.assertEqual(context['action_center'][key], value)
        admin_client = app.test_client()
        with admin_client.session_transaction() as session:
            session['user_id'] = self.admin
        queue = admin_client.get('/admin/finance-subscription-bills')
        self.assertEqual(queue.status_code, 200)
        self.assertIn(url, Links(queue.text).links.values())
        self.assertEqual(admin_client.post(url + '/review', data={'decision': 'reject'}).status_code, 303)
        self.assertEqual(billing.bill(self.b, bill_id, self.uid)['status'], 'REJECTED')
        _, context = self.admin_page()
        self.assertEqual(context['action_center']['finance_bills_waiting_review'], 0)
        self.assertEqual(entitlement.state(self.b)['status'], 'NOT_ACTIVATED')
        new_image = prior.prior.image_bytes('JPEG')
        self.assertEqual(self.client.post(url, data={'proof_file': (io.BytesIO(new_image), 'proof.jpg')}).status_code, 303)
        self.assertEqual(admin_client.post(url + '/review', data={'decision': 'approve'}).status_code, 303)
        _, context = self.admin_page()
        self.assertEqual(context['action_center']['finance_bills_waiting_review'], 0)
        self.assertEqual(entitlement.state(self.b)['status'], 'PAID_ACTIVE')

    def test_non_admin_cannot_open_finance_admin_views(self):
        for url in ('/admin/?finance=trial', '/admin/finance-subscription-bills'):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertIn(app.test_client().get(url).status_code, (302, 303))

    def test_finance_dashboard_lifecycle_and_customer_trial_post(self):
        response, _ = self.dashboard('READY_FOR_REVIEW')
        self.assertEqual(entitlement.state(self.b)['status'], 'NOT_ACTIVATED')
        self.assertIn('Coba Gratis 7 Hari', response.text)
        self.assertEqual(self.client.post(self.setup_url, data={'action': 'trial', 'terms': 'yes'}).status_code, 303)
        self.assertEqual(entitlement.state(self.b)['status'], 'TRIAL_ACTIVE')
        response, links = self.dashboard('READY_FOR_REVIEW')
        self.assertIn('Trial aktif', response.text)
        self.assertEqual(links['Buka Finance'], self.url)
        self.time.return_value += timedelta(days=7)
        response, links = self.dashboard('READY_FOR_REVIEW')
        self.assertEqual(entitlement.state(self.b)['status'], 'EXPIRED')
        self.assertIn('data hanya-baca', response.text)
        self.assertNotIn('Buka Finance', links)
        self.assertEqual(links['Lihat Data & Perpanjang'], self.setup_url)
        self.verified()
        response, links = self.dashboard('READY_FOR_REVIEW')
        self.assertEqual(entitlement.state(self.b)['status'], 'PAID_ACTIVE')
        self.assertIn('Langganan aktif', response.text)
        self.assertEqual(links['Buka Finance'], self.url)


if __name__ == '__main__':
    unittest.main()
