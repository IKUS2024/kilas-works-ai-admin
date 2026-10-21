"""Focused single-offer, custom capacity, and admin console contracts."""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-console-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-console-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
import platform_console  # noqa: E402
from kilas_ai import topups, usage  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402


class SinglePlanConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("single-plan-owner@example.test", "hash", full_name="Pemilik Kilas")
        cls.other = repo.create_user("single-plan-other@example.test", "hash")
        cls.admin = repo.create_user("single-plan-admin@example.test", "hash", role="KILAS_ADMIN")
        cls.business = repo.create_business(cls.owner, "Bisnis Finance", package="NONE")
        db.execute("INSERT INTO finance_entitlements(business_id,trial_started_at,trial_until,updated_at) VALUES (?,?,?,?)",
                   (cls.business, usage._now().isoformat(), (usage._now() + timedelta(days=7)).isoformat(), usage._now().isoformat()))

    def client_for(self, user, role="CLIENT_OWNER"):
        import customer_auth
        client = self.app.test_client()
        with self.app.app_context():
            token = customer_auth.create(repo.get_user_by_id(user)) if role != 'KILAS_ADMIN' else None
        with client.session_transaction() as session:
            session.update(user_id=user, role=role, _csrf_token="console-csrf")
            if token:
                session[customer_auth.SID] = token
        client.set_cookie('kilas_language', 'id')
        return client

    def test_customer_offer_and_amount_validation(self):
        client = self.client_for(self.owner)
        preview = client.get("/kilas-ai/usage").get_data(as_text=True)
        self.assertIn("Kredit &amp; Penggunaan", preview)
        self.assertIn('view=legacy', preview)
        self.assertIn('type="button" disabled', preview)
        self.assertNotIn('action="/kilas-ai/checkout"', preview)
        body = client.get("/kilas-ai/usage?view=legacy").get_data(as_text=True)
        self.assertIn("Rp99.000", body)
        self.assertIn("Kapasitas Premium", body)
        self.assertEqual(body.count('action="/kilas-ai/checkout"'), 1)
        for forbidden in ("Penggunaan periode ini", "Pilih Plus", "Pilih Pro",
                          "Pilih Max", "GPT-6", "provider cost", "Chat hari ini"):
            self.assertNotIn(forbidden, body)
        for amount in ("", "-20000", "19999", "abc", "1e6", "100000001"):
            with self.subTest(amount=amount):
                response = client.post("/kilas-ai/topups", data={"amount_idr": amount, "csrf_token": "console-csrf"})
                self.assertEqual(response.status_code, 400)
        response = client.post("/kilas-ai/topups", data={"pack":"MINI","amount_idr":"1","csrf_token":"console-csrf"})
        self.assertEqual(response.status_code, 303)
        item = topups.owner_orders(self.owner)[0]
        self.assertEqual(item["amount_idr"], 25000)
        self.assertTrue(item["invoice_number"].startswith("KAI-P-"))
        self.assertEqual(self.client_for(self.other).get(f"/kilas-ai/topups/{item['id']}").status_code, 404)

    def test_custom_payment_allocates_once_and_expires_after_365_days(self):
        order_id = topups.create_custom_order(self.owner, "25000")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            topups.submit_proof(self.owner, order_id, FileStorage(stream=io.BytesIO(b"synthetic proof"),
                filename="proof.png", content_type="image/png"))
        topups.review(order_id, self.admin, "VERIFIED")
        topups.review(order_id, self.admin, "VERIFIED")
        credit = db.query_one("SELECT total_micro,expires_at FROM kilas_ai_topup_credits WHERE order_id=?", (order_id,))
        self.assertEqual(credit["total_micro"], topups._budget_micro(25000))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_topup_credits WHERE order_id=?", (order_id,))["n"], 1)
        self.assertGreaterEqual((usage._as_utc(credit["expires_at"]) - usage._now()).days, 364)
        self.assertFalse(topups.balance(self.other)["available"])

    def test_design_proposal_preserves_existing_credit_and_subscription_records(self):
        now = usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?) ON CONFLICT(user_id) DO UPDATE SET plan='PLUS',status='ACTIVE',period_start=excluded.period_start,period_end=excluded.period_end",
                   (self.owner, now.isoformat(), (now + timedelta(days=30)).isoformat()))
        db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,150) ON CONFLICT(user_id) DO UPDATE SET seconds=150', (self.owner,))
        tables = ('kilas_ai_subscriptions', 'kilas_ai_topup_orders', 'kilas_ai_topup_credits',
                  'kilas_ai_topup_debits', 'kilas_audio_balances', 'kilas_ai_usage')
        before = {table: db.query_all('SELECT * FROM ' + table) for table in tables}
        client = self.client_for(self.owner)
        for language, heading in (('en', 'Credits &amp; Usage'), ('id', 'Kredit &amp; Penggunaan')):
            client.set_cookie('kilas_language', language)
            response = client.get('/kilas-ai/usage')
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn(heading, body)
            self.assertIn('href="/kilas-ai/usage?view=legacy"', body)
            self.assertNotIn('name="pack"', body)
            self.assertNotIn('action="/kilas-ai/topups"', body)
        self.assertEqual(before, {table: db.query_all('SELECT * FROM ' + table) for table in tables})
        self.assertEqual(usage.effective_plan(self.owner)['plan'], 'PLUS')
        self.assertEqual(client.get('/kilas-ai/usage?view=legacy').status_code, 200)
        self.assertIn('/login', self.app.test_client().get('/kilas-ai/usage').location)

    def test_admin_overview_escapes_postgres_percent_wildcard(self):
        with patch.object(platform_console.db, "query_all", return_value=[]), \
                patch.object(platform_console, "_number", return_value=0) as number:
            platform_console.overview()
        sql_calls = [call.args[0] for call in number.call_args_list]
        self.assertTrue(any("invoice_number LIKE 'KAI-C-%%'" in sql for sql in sql_calls))

    def test_admin_only_directories_and_logout(self):
        owner, admin = self.client_for(self.owner), self.client_for(self.admin, "KILAS_ADMIN")
        for path in ("/platform/", "/platform/customers", "/platform/kilas-ai", "/platform/finance",
                     "/platform/payments", "/platform/usage-cost", f"/platform/customers/{self.owner}"):
            self.assertEqual(owner.get(path).status_code, 403, path)
            self.assertEqual(admin.get(path).status_code, 200, path)
        overview = admin.get("/platform/").get_data(as_text=True)
        self.assertIn("Kilas Works Admin", overview)
        self.assertIn("Keluar", overview)
        self.assertNotIn("Kilas Assist", overview)
        directory = admin.get("/platform/customers?q=Pemilik").get_data(as_text=True)
        self.assertIn("Pemilik Kilas", directory)
        self.assertIn("Kilas Finance", directory)
        detail = admin.get(f"/platform/customers/{self.owner}").get_data(as_text=True)
        self.assertIn("Kilas AI", detail)
        self.assertIn("Bisnis Finance", detail)
        self.assertIn("Bisnis Finance", admin.get("/platform/finance").get_data(as_text=True))
        self.assertEqual(admin.get("/logout").status_code, 302)
        self.assertNotEqual(admin.get("/platform/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
